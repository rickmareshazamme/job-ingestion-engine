"""Map view — /map page + /api/v1/jobs/map data endpoint.

Returns clustered city pins, not individual jobs. With 60K jobs we can't
ship raw markers to the browser; clustering by (location_lat,location_lng)
rounded to ~10km gives ~5K stable clusters across the world map.
"""

from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Job

router = APIRouter(tags=["Map"])
templates = Jinja2Templates(directory="src/templates")


# Round to 0.1 degree (~11km) for cluster aggregation
def _round(v: float) -> float:
    return round(v * 10) / 10


@router.get("/api/v1/jobs/map", summary="Job clusters by location for map rendering")
async def jobs_map(
    request: Request,
    country: Optional[str] = Query(None, description="ISO alpha-2 country filter, e.g. US, GB, AU"),
    q: Optional[str] = Query(None, description="Title keyword filter"),
    remote: Optional[bool] = None,
    employment_type: Optional[str] = None,
    limit: int = Query(5000, le=10000),
    session: AsyncSession = Depends(get_session),
):
    """Return job clusters as `{clusters: [{lat, lng, count, top_titles, top_employer}]}`.

    Pre-aggregated server-side. Markers cluster at ~11km grid; client-side
    Leaflet.markercluster handles further visual clustering at low zoom.
    """
    # Base query: only jobs with coords
    stmt = (
        select(
            func.round((Job.location_lat * 10).cast_to_text() if False else Job.location_lat * 10) / 10,  # placeholder, see below
        )
    )
    # Use raw SQL for the rounding aggregation — cleaner with SQLAlchemy core
    from sqlalchemy import text as sql_text

    where_clauses = ["j.status = 'active'", "j.location_lat IS NOT NULL", "j.location_lng IS NOT NULL"]
    params = {}
    if country:
        where_clauses.append("j.location_country = :country")
        params["country"] = country.upper().replace("UK", "GB")
    if q:
        where_clauses.append("j.title ILIKE :q")
        params["q"] = f"%{q}%"
    if remote is not None:
        where_clauses.append("j.is_remote = :remote")
        params["remote"] = remote
    if employment_type:
        where_clauses.append("j.employment_type = :emp_type")
        params["emp_type"] = employment_type.upper()

    where_sql = " AND ".join(where_clauses)
    # Aggregate jobs into ~11km buckets, return count + top 3 sample titles + most-common employer per bucket
    sql = sql_text(f"""
        SELECT
          ROUND(j.location_lat::numeric, 1) AS lat_bucket,
          ROUND(j.location_lng::numeric, 1) AS lng_bucket,
          j.location_country AS country,
          COUNT(*) AS cnt,
          (ARRAY_AGG(j.location_city ORDER BY j.date_posted DESC NULLS LAST))[1] AS sample_city,
          (ARRAY_AGG(j.title ORDER BY j.date_posted DESC NULLS LAST))[1:3] AS sample_titles,
          (ARRAY_AGG(j.employer_name ORDER BY j.date_posted DESC NULLS LAST))[1] AS top_employer
        FROM jobs j
        WHERE {where_sql}
        GROUP BY lat_bucket, lng_bucket, j.location_country
        ORDER BY cnt DESC
        LIMIT :limit
    """)
    params["limit"] = limit
    result = await session.execute(sql, params)

    clusters = []
    for row in result.all():
        lat, lng, ccc, cnt, sample_city, sample_titles, top_emp = row
        clusters.append({
            "lat": float(lat),
            "lng": float(lng),
            "count": int(cnt),
            "country": ccc,
            "city": sample_city,
            "top_titles": list(sample_titles or []),
            "top_employer": top_emp,
        })

    # Total count for the same filters (could differ from sum of clusters if some have no coords)
    total_sql = sql_text(f"SELECT COUNT(*) FROM jobs j WHERE {where_sql}")
    total = (await session.execute(total_sql, {k: v for k, v in params.items() if k != "limit"})).scalar() or 0

    return {
        "total_jobs_matching": total,
        "clusters_returned": len(clusters),
        "clusters": clusters,
    }


@router.get("/map", response_class=HTMLResponse, summary="Interactive job map")
async def map_page(
    request: Request,
    country: Optional[str] = None,
    q: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """SSR map page with Leaflet + markercluster, fetches from /api/v1/jobs/map on load."""
    # Counts for the header
    total = (await session.execute(
        select(func.count()).select_from(Job)
        .where(Job.status == "active")
        .where(Job.location_lat.isnot(None))
    )).scalar() or 0
    return templates.TemplateResponse(request, "map.html", {
        "total_with_coords": total,
        "preset_country": (country or "").upper() if country else "",
        "preset_q": q or "",
    })
