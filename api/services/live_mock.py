"""Replays an already-processed match as if it were being played live: the same events the real pipeline will send,
paced in real time (or faster). Used to build and test the live dashboard before the real pipeline was wired in, and
as a demo that needs no camera. It invents nothing: every event, position and number comes from the match's own
match.json and tracks.json, only released chunk by chunk with a simulated processing delay.
"""
from __future__ import annotations

import math
import time
from typing import Callable

from api.services.live_hub import SessionLog

POSITION_HZ = 5.0
SIMULATED_RTF = 0.45         # processing takes this fraction of a chunk's length in the simulation


def replay(log: SessionLog, match: dict, tracks: dict, *, speed: float = 1.0, chunk_seconds: float = 5.0,
           sleep: Callable[[float], None] = time.sleep, rtf: float = SIMULATED_RTF) -> None:
    """Emit the match's events chunk by chunk. `speed` > 1 plays faster than real time; `sleep` is injectable for tests."""
    from rallyos.analytics.movement import movement_stats

    fps = float(tracks["fps"])
    frames = tracks["frames"]
    duration = float(match["video"]["duration_s"])
    n_chunks = max(1, math.ceil(duration / chunk_seconds))
    events = sorted(match.get("events", []), key=lambda e: e["t"])
    rallies = sorted(match.get("rallies", []), key=lambda r: r["t_end"])
    calib = match.get("calibration", {})
    auto = calib.get("auto") or {}
    log.meta.update(sport=match["sport"], chunk_seconds=chunk_seconds, mode="mock")
    log.emit("session", status="recording", sport=match["sport"], chunk_seconds=chunk_seconds, mode="mock",
             match_id=match["match_id"], players=match.get("players", []))
    log.emit("calibration_status", quality=auto.get("quality", "high" if calib.get("method") in ("auto", "4-tap") else "none"),
             sport=match["sport"], method=calib.get("method"), precision=auto.get("precision"),
             corners_px=calib.get("taps_px") or auto.get("corners_px"), note=calib.get("note"))

    sent = 0
    closed = 0
    started = time.time()
    lag_samples: list[float] = []
    for seq in range(n_chunks):
        t0, t1 = seq * chunk_seconds, min(duration, (seq + 1) * chunk_seconds)
        wait = (t1 / speed) - (time.time() - started)       # the chunk is only complete once its last second has happened
        if wait > 0:
            sleep(wait)
        log.emit("chunk_received", seq=seq, t0=round(t0, 2), t1=round(t1, 2))
        process_s = rtf * (t1 - t0) / speed
        sleep(process_s)
        samples = _positions(frames, fps, t0, t1)
        log.emit("positions", seq=seq, samples=samples, provisional=True)
        fresh = []
        while sent < len(events) and events[sent]["t"] < t1:
            fresh.append({**events[sent], "provisional": True})
            sent += 1
        if fresh:
            log.emit("new_events", seq=seq, events=fresh)
        # a rally is closed once its last hit is more than 4 s behind (or the match footage has ended)
        while closed < len(rallies) and (rallies[closed]["t_end"] < t1 - 1.5 or t1 >= duration):
            log.emit("rally_closed", rally={**rallies[closed], "provisional": True})
            closed += 1
        pts = {tid: [(f["f"] / fps, tuple(p["court"])) for f in frames[: int(t1 * fps)]
                     if f["f"] % 3 == 0 for p in f["players"] if p["track_id"] == tid and p.get("court")] for tid in (1, 2)}
        last_closed = rallies[closed - 1] if closed else None
        log.emit("stats", provisional=True, rallies=closed, hits=sum(1 for e in events[:sent] if e["type"] == "hit"),
                 score={"suggested": last_closed.get("score_after") if last_closed else None, "provisional": True},
                 per_player={str(t): {k: v for k, v in movement_stats(p).items() if k in ("distance_m", "top_speed_mps")}
                             for t, p in pts.items() if len(p) > 1})
        lag = (time.time() - started) * speed - t1
        lag_samples.append(max(0.0, lag))
        log.emit("chunk_processed", seq=seq, t0=round(t0, 2), t1=round(t1, 2), process_s=round(process_s * speed, 2),
                 lag_s=round(max(0.0, lag), 2), rtf=round(rtf, 2), frames=int((t1 - t0) * fps), dropped_frames=0,
                 reduced_quality=False)
        log.emit("lag", lag_s=round(lag_samples[-1], 2), max_lag_s=round(max(lag_samples), 2),
                 avg_latency_s=round(sum(lag_samples) / len(lag_samples), 2))
    log.emit("finalising")
    sleep(0.5 / speed)
    log.emit("finalised", match_id=match["match_id"], mock=True)


def _positions(frames: list[dict], fps: float, t0: float, t1: float) -> list[dict]:
    step = max(1, round(fps / POSITION_HZ))
    out = []
    for f in range(int(t0 * fps), min(len(frames), int(t1 * fps)), step):
        fr = frames[f]
        ball = fr.get("ball")
        out.append({"t": round(f / fps, 2),
                    "players": [{"track_id": p["track_id"], "court": p.get("court"),
                                 "px": [round((p["bbox"][0] + p["bbox"][2]) / 2), round(p["bbox"][3])]} for p in fr["players"]],
                    "ball": {"px": ball["px"], "court": ball.get("court"), "conf": ball.get("conf"), "interp": ball.get("interp")} if ball else None})
    return out
