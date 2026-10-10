"""RacketVision TrackNetV3 ball tracker as an optional candidate source (AGENTS.md, "Optional pretrained ball tracker").

Inference only: the pretrained `balltrack_best.pth` is used exactly as released and is never trained or
fine-tuned. It covers badminton, table tennis and tennis; other sports use the geometric tracker.

The model runs on the GPU machine in its own venv (Python 3.10, torch 2.1.2), so this module never imports
it. It reads the model's CSV output and, on the GPU machine, can drive its scripts through a subprocess.

CSV formats accepted:
  * per-video results.csv from inference.py:  Frame,X,Y,Visibility,Confidence
    (Frame is one ahead of the real video frame, so video_frame = Frame - 1; the -1 row is dropped)
  * the runner's combined CSV:  video_frame,Frame,X,Y,Visibility,Confidence,match,rally

CLI (python -m rallyos.track.plugins.racketvision ...):
  list  <csv>                                      clips in a combined CSV with detection rates
  build <csv> --clip match117_000 [--video V]      write demo/out/rv_<clip>/ (match.json + tracks.json)
  build <csv> --all [--videos DIR]                 every clip in the CSV
  merge <out_dir> <csv> [--clip C]                 replace the ball track in an existing output folder
  run   <video> --out DIR                          GPU machine only: run their inference on a new video
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from rallyos.export import ball_only_match, video_fingerprint, write_outputs
from rallyos.track.kalman import fill_short_gaps

SUPPORTED_SPORTS = ("badminton", "table_tennis", "tennis")
MODEL_INFO = {
    "tracker": "racketvision",
    "model": "RacketVision TrackNetV3 (pretrained checkpoint, inference only, not trained by us)",
    "checkpoint": "balltrack_best.pth (linfeng302/RacketVision-Models)",
}


def supports(sport: str) -> bool:
    return sport in SUPPORTED_SPORTS


def use_plugin(sport: str, setting: str | None = None) -> bool:
    """RALLYOS_BALL_TRACKER=auto|geometric|racketvision. auto = plug-in for supported sports when installed."""
    choice = (setting or os.environ.get("RALLYOS_BALL_TRACKER") or "auto").lower()
    if choice == "geometric":
        return False
    if choice == "racketvision":
        if not supports(sport):
            raise ValueError(f"RacketVision does not cover {sport}; use the geometric tracker")
        return True
    return supports(sport) and bool(os.environ.get("RALLYOS_RACKETVISION_ROOT"))


def _ball(x: float, y: float, conf: float) -> dict:
    return {"px": [float(x), float(y)], "court": None, "conf": round(float(conf), 4), "interp": False}


def read_predictions(path: str | Path) -> dict[str, list[dict | None]]:
    """Parse a RacketVision CSV into {clip_id: per-frame ball list (None = not visible)}.

    clip_id is "<match>_<rally>" for the combined CSV and "clip" for a single results.csv.
    """
    per_clip: dict[str, dict[int, dict | None]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            frame = int(row["video_frame"]) if row.get("video_frame") not in (None, "") else int(row["Frame"]) - 1
            if frame < 0:
                continue
            clip = f"{row['match']}_{row['rally']}" if row.get("match") else "clip"
            visible = int(float(row["Visibility"])) == 1
            per_clip[clip][frame] = _ball(row["X"], row["Y"], row["Confidence"]) if visible else None
    return {clip: [frames.get(i) for i in range(max(frames) + 1)] for clip, frames in per_clip.items() if frames}


def clip_summary(preds: dict[str, list[dict | None]]) -> list[dict]:
    rows = []
    for clip, balls in sorted(preds.items()):
        det = sum(b is not None for b in balls)
        rows.append({"clip": clip, "frames": len(balls), "detected_pct": round(det / len(balls), 3) if balls else 0.0})
    return rows


def _reference_metrics(csv_path: Path) -> dict:
    """Metrics from the runner's summary.json next to the CSV, if present (their test set, not our footage)."""
    summary = csv_path.parent / "summary.json"
    if not summary.is_file():
        return {}
    data = json.loads(summary.read_text(encoding="utf-8"))
    return {"reference_metrics": data.get("metrics", {}),
            "reference_note": f"Measured on the RacketVision badminton test set ({data.get('n_clips', '?')} broadcast clips) "
                              "on the GPU runner. Not yet measured on our own phone footage."}


def build_clip(csv_path: str | Path, clip: str, out_dir: str | Path, *, video: str | Path | None = None,
               sport: str = "badminton", fps: float = 25.0, width: int = 1920, height: int = 1080,
               preds: dict[str, list[dict | None]] | None = None, match_id: str | None = None) -> Path:
    """Write match.json + tracks.json (+ source.mp4 when the video is given) for one clip."""
    csv_path = Path(csv_path)
    preds = preds if preds is not None else read_predictions(csv_path)
    if clip not in preds:
        raise KeyError(f"clip {clip!r} not in {csv_path.name}; available e.g. {sorted(preds)[:5]}")
    balls = preds[clip]
    if video is not None:
        from rallyos.videoio import video_info

        info = video_info(video)
        fps, width, height = info["fps"], info["width"], info["height"]
        if info["frames"] and abs(info["frames"] - len(balls)) > 2:
            raise ValueError(f"{clip}: video has {info['frames']} frames but the CSV has {len(balls)}")
    match_id = match_id or f"rv_{clip}"
    match_name, _, rally = (Path(video).stem if clip == "clip" and video else clip).rpartition("_")
    match, tracks = ball_only_match(
        match_id=match_id, title=f"RacketVision clip · {match_name or clip} rally {rally}", sport=sport,
        balls=balls, fps=fps, width=width, height=height, video_src=None, sha256=video_fingerprint(video),
        tracker={**MODEL_INFO, **_reference_metrics(csv_path), "source_csv": csv_path.name})
    return write_outputs(out_dir, match, tracks, video=video)


def merge_into(out_dir: str | Path, csv_path: str | Path, clip: str | None = None, max_gap: int = 5) -> Path:
    """Replace the ball track in an existing output folder's tracks.json with the plug-in's track."""
    out = Path(out_dir)
    preds = read_predictions(csv_path)
    key = clip or (next(iter(preds)) if len(preds) == 1 else None)
    if key is None or key not in preds:
        raise KeyError("pass --clip: the CSV holds several clips" if key is None else f"clip {key!r} not in CSV")
    tracks = json.loads((out / "tracks.json").read_text(encoding="utf-8"))
    balls = fill_short_gaps(preds[key], max_gap=max_gap)
    for i, fr in enumerate(tracks["frames"]):
        fr["ball"] = balls[i] if i < len(balls) else None
    (out / "tracks.json").write_text(json.dumps(tracks, separators=(",", ":")), encoding="utf-8")
    return out


# -- GPU machine: drive their scripts ------------------------------------------------------------------

def _entry_like(example: object, match: str, rally: str) -> object:
    """Build a test.json entry for our clip in the same shape as an existing entry."""
    if isinstance(example, str):
        return f"{match}_{rally}"
    if isinstance(example, dict) and {"match", "rally"} <= set(example):
        return {**{k: v for k, v in example.items() if k not in ("match", "rally")}, "match": match, "rally": rally}
    if isinstance(example, (list, tuple)) and len(example) == 2:
        return [match, rally]
    raise RuntimeError(f"unrecognised entry in info/test.json: {example!r}; register the clip by hand")


def run_inference(video: str | Path, *, root: str | Path | None = None, python: str | None = None,
                  sport: str = "badminton", timeout: float | None = None) -> Path:
    """Run RacketVision's extract_frames -> create_median -> inference on one video; returns its results.csv.

    root   = RacketVision/source (env RALLYOS_RACKETVISION_ROOT)
    python = the .venv-racketvision interpreter (env RALLYOS_RACKETVISION_PY)
    Their inference reads the clip list from data/<sport>/info/test.json, so it is swapped for a one-clip
    list during the run and restored afterwards.
    """
    if not supports(sport):
        raise ValueError(f"RacketVision does not cover {sport}")
    root = Path(root or os.environ["RALLYOS_RACKETVISION_ROOT"])
    py = python or os.environ["RALLYOS_RACKETVISION_PY"]
    video = Path(video)
    stem = video.stem
    match, rally = (stem.rsplit("_", 1) if "_" in stem and stem.rsplit("_", 1)[1].isdigit() else (stem, "000"))
    data = root / "data" / sport
    (data / "videos").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, data / "videos" / f"{match}_{rally}.mp4")

    info = data / "info" / "test.json"
    original = info.read_text(encoding="utf-8")
    entries = json.loads(original)
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("info/test.json is not a non-empty list; register the clip by hand")
    info.write_text(json.dumps([_entry_like(entries[0], match, rally)]), encoding="utf-8")
    try:
        prep = root / "DataPreprocess"
        for script in ("extract_frames.py", "create_median.py"):
            subprocess.run([py, script, "--data_root", "../data", "--sports", sport], cwd=prep, check=True, timeout=timeout)
        subprocess.run([py, "inference.py", "--sport", sport, "--split", "test"], cwd=root / "BallTrack", check=True, timeout=timeout)
    finally:
        info.write_text(original, encoding="utf-8")
    result = data / "pred_ball" / match / rally / "results.csv"
    if not result.is_file():
        raise FileNotFoundError(f"inference finished but {result} is missing")
    return result


# -- CLI ------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m rallyos.track.plugins.racketvision")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="clips in a CSV")
    p.add_argument("csv")

    p = sub.add_parser("build", help="write match.json + tracks.json for clips")
    p.add_argument("csv")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--clip")
    g.add_argument("--all", action="store_true")
    p.add_argument("--video", help="source video for --clip")
    p.add_argument("--videos", help="folder with <clip>.mp4 files (used when present)")
    p.add_argument("--out", help="output folder for --clip (default demo/out/rv_<clip>)")
    p.add_argument("--out-root", default="demo/out")
    p.add_argument("--sport", default="badminton", choices=SUPPORTED_SPORTS)
    p.add_argument("--fps", type=float, default=25.0, help="used only when no video is given")

    p = sub.add_parser("merge", help="replace the ball track in an output folder")
    p.add_argument("out_dir")
    p.add_argument("csv")
    p.add_argument("--clip")

    p = sub.add_parser("run", help="GPU machine: run RacketVision inference on a video")
    p.add_argument("video")
    p.add_argument("--sport", default="badminton", choices=SUPPORTED_SPORTS)
    p.add_argument("--out", help="also build an output folder from the result")

    a = ap.parse_args(argv)
    if a.cmd == "list":
        for r in clip_summary(read_predictions(a.csv)):
            print(f"{r['clip']:<16} {r['frames']:>5} frames  {r['detected_pct']:.0%} detected")
    elif a.cmd == "build":
        preds = read_predictions(a.csv)
        clips = sorted(preds) if a.all else [a.clip]
        for clip in clips:
            video = a.video if a.clip else None
            if video is None and a.videos and (Path(a.videos) / f"{clip}.mp4").is_file():
                video = Path(a.videos) / f"{clip}.mp4"
            out = a.out if a.clip and a.out else Path(a.out_root) / f"rv_{clip}"
            build_clip(a.csv, clip, out, video=video, sport=a.sport, fps=a.fps, preds=preds)
            print(f"wrote {out}{'  (with video)' if video else ''}")
    elif a.cmd == "merge":
        print("updated", merge_into(a.out_dir, a.csv, a.clip))
    elif a.cmd == "run":
        result = run_inference(a.video, sport=a.sport)
        print("results:", result)
        if a.out:
            print("wrote", build_clip(result, "clip", a.out, video=a.video, sport=a.sport, match_id=f"rv_{Path(a.video).stem}"))


if __name__ == "__main__":
    sys.exit(main())
