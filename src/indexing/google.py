"""Google Indexing API — instant index/remove for JobPosting URLs.

Docs: https://developers.google.com/search/apis/indexing-api
Auth: service account JSON, scope https://www.googleapis.com/auth/indexing
Free quota: 200 URL submissions / day per project.

Setup:
1. Create a GCP project + enable "Indexing API"
2. Create a service account, download JSON key
3. Set GOOGLE_SA_FILE env var to its path (or paste JSON into the env var directly)
4. Verify domain ownership in Google Search Console + grant the SA owner role

Usage:
    from src.indexing.google import notify_url_updated, notify_url_deleted
    await notify_url_updated("https://zammejobs.com/jobs/abc-123")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import aiohttp

from src.config import settings

logger = logging.getLogger("zammejobs.google_indexing")

ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPE = "https://www.googleapis.com/auth/indexing"


def _load_credentials() -> Optional[dict]:
    raw = settings.google_sa_file
    if not raw:
        return None
    if raw.strip().startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("GOOGLE_SA_FILE looks like inline JSON but didn't parse")
            return None
    if not os.path.isfile(raw):
        logger.error("GOOGLE_SA_FILE path not found: %s", raw)
        return None
    with open(raw) as f:
        return json.load(f)


async def _get_access_token(creds: dict) -> Optional[str]:
    """Exchange service-account JSON for a short-lived OAuth token."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GAuthRequest
    except ImportError:
        logger.error("google-auth not installed — pip install google-auth")
        return None

    sa_creds = service_account.Credentials.from_service_account_info(creds, scopes=[SCOPE])
    sa_creds.refresh(GAuthRequest())
    return sa_creds.token


async def _publish(url: str, action: str) -> bool:
    creds = _load_credentials()
    if not creds:
        logger.debug("Google Indexing credentials not configured — skipping")
        return False

    token = await _get_access_token(creds)
    if not token:
        return False

    payload = {"url": url, "type": action}  # action: URL_UPDATED | URL_DELETED
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        try:
            async with session.post(ENDPOINT, json=payload, headers=headers) as resp:
                if 200 <= resp.status < 300:
                    return True
                body = (await resp.text())[:200]
                logger.warning("Google Indexing %s rejected (%d): %s", action, resp.status, body)
                return False
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.warning("Google Indexing %s failed: %s", action, e)
            return False


async def notify_url_updated(url: str) -> bool:
    """Tell Google a JobPosting URL was created or updated. Triggers near-instant indexing."""
    return await _publish(url, "URL_UPDATED")


async def notify_url_deleted(url: str) -> bool:
    """Tell Google a JobPosting was removed (job filled/expired)."""
    return await _publish(url, "URL_DELETED")
