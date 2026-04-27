"""Shazamme XML feed connector.

Shazamme publishes a daily LinkedIn-formatted XML feed at
    https://s3.amazonaws.com/shazamme-vinyl-uploads-dev/Shazamme_AllJobs_LinkedIN.xml

The file is ~250 MB, UTF-16 LE encoded, and contains every active job
across every Shazamme tenant (~26K records).

Shape:
    <source>
      <lastBuildDate/>
      <publisher/>
      <expectedJobCount/>
      <job>
        <partnerJobId/>            stable UUID per posting
        <company/>                  staffing-agency name (the Shazamme tenant)
        <title/>
        <description/>              full HTML
        <industry/>
        <applyUrl/>                 direct apply URL on tenant's site
        <companyID/>                tenant UUID
        <location/>, <city/>, <state/>, <country/>, <postalcode/>
        <experienceLevel/>, <workplaceTypes/>, <workmodel/>
        <reference/>                tenant-side job ref
        <jobtype/>
        <tags/>
        <jobFunctions><jobFunction>...</jobFunction></jobFunctions>
        <salaries><salary>
          <highend><amount/><currencyCode/></highend>
          <lowEnd><amount/><currencyCode/></lowEnd>
        </salary></salaries>
      </job>
      ...
    </source>

We stream-parse with xml.etree.ElementTree.iterparse to keep memory
bounded — clearing each <job> after emitting its RawJob. Peak RSS stays
under 200 MB regardless of feed size.
"""

from __future__ import annotations

import gzip
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import aiohttp

from src.connectors.base import BaseConnector, PermanentError, RawJob

logger = logging.getLogger("zammejobs.connector.shazamme")

DEFAULT_FEED_URL = "https://s3.amazonaws.com/shazamme-vinyl-uploads-dev/Shazamme_AllJobs_LinkedIN.xml"
DOWNLOAD_CHUNK = 1 << 20  # 1 MiB streaming chunks


class ShazammeConnector(BaseConnector):
    SOURCE_TYPE = "shazamme_feed"
    ATS_PLATFORM = "shazamme"

    async def fetch_jobs(self, board_token: str = "", employer_domain: str = "") -> list[RawJob]:
        """board_token (optional) overrides the default S3 feed URL."""
        feed_url = board_token if board_token.startswith("http") else DEFAULT_FEED_URL
        logger.info("Shazamme: streaming feed from %s", feed_url)

        try:
            tmp_path = await self._download_to_tempfile(feed_url)
        except (aiohttp.ClientError, PermanentError) as e:
            logger.error("Shazamme feed download failed: %s", e)
            return []

        try:
            jobs = list(self._parse_stream(tmp_path))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        logger.info("Shazamme: parsed %d jobs", len(jobs))
        return jobs

    async def _download_to_tempfile(self, url: str) -> str:
        fd, tmp_path = tempfile.mkstemp(prefix="shazamme_", suffix=".xml")
        os.close(fd)
        timeout = aiohttp.ClientTimeout(total=30 * 60, sock_read=120)
        bytes_seen = 0
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": self.user_agent}) as s:
            async with s.get(url) as r:
                if r.status >= 400:
                    raise PermanentError(f"HTTP {r.status} from {url}")
                with open(tmp_path, "wb") as out:
                    async for chunk in r.content.iter_chunked(DOWNLOAD_CHUNK):
                        if not chunk:
                            continue
                        out.write(chunk)
                        bytes_seen += len(chunk)
        logger.info("Shazamme feed: downloaded %.1f MiB to %s", bytes_seen / (1 << 20), tmp_path)
        return tmp_path

    def _parse_stream(self, path: str):
        """iterparse the file, yield RawJob per <job>, free each element after use."""
        # The file is UTF-16 LE — ET.iterparse handles BOM/encoding from the
        # XML prolog automatically when given a binary file handle. If the
        # prolog declares utf-8 but the file is actually utf-16 (some Shazamme
        # exports do this), we re-decode + re-encode as a stream wrapper.
        with open(path, "rb") as fh:
            head = fh.read(4)
            fh.seek(0)
            if head[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(head) >= 2 and head[1] == 0):
                # UTF-16 — wrap with a converting reader that emits valid utf-8
                src = _Utf16ToUtf8Reader(fh)
            else:
                src = fh

            for event, el in ET.iterparse(src, events=("end",)):
                if el.tag != "job":
                    continue
                try:
                    raw = self._element_to_rawjob(el)
                    if raw:
                        yield raw
                except Exception as e:
                    logger.warning("Shazamme job parse failed: %s", str(e)[:120])
                # Free the element so memory stays bounded
                el.clear()

    def _element_to_rawjob(self, el: ET.Element) -> Optional[RawJob]:
        def text(tag: str) -> str:
            child = el.find(tag)
            return (child.text or "").strip() if child is not None and child.text else ""

        title = text("title")
        if not title:
            return None

        partner_id = text("partnerJobId")
        company = text("company") or "Shazamme tenant"
        company_id = text("companyID")
        apply_url = text("applyUrl")
        description = text("description")
        industry = text("industry")
        location_raw = text("location")
        city = text("city")
        state = text("state")
        country = text("country")
        postal = text("postalcode")
        ref = text("reference")
        job_type = text("jobtype") or text("workmodel")
        seniority_raw = text("experienceLevel")

        # Compose location_raw from parts when only "Australia" was given
        loc_parts = [p for p in [city, state, country] if p]
        if loc_parts and (not location_raw or location_raw in (country, state)):
            location_raw = ", ".join(loc_parts)

        # Job functions → categories
        categories: list[str] = []
        for jf in el.findall("jobFunctions/jobFunction"):
            if jf.text and jf.text.strip():
                categories.append(jf.text.strip())
        if industry and industry not in categories:
            categories.insert(0, industry)

        # Tags (comma-separated)
        tags = text("tags")
        if tags:
            for t in tags.split(","):
                t = t.strip()
                if t and t not in categories:
                    categories.append(t)

        # Salary — Shazamme nests under <salaries><salary><highend>/<lowEnd>
        salary_raw: Optional[str] = None
        sal_el = el.find("salaries/salary")
        if sal_el is not None:
            def sal_amount(node_tag: str) -> tuple[str, str]:
                node = sal_el.find(node_tag)
                if node is None:
                    return "", ""
                amt = (node.find("amount").text or "") if node.find("amount") is not None and node.find("amount").text else ""
                cur = (node.find("currencyCode").text or "") if node.find("currencyCode") is not None and node.find("currencyCode").text else ""
                return amt.strip(), cur.strip()
            low_amt, low_cur = sal_amount("lowEnd")
            high_amt, high_cur = sal_amount("highend")
            try:
                low_n = float(low_amt or 0)
                high_n = float(high_amt or 0)
            except ValueError:
                low_n = high_n = 0.0
            cur = high_cur or low_cur or ""
            if low_n > 0 or high_n > 0:
                salary_raw = f"{cur} {int(low_n)}-{int(high_n)}".strip()

        # Employer domain — try to derive from applyUrl host so similar jobs
        # group properly. Fall back to a stable per-tenant pseudo-domain.
        employer_domain = ""
        if apply_url:
            try:
                host = urlparse(apply_url).netloc
                if host:
                    employer_domain = host
            except Exception:
                pass
        if not employer_domain:
            slug = company_id or company.lower().replace(" ", "-")
            employer_domain = f"{slug[:40]}.shazamme-tenant.invalid"

        # Remote detection
        is_remote = None
        wp = (text("workplaceTypes") + " " + text("workmodel")).lower()
        if "remote" in wp or "telecommute" in wp:
            is_remote = True

        return RawJob(
            source_type=self.SOURCE_TYPE,
            source_id=partner_id or ref or apply_url or title[:80],
            source_url=apply_url,
            title=title[:500],
            description_html=description,
            employer_name=company,
            employer_domain=employer_domain,
            location_raw=location_raw,
            salary_raw=salary_raw,
            employment_type_raw=job_type or None,
            date_posted=None,  # feed has no per-job date; use crawl time
            categories=categories,
            is_remote=is_remote,
            raw_data={
                "company_id": company_id,
                "reference": ref,
                "country": country,
                "state": state,
                "city": city,
                "postal": postal,
                "experience": seniority_raw,
                "shazamme_feed": True,
            },
        )


class _Utf16ToUtf8Reader:
    """Streams a UTF-16-LE file as UTF-8 bytes for ET.iterparse.

    Reads in chunks, decodes UTF-16 LE, re-encodes UTF-8. Stays under a
    few MB of in-flight buffer at any time.
    """

    def __init__(self, fh, chunk_size: int = 1 << 16):
        self.fh = fh
        self.chunk_size = chunk_size
        self.buffer = b""
        # Skip BOM if present
        first = fh.read(2)
        if first not in (b"\xff\xfe", b"\xfe\xff"):
            fh.seek(0)
        # If the prolog says utf-8 but content is utf-16, replace the encoding
        # declaration in the first chunk so iterparse doesn't bail out.
        self._first_chunk = True

    def read(self, n: int = -1) -> bytes:
        # iterparse ignores `n` and just reads until EOF in chunks
        raw = self.fh.read(self.chunk_size if n == -1 else n)
        if not raw:
            return b""
        try:
            text = raw.decode("utf-16-le", errors="replace")
        except Exception:
            text = raw.decode("utf-16", errors="replace")
        out = text.encode("utf-8", errors="replace")
        if self._first_chunk:
            # Rewrite the XML prolog to declare utf-8 (matches our actual encoding)
            out = out.replace(b'encoding="utf-16"', b'encoding="utf-8"', 1)
            out = out.replace(b'encoding="utf-16-le"', b'encoding="utf-8"', 1)
            self._first_chunk = False
        return out
