"""FastAPI app.  Run from the repo root:  uvicorn api.main:app --reload --port 8000   (docs: /docs)"""
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api import db as db_module
from api.db import backend, create_all
from api.services import live as live_service
from api.routers import (auth, calibrate, coach, courts3d, disputes, highlights, live, matches, network, players, sports,
                         team, tournaments, videos)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    if os.getenv("RALLYOS_WARMUP", "1") != "0":                   # load the pose model before the first live chunk needs it
        threading.Thread(target=live_service.warm_up, name="warmup", daemon=True).start()
    yield


app = FastAPI(title="RallyOS API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (auth, team, highlights, courts3d, calibrate, videos, live, matches, disputes, players, coach, network, tournaments, sports):
    app.include_router(r.router, prefix="/v1")

app.mount("/media", StaticFiles(directory=str(settings.media_dir)), name="media")


@app.get("/health")
def health():
    return {"ok": True, "mock_fallback": settings.mock_fallback, "coach": "claude" if settings.anthropic_key else "template",
            "database": backend(), "database_note": db_module.FALLBACK_NOTE, "warmup": live_service.WARMUP}
