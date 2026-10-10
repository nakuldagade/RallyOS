"""Feed a recorded clip to the StreamAnalyzer as if it were being filmed right now (for demos, CI and measurements).

    python -m rallyos.live.replay <clip> --chunk-seconds 5 --realtime [--taps "[[x,y]*4]"] [--sport badminton] [--out dir]

The clip is cut into overlapping chunks (each a standalone file with its own header). With --realtime, chunk k is only
handed over once the camera would have finished recording it (its end time after the start), and the printed lag is
what a viewer would see: seconds between the end of the chunk and its results being ready. Without --realtime the chunks
are fed back to back as fast as they can be analysed (the real-time factor is then the speed measure).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

from rallyos.live.segments import cut_clip
from rallyos.live.stream import StreamAnalyzer


def run_replay(clip: str | Path, *, chunk_seconds: float = 5.0, overlap_seconds: float = 0.5, realtime: bool = False,
               speed: float = 1.0, taps: list | None = None, sport: str = "auto", out_dir: str | Path | None = None,
               max_chunks: int | None = None, on_chunk: Callable[[dict], None] | None = None, fmt: str = "mp4",
               analyzer: StreamAnalyzer | None = None, **analyzer_kw):
    """Cut `clip` into chunks and feed them in order. Returns (analyzer, per-chunk results, chunk metas)."""
    out = Path(out_dir) if out_dir else Path("demo/out/live") / f"replay_{Path(clip).stem}"
    metas = cut_clip(clip, out / "chunks", chunk_seconds, overlap_seconds, fmt=fmt)
    if max_chunks:
        metas = metas[:max_chunks]
    an = analyzer or StreamAnalyzer(sport=sport, taps=taps, out_dir=out, chunk_seconds=chunk_seconds, **analyzer_kw)
    an.start()
    results = []
    wall0 = time.time()
    for m in metas:
        ready_at = wall0 + (m.t1 / speed if realtime else 0.0)       # the camera has just finished recording this chunk
        if realtime and ready_at > time.time():
            time.sleep(ready_at - time.time())
        t_ready = ready_at if realtime else time.time()
        res = an.feed_chunk(m.path, m.seq, m.t0, m.duration, t_ready=t_ready)
        res["lag_s"] = round(time.time() - t_ready, 2)               # chunk complete -> results ready
        results.append(res)
        if on_chunk:
            on_chunk(res)
    return an, results, metas


def _print_chunk(r: dict) -> None:
    new = r["new_events"]
    print(f"chunk {r['seq']:3d} [{r['t0']:6.1f}-{r['t1']:6.1f}s]  analysed in {r['process_s']:5.2f} s  rtf {r['rtf']:.2f}  "
          f"lag {r['lag_s']:5.2f} s  frames {r['frames']:3d} (+{r['overlap_frames_skipped']} overlap)  new events {len(new):2d}  "
          f"closed rallies {r['stats']['rallies']}  court {r['calibration']['quality']}", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rallyos.live.replay")
    ap.add_argument("clip")
    ap.add_argument("--chunk-seconds", type=float, default=5.0)
    ap.add_argument("--overlap-seconds", type=float, default=0.5)
    ap.add_argument("--realtime", action="store_true", help="hand over each chunk only when the camera would have finished it")
    ap.add_argument("--speed", type=float, default=1.0, help="with --realtime: play this many times faster")
    ap.add_argument("--sport", default="auto")
    ap.add_argument("--taps", default=None, help='JSON [[x,y]*4]: near-left, near-right, far-right, far-left')
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-chunks", type=int, default=None)
    ap.add_argument("--stride", type=int, default=3)
    args = ap.parse_args(argv)
    an, results, _ = run_replay(args.clip, chunk_seconds=args.chunk_seconds, overlap_seconds=args.overlap_seconds, realtime=args.realtime,
                                speed=args.speed, taps=json.loads(args.taps) if args.taps else None, sport=args.sport,
                                out_dir=args.out, max_chunks=args.max_chunks, on_chunk=_print_chunk, stride=args.stride)
    dur = sum(r["frames"] for r in results) / an.fps
    work = sum(r["process_s"] for r in results)
    lags = [r["lag_s"] for r in results]
    print(f"\n{len(results)} chunks, {dur:.1f} s of footage analysed in {work:.1f} s  (real-time factor {work / max(dur, 1e-6):.2f})")
    print(f"lag after the chunk ended: average {sum(lags) / len(lags):.1f} s, worst {max(lags):.1f} s;  "
          f"events {len(an.events)}  closed rallies {sum(1 for r in an.rallies if r.get('closed'))}  court {an.calibration_quality}")


if __name__ == "__main__":
    main()
