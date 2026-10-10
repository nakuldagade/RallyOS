"""In-process job queue. Runs rallyos.pipeline.Analyzer on the upload, which writes each stage into
demo/out/<match_id>/, then imports the folder so the new match opens in the web app.
Everything runs locally on this machine. If the pipeline raises NotImplementedError (a stage not built) it
falls back to SIMULATED progress and the mock match, flagged `simulated`."""
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


def submit(video_path: Path, sport: str = "auto", taps: Optional[list] = None,
           names: Optional[dict[int, str]] = None) -> str:
    job_id = "j_" + uuid.uuid4().hex[:8]
    JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": None, "progress": 0.0, "match_id": None,
                    "error": None, "simulated": False, "skipped": [], "calibrated": bool(taps), "started": time.time()}
    threading.Thread(target=_run, args=(job_id, video_path, sport, taps, names), daemon=True).start()
    return job_id


def _simulate(job: dict) -> None:
    job["simulated"] = True
    for i, stage in enumerate(STAGES):
        job.update(stage=stage, progress=round(i / len(STAGES), 2))
        time.sleep(0.8)
    job["match_id"] = "m_001"                       # the mock match


def _run(job_id: str, video_path: Path, sport: str, taps: Optional[list], names: Optional[dict[int, str]]) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    try:
        from rallyos.pipeline import Analyzer

        match_id = "m_" + job_id[2:]
        out = settings.out_dir / match_id
        out.mkdir(parents=True, exist_ok=True)
        job["skipped"] = list(Analyzer.SKIPPED_STAGES)
        stage_base = {"calibrate": 0.0, "players": 0.05, "audio": 0.85, "ball": 0.87, "rallies": 0.9, "analytics": 0.93, "render": 0.96}
        stage_span = {"players": 0.8}

        def progress(stage: str, frac: float) -> None:
            base = stage_base.get(stage, job["progress"])
            job.update(stage=stage, progress=round(base + stage_span.get(stage, 0.0) * frac, 3))

        try:
            Analyzer(sport=sport, taps=taps, names=names, match_id=match_id).run(
                str(video_path), out_dir=str(out), progress=progress)
        except NotImplementedError:
            _simulate(job)
        else:
            with Session(engine) as s:
                job["match_id"] = import_folder(out, s)
        job.update(status="done", stage="done", progress=1.0)
    except Exception as exc:  # stage outputs already on disk are kept; report the error
        job.update(status="failed", error=str(exc))
