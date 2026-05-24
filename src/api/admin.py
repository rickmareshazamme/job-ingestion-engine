"""Admin endpoints for one-off ops. Token-gated."""

from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select
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


@router.get("/shazamme-status")
async def shazamme_status(
    x_admin_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Snapshot of the Shazamme ingestion state."""
    _check_token(x_admin_token)

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
