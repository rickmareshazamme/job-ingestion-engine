from fastapi import FastAPI

app = FastAPI(
    title="Job Ingestion Engine",
    description="Global AI job index — ingestion pipeline for ATS platforms",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "job-ingestion-engine"}
