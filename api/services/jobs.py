"""In-process job queue. Runs rallyos.pipeline.Analyzer, which writes each stage into demo/out/<job>/,
then imports the folder. Until the pipeline stages exist (Analyzer.run raises NotImplementedError) it
SIMULATES progress and finishes with the mock match, so the upload flow in the UI works today.
Forwarding to RALLYOS_WORKER_URL (Mode 2) is a clearly marked TODO."""
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from sqlmodel import Session

from api.config import settings
from api.db import engine
from api.services.importer import import_folder

STAGES = ["calibrate", "players", "ball", "audio", "rallies", "analytics", "render"]
JOBS: dict[str, dict] = {}


def get_job(job_id: str) -> Optional[dict]:
    return JOBS.get(job_id)


def submit(video_path: Path, sport: str = "auto") -> str:
    job_id = "j_" + uuid.uuid4().hex[:8]
    JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": None, "progress": 0.0,
                    "match_id": None, "error": None, "simulated": False}
    threading.Thread(target=_run, args=(job_id, video_path, sport), daemon=True).start()
    return job_id


def _simulate(job: dict) -> None:
    job["simulated"] = True
    for i, stage in enumerate(STAGES):
        job.update(stage=stage, progress=round(i / len(STAGES), 2))
        time.sleep(0.8)
    job["match_id"] = "m_001"                       # the mock match


def _run(job_id: str, video_path: Path, sport: str) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    try:
        # TODO (Mode 2): if settings.worker_url: POST the video to the GPU worker and mirror its progress here.
        from rallyos.pipeline import Analyzer

        out = settings.out_dir / job_id
        out.mkdir(parents=True, exist_ok=True)

        def progress(stage: str, frac: float) -> None:
            job.update(stage=stage, progress=round(frac, 2))

        try:
            Analyzer(sport=sport).run(str(video_path), out_dir=str(out), progress=progress)
        except NotImplementedError:
            _simulate(job)
        else:
            with Session(engine) as s:
                job["match_id"] = import_folder(out, s)
        job.update(status="done", stage="done", progress=1.0)
    except Exception as exc:  # stage outputs already on disk are kept; report the error
        job.update(status="failed", error=str(exc))
