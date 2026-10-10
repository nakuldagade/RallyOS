"""FastAPI app.  Run from the repo root:  uvicorn api.main:app --reload --port 8000   (docs: /docs)"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.db import create_all
from api.routers import (calibrate, coach, courts, disputes, matches, network, players, sports,
                         tournaments, videos)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(title="RallyOS API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (calibrate, videos, matches, disputes, players, coach, network, courts, tournaments, sports):
    app.include_router(r.router, prefix="/v1")

app.mount("/media", StaticFiles(directory=str(settings.media_dir)), name="media")


@app.get("/health")
def health():
    return {"ok": True, "mock_fallback": settings.mock_fallback, "coach": "claude" if settings.anthropic_key else "template",
            "worker": bool(settings.worker_url)}
