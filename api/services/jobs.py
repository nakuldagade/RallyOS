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

JOBS: dict[str, dict] = {}


def _stage_table(taps_given: bool = True) -> tuple[list, dict]:
    """The pipeline's own stage list and weights (rallyos.pipeline.Analyzer), so the bar and the list can't disagree."""
    from rallyos.pipeline import Analyzer

    return list(Analyzer.STAGES), dict(Analyzer.STAGE_WEIGHTS if taps_given else Analyzer.STAGE_WEIGHTS_AUTO)


def _fresh_stages() -> list[dict]:
    return [{"id": sid, "label": label, "state": "pending", "frac": 0.0, "note": None, "seconds": None}
            for sid, label in _stage_table()[0]]


def apply_progress(job: dict, stage: str, frac: float, note: Optional[str] = None) -> None:
    """Fold one pipeline progress event into the job: earlier stages are done, this one is active, the bar is
    the weighted sum of finished stages plus this stage's share. Stages that finish between two polls still
    show as done, because the state is kept per stage, not as 'the latest stage'."""
    now = time.time()
    stages, weights = job["stages"], _stage_table(job.get("taps_given", True))[1]
    if stage == "done":
        for st in stages:
            if st["state"] in ("pending", "active"):
                st.update(state="done", frac=1.0)
        job.update(stage="done", progress=1.0)
        return
    ids = [st["id"] for st in stages]
    if stage not in ids:
        return
    cur = ids.index(stage)
    for i, st in enumerate(stages):
        if i < cur and st["state"] in ("pending", "active"):
            st.update(state="done", frac=1.0)
            if st.get("_t0"):
                st["seconds"] = round(now - st["_t0"], 1)
    st = stages[cur]
    if not st.get("_t0"):
        st["_t0"] = now
    skipped = bool(note and note.startswith("skipped:"))
    st.update(state="skipped" if skipped else "active", frac=round(min(1.0, max(0.0, frac)), 3),
              note=note[len("skipped:"):].strip() if skipped else (note or st["note"]))
    st["seconds"] = round(now - st["_t0"], 1)
    done = sum(weights[x["id"]] for x in stages[:cur])
    job.update(stage=stage, progress=round(min(0.999, done + weights[stage] * st["frac"]), 3))


def get_job(job_id: str) -> Optional[dict]:
    return JOBS.get(job_id)


def submit(video_path: Path, sport: str = "auto", taps: Optional[list] = None,
           names: Optional[dict[int, str]] = None, match_id: Optional[str] = None) -> str:
    """Queue a pipeline run. match_id re-processes an existing match in place (e.g. after calibrating it)."""
    job_id = "j_" + uuid.uuid4().hex[:8]
    JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": None, "progress": 0.0, "match_id": None,
                    "error": None, "simulated": False, "skipped": [], "calibrated": bool(taps), "started": time.time(),
                    "stages": _fresh_stages(), "taps_given": bool(taps)}
    threading.Thread(target=_run, args=(job_id, video_path, sport, taps, names, match_id), daemon=True).start()
    return job_id


def _simulate(job: dict) -> None:
    job["simulated"] = True
    stages = _stage_table()[0]
    for i, (stage, _) in enumerate(stages):
        apply_progress(job, stage, 0.5)
        time.sleep(0.8)
    job["match_id"] = "m_001"                       # the mock match


def _run(job_id: str, video_path: Path, sport: str, taps: Optional[list], names: Optional[dict[int, str]],
         match_id: Optional[str] = None) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    try:
        from rallyos.pipeline import Analyzer

        match_id = match_id or "m_" + job_id[2:]
        out = settings.out_dir / match_id
        out.mkdir(parents=True, exist_ok=True)

        def progress(stage: str, frac: float, note: Optional[str] = None) -> None:
            apply_progress(job, stage, frac, note)

        try:
            Analyzer(sport=sport, taps=taps, names=names, match_id=match_id).run(
                str(video_path), out_dir=str(out), progress=progress)
        except NotImplementedError:
            _simulate(job)
        else:
            with Session(engine) as s:
                job["match_id"] = import_folder(out, s)
        apply_progress(job, "done", 1.0)
        job.update(status="done", skipped=[st["id"] for st in job["stages"] if st["state"] == "skipped"])
    except Exception as exc:  # stage outputs already on disk are kept; report the error
        for st in job["stages"]:
            if st["state"] == "active":
                st.update(state="failed", note=str(exc)[:200])
        job.update(status="failed", error=str(exc))
