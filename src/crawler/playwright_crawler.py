"""Headless browser crawler for JS-rendered career pages.

Uses Playwright to render career pages that don't expose public APIs,
then extracts job listings from the DOM.
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from src.config import settings
from src.connectors.base import RawJob


class PlaywrightCrawler:
    """Crawl JS-rendered career pages using a headless browser."""

    def __init__(self):
        self._browser: Optional[Browser] = None

    async def _get_browser(self) -> Browser:
        if self._browser is None:
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
        return self._browser

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None

    async def crawl_career_page(
        self,
        url: str,
        employer_domain: str,
        employer_name: str,
        max_jobs: int = 500,
    ) -> list[RawJob]:
        """Crawl a career page and extract job listings.

        Steps:
        1. Navigate to career page
        2. Wait for job listings to render
        3. Try to extract JobPosting JSON-LD first (highest quality)
        4. Fall back to DOM extraction
        5. Handle pagination
        """
        browser = await self._get_browser()
        context = await browser.new_context(
            user_agent=settings.bot_user_agent,
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Try JSON-LD extraction first
            json_ld_jobs = await self._extract_json_ld(page, employer_domain, employer_name)
            if json_ld_jobs:
                return json_ld_jobs[:max_jobs]

            # Fall back to DOM extraction
            jobs = await self._extract_from_dom(page, url, employer_domain, employer_name)

            # Handle pagination
            page_num = 1
            while len(jobs) < max_jobs and page_num < 25:
                next_clicked = await self._click_next_page(page)
                if not next_clicked:
                    break
                page_num += 1
                await page.wait_for_timeout(2000)
                more_jobs = await self._extract_from_dom(page, url, employer_domain, employer_name)
                if not more_jobs:
                    break
                jobs.extend(more_jobs)

            return jobs[:max_jobs]

        except Exception as e:
            return []
        finally:
            await context.close()

    async def _extract_json_ld(
        self, page: Page, employer_domain: str, employer_name: str
    ) -> list[RawJob]:
        """Extract jobs from JobPosting JSON-LD if present."""
        scripts = await page.query_selector_all('script[type="application/ld+json"]')
        jobs = []

        for script in scripts:
            try:
                content = await script.inner_text()
                data = json.loads(content)

                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    if data.get("@type") == "JobPosting":
                        items = [data]
                    elif "@graph" in data:
                        items = [i for i in data["@graph"] if i.get("@type") == "JobPosting"]

                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue

                    location_parts = []
                    job_location = item.get("jobLocation", {})
                    if isinstance(job_location, dict):
                        address = job_location.get("address", {})
                        if isinstance(address, dict):
                            for key in ["addressLocality", "addressRegion", "addressCountry"]:
                                val = address.get(key, "")
                                if val:
                                    location_parts.append(str(val))
                    location_raw = ", ".join(location_parts)

                    salary_raw = None
                    base_salary = item.get("baseSalary", {})
                    if isinstance(base_salary, dict):
                        value = base_salary.get("value", {})
                        currency = base_salary.get("currency", "")
                        if isinstance(value, dict):
                            min_v = value.get("minValue", "")
                            max_v = value.get("maxValue", "")
                            unit = value.get("unitText", "")
                            salary_raw = f"{currency} {min_v}-{max_v} {unit}".strip()

                    date_posted = None
                    dp_str = item.get("datePosted", "")
                    if dp_str:
                        try:
                            date_posted = datetime.fromisoformat(dp_str[:10])
                        except (ValueError, AttributeError):
                            pass

                    jobs.append(RawJob(
                        source_type="playwright_crawl",
                        source_id=item.get("url", item.get("title", "")),
                        source_url=item.get("url", ""),
                        title=item.get("title", ""),
                        description_html=item.get("description", ""),
                        employer_name=employer_name,
                        employer_domain=employer_domain,
                        location_raw=location_raw,
                        salary_raw=salary_raw,
                        employment_type_raw=item.get("employmentType"),
                        date_posted=date_posted,
                        is_remote=item.get("jobLocationType") == "TELECOMMUTE",
                        raw_data=item,
                    ))

            except (json.JSONDecodeError, Exception):
                continue

        return jobs

    async def _extract_from_dom(
        self, page: Page, base_url: str, employer_domain: str, employer_name: str
    ) -> list[RawJob]:
        """Extract job listings from DOM elements."""
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        jobs = []

        # Common job listing selectors across career sites
        job_selectors = [
            "a[href*='job']", "a[href*='position']", "a[href*='career']",
            "a[href*='opening']", "a[href*='vacancy']",
            ".job-listing a", ".job-card a", ".job-item a",
            "[class*='job'] a", "[class*='position'] a",
            "[data-job] a", "[data-posting] a",
            "tr[class*='job'] a", "li[class*='job'] a",
        ]

        seen_urls = set()

        for selector in job_selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get("href", "")
                if not href or href == "#":
                    continue

                full_url = urljoin(base_url, href)
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                title = link.get_text(strip=True)
                if not title or len(title) < 3 or len(title) > 200:
                    continue

                # Skip navigation/footer links
                skip_words = {"about", "contact", "privacy", "terms", "login", "sign", "home", "blog"}
                if title.lower() in skip_words:
                    continue

                # Extract nearby location/metadata text
                parent = link.parent
                location_raw = ""
                if parent:
                    location_el = parent.select_one("[class*='location'], [class*='city']")
                    if location_el:
                        location_raw = location_el.get_text(strip=True)

                jobs.append(RawJob(
                    source_type="playwright_crawl",
                    source_id=full_url,
                    source_url=full_url,
                    title=title,
                    description_html="",
                    employer_name=employer_name,
                    employer_domain=employer_domain,
                    location_raw=location_raw,
                    raw_data={"crawled_url": base_url},
                ))

        return jobs

    async def _click_next_page(self, page: Page) -> bool:
        """Try to click a next page / load more button."""
        next_selectors = [
            "button:has-text('Load More')",
            "button:has-text('Show More')",
            "button:has-text('View More')",
            "a:has-text('Next')",
            "button:has-text('Next')",
            "[class*='next'] a",
            "[class*='next'] button",
            "[class*='load-more']",
            "[class*='loadMore']",
            "[aria-label='Next page']",
            "[aria-label='next']",
        ]

        for selector in next_selectors:
            try:
                button = await page.query_selector(selector)
                if button and await button.is_visible():
                    await button.click()
                    return True
            except Exception:
                continue

        return False

    async def fetch_job_detail(self, url: str) -> dict:
        """Fetch full job details from a detail page."""
        browser = await self._get_browser()
        context = await browser.new_context(user_agent=settings.bot_user_agent)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(1000)
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Extract description from common containers
            desc_selectors = [
                ".job-description", ".job-details", ".job-content",
                "[class*='description']", "[class*='details']",
                "article", "main",
            ]

            description = ""
            for sel in desc_selectors:
                el = soup.select_one(sel)
                if el and len(el.get_text(strip=True)) > 100:
                    description = str(el)
                    break

            return {"description_html": description, "url": url}

        except Exception:
            return {"description_html": "", "url": url}
        finally:
            await context.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
