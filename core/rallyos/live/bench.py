"""Phase F measuring tool: run the live pipeline over real clips with different speed settings and report, for each setting,
how long a chunk takes (warm) and how much the result differs from the slowest, most careful setting.

    python -m rallyos.live.bench demo/out/m_5a3ab64f/source.mp4:taps.json ... --configs "3:1280,3:960,6:1280"

A config is `stride:imgsz` (pose every `stride` frames, at `imgsz` px). Each clip is `path` or `path:match.json` (the corners
are read from that match's calibration). Accuracy is measured against the FIRST config on the same clip (hits matched within
0.2 s, the fraction of frames with both players found), so the table says what a speed-up costs, not whether the baseline is
right: ground truth needs the hand-labelled set (AGENTS.md next step 9).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rallyos.live.replay import run_replay


def _taps(spec: str) -> tuple[str, list | None]:
    if ":" in spec and not Path(spec).exists():
        clip, meta = spec.rsplit(":", 1)
        return clip, json.loads(Path(meta).read_text(encoding="utf-8"))["calibration"].get("taps_px")
    return spec, None


def _match_hits(a: list[float], b: list[float], tol: float = 0.2) -> int:
    used, n = set(), 0
    for t in a:
        j = next((k for k, u in enumerate(b) if k not in used and abs(u - t) <= tol), None)
        if j is not None:
            used.add(j)
            n += 1
    return n


def run(clips: list[str], configs: list[tuple[int, int]], chunk_seconds: float = 5.0, out: str = "demo/out/live/bench") -> list[dict]:
    rows = []
    for spec in clips:
        clip, taps = _taps(spec)
        ref_hits: list[float] | None = None
        for ci, (stride, imgsz) in enumerate(configs):
            an, res, _ = run_replay(clip, chunk_seconds=chunk_seconds, taps=taps, sport="badminton", stride=stride, imgsz=imgsz,
                                    out_dir=f"{out}/{Path(clip).parent.name}_{stride}_{imgsz}")[:3]
            hits = sorted(h["t"] for h in an.hits)
            if ref_hits is None:
                ref_hits = hits
            warm = [r["process_s"] for r in res[1:]] or [res[0]["process_s"]]
            frames = [r["frames"] for r in res[1:]] or [res[0]["frames"]]
            both = sum(1 for p in an.tracker.frames if len({q["track_id"] for q in p["players"]} & {1, 2}) == 2) if getattr(an.tracker, "frames", None) else None
            rows.append({"clip": Path(clip).parent.name, "stride": stride, "imgsz": imgsz,
                         "chunk_s": [r["process_s"] for r in res], "warm_chunk_s": round(sum(warm) / len(warm), 2),
                         "warm_factor": round(sum(warm) / (len(warm) * chunk_seconds), 2), "hits": len(hits),
                         "hits_matched_vs_first": _match_hits(ref_hits, hits), "hits_first": len(ref_hits), "frames_both_players": both})
            print(json.dumps(rows[-1]), flush=True)
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rallyos.live.bench")
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--configs", default="3:1280,3:960,6:1280")
    ap.add_argument("--chunk-seconds", type=float, default=5.0)
    a = ap.parse_args(argv)
    cfgs = [tuple(int(v) for v in c.split(":")) for c in a.configs.split(",")]
    t = time.time()
    run(a.clips, cfgs, a.chunk_seconds)
    print(f"total {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()
