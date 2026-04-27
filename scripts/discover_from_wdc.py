"""Common Crawl / Web Data Commons DISCOVERY mode.

Reads WDC's JobPosting_domain_stats.csv (lists every paid-level-domain
that had a JobPosting in the October 2024 Common Crawl), diffs it
against employers we already crawl, runs ATS detection on the unknowns,
and inserts source_configs for any that match a connector we have.

This is the "find every site in the world with jobs" play. Each new
source_config = the next 30-min Celery beat picks it up = LIVE jobs
flow into the index.

Run modes:
    python3 -m scripts.discover_from_wdc                    # default: top 2K domains
    python3 -m scripts.discover_from_wdc --top 5000         # bigger probe
    python3 -m scripts.discover_from_wdc --min-jobs 10      # only domains with >=10 jobs in CC
    python3 -m scripts.discover_from_wdc --concurrency 30   # tune ATS detection parallelism
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import logging
import sys
import uuid
from typing import Optional

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover_wdc")

WDC_STATS_URL = (
    "https://data.dws.informatik.uni-mannheim.de/structureddata/2024-12/"
    "quads/classspecific/JobPosting/JobPosting_domain_stats.csv"
)


async def download_stats() -> list[tuple[str, int]]:
    """Returns [(domain, job_count)] sorted by job_count desc."""
    logger.info("Downloading WDC JobPosting domain stats…")
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as s:
        async with s.get(WDC_STATS_URL) as r:
            r.raise_for_status()
            text = await r.text()

    rows: list[tuple[str, int]] = []
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 3:
            continue
        domain = row[0].strip()
        try:
            n = int(row[2])
        except (ValueError, IndexError):
            continue
        if domain and n > 0:
            rows.append((domain, n))
    rows.sort(key=lambda r: -r[1])
    logger.info("Parsed %d domains from stats", len(rows))
    return rows


async def filter_unknowns(domains: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Drop domains we already have an Employer row for."""
    from sqlalchemy import create_engine, text as sql_text
    from src.config import settings

    engine = create_engine(settings.database_url_sync)
    known: set[str] = set()
    with engine.connect() as conn:
        rs = conn.execute(sql_text("SELECT lower(domain) FROM employers WHERE domain IS NOT NULL"))
        for (d,) in rs:
            if d:
                known.add(d.strip().lower())
    logger.info("DB has %d known employer domains", len(known))

    unknown = [(d, n) for d, n in domains if d.lower() not in known]
    logger.info("Unknown to us: %d / %d candidate domains", len(unknown), len(domains))
    return unknown


async def detect_one(domain: str, sem: asyncio.Semaphore):
    from src.discovery.ats_detector import detect_ats_for_domain
    async with sem:
        try:
            return domain, await detect_ats_for_domain(domain)
        except Exception as e:
            logger.debug("Detect failed for %s: %s", domain, str(e)[:80])
            return domain, None


async def run_detection(domains: list[str], concurrency: int = 20) -> list[tuple[str, object]]:
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(detect_one(d, sem) for d in domains))
    return [(d, r) for d, r in results if r is not None and r.connector_type and r.board_token]


def insert_source_configs(matched: list[tuple[str, object]]) -> int:
    """Insert Employer + SourceConfig for each matched (domain, ATSDetection).
    Idempotent — uses ON CONFLICT DO NOTHING on Employer.domain.
    Returns count of NEW source_configs created.
    """
    from sqlalchemy import create_engine, text as sql_text
    from src.config import settings

    engine = create_engine(settings.database_url_sync)
    new_count = 0
    with engine.begin() as conn:
        for domain, det in matched:
            # Upsert Employer
            existing = conn.execute(sql_text(
                "SELECT id FROM employers WHERE lower(domain) = lower(:d)"
            ), {"d": domain}).fetchone()
            if existing:
                emp_id = existing[0]
            else:
                emp_id = uuid.uuid4()
                conn.execute(sql_text("""
                    INSERT INTO employers (id, name, domain, ats_platform, created_at, updated_at)
                    VALUES (:id, :name, :domain, :ats, NOW(), NOW())
                    ON CONFLICT (domain) DO NOTHING
                """), {"id": emp_id, "name": domain, "domain": domain, "ats": det.ats_platform})

            # Skip if a source_config already exists for this employer + source_type
            existing_sc = conn.execute(sql_text("""
                SELECT id FROM source_configs
                 WHERE employer_id = :eid AND source_type = :st
            """), {"eid": emp_id, "st": det.connector_type}).fetchone()
            if existing_sc:
                continue

            conn.execute(sql_text("""
                INSERT INTO source_configs
                  (id, employer_id, source_type, config, crawl_interval_hours, is_active, created_at)
                VALUES
                  (:id, :eid, :st, :cfg, 6, TRUE, NOW())
            """), {
                "id": uuid.uuid4(),
                "eid": emp_id,
                "st": det.connector_type,
                "cfg": '{"board_token": "%s", "employer_domain": "%s"}' % (det.board_token, domain),
            })
            new_count += 1
    return new_count


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=2000, help="Probe the top-N domains by job count")
    p.add_argument("--min-jobs", type=int, default=3, help="Skip domains with fewer than N jobs in CC")
    p.add_argument("--concurrency", type=int, default=20, help="Parallel ATS-detection requests")
    args = p.parse_args()

    domains = await download_stats()
    domains = [(d, n) for d, n in domains if n >= args.min_jobs]
    domains = domains[: args.top]
    logger.info("Filtered to top %d domains (>= %d jobs each)", len(domains), args.min_jobs)

    unknown = await filter_unknowns(domains)
    if not unknown:
        logger.info("Nothing new to discover.")
        return

    logger.info("Running ATS detection on %d unknown domains (concurrency=%d)…", len(unknown), args.concurrency)
    matched = await run_detection([d for d, _ in unknown], concurrency=args.concurrency)
    logger.info("Detected ATS for %d / %d unknown domains", len(matched), len(unknown))

    if matched:
        # Tally by ATS
        by_ats: dict[str, int] = {}
        for _, det in matched:
            by_ats[det.ats_platform] = by_ats.get(det.ats_platform, 0) + 1
        logger.info("Breakdown by ATS:")
        for ats, n in sorted(by_ats.items(), key=lambda x: -x[1]):
            logger.info("  %-20s %d", ats, n)

        new_count = insert_source_configs(matched)
        logger.info("Inserted %d new source_configs (out of %d matched)", new_count, len(matched))
        logger.info("They'll be picked up by the next 30-min Celery beat run and start fetching live jobs.")
    else:
        logger.info("No matches. Try a larger --top or lower --min-jobs.")


if __name__ == "__main__":
    asyncio.run(main())
