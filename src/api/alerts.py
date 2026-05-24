"""Job alerts — subscribe, confirm, unsubscribe.

UI lives at /alerts with a single form: email + natural-language query.
On submit we create a JobAlert row in 'unconfirmed' state, generate a
signed confirmation token, and email it. Double opt-in. Every alert
email also carries a one-click unsubscribe token.

Sending the alerts themselves is a Celery beat task — see
src.tasks.crawl.send_due_alerts (added in same release).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url
from src.db import get_session
from src.models import JobAlert
from src.services.email import send_email, signed_token, verify_token

router = APIRouter(tags=["Alerts"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, status: Optional[str] = None):
    canonical = _canonical_url("/alerts")
    return templates.TemplateResponse(request, "alerts.html", {
        "title": "Get job alerts in your inbox | ZammeJobs",
        "description": "Subscribe to a natural-language job alert. ZammeJobs emails you when new matching roles land. No account required.",
        "canonical_url": canonical, "status": status,
    })


@router.post("/alerts/subscribe")
async def alerts_subscribe(
    request: Request,
    email: str = Form(...),
    query: str = Form(...),
    cadence: str = Form("daily"),
    session: AsyncSession = Depends(get_session),
):
    email = email.strip().lower()
    if "@" not in email or "." not in email:
        return RedirectResponse("/alerts?status=invalid_email", status_code=303)
    if not query.strip():
        return RedirectResponse("/alerts?status=missing_query", status_code=303)
    if cadence not in ("daily", "weekly", "instant"):
        cadence = "daily"

    alert_id = uuid.uuid4()
    token = signed_token({"alert_id": str(alert_id), "purpose": "confirm"})

    alert = JobAlert(
        id=alert_id, email=email, query=query.strip(),
        cadence=cadence, is_confirmed=False, is_active=True,
        confirm_token=token,
    )
    session.add(alert)
    await session.commit()

    confirm_url = _canonical_url(f"/alerts/confirm?token={token}")
    html = f"""<!doctype html><html><body style="font-family: -apple-system, sans-serif; max-width: 520px; margin: 2rem auto; color: #111;">
<h2 style="color: #EC008C;">Confirm your ZammeJobs alert</h2>
<p>You asked us to alert you about: <strong>{query}</strong></p>
<p>Confirm with one click to start receiving {cadence} matches:</p>
<p><a href="{confirm_url}" style="display: inline-block; background: #EC008C; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600;">Confirm subscription</a></p>
<p style="color: #6b7280; font-size: 13px;">If you didn't request this, ignore the email — nothing is sent until you confirm.</p>
<p style="color: #6b7280; font-size: 13px;">ZammeJobs · <a href="https://www.zammejobs.com" style="color: #EC008C;">www.zammejobs.com</a></p>
</body></html>"""
    await send_email(email, "Confirm your ZammeJobs alert", html)
    return RedirectResponse("/alerts?status=check_email", status_code=303)


@router.get("/alerts/confirm")
async def alerts_confirm(token: str, session: AsyncSession = Depends(get_session)):
    payload = verify_token(token)
    if not payload or payload.get("purpose") != "confirm":
        return RedirectResponse("/alerts?status=bad_token", status_code=303)
    alert_id = payload.get("alert_id")
    if not alert_id:
        return RedirectResponse("/alerts?status=bad_token", status_code=303)

    await session.execute(
        update(JobAlert)
        .where(JobAlert.id == uuid.UUID(alert_id))
        .values(is_confirmed=True, confirm_token=None)
    )
    await session.commit()
    return RedirectResponse("/alerts?status=confirmed", status_code=303)


@router.get("/alerts/unsubscribe")
async def alerts_unsubscribe(token: str, session: AsyncSession = Depends(get_session)):
    payload = verify_token(token)
    if not payload or payload.get("purpose") != "unsubscribe":
        return RedirectResponse("/alerts?status=bad_token", status_code=303)
    alert_id = payload.get("alert_id")
    if not alert_id:
        return RedirectResponse("/alerts?status=bad_token", status_code=303)

    await session.execute(
        update(JobAlert)
        .where(JobAlert.id == uuid.UUID(alert_id))
        .values(is_active=False)
    )
    await session.commit()
    return RedirectResponse("/alerts?status=unsubscribed", status_code=303)
