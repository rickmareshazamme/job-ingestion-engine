"""Minimal email sender — Resend HTTP API.

No SDK; just an httpx POST to https://api.resend.com/emails. Set
RESEND_API_KEY in Railway env to enable. Without the key, send() logs
a warning and returns False — the rest of the system continues running
so we can ship alert infrastructure before email is wired in.

Also exposes signed_token() / verify_token() helpers used by the alerts
flow for confirm + unsubscribe links.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from itsdangerous import BadSignature, URLSafeSerializer

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"

_SECRET = os.getenv("APP_SECRET_KEY") or "dev-secret-do-not-use-in-prod"
_serializer = URLSafeSerializer(_SECRET, salt="zammejobs-alerts")


def signed_token(payload: dict) -> str:
    return _serializer.dumps(payload)


def verify_token(token: str) -> Optional[dict]:
    try:
        return _serializer.loads(token)
    except BadSignature:
        return None


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
    *,
    from_addr: Optional[str] = None,
) -> bool:
    """Send via Resend. Returns True on 2xx, False otherwise (or if no key)."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        logger.warning("send_email skipped — RESEND_API_KEY not configured. to=%s subject=%r", to, subject)
        return False

    sender = from_addr or os.getenv("EMAIL_FROM") or "ZammeJobs <alerts@zammejobs.com>"
    body = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        body["text"] = text

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code >= 300:
                logger.warning("Resend send failed status=%d body=%s", resp.status_code, resp.text[:300])
                return False
            return True
        except Exception as e:
            logger.warning("Resend send error: %s", e)
            return False
