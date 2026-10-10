"""POST /v1/videos (upload), GET /v1/jobs/{id} (SSE progress)."""
import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from api.config import settings
from api.services import jobs

router = APIRouter(tags=["videos"])


def _safe_name(filename: str | None) -> str:
    name = Path(filename or "video.mp4").name                  # drop any client-supplied directories
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "video.mp4"


@router.post("/videos", status_code=202)
async def upload(video: UploadFile = File(...), sport: str = Form("auto")):
    up = settings.media_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    dest = up / f"{uuid.uuid4().hex[:8]}_{_safe_name(video.filename)}"
    with dest.open("wb") as f:
        shutil.copyfileobj(video.file, f)
    return {"job_id": jobs.submit(dest, sport)}


@router.get("/jobs/{job_id}")
async def job_progress(job_id: str):
    if not jobs.get_job(job_id):
        raise HTTPException(404, "job not found")

    async def stream():
        while True:
            job = jobs.get_job(job_id)
            yield f"data: {json.dumps(job)}\n\n"
            if job["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")
