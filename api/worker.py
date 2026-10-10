"""GPU-machine worker app (Mode 2):  uvicorn api.worker:app --port 8001
POST /process (video upload) -> job_id;  GET /status/{id} -> job progress.
Runs the same job queue as the laptop backend, so outputs land in demo/out/<job>/ on the GPU machine.
TODO: GET /result/{id} to stream the output folder back to the laptop backend."""
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from api.config import settings
from api.db import create_all
from api.services import jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(title="RallyOS GPU worker", version="1.0", lifespan=lifespan)


@app.post("/process", status_code=202)
async def process(video: UploadFile = File(...), sport: str = Form("auto")):
    up = settings.media_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(video.filename or "video.mp4").name)
    dest = up / f"{uuid.uuid4().hex[:8]}_{name}"
    with dest.open("wb") as f:
        shutil.copyfileobj(video.file, f)
    return {"job_id": jobs.submit(dest, sport)}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job
