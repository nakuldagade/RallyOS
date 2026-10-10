"""End-to-end pipeline (Analyzer). Each stage writes its output to disk so a crash keeps partial results.

    python -m rallyos.pipeline <clip.mp4> --sport badminton --taps "[[x,y],[x,y],[x,y],[x,y]]" --out demo/out/<clip>/

Stages in this version:
  calibrate  4-tap homography (automatic Court Fingerprint not built yet; without taps: no court positions),
             then focal length + camera position from that homography (self-calibration, 4.2)
  players    pretrained YOLO11n-pose at 1280 px, near/far roles (every `stride` frames)
  ball       three-frame-difference candidates + constant-velocity linking (geometric, no trained detector)
  audio      hit onsets from the soundtrack (band-limited spectral flux, sample-precise; 4.4)
  rallies    hit candidates from the shuttle path, attributed to the nearest wrist, fused with audio onsets
             (A/V sync, speed-of-sound correction, audio-only hits in tracking gaps); rallies from pauses
  analytics  per-player distance / top speed / coverage (needs calibration), ball tracking stats
  render     match.json + tracks.json + source video (the web app draws the overlay live)
  outcome    landing after each rally's last hit -> IN/OUT probability + uncertainty ellipse -> suggested
             rally winner -> score via the sport's rules engine (needs calibration; human confirms);
             calls below 90% get a Fair-Play Replay clip (6 s, half speed, trail drawn)
Not built yet (reported as skipped, never faked): shot types, speeds.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from rallyos.device import get_device
from rallyos.sports import load_sport

PLAYER_COLORS = {1: "#3b82f6", 2: "#ef4444"}


class Analyzer:
    SKIPPED_STAGES: tuple[str, ...] = ()
    NOT_COMPUTED = ["shot types", "speeds"]

    def __init__(self, sport: str = "auto", device: str | None = None, taps: list | None = None,
                 names: dict[int, str] | None = None, match_id: str | None = None,
                 imgsz: int | None = None, stride: int = 3):
        self.sport = "badminton" if sport in (None, "", "auto") else sport
        self.sport_given = sport not in (None, "", "auto")
        self.device = get_device(device)
        self.taps = taps
        self.names = {1: "Near player", 2: "Far player", **(names or {})}
        self.match_id = match_id
        # 1280 px input finds the far player (~20 px tall at 640); RALLYOS_MAX_WIDTH lowers it for quick CPU runs
        self.imgsz = imgsz or int(os.environ.get("RALLYOS_MAX_WIDTH") or 1280)
        self.stride = max(1, stride)

    def run(self, video_path: str, out_dir: str | None = None,
            progress: Callable[[str, float], None] | None = None) -> str:
        """Process a clip, writing each stage's output (and finally match.json) into out_dir. Returns out_dir."""
        import cv2

        from rallyos.audio.onsets import detect_onsets, load_audio
        from rallyos.calibration.camera import camera_from_homography
        from rallyos.calibration.template_fit import homography_from_taps
        from rallyos.detect.ball_candidates import BallCandidateDetector
        from rallyos.detect.players import PlayerSelector, find_static_people, load_pose_detector
        from rallyos.events.hits import attribute_hits, detect_hits, fuse_audio
        from rallyos.events.rallies import segment_rallies
        from rallyos.export import NO_CALIBRATION, ball_stats, write_outputs
        from rallyos.track.ball_dp import link_candidates
        from rallyos.track.kalman import fill_short_gaps
        from rallyos.videoio import sha256_file, video_info

        t0 = time.time()
        emit = progress or (lambda stage, frac: None)
        video = Path(video_path)
        match_id = self.match_id or f"m_{video.stem}"
        out = Path(out_dir or Path("demo/out") / match_id)
        out.mkdir(parents=True, exist_ok=True)
        cfg = load_sport(self.sport)
        info = video_info(video)
        fps, W, Hh = info["fps"], info["width"], info["height"]

        # -- calibrate --------------------------------------------------------------------------------
        emit("calibrate", 0.02)
        calib = homography_from_taps(self.taps, cfg) if self.taps else dict(NO_CALIBRATION)
        H = np.array(calib["homography"]) if self.taps else None
        camera = camera_from_homography(H, W, Hh) if H is not None else None
        if camera:
            calib["focal_px"] = camera["focal_px"]
            calib["camera_position_m"] = camera["position_m"]
        _dump(out / "stage_calibration.json", calib)
        x_range = None
        if self.taps:
            xs = [p[0] for p in self.taps]
            pad = 0.15 * W
            x_range = (min(xs) - pad, max(xs) + pad)

        # -- players + ball candidates (one decode pass) ------------------------------------------------
        detector, pose_backend = load_pose_detector(device=self.device, imgsz=self.imgsz)
        _dump(out / "stage_players_backend.json", {"available": detector is not None, "backend": pose_backend})
        balls_det = BallCandidateDetector()
        cap = cv2.VideoCapture(str(video))
        n_total = info["frames"] or 1
        sampled: list[tuple[int, list[dict]]] = []   # (frame index, every person detected) for pose frames
        cands: list[list] = []
        window: deque = deque(maxlen=3)            # (grey, all person boxes)
        last_boxes: list = []
        f = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if detector is not None and f % self.stride == 0:
                dets = detector(frame)
                sampled.append((f, dets))
                last_boxes = [d["bbox"] for d in dets]   # mask everyone (players and officials) for the ball search
            window.append((balls_det.prepare(frame), last_boxes))
            if len(window) == 3:
                (g0, _), (g1, boxes), (g2, _) = window
                cands.append(balls_det.candidates(g0, g1, g2, boxes, x_range))
            elif f == 0:
                cands.append([])
            f += 1
            if f % 10 == 0:
                emit("players", min(0.95, f / n_total))
        cap.release()
        n = f
        if n == 0:
            raise IOError(f"no frames decoded from {video}")
        cands.append([])                           # last frame has no successor
        cands = cands[:n]

        # -- audio onsets ---------------------------------------------------------------------------------
        emit("audio", 0.1)
        acfg = cfg.get("audio", {})
        samples, audio_status = load_audio(video)
        onsets = detect_onsets(samples, 44100, min_gap_s=acfg.get("min_gap_s", 0.15),
                               band_hz=acfg.get("band_hz", (1500, 10000))) if samples is not None else []
        _dump(out / "stage_audio.json", {"status": audio_status, "sample_rate": 44100, "onsets": onsets})

        # -- who is a player: drop static people (officials), then court + size checks per frame --------
        statics = find_static_people([d for _, d in sampled], Hh)
        selector = PlayerSelector(H, cfg["court"], Hh, statics)
        roles_at: dict[int, tuple[list, list]] = {}
        ignored_counts: dict[str, int] = {}
        for fi, dets in sampled:
            roles, ignored = selector.select(dets)
            roles_at[fi] = ([p for _, p in sorted(roles.items())], ignored)
            for ig in ignored:
                ignored_counts[ig["reason"]] = ignored_counts.get(ig["reason"], 0) + 1
        frames: list[dict] = []
        held: tuple[list, list] = ([], [])
        for fi in range(n):                        # hold the last pose frame's result in between
            held = roles_at.get(fi, held)
            frames.append({"f": fi, "players": [dict(p) for p in held[0]], "others": held[1], "ball": None})
        _dump(out / "stage_players.json", {"static_people": statics, "ignored_counts": ignored_counts,
                                           "sampled_frames": len(sampled)})
        _dump(out / "stage_ball_candidates.json", {"fps": fps, "candidates": cands})

        # -- ball track -----------------------------------------------------------------------------------
        emit("ball", 0.2)
        raw = link_candidates(cands, width=W, fps=fps)
        balls = fill_short_gaps(raw, max_gap=5)
        for fr, b in zip(frames, balls):
            fr["ball"] = b
        tracks = {"fps": fps, "frames": frames}
        _dump(out / "tracks.json", tracks, compact=True)

        # -- events ---------------------------------------------------------------------------------------
        emit("rallies", 0.3)
        hits = attribute_hits(detect_hits(balls, fps=fps, width=W), frames, Hh)
        hits, audio_info = fuse_audio(hits, onsets, fps, frames, camera_m=camera["position_m"] if camera else None,
                                      allow_audio_only=not cfg["projectile"].get("bounces", False),
                                      min_gap_s=acfg.get("min_gap_s", 0.15),
                                      contact_h=acfg.get("contact_height_m", 1.5))
        audio_info = {"status": audio_status, **audio_info}
        _dump(out / "stage_hits.json", {"audio": audio_info, "hits": hits})
        duration = round(n / fps, 3)
        rallies = segment_rallies(hits, duration)
        rally_of = {fr: r["idx"] for r in rallies for fr in r["hit_frames"]}
        events = []
        for h in hits:
            if h["frame"] not in rally_of:
                continue
            hitter = next((p for p in frames[h["frame"]]["players"] if p["track_id"] == h["track_id"]), None)
            events.append({
                "id": f"e_{len(events) + 1:04d}", "rally_idx": rally_of[h["frame"]], "t": h["t"], "type": "hit",
                "track_id": h["track_id"], "px": h["px"], "court": hitter["court"] if hitter else None,
                "shot": None, "speed_kmh": None, "speed_err_pct": None, "confidence": h["confidence"],
                "source": h.get("source", ["vision"]),
                **{k: h[k] for k in ("t_audio", "sound_delay_ms", "hitter_inferred") if h.get(k) is not None},
            })

        # -- rally outcome: landing -> line call -> suggested winner -> score -------------------------------
        from rallyos.analytics.linecall import DISPUTE_BELOW, resolve_rally_ends, score_rallies
        from rallyos.render.clips import render_review_clip

        landings = resolve_rally_ends(rallies, hits, balls, frames, cfg, fps, W, H=H, camera=camera)
        for r in rallies:
            r.pop("hit_frames")
        events = sorted(events + landings, key=lambda e: (e["t"], e["type"] != "hit"))
        for i, e in enumerate(events):
            e["id"] = f"e_{i + 1:04d}"
        disputes = []
        for e in events:
            if e["type"] != "landing" or "call" not in e:
                continue
            certain = e["call_prob"] if e["call"] != "TOO CLOSE TO CALL" else 0.0
            if certain >= DISPUTE_BELOW:
                continue
            did = f"d_{len(disputes) + 1:03d}"
            ok = render_review_clip(video, out / f"{did}.mp4", e["t"], fps, balls, e["px"], e["frame"],
                                    e["call"], e["call_prob"])
            e["dispute_id"] = did
            disputes.append({"id": did, "event_id": e["id"], "clip_url": f"/media/{match_id}/{did}.mp4" if ok else None,
                             "call": e["call"], "prob": e["call_prob"], "status": "open"})
        for e in landings:
            e.pop("frame", None)
        score = score_rallies(cfg, rallies, {1: 0, 2: 1}) if H is not None else             {"games": [], "winner_track_id": None, "confirmed_by_human": False, "source": None,
             "unresolved_rallies": len(rallies)}
        _dump(out / "stage_outcome.json", {"landings": landings, "disputes": disputes, "score": score,
                                          "rallies": rallies})

        # -- analytics ------------------------------------------------------------------------------------
        emit("analytics", 0.5)
        from rallyos.analytics.movement import movement_stats

        per_player: dict[str, dict] = {}
        for tid in (1, 2):
            seen = [(fr["f"] / fps, fr["players"]) for fr in frames if fr["f"] % self.stride == 0]
            pts = [(t, tuple(p["court"])) for t, ps in seen for p in ps if p["track_id"] == tid and p.get("court")]
            frames_seen = sum(1 for _, ps in seen if any(p["track_id"] == tid for p in ps))
            stats = {"tracked_pct": round(frames_seen / max(1, len(seen)), 3),
                     "hits": sum(1 for e in events if e["track_id"] == tid)}
            stats.update(movement_stats(pts))
            per_player[str(tid)] = stats
        rally_hits = [r["hits"] for r in rallies]
        players_meta = [{"track_id": tid, "player_id": None, "name": self.names[tid], "side": side,
                         "color": PLAYER_COLORS[tid]} for tid, side in ((1, "near"), (2, "far"))
                        if per_player[str(tid)]["tracked_pct"] > 0]

        # -- render ---------------------------------------------------------------------------------------
        emit("render", 0.8)
        match = {
            "schema_version": "1.0", "match_id": match_id, "title": None, "sport": self.sport,
            "sport_confidence": None,
            "sport_source": "chosen by user" if self.sport_given else "default (automatic detection not built yet)",
            "video": {"src": f"/media/{match_id}/source.mp4", "overlay": None, "fps": fps, "width": W, "height": Hh,
                      "duration_s": duration, "sha256": sha256_file(video)},
            "calibration": calib,
            "players": players_meta,
            "tracks_url": f"/media/{match_id}/tracks.json",
            "rallies": rallies,
            "events": events,
            "score": score,
            "stats": {
                "per_player": {k: v for k, v in per_player.items() if v["tracked_pct"] > 0},
                "match": {"rallies": len(rallies), "avg_rally_hits": round(sum(rally_hits) / len(rallies), 1) if rallies else 0.0,
                          "longest_rally_hits": max(rally_hits, default=0)},
                "ball": {**ball_stats(raw, balls, fps), "hit_candidates": len(hits), "tracker": "geometric",
                         "model": "three-frame differencing + physics-consistent tracklets (no trained ball detector)"},
                "audio": {**audio_info, "method": "band-limited spectral flux, sample-precise onsets (no training)"},
                "pipeline": {"device": self.device, "imgsz": self.imgsz, "player_stride": self.stride,
                             "players_backend": pose_backend if detector is not None else None,
                             "static_people_ignored": statics,
                             "ignored_detections": ignored_counts,
                             "players_skipped_reason": None if detector is not None else pose_backend,
                             "processing_s": round(time.time() - t0, 1),
                             "not_computed": self.NOT_COMPUTED + ([] if detector is not None else ["players + pose"])
                             + ([] if H is not None else ["line calls + score (need court calibration: 4 taps)"])},
            },
            "disputes": disputes,
            "insights": [],
        }
        write_outputs(out, match, tracks, video=video)
        emit("render", 1.0)
        return str(out)


def _dump(path: Path, data: dict, compact: bool = False) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rallyos.pipeline")
    ap.add_argument("video")
    ap.add_argument("--sport", default="auto")
    ap.add_argument("--device", default=None, choices=["auto", "cpu", "cuda"])
    ap.add_argument("--taps", default=None, help='JSON [[x,y]*4]: near-left, near-right, far-right, far-left (video px)')
    ap.add_argument("--out", default=None)
    ap.add_argument("--imgsz", type=int, default=None, help="pose model input size (default RALLYOS_MAX_WIDTH or 1280)")
    ap.add_argument("--stride", type=int, default=3, help="run the pose model every N frames")
    args = ap.parse_args(argv)
    t0 = time.time()
    out = Analyzer(sport=args.sport, device=args.device, taps=json.loads(args.taps) if args.taps else None,
                   imgsz=args.imgsz, stride=args.stride).run(
        args.video, out_dir=args.out, progress=lambda s, p: print(f"\r{s:<10} {p:4.0%}", end="", flush=True))
    print(f"\nwrote {out} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
