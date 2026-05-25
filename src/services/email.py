"""Minimal email sender — SendGrid v3 HTTP API.

No SDK; just an httpx POST to https://api.sendgrid.com/v3/mail/send.
Set SENDGRID_API_KEY in Railway env to enable. Without the key, send()
logs a warning and returns False — the rest of the system continues
running so we can ship alert infrastructure before email is wired in.

Also exposes signed_token() / verify_token() helpers used by the alerts
flow for confirm + unsubscribe links.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import httpx
from itsdangerous import BadSignature, URLSafeSerializer

logger = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

_SECRET = os.getenv("APP_SECRET_KEY") or "dev-secret-do-not-use-in-prod"
_serializer = URLSafeSerializer(_SECRET, salt="zammejobs-alerts")


def signed_token(payload: dict) -> str:
    return _serializer.dumps(payload)


def verify_token(token: str) -> Optional[dict]:
    try:
        return _serializer.loads(token)
    except BadSignature:
        return None


_NAME_ADDR_RE = re.compile(r"^\s*(?P<name>.*?)\s*<\s*(?P<email>[^>]+?)\s*>\s*$")


def _parse_from(raw: str) -> dict:
    """Accept either 'foo@bar.com' or 'Display Name <foo@bar.com>' and
    return SendGrid's {email, name?} shape.

    Defensively strips surrounding quotes / whitespace because Railway's
    env-var UI sometimes captures the literal '"' if a user pastes a
    quoted value."""
    raw = (raw or "").strip().strip('"').strip("'").strip()
    m = _NAME_ADDR_RE.match(raw)
    if m:
        return {"email": m.group("email").strip(), "name": m.group("name").strip()}
    return {"email": raw}


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
    *,
    from_addr: Optional[str] = None,
) -> bool:
    """Send via SendGrid. Returns True on 2xx, False otherwise (or if no key)."""
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        logger.warning("send_email skipped — SENDGRID_API_KEY not configured. to=%s subject=%r", to, subject)
        return False

    sender_raw = from_addr or os.getenv("EMAIL_FROM") or "ZammeJobs <alerts@zammejobs.com>"
    body = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": _parse_from(sender_raw),
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    if text:
        # SendGrid requires text/plain BEFORE text/html when both supplied.
        body["content"] = [
            {"type": "text/plain", "value": text},
            {"type": "text/html", "value": html},
        ]

    # Strip whitespace defensively — Railway env values sometimes carry
    # trailing newlines that break the Authorization header.
    api_key = api_key.strip()

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                SENDGRID_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
            if resp.status_code >= 300:
                logger.warning(
                    "SendGrid send failed status=%d body=%s from=%r to=%s",
                    resp.status_code, resp.text[:400],
                    body.get("from"), to,
                )
                return False
            logger.info("SendGrid send OK to=%s subject=%r status=%d", to, subject, resp.status_code)
            return True
        except Exception as e:
            logger.warning("SendGrid send error: %s (to=%s)", e, to)
            return False
