"""Live sessions: chunks in, results out, in order.

One LiveSession per match being filmed. It owns a StreamAnalyzer (tracking is stateful, so chunks MUST be analysed in
sequence) and a worker thread that does exactly that; different sessions run in parallel, following the in-process
queue pattern of jobs.py. Everything the worker learns is appended to the session's event log, which SSE clients read.

Chunk arrival is not trusted to be tidy:
  * out of order     -> held until its turn;
  * sent twice (a retry after a dropped connection) -> the second copy is ignored, and acknowledged;
  * never arrives    -> after RALLYOS_LIVE_MISSING_WAIT_S the session moves on, the gap is reported (chunk_missing) and the
                        analyzer counts the missing frames as dropped;
  * analysis fails   -> reported (chunk_failed); the session carries on with the next chunk.
On stop the worker drains what has arrived, finalises the match and imports it through the normal importer, so every
existing page works on it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session as DbSession

from api.config import settings
from api.db import engine
from api.services.importer import import_folder
from api.services.live_hub import SessionLog, new_session

log = logging.getLogger(__name__)
LIVE: dict[str, "LiveSession"] = {}
MAX_CHUNK_BYTES = 200 * 1024 * 1024


def clean(obj: Any) -> Any:
    """JSON-safe copy (numpy numbers and arrays become plain Python)."""
    def default(o):
        if hasattr(o, "item"):
            return o.item()
        if hasattr(o, "tolist"):
            return o.tolist()
        return str(o)
    return json.loads(json.dumps(obj, default=default))


@dataclass
class ChunkJob:
    seq: int
    path: Path
    t0: float
    duration: float | None
    upload_s: float | None
    arrived: float


class LiveSession:
    def __init__(self, session_id: str | None = None, *, sport: str = "auto", taps: list | None = None,
                 names: dict[int, str] | None = None, chunk_seconds: float | None = None, storage=None,
                 resume: bool = False):
        from rallyos.live.stream import StreamAnalyzer

        self.log: SessionLog = new_session({"mode": "live"}, session_id)
        self.id = self.log.session_id
        self.chunk_seconds = chunk_seconds or settings.chunk_seconds
        self.storage = storage
        self.out_dir = settings.live_dir / self.id
        self.analyzer = (StreamAnalyzer(sport=sport, taps=taps, names=names, session_id=self.id, out_dir=self.out_dir,
                                        chunk_seconds=self.chunk_seconds) if not resume else None)
        self.sport, self.taps, self.names = sport, taps, names
        self.cond = threading.Condition()
        self.pending: dict[int, ChunkJob] = {}
        self.received: set[int] = set()
        self.tasks: list[tuple[str, Any]] = []
        self.next_seq = 0
        self.stopping = False
        self.last_seq: int | None = None
        self.state = "recording"
        self.match_id: str | None = None
        self.lags: list[float] = []
        self.latencies: list[float] = []
        self._gap_since: float | None = None
        self._last_cal: tuple | None = None
        self.alock = threading.Lock()                       # the analyzer is touched by the worker and by snapshot()
        LIVE[self.id] = self
        self.thread = threading.Thread(target=self._run, name=f"live-{self.id}", daemon=True)
        if not resume:
            self.analyzer.start()
            self.log.emit("session", status="recording", sport=sport, chunk_seconds=self.chunk_seconds, mode="live",
                          storage=getattr(storage, "name", "local"), corners_given=bool(taps))
            self.thread.start()

    # -- called from the API ---------------------------------------------------------------------------------------
    def add_chunk(self, seq: int, path: Path, t0: float | None, duration: float | None, upload_s: float | None = None) -> dict:
        with self.cond:
            if seq in self.received or seq < self.next_seq:
                return {"seq": seq, "duplicate": True}      # a retry of a chunk already taken: acknowledged, not repeated
            if self.stopping and (self.last_seq is None or seq > self.last_seq):
                raise ValueError("the session was stopped")
            t0 = float(t0) if t0 is not None else seq * self.chunk_seconds
            self.received.add(seq)
            self.pending[seq] = ChunkJob(seq, Path(path), t0, duration, upload_s, time.time())
            self.log.emit("chunk_received", seq=seq, t0=round(t0, 2), t1=round(t0 + (duration or self.chunk_seconds), 2),
                          upload_s=upload_s)
            self.cond.notify_all()
        return {"seq": seq, "duplicate": False}

    def stop(self, last_seq: int | None = None) -> None:
        with self.cond:
            self.stopping = True
            self.last_seq = last_seq
            self.cond.notify_all()

    def set_corners(self, taps: list) -> None:
        """Re-run the stored chunks with corrected corners, between two chunks, without ending the session."""
        with self.cond:
            self.tasks.append(("corners", taps))
            self.cond.notify_all()

    def snapshot(self) -> dict:
        with self.alock:
            snap = self.analyzer.snapshot() if self.analyzer and self.analyzer.scene else {"events": [], "rallies": []}
        return clean({"session_id": self.id, "state": self.state, "match_id": self.match_id, "next_seq": self.next_seq,
                      "pending": sorted(self.pending), **snap})

    def info(self) -> dict:
        return {"session_id": self.id, "state": self.state, "match_id": self.match_id, "next_seq": self.next_seq,
                "pending": sorted(self.pending), "received": len(self.received), "closed": self.log.closed,
                "chunk_seconds": self.chunk_seconds, "stopping": self.stopping}

    # -- the worker ------------------------------------------------------------------------------------------------
    def _run(self) -> None:
        try:
            while True:
                item = self._next()
                if item is None:
                    break
                kind, payload = item
                if kind == "corners":
                    self._recompute(payload)
                else:
                    self._process(payload)
            self._finalise()
        except Exception as exc:                                # the worker must never die silently
            log.exception("live session %s failed", self.id)
            self.state = "error"
            self.log.emit("error", message=f"{type(exc).__name__}: {exc}")

    def _next(self):
        wait = settings.live_missing_wait_s
        with self.cond:
            while True:
                if self.tasks:
                    return self.tasks.pop(0)
                if self.next_seq in self.pending:
                    self._gap_since = None
                    return "chunk", self.pending.pop(self.next_seq)
                done_by_count = self.last_seq is not None and self.next_seq > self.last_seq
                if done_by_count or (self.stopping and self.last_seq is None and not self.pending):
                    return None
                waiting_for_missing = bool(self.pending) or (self.stopping and self.last_seq is not None)
                if waiting_for_missing:
                    self._gap_since = self._gap_since or time.time()
                    if time.time() - self._gap_since >= wait:
                        self.log.emit("chunk_missing", seq=self.next_seq, waited_s=round(wait, 1))
                        self.next_seq += 1
                        self._gap_since = None
                        continue
                self.cond.wait(timeout=0.2)

    def _process(self, job: ChunkJob) -> None:
        try:
            t_ready = job.arrived - (job.upload_s or 0.0)       # the chunk was complete this long before it reached us
            with self.alock:
                res = self.analyzer.feed_chunk(job.path, job.seq, job.t0, job.duration, t_ready=t_ready)
        except Exception as exc:
            log.exception("chunk %s of %s failed", job.seq, self.id)
            self.log.emit("chunk_failed", seq=job.seq, message=f"{type(exc).__name__}: {exc}")
            self.next_seq = job.seq + 1
            return
        done = time.time()
        lag = done - job.arrived                                # queue wait + analysis
        latency = done - t_ready                                # + the upload, as the viewer experiences it
        self.lags.append(lag)
        self.latencies.append(latency)
        self.next_seq = job.seq + 1
        self._emit_results(job, res, lag, latency)

    def _emit_results(self, job: ChunkJob, res: dict, lag: float, latency: float) -> None:
        cal = res["calibration"]
        key = (cal.get("quality"), cal.get("method"), cal.get("sport"))
        if key != self._last_cal:
            self._last_cal = key
            self.log.emit("calibration_status", **clean(cal))
        self.log.emit("positions", seq=job.seq, samples=clean(res["positions"]), provisional=True)
        if res["new_events"]:
            self.log.emit("new_events", seq=job.seq, events=clean(res["new_events"]))
        for r in res["closed_rallies"]:
            self.log.emit("rally_closed", rally=clean(r))
        self.log.emit("stats", **clean(res["stats"]))
        self.log.emit("chunk_processed", seq=job.seq, t0=res["t0"], t1=res["t1"], process_s=res["process_s"], lag_s=round(lag, 2),
                      latency_s=round(latency, 2), rtf=res["rtf"], frames=res["frames"], dropped_frames=res["dropped_frames"],
                      reduced_quality=res["reduced_quality"])
        self.log.emit("lag", lag_s=round(lag, 2), latency_s=round(latency, 2), max_lag_s=round(max(self.lags), 2),
                      avg_latency_s=round(sum(self.latencies) / len(self.latencies), 2))

    def _recompute(self, taps: list) -> None:
        try:
            with self.alock:
                self.analyzer.set_corners(taps)
        except Exception as exc:
            self.log.emit("chunk_failed", seq=-1, message=f"re-running with the new corners failed: {exc}")
            return
        self._last_cal = None
        snap = self.snapshot()
        self.log.emit("calibration_status", **clean(self.analyzer.calibration_status()))
        self.log.emit("recomputed", events=snap["events"], rallies=snap["rallies"], stats=snap["stats"],
                      chunks=len(self.analyzer.chunk_files))

    def _finalise(self) -> None:
        if self.analyzer is None or self.analyzer.scene is None or not self.analyzer.chunk_files:
            self.state = "error"
            self.log.emit("error", message="the session was stopped before any chunk was analysed")
            return
        self.state = "finalising"
        self.log.emit("finalising")
        match_id = f"m_{self.id.removeprefix('s_')}"
        out = settings.out_dir / match_id
        with self.alock:
            self.analyzer.finalize(match_id=match_id, out_dir=out)
        with DbSession(engine) as s:
            import_folder(out, s)
        self.match_id, self.state = match_id, "done"
        self.log.emit("finalised", match_id=match_id)

    # -- after a restart -------------------------------------------------------------------------------------------
    @classmethod
    def from_disk(cls, session_id: str, storage=None) -> "LiveSession":
        """Rebuild a session whose process died: its chunk files and session.json are on disk. The chunks are re-analysed
        in the background (the events appear in the new log), and the session then accepts the chunks that follow."""
        from rallyos.live.stream import StreamAnalyzer

        folder = settings.live_dir / session_id
        if not (folder / "session.json").is_file():
            raise KeyError(session_id)
        self = cls(session_id, storage=storage, resume=True)
        self.log.emit("session", status="resuming", mode="live", resumed=True)

        def work() -> None:
            try:
                self.analyzer = StreamAnalyzer.resume(folder)
                n = len(self.analyzer.chunk_files)
                self.received = {c.seq for c in self.analyzer.chunk_files}
                self.next_seq = (max(self.received) + 1) if self.received else 0
                snap = self.snapshot()
                self.log.emit("calibration_status", **clean(self.analyzer.calibration_status()))
                self.log.emit("recomputed", events=snap["events"], rallies=snap["rallies"], stats=snap["stats"], chunks=n)
                self.log.emit("session", status="recording", mode="live", resumed=True, chunk_seconds=self.chunk_seconds)
                self._run()
            except Exception as exc:
                self.state = "error"
                self.log.emit("error", message=f"could not resume: {type(exc).__name__}: {exc}")

        self.thread = threading.Thread(target=work, name=f"live-resume-{session_id}", daemon=True)
        self.thread.start()
        return self


def get(session_id: str) -> LiveSession | None:
    return LIVE.get(session_id)


def warm_up() -> dict:
    """Load what the first chunk would otherwise wait for: PyTorch, the pose model, one dummy inference, ffmpeg.

    The first chunk of the first session in a fresh server process took 46 s on this laptop (cold imports and model
    load, with Windows scanning the freshly written files) against 8 s once warm; a live match cannot afford that.
    Run in a background thread at start-up; RALLYOS_WARMUP=0 turns it off (tests, CI)."""
    import os

    t = time.time()
    try:
        import numpy as np

        from rallyos.audio.onsets import ffmpeg_exe
        from rallyos.detect.players import load_pose_detector

        detector, backend = load_pose_detector(device=None, imgsz=int(os.environ.get("RALLYOS_MAX_WIDTH") or 1280))
        if detector is not None:
            detector(np.zeros((720, 1280, 3), np.uint8))          # the first inference allocates buffers
        ffmpeg_exe()
        info = {"ok": True, "backend": backend, "seconds": round(time.time() - t, 1)}
    except Exception as exc:                                       # warming is best effort: never stop the server
        info = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t, 1)}
    log.info("live warm-up: %s", info)
    WARMUP.update(info)
    return info


WARMUP: dict = {"ok": None}
