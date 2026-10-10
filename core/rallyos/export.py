"""Write pipeline outputs (match.json + tracks.json) in the §11.3 contract.

ball_only_match builds a match record when only a ball track exists (e.g. a RacketVision clip):
no players, no calibration, no score. Everything not measured is left empty rather than invented.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rallyos.events.hits import detect_hits
from rallyos.track.kalman import fill_short_gaps
from rallyos.videoio import sha256_file

NO_CALIBRATION = {"method": "none", "homography": [[0.0] * 3, [0.0] * 3, [0.0] * 3],
                  "focal_px": None, "reprojection_error_px": None}


def ball_stats(raw: list[dict | None], filled: list[dict | None], fps: float) -> dict:
    n = len(raw)
    det = [b for b in raw if b is not None]
    longest = cur = 0
    for b in filled:
        cur = cur + 1 if b is None else 0
        longest = max(longest, cur)
    return {
        "frames": n,
        "detected_frames": len(det),
        "detected_pct": round(len(det) / n, 3) if n else 0.0,
        "interpolated_frames": sum(1 for b in filled if b is not None and b.get("interp")),
        "longest_gap_s": round(longest / fps, 2),
        "mean_conf": round(sum(b["conf"] for b in det) / len(det), 3) if det else None,
    }


def ball_only_match(*, match_id: str, title: str, sport: str, balls: list[dict | None], fps: float,
                    width: int, height: int, video_src: str | None, sha256: str | None,
                    tracker: dict, max_gap: int = 5) -> tuple[dict, dict]:
    """Return (match_json, tracks_json) for a clip where only the ball was tracked."""
    filled = fill_short_gaps(balls, max_gap=max_gap)
    hits = detect_hits(filled, fps=fps, width=width)
    seen = [i for i, b in enumerate(balls) if b is not None]
    events = [{
        "id": f"e_{k + 1:04d}", "rally_idx": 0, "t": h["t"], "type": "hit", "track_id": None,
        "px": h["px"], "court": None, "shot": None, "speed_kmh": None, "speed_err_pct": None,
        "confidence": h["confidence"], "source": ["vision"],
    } for k, h in enumerate(hits)]
    rallies = []
    if seen:
        rallies.append({
            "idx": 0, "t_start": round(seen[0] / fps, 2), "t_end": round(seen[-1] / fps, 2), "hits": len(hits),
            "winner_track_id": None, "end_reason": None,
            # vision-only: hits inside long tracking gaps are missed until audio onsets confirm them
            "confidence": round(0.5 * ball_stats(balls, filled, fps)["detected_pct"], 2), "score_after": None,
        })
    stats_ball = {**ball_stats(balls, filled, fps), "hit_candidates": len(hits), **tracker}
    match = {
        "schema_version": "1.0", "match_id": match_id, "title": title, "sport": sport, "sport_confidence": None,
        "video": {"src": video_src or f"/media/{match_id}/source.mp4", "overlay": None, "fps": fps,
                  "width": width, "height": height, "duration_s": round(len(balls) / fps, 3), "sha256": sha256},
        "calibration": dict(NO_CALIBRATION),
        "players": [],
        "tracks_url": f"/media/{match_id}/tracks.json",
        "rallies": rallies,
        "events": events,
        "score": {"games": [], "winner_track_id": None, "confirmed_by_human": False},
        "stats": {"per_player": {}, "match": {"rallies": len(rallies), "avg_rally_hits": float(len(hits)),
                                              "longest_rally_hits": len(hits)}, "ball": stats_ball},
        "disputes": [],
        "insights": [],
    }
    tracks = {"fps": fps, "frames": [{"f": i, "players": [], "ball": b} for i, b in enumerate(filled)]}
    return match, tracks


def write_outputs(out_dir: str | Path, match: dict, tracks: dict, video: str | Path | None = None) -> Path:
    """Write match.json, tracks.json (and copy the source video as source.mp4) into out_dir."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "tracks.json").write_text(json.dumps(tracks, separators=(",", ":")), encoding="utf-8")
    if video is not None:
        dest = out / "source.mp4"
        if Path(video).resolve() != dest.resolve():
            shutil.copyfile(video, dest)
    (out / "match.json").write_text(json.dumps(match, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def video_fingerprint(video: str | Path | None) -> str | None:
    return sha256_file(video) if video else None
