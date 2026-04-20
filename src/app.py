from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.employers import router as employers_router
from src.api.jobs import router as jobs_router
from src.api.stats import router as stats_router

app = FastAPI(
    title="Job Index API",
    description=(
        "Global AI-native job index. Search millions of jobs from corporate ATS "
        "platforms (Greenhouse, Lever, Workday, and more) that are invisible to "
        "AI search — free for everyone."
    ),
    version="0.2.0",
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

app.include_router(jobs_router)
app.include_router(employers_router)
app.include_router(stats_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "job-index-api", "version": "0.2.0"}
