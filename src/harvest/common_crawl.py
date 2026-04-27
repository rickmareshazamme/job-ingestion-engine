"""Common Crawl JobPosting harvester (streaming, production-grade).

Strategy: Web Data Commons publishes pre-extracted schema.org structured
data from each monthly Common Crawl. We download the JobPosting subset,
filter, normalize, and upsert into our index.

Sources:
- Web Data Commons schema.org JobPosting extracts:
  https://webdatacommons.org/structureddata/2024-12/files.html
- Common Crawl indexes (CC-MAIN-YYYY-WW):
  https://commoncrawl.org/get-started

Two run modes:
1. WDC subset (recommended) — pre-filtered to JobPosting-only, ~1-3GB per crawl
2. Full Common Crawl URL index query — slower, more complete, $100-500 in S3 fees

This module implements (1). Mode (2) is documented at the bottom for reference.

Memory model:
- WDC NQ files are 100MB-2GB compressed. We never load the full body
  in memory: aiohttp streams chunks to a tempfile on disk, then we
  iterate `gzip.open(..., 'rt')` line-by-line.
- The parser keeps an in-flight buffer of "pages whose quads we are
  still accumulating". Because WDC NQ files are sorted by graph URL,
  all quads for one page are contiguous — when the graph changes we
  emit/flush the prior page. A periodic full-flush every FLUSH_EVERY
  lines is a safety valve for unsorted inputs. Worst-case RSS:
  ~FLUSH_EVERY * avg_record_size, which on real WDC data is <50 MB.

Usage (library):
    from src.harvest.common_crawl import iter_raw_jobs
    async for raw in iter_raw_jobs(crawl_id="2024-12", max_files=1):
        ...

Usage (Celery): see src.tasks.crawl.harvest_common_crawl.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import re
import tempfile
from datetime import datetime
from typing import AsyncIterator, Optional
from urllib.parse import urlparse

import aiohttp

from src.connectors.base import RawJob

logger = logging.getLogger("zammejobs.harvest.commoncrawl")

# Web Data Commons schema.org structured data extracts. Their CDN serves
# .nq.gz N-Quads files filtered by schema.org type.
WDC_BASE = "https://webdatacommons.org/structureddata"
DEFAULT_CRAWL = "2024-12"  # Update this monthly

# Pattern: <subject> <predicate> <object> <graph_url> .
QUAD_RE = re.compile(r'^<([^>]+)>\s+<([^>]+)>\s+(.+?)\s+<([^>]+)>\s*\.\s*$')

# Streaming knobs
DOWNLOAD_CHUNK = 1 << 20            # 1 MiB HTTP read chunks
FLUSH_EVERY = 50_000                # safety-valve full flush every N quads
DOWNLOAD_TIMEOUT_SECS = 60 * 60     # WDC files can be huge; 1h ceiling


async def list_wdc_files(crawl_id: str = DEFAULT_CRAWL) -> list[str]:
    """Get the list of JobPosting NQ files for a given crawl from WDC's file index."""
    index_url = f"{WDC_BASE}/{crawl_id}/files/"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.get(index_url) as r:
            if r.status != 200:
                logger.error("WDC index unreachable for %s (HTTP %d)", crawl_id, r.status)
                return []
            html = await r.text()
    files = re.findall(r'href="(JobPosting[^"]+\.nq\.gz)"', html)
    return [f"{WDC_BASE}/{crawl_id}/files/{f}" for f in files]


async def _download_to_tempfile(url: str) -> str:
    """Stream a (potentially multi-GB) URL to a tempfile on disk. Returns path.

    Caller is responsible for unlinking the file when done. Uses a 1 MiB
    chunked read so peak RSS stays in the low MB regardless of file size.
    """
    fd, tmp_path = tempfile.mkstemp(prefix="wdc_", suffix=".nq.gz")
    os.close(fd)
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_SECS, sock_read=120)
    bytes_seen = 0
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as out:
                async for chunk in r.content.iter_chunked(DOWNLOAD_CHUNK):
                    if not chunk:
                        continue
                    out.write(chunk)
                    bytes_seen += len(chunk)
    logger.info("Downloaded %s -> %s (%.1f MiB)", url, tmp_path, bytes_seen / (1 << 20))
    return tmp_path


def _strip_literal(obj: str) -> str:
    """Extract the literal value from an N-Quad object like \"foo\"@en or \"foo\"^^<...>."""
    if obj.startswith('"'):
        end = obj.rfind('"')
        return obj[1:end] if end > 0 else obj.strip('"')
    if obj.startswith("<") and obj.endswith(">"):
        return obj[1:-1]
    return obj


def _record_to_raw_job(url: str, rec: dict) -> Optional[RawJob]:
    """Materialize an in-flight record into a RawJob, or return None if invalid."""
    if not rec.get("title"):
        return None
    try:
        host = urlparse(url).netloc or "commoncrawl-source.invalid"
    except Exception:
        host = "commoncrawl-source.invalid"

    date_posted = None
    dp = rec.get("date_posted")
    if dp:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                date_posted = datetime.strptime(dp[:19], "%Y-%m-%dT%H:%M:%S")
                break
            except ValueError:
                continue

    return RawJob(
        source_type="commoncrawl_jobposting",
        source_id=url,
        source_url=url,
        title=rec.get("title", "")[:500],
        description_html=rec.get("description", "")[:50000],
        employer_name=host,
        employer_domain=host,
        location_raw="",
        employment_type_raw=rec.get("employment_type"),
        date_posted=date_posted,
        categories=[],
        is_remote=None,
        raw_data={"crawl_source": "common_crawl_wdc", "graph_url": url},
    )


def _apply_quad(rec: dict, pred: str, obj: str) -> None:
    """Mutate `rec` with a single (predicate, object) pair from a quad."""
    pred_short = pred.split("/")[-1].lower()
    if pred_short in ("title", "name"):
        rec.setdefault("title", _strip_literal(obj))
    elif pred_short == "description":
        rec.setdefault("description", _strip_literal(obj))
    elif pred_short == "dateposted":
        rec.setdefault("date_posted", _strip_literal(obj))
    elif pred_short in ("validthrough", "expires"):
        rec.setdefault("date_expires", _strip_literal(obj))
    elif pred_short == "employmenttype":
        rec.setdefault("employment_type", _strip_literal(obj))
    elif pred_short == "hiringorganization":
        rec.setdefault("_org_subj", _strip_literal(obj))
    elif pred_short == "joblocation":
        rec.setdefault("_loc_subj", _strip_literal(obj))
    elif pred_short == "basesalary":
        rec.setdefault("_salary_subj", _strip_literal(obj))


def _iter_local_gzip_quads(path: str) -> AsyncIterator[tuple[str, str, str, str]]:
    """Synchronous generator wrapped as async — yields parsed quads from a gzipped file.

    Uses gzip.open(text mode) which decompresses on the fly without ever
    materializing the whole file. We yield in an async generator to keep
    the calling site's await-based control flow intact.
    """
    async def _gen() -> AsyncIterator[tuple[str, str, str, str]]:
        # gzip.open in text mode streams; no full decompression in memory.
        with gzip.open(path, mode="rt", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                m = QUAD_RE.match(line)
                if not m:
                    continue
                # Periodically yield control to the event loop.
                if i and i % 10_000 == 0:
                    await asyncio.sleep(0)
                yield m.group(1), m.group(2), m.group(3), m.group(4)

    return _gen()


async def stream_raw_jobs_from_file(
    file_url: str,
    max_records: Optional[int] = None,
    seen_urls: Optional[set[str]] = None,
) -> AsyncIterator[RawJob]:
    """Stream RawJob records from one WDC .nq.gz file.

    Memory: O(FLUSH_EVERY) records held in flight. Disk: one tempfile equal
    in size to the compressed source. The tempfile is unlinked on exit.

    `seen_urls`, if provided, short-circuits emit when an already-known URL
    is seen — saves the downstream cost of normalizing duplicates.
    """
    logger.info("Harvesting Common Crawl file: %s", file_url)
    tmp_path: Optional[str] = None
    emitted = 0
    try:
        tmp_path = await _download_to_tempfile(file_url)
        in_flight: dict[str, dict] = {}
        current_graph: Optional[str] = None
        line_count = 0

        async for subj, pred, obj, graph in _iter_local_gzip_quads(tmp_path):
            line_count += 1

            # Sorted-input fast path: when graph changes, prior page is complete.
            if current_graph is not None and graph != current_graph:
                rec = in_flight.pop(current_graph, None)
                if rec is not None:
                    if seen_urls is not None and current_graph in seen_urls:
                        pass  # short-circuit duplicate
                    else:
                        raw = _record_to_raw_job(current_graph, rec)
                        if raw is not None:
                            emitted += 1
                            yield raw
                            if max_records and emitted >= max_records:
                                return

            current_graph = graph
            rec = in_flight.get(graph)
            if rec is None:
                rec = {"_subject": subj}
                in_flight[graph] = rec
            _apply_quad(rec, pred, obj)

            # Safety valve for unsorted inputs: hard flush if buffer balloons.
            if line_count % FLUSH_EVERY == 0 and len(in_flight) > 1:
                # Keep the current graph in flight; emit everyone else.
                victims = [g for g in in_flight if g != current_graph]
                for g in victims:
                    rec_v = in_flight.pop(g)
                    if seen_urls is not None and g in seen_urls:
                        continue
                    raw = _record_to_raw_job(g, rec_v)
                    if raw is not None:
                        emitted += 1
                        yield raw
                        if max_records and emitted >= max_records:
                            return

        # End of file — flush whatever is left.
        for g, rec in in_flight.items():
            if seen_urls is not None and g in seen_urls:
                continue
            raw = _record_to_raw_job(g, rec)
            if raw is not None:
                emitted += 1
                yield raw
                if max_records and emitted >= max_records:
                    return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        logger.info("Common Crawl file %s: emitted %d RawJobs", file_url, emitted)


async def iter_raw_jobs(
    crawl_id: str = DEFAULT_CRAWL,
    max_files: int = 3,
    max_records: Optional[int] = None,
    seen_urls: Optional[set[str]] = None,
) -> AsyncIterator[RawJob]:
    """Stream RawJobs across the first `max_files` WDC files for a crawl.

    Stops early when `max_records` is hit. Memory and disk usage are bounded
    per-file (see `stream_raw_jobs_from_file`).
    """
    files = await list_wdc_files(crawl_id)
    if not files:
        logger.warning("No JobPosting files found for crawl %s", crawl_id)
        return

    targets = files[:max_files]
    logger.info(
        "Common Crawl harvest: %d files from crawl %s (of %d available)",
        len(targets), crawl_id, len(files),
    )

    total = 0
    for f in targets:
        try:
            async for raw in stream_raw_jobs_from_file(f, max_records=None, seen_urls=seen_urls):
                yield raw
                total += 1
                if max_records and total >= max_records:
                    return
        except Exception as e:
            logger.warning("Common Crawl file failed: %s — %s", f, str(e)[:200])


# ---------------------------------------------------------------------------
# Backwards-compatible buffered API
#
# Preserves the original function signatures (`harvest_file`, `harvest_latest`)
# for any caller that wants the all-at-once list. Internally these now use
# the streaming generators above so memory is bounded by the caller's
# willingness to hold the result list, not by the source file size.
# ---------------------------------------------------------------------------


async def harvest_file(file_url: str, max_records: Optional[int] = None) -> list[RawJob]:
    """Parse one WDC file into RawJob records (buffered). Streaming under the hood."""
    out: list[RawJob] = []
    async for raw in stream_raw_jobs_from_file(file_url, max_records=max_records):
        out.append(raw)
        if max_records and len(out) >= max_records:
            break
    logger.info("Common Crawl file yielded %d JobPostings", len(out))
    return out


async def harvest_latest(
    crawl_id: str = DEFAULT_CRAWL,
    max_files: int = 3,
    max_records: Optional[int] = None,
) -> list[RawJob]:
    """Fetch the N most recent JobPosting NQ files from WDC and harvest them (buffered)."""
    out: list[RawJob] = []
    async for raw in iter_raw_jobs(crawl_id=crawl_id, max_files=max_files, max_records=max_records):
        out.append(raw)
        if max_records and len(out) >= max_records:
            break
    return out


# ---------------------------------------------------------------------------
# Reference: full Common Crawl URL-index query mode (NOT IMPLEMENTED HERE)
#
# The CDX index lets you query "all URLs containing JobPosting JSON-LD" in
# a given crawl. Pattern:
#   GET https://index.commoncrawl.org/CC-MAIN-{YYYY-WW}-index?url=*&filter=mime:application/ld%2Bjson&output=json
# Then for each match, fetch the WARC range and parse the JSON-LD blob.
# Costs $0.05/GB on AWS S3 for the WARC reads, ~$200-500 per full crawl
# pass. Use only when WDC's pre-extracted set isn't enough.
# ---------------------------------------------------------------------------
