"""Embeddable widgets so Shazamme tenants (and any third party) can drop
a related-jobs carousel onto their own site with one tag.

Usage on a tenant's site:
    <div data-zammejobs data-employer="tenant.com" data-limit="6"></div>
    <script async src="https://www.zammejobs.com/embed/widget.js"></script>

Each placement is a backlink to the matching jobs on zammejobs.com,
plus a UTM-tagged click-through to the actual apply URL.

Iframe alternative for sandbox-friendly hosts:
    <iframe src="https://www.zammejobs.com/embed/iframe?employer=tenant.com&limit=6"
            width="100%" height="420" frameborder="0"></iframe>
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.frontend import _canonical_url, _job_to_template_obj
from src.db import get_session
from src.models import Job

router = APIRouter(prefix="/embed", tags=["Embed"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/widget.js", include_in_schema=False)
async def widget_js():
    """Self-contained vanilla JS. Looks for any element with
    data-zammejobs, fetches /embed/iframe with the parsed config, and
    injects a styled iframe (height auto-resized via postMessage)."""
    js = """
(function(){
  var ORIGIN = 'https://www.zammejobs.com';
  function mount(el){
    if(el.__zjMounted) return;
    el.__zjMounted = true;
    var qs = new URLSearchParams();
    ['employer','role','city','country','limit','theme'].forEach(function(k){
      var v = el.getAttribute('data-' + k);
      if(v) qs.set(k, v);
    });
    var src = ORIGIN + '/embed/iframe?' + qs.toString();
    var iframe = document.createElement('iframe');
    iframe.src = src;
    iframe.style.cssText = 'width:100%;border:0;display:block;min-height:280px;';
    iframe.setAttribute('loading','lazy');
    iframe.setAttribute('referrerpolicy','no-referrer-when-downgrade');
    iframe.setAttribute('title','Open jobs — powered by ZammeJobs');
    el.innerHTML = '';
    el.appendChild(iframe);
    window.addEventListener('message', function(e){
      if(e.source !== iframe.contentWindow) return;
      if(e.data && e.data.zjHeight){ iframe.style.height = e.data.zjHeight + 'px'; }
    });
  }
  function init(){
    var els = document.querySelectorAll('[data-zammejobs]');
    for(var i=0;i<els.length;i++) mount(els[i]);
  }
  if(document.readyState === 'loading'){ document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
""".strip()
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=600"},
    )


@router.get("/iframe", response_class=HTMLResponse, include_in_schema=False)
async def widget_iframe(
    request: Request,
    employer: Optional[str] = None,
    role: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(6, ge=1, le=20),
    theme: str = Query("auto", regex="^(auto|light|dark)$"),
    session: AsyncSession = Depends(get_session),
):
    clauses = [Job.status == "active"]
    if employer:
        emp_pat = f"%{employer}%"
        clauses.append(or_(Job.employer_domain.ilike(emp_pat), Job.employer_name.ilike(f"%{employer}%")))
    if role:
        clauses.append(or_(Job.title.ilike(f"%{role}%"), Job.categories.any(role)))
    if city:
        clauses.append(or_(Job.location_city.ilike(f"%{city}%"), Job.location_raw.ilike(f"%{city}%")))
    if country:
        clauses.append(Job.location_country == country.upper())

    rows = (await session.execute(
        select(Job).where(and_(*clauses))
        .order_by(Job.date_posted.desc().nullslast())
        .limit(limit)
    )).scalars().all()

    return templates.TemplateResponse(request, "embed_widget.html", {
        "jobs": [_job_to_template_obj(j) for j in rows],
        "theme": theme,
        "more_url": _canonical_url("/search" + (f"?employer={employer}" if employer else "")),
    })
