from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.ai import router as ai_router
from src.api.employers import router as employers_router
from src.api.frontend import router as frontend_router
from src.api.jobs import router as jobs_router
from src.api.sitemap import router as sitemap_router
from src.api.stats import router as stats_router

app = FastAPI(
    title="Job Index API",
    description=(
        "Global AI-native job index. Search millions of jobs from corporate ATS "
        "platforms (Greenhouse, Lever, Workday, and more) that are invisible to "
        "AI search — free for everyone."
    ),
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")

# API routes
app.include_router(jobs_router)
app.include_router(employers_router)
app.include_router(stats_router)
app.include_router(ai_router)
app.include_router(sitemap_router)

# Frontend routes (must be last — catches / and /search)
app.include_router(frontend_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "job-index", "version": "0.3.0"}
