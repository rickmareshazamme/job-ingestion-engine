"""Admin endpoints for one-off ops. Token-gated."""

from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from src.config import settings
from src.db import get_session
from src.models import Job, SourceConfig

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"], include_in_schema=False)


def _check_token(x_admin_token: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN") or settings.indexnow_key
    if not expected:
        raise HTTPException(503, "admin endpoints disabled (no token configured)")
    if x_admin_token != expected:
        raise HTTPException(401, "invalid admin token")


@router.post("/import-shazamme")
def import_shazamme(x_admin_token: str | None = Header(default=None)):
    """Spawn scripts.import_shazamme as a detached subprocess. Returns immediately."""
    _check_token(x_admin_token)
    log_path = "/tmp/shazamme_import.log"
    proc = subprocess.Popen(
        ["python3", "-m", "scripts.import_shazamme"],
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=os.environ.copy(),
    )
    return {"status": "dispatched", "pid": proc.pid, "log_path": log_path}


@router.post("/indexnow-bulk")
def indexnow_bulk(x_admin_token: str | None = Header(default=None)):
    """Bulk-submit every active job URL to IndexNow (Bing/Yandex/Naver/Seznam).
    Spawns scripts.indexnow_bulk_submit in the background."""
    _check_token(x_admin_token)
    log_path = "/tmp/indexnow_bulk.log"
    proc = subprocess.Popen(
        ["python3", "-m", "scripts.indexnow_bulk_submit"],
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=os.environ.copy(),
    )
    return {"status": "dispatched", "pid": proc.pid, "log_path": log_path}


@router.get("/db-schema")
async def db_schema(session: AsyncSession = Depends(get_session)):
    """Live DB schema snapshot. No auth — reveals only column metadata,
    no row data. Use to confirm migrations applied."""
    alembic_version = None
    try:
        r = await session.execute(text("SELECT version_num FROM alembic_version"))
        alembic_version = r.scalar_one_or_none()
    except Exception as e:
        alembic_version = f"<error: {e}>"

    cols = []
    try:
        r = await session.execute(text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_name = 'employers' "
            "ORDER BY ordinal_position"
        ))
        cols = [{"name": row[0], "type": row[1], "nullable": row[2]} for row in r.all()]
    except Exception as e:
        cols = [{"error": str(e)}]

    triggers = []
    try:
        r = await session.execute(text(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE event_object_table = 'employers'"
        ))
        triggers = [row[0] for row in r.all()]
    except Exception as e:
        triggers = [f"<error: {e}>"]

    slug_count = None
    try:
        r = await session.execute(text("SELECT COUNT(*) FROM employers WHERE slug IS NOT NULL"))
        slug_count = r.scalar_one_or_none()
    except Exception as e:
        slug_count = f"<error: {e}>"

    return {
        "alembic_version": alembic_version,
        "employers_columns": cols,
        "employers_triggers": triggers,
        "employers_with_slug": slug_count,
    }


@router.get("/shazamme-status")
async def shazamme_status(session: AsyncSession = Depends(get_session)):
    """Snapshot of the Shazamme ingestion state. Read-only, no auth — same
    counts are already exposed on /api/v1/stats; this endpoint just
    breaks them out by source_type and tails the import log."""
    sc_count = (await session.execute(
        select(func.count()).select_from(SourceConfig)
        .where(SourceConfig.source_type == "shazamme_feed")
    )).scalar() or 0

    job_count = (await session.execute(
        select(func.count()).select_from(Job)
        .where(Job.source_type == "shazamme_feed")
    )).scalar() or 0

    active_shazamme = (await session.execute(
        select(func.count()).select_from(Job)
        .where(Job.source_type == "shazamme_feed", Job.status == "active")
    )).scalar() or 0

    hidden_non_shazamme = (await session.execute(
        select(func.count()).select_from(Job)
        .where(Job.source_type != "shazamme_feed", Job.status == "hidden")
    )).scalar() or 0

    # Tail the import log if it exists
    log_tail = None
    try:
        with open("/tmp/shazamme_import.log", "rb") as f:
            data = f.read()[-4000:]
            log_tail = data.decode("utf-8", errors="replace")
    except FileNotFoundError:
        pass

    return {
        "source_configs": sc_count,
        "shazamme_jobs_total": job_count,
        "shazamme_jobs_active": active_shazamme,
        "non_shazamme_hidden": hidden_non_shazamme,
        "shazamme_only_ingestion": settings.shazamme_only_ingestion,
        "log_tail": log_tail,
    }


@router.get("/email-config", include_in_schema=False)
def email_config(x_admin_token: str | None = Header(default=None)):
    """Diagnostic — confirm which of the email-related env vars are set
    on THIS process (web service). Returns booleans + lengths only;
    never echoes the actual key values.

    To check the beat service, hit this from a Railway shell into beat
    (or temporarily expose beat over HTTP)."""
    _check_token(x_admin_token)
    sg = os.environ.get("SENDGRID_API_KEY") or ""
    secret = os.environ.get("APP_SECRET_KEY") or ""
    anth = os.environ.get("ANTHROPIC_API_KEY") or ""
    return {
        "sendgrid_api_key_set": bool(sg),
        "sendgrid_api_key_len": len(sg),
        "sendgrid_api_key_prefix": (sg[:3] + "…") if sg else None,
        "email_from": os.environ.get("EMAIL_FROM") or "(default) ZammeJobs <alerts@zammejobs.com>",
        "app_secret_key_set": bool(secret),
        "app_secret_key_len": len(secret),
        "app_secret_key_is_dev_default": secret == "" or secret == "dev-secret-do-not-use-in-prod",
        "anthropic_api_key_set": bool(anth),
        "anthropic_api_key_len": len(anth),
        "resend_api_key_set_legacy": bool(os.environ.get("RESEND_API_KEY")),  # warn if old var still hanging around
    }


@router.post("/email-test", include_in_schema=False)
async def email_test(
    to: str,
    x_admin_token: str | None = Header(default=None),
):
    """Send a one-off test email to `to`. Returns the boolean result
    and a hint if it failed."""
    _check_token(x_admin_token)
    from src.services.email import send_email
    html = """<!doctype html><html><body style="font-family:-apple-system,sans-serif;padding:24px;color:#111;">
<h2 style="color:#EC008C;">ZammeJobs email pipeline test</h2>
<p>If you're reading this, SendGrid + Railway env vars + DNS are all wired correctly.</p>
<p style="color:#6b7280;font-size:13px;">Sent at deploy time from /api/v1/admin/email-test.</p>
</body></html>"""
    ok = await send_email(to, "ZammeJobs — test email", html)
    return {
        "sent": ok,
        "hint": None if ok else (
            "Check: SENDGRID_API_KEY env is set on the web service, "
            "domain authentication is verified in SendGrid, and EMAIL_FROM "
            "uses a verified sender. Also check the web service logs for "
            "'SendGrid send failed' or 'send_email skipped' lines."
        ),
    }
