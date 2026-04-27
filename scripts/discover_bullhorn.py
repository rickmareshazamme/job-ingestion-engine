"""Discover Bullhorn customer corporationIds and write data/bullhorn_corps.txt.

Bullhorn powers ~10,000 staffing agencies globally. Each customer's public
job board exposes their `corporationId` either:

  (a) embedded in the page HTML at {slug}.bullhornstaffing.com/jobs, OR
  (b) reachable directly by querying the public-rest endpoint with the
      corp_id and seeing whether it returns jobs (valid) or 401 (invalid).

This script combines multiple discovery vectors to build a comprehensive
seed table. Output: data/bullhorn_corps.txt — CSV `slug,corp_id,swimlane,public_url,name`.

Vectors implemented:
  1. SLUG_LIST — probe known staffing-agency vanity slugs (seed list)
  2. CORP_ID_ENUM — iterate corp_ids 1..10000 against each public-rest
     swimlane and keep the ones returning data

Usage:
    # Probe the seed list of known agencies (fast, ~5 min)
    python3 -m scripts.discover_bullhorn --slugs

    # Exhaustive corp_id enumeration (~2 hours, ~6,000-8,000 results)
    python3 -m scripts.discover_bullhorn --enumerate

    # Both (recommended — slugs first, then enum, deduped)
    python3 -m scripts.discover_bullhorn --slugs --enumerate

    # Limit enum range for testing
    python3 -m scripts.discover_bullhorn --enumerate --enum-start 1 --enum-end 500
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import sys
from pathlib import Path

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("discover_bullhorn")

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "bullhorn_corps.txt"

USER_AGENT = "ZammeJobsBot/1.0 (+https://zammejobs.com/bot; bullhorn-discovery)"
SWIMLANES = [30, 31, 32, 33, 40, 41, 42, 43, 44]  # known shards as of 2026
ENUM_PARALLEL = 30
SLUG_PARALLEL = 20

# Seed list of known staffing-agency Bullhorn slugs. Curated from Bullhorn's
# own customer pages + LinkedIn + recruiting industry directories. Replace
# or extend with your own list of 100+ known clients.
SEED_SLUGS = [
    # US large staffing
    "kforce", "aerotek", "insightglobal", "robertshaw", "thinkfbi",
    "tek-systems", "teksystems", "randstad", "manpower", "kellyservices",
    "addisongroup", "judge", "mondo", "syseng", "talentcruit",
    "yoh", "wsi", "questsg", "modis", "experis",
    # Healthcare / IT / engineering staffing
    "medical-staffing-network", "healthtrust", "trustaff", "crosscountry",
    "favoritehealthcare", "supplementalhealth", "atlasmed", "soliant",
    "rs-eng", "actalent", "cyberco", "diversant", "softworld",
    # UK / EU staffing
    "hays", "robertwalters", "michaelpage", "sthree", "harvey-nash",
    "computer-futures", "real-staffing", "huxley",
    # AU / NZ staffing
    "talent-international", "morgan-mckinley", "michael-page-au",
    # APAC
    "rgf", "robertwalters-jp", "hays-au", "hays-jp",
    # Specialist
    "mainstreaminvestor", "frankrecruitment", "frgconsulting",
    "ageofknow", "venturi", "harnham", "arrowsofttech",
    "the-burnie-group", "bcg-staffing", "talent-acquisition-group",
]


async def probe_slug(session: aiohttp.ClientSession, slug: str) -> dict | None:
    """Try to scrape corporationId + swimlane from {slug}.bullhornstaffing.com/jobs."""
    for path in ("/jobs", "/", "/jobboard"):
        url = f"https://{slug}.bullhornstaffing.com{path}"
        try:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status >= 400:
                    continue
                html = await r.text()
            corp = None
            swim = None
            m = re.search(r'["\']corporationId["\']\s*:\s*["\']?(\d+)', html)
            if m:
                corp = m.group(1)
            else:
                m = re.search(r'corporationId\s*=\s*["\']?(\d+)', html)
                if m:
                    corp = m.group(1)
            m = re.search(r'public-rest(\d+)\.bullhornstaffing\.com', html)
            if m:
                swim = m.group(1)
            else:
                m = re.search(r'["\']swimlane["\']\s*:\s*["\']?(\d+)', html)
                if m:
                    swim = m.group(1)
            if corp:
                return {"slug": slug, "corp_id": corp, "swimlane": swim or "", "public_url": url, "name": slug}
        except (aiohttp.ClientError, TimeoutError):
            continue
    return None


async def probe_corp_id(session: aiohttp.ClientSession, corp_id: int) -> dict | None:
    """For each swimlane, hit the public-rest endpoint with corp_id and a count=1
    JobBoardPost query. Valid corp_ids return data (or 0 jobs but valid auth);
    invalid ones return badCorpToken or 401.
    """
    for swim in SWIMLANES:
        url = (
            f"https://public-rest{swim}.bullhornstaffing.com/rest-services/{corp_id}/"
            f"query/JobBoardPost?fields=id&where=isPublic%3D1&count=1&start=0"
        )
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    body = await r.json(content_type=None)
                    if isinstance(body, dict) and "data" in body:
                        return {
                            "slug": f"corp-{corp_id}",
                            "corp_id": str(corp_id),
                            "swimlane": str(swim),
                            "public_url": "",
                            "name": f"Bullhorn corp #{corp_id}",
                        }
        except (aiohttp.ClientError, TimeoutError, ValueError):
            continue
    return None


def _read_existing() -> dict[str, dict]:
    """Read the existing output file (if any) so we can dedupe and keep human-curated names."""
    if not OUTPUT.exists():
        return {}
    rows: dict[str, dict] = {}
    with open(OUTPUT, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",", 4)]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            slug, corp, swim, url, name = (parts + ["", "", ""])[:5]
            rows[corp] = {"slug": slug, "corp_id": corp, "swimlane": swim, "public_url": url, "name": name}
    return rows


def _write(rows: dict[str, dict]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("# slug,corp_id,swimlane,public_url,name\n")
        f.write("# Generated by scripts/discover_bullhorn.py — extend or hand-edit as needed.\n")
        for corp_id in sorted(rows.keys(), key=lambda x: (len(x), x)):
            r = rows[corp_id]
            f.write(f"{r['slug']},{r['corp_id']},{r.get('swimlane','')},{r.get('public_url','')},{r.get('name','')}\n")
    logger.info("Wrote %d rows to %s", len(rows), OUTPUT)


async def run_slugs(session: aiohttp.ClientSession, slugs: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(SLUG_PARALLEL)

    async def one(s):
        async with sem:
            return await probe_slug(session, s)

    results = await asyncio.gather(*(one(s) for s in slugs))
    found = [r for r in results if r]
    logger.info("Slug probe: %d/%d slugs returned a corporationId", len(found), len(slugs))
    return found


async def run_enum(session: aiohttp.ClientSession, start: int, end: int) -> list[dict]:
    sem = asyncio.Semaphore(ENUM_PARALLEL)
    found: list[dict] = []

    async def one(cid):
        async with sem:
            r = await probe_corp_id(session, cid)
            if r:
                found.append(r)
                logger.info("Found corp_id %s on swimlane %s", r["corp_id"], r["swimlane"])
            return r

    total = end - start + 1
    logger.info("Enumerating corp_ids %d..%d (%d candidates, %d parallel)", start, end, total, ENUM_PARALLEL)
    await asyncio.gather(*(one(cid) for cid in range(start, end + 1)))
    logger.info("Enum: %d valid corp_ids found in range", len(found))
    return found


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--slugs", action="store_true", help="Probe seed slug list")
    p.add_argument("--enumerate", action="store_true", help="Iterate corp_ids 1..10000")
    p.add_argument("--enum-start", type=int, default=1)
    p.add_argument("--enum-end", type=int, default=10000)
    p.add_argument("--slug-list", type=str, help="Optional path to extra slug list (one per line)")
    args = p.parse_args()

    if not args.slugs and not args.enumerate:
        p.error("Pass --slugs and/or --enumerate")

    rows = _read_existing()
    logger.info("Starting with %d existing rows", len(rows))

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html"}
    async with aiohttp.ClientSession(headers=headers) as session:
        if args.slugs:
            slugs = list(SEED_SLUGS)
            if args.slug_list and Path(args.slug_list).exists():
                with open(args.slug_list) as f:
                    slugs.extend(s.strip() for s in f if s.strip() and not s.startswith("#"))
                slugs = list(dict.fromkeys(slugs))
            new = await run_slugs(session, slugs)
            for r in new:
                rows[r["corp_id"]] = r
            _write(rows)

        if args.enumerate:
            new = await run_enum(session, args.enum_start, args.enum_end)
            for r in new:
                # Don't overwrite slug-discovered rows (they have nicer names)
                if r["corp_id"] not in rows:
                    rows[r["corp_id"]] = r
            _write(rows)

    logger.info("Done. Total rows: %d", len(rows))


if __name__ == "__main__":
    asyncio.run(main())
