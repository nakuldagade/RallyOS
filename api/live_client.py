"""Behave like the browser against a running API: cut a clip into chunks, upload each one when the "camera" would have finished
it, press Stop, and report what came back and how late.

    python -m api.live_client demo/clip.mp4 --sport badminton --taps "[[x,y]*4]" --realtime [--api http://localhost:8000]

It is the HTTP-level counterpart of `python -m rallyos.live.replay` (which skips the server): it measures the path a real
phone takes: upload, queue, analysis, SSE.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import httpx


def run(clip: str, api: str = "http://localhost:8000", sport: str = "auto", taps: list | None = None, chunk_seconds: float = 5.0,
        overlap: float = 0.5, realtime: bool = True, speed: float = 1.0, out: str | None = None, quiet: bool = False) -> dict:
    from rallyos.live.segments import cut_clip

    log = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))
    out_dir = Path(out or Path("demo/out/live") / f"client_{Path(clip).stem}")
    metas = cut_clip(clip, out_dir / "chunks", chunk_seconds, overlap)
    http = httpx.Client(base_url=api, timeout=120.0)
    created = http.post("/v1/live/sessions", json={"sport": sport, "corners": taps, "chunk_seconds": chunk_seconds}).json()
    sid = created["session_id"]
    log(f"session {sid} ({created['storage']} storage); {len(metas)} chunks")
    events: list[dict] = []
    done = threading.Event()

    def reader() -> None:
        with httpx.stream("GET", f"{api}{created['stream']}", timeout=None) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append({**ev, "_seen": time.time()})
                    if ev["type"] == "chunk_processed":
                        log(f"  chunk {ev['seq']:2d} analysed in {ev['process_s']:5.2f} s, lag {ev['lag_s']:5.2f} s, latency {ev['latency_s']:5.2f} s")
                    elif ev["type"] in ("chunk_missing", "chunk_failed", "error", "finalising"):
                        log(f"  {ev['type']} {ev.get('seq', '')} {ev.get('message', '')}")
                    if ev["type"] in ("finalised", "error"):
                        break
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    start = time.time()
    for m in metas:
        ready = start + m.t1 / speed
        if realtime and ready > time.time():
            time.sleep(ready - time.time())
        t = time.time()
        with open(m.path, "rb") as fh:
            http.post(f"/v1/live/sessions/{sid}/chunks", files={"chunk": (Path(m.path).name, fh.read(), "video/mp4")},
                      data={"seq": m.seq, "t0": m.t0, "duration": m.duration, "upload_s": 0.0})
        upload_s = time.time() - t
        log(f"  chunk {m.seq:2d} [{m.t0:5.1f}-{m.t1:5.1f}s] uploaded in {upload_s:.2f} s")
    http.post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": metas[-1].seq})
    done.wait(timeout=900)
    final = next((e for e in events if e["type"] == "finalised"), None)
    proc = [e for e in events if e["type"] == "chunk_processed"]
    summary = {"session_id": sid, "match_id": final["match_id"] if final else None, "chunks": len(proc),
               "avg_process_s": round(sum(e["process_s"] for e in proc) / max(1, len(proc)), 2),
               "avg_lag_s": round(sum(e["lag_s"] for e in proc) / max(1, len(proc)), 2),
               "max_lag_s": max((e["lag_s"] for e in proc), default=None),
               "events": len([e for e in events if e["type"] == "new_events" for _ in e["events"]]),
               "finished": bool(final)}
    log(json.dumps(summary, indent=1))
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="api.live_client")
    ap.add_argument("clip")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--sport", default="auto")
    ap.add_argument("--taps", default=None)
    ap.add_argument("--chunk-seconds", type=float, default=5.0)
    ap.add_argument("--realtime", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args(argv)
    run(a.clip, a.api, a.sport, json.loads(a.taps) if a.taps else None, a.chunk_seconds, realtime=a.realtime, speed=a.speed)


if __name__ == "__main__":
    main()
