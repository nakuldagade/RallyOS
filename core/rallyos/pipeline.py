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
Shot types follow the YAML rules (analytics/shots.py); rules that need bounce / wall data are never guessed.
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
    # (id, label) in execution order, and each stage's share of the total time. progress callbacks report
    # (stage, fraction of that stage, note); a note starting with "skipped:" marks the stage as skipped.
    STAGES = (("calibrate", "Court calibration"), ("players", "Players, pose and shuttle search"),
              ("audio", "Hit sounds"), ("ball", "Shuttle trajectory"), ("rallies", "Hits and rallies"),
              ("outcome", "Landings, calls and score"), ("analytics", "Movement stats"), ("render", "Match record"))
    # share of the total time per stage, measured on 10 s clips on a CPU laptop. Finding the court automatically
    # takes several seconds; with the user's corners it is instant, so the bar uses the matching table.
    STAGE_WEIGHTS = {"calibrate": 0.01, "players": 0.84, "audio": 0.06, "ball": 0.01, "rallies": 0.01,
                     "outcome": 0.04, "analytics": 0.01, "render": 0.02}
    STAGE_WEIGHTS_AUTO = {"calibrate": 0.26, "players": 0.62, "audio": 0.06, "ball": 0.01, "rallies": 0.01,
                          "outcome": 0.02, "analytics": 0.01, "render": 0.01}
    SKIPPED_STAGES: tuple[str, ...] = ()
    NOT_COMPUTED: list[str] = []

    def __init__(self, sport: str = "auto", device: str | None = None, taps: list | None = None,
                 names: dict[int, str] | None = None, match_id: str | None = None,
                 imgsz: int | None = None, stride: int = 3, auto_calibrate: bool = True):
        self.sport = "badminton" if sport in (None, "", "auto") else sport
        self.sport_given = sport not in (None, "", "auto")
        self.device = get_device(device)
        self.taps = taps
        self.names = {1: "Near player", 2: "Far player", **(names or {})}
        self.match_id = match_id
        # 1280 px input finds the far player (~20 px tall at 640); RALLYOS_MAX_WIDTH lowers it for quick CPU runs
        self.imgsz = imgsz or int(os.environ.get("RALLYOS_MAX_WIDTH") or 1280)
        self.imgsz_fixed = bool(imgsz or os.environ.get("RALLYOS_MAX_WIDTH"))   # otherwise sized from the far player
        self.stride = max(1, stride)
        self.auto_calibrate = auto_calibrate     # find the court lines automatically when no taps are given

    def run(self, video_path: str, out_dir: str | None = None,
            progress: Callable[[str, float, str | None], None] | None = None) -> str:
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
        clock = {"stage": None, "t": time.time()}
        stage_seconds: dict[str, float] = {}

        def emit(stage: str, frac: float, note: str | None = None) -> None:
            if stage != clock["stage"]:
                if clock["stage"]:
                    stage_seconds[clock["stage"]] = round(stage_seconds.get(clock["stage"], 0.0) + time.time() - clock["t"], 2)
                clock.update(stage=stage, t=time.time())
            if progress:
                progress(stage, frac, note)

        video = Path(video_path)
        match_id = self.match_id or f"m_{video.stem}"
        out = Path(out_dir or Path("demo/out") / match_id)
        out.mkdir(parents=True, exist_ok=True)
        info = video_info(video)
        fps, W, Hh = info["fps"], info["width"], info["height"]

        # -- calibrate: the user's 4 taps, else the automatic Court Fingerprint ---------------------------
        emit("calibrate", 0.0, "starting")
        taps, auto, auto_note = self.taps, None, None
        if taps is None and self.auto_calibrate:
            from rallyos.calibration.court_fit import detect_court
            from rallyos.videoio import sample_frames

            emit("calibrate", 0.15, "reading frames to find the court lines")
            try:
                auto = detect_court(sample_frames(video, 9, span_s=3.0), [self.sport] if self.sport_given else None)
            except Exception as exc:                      # never let the optional auto step stop the analysis
                auto, auto_note = None, f"automatic court detection failed: {exc}"
            if auto is None and auto_note is None:
                auto_note = "no court found automatically: tap the 4 corners on the match page"
            elif auto is not None and auto["quality"] == "high":
                taps = auto["corners_px"]
                if not self.sport_given:
                    self.sport = auto["sport"]
            elif auto is not None:
                auto_note = (f"court proposed but not certain (precision {auto['precision']:.0%}): "
                             "not applied, check or tap the corners on the match page")
        emit("calibrate", 0.8, "building the court model")
        cfg = load_sport(self.sport)
        calib = homography_from_taps(taps, cfg) if taps else dict(NO_CALIBRATION)
        if auto is not None and taps is not None and self.taps is None:
            calib["method"] = "auto"
            calib["reprojection_error_px"] = auto["reprojection_error_px"]
        if auto is not None:
            calib["auto"] = {k: auto[k] for k in ("sport", "sport_confidence", "fit_score", "precision", "recall",
                                                  "quality", "corners_px", "ranking")}
        if auto_note:
            calib["note"] = auto_note
        H = np.array(calib["homography"]) if taps else None
        camera = camera_from_homography(H, W, Hh) if H is not None else None
        if camera:
            calib["focal_px"] = camera["focal_px"]
            calib["camera_position_m"] = camera["position_m"]
        _dump(out / "stage_calibration.json", calib)
        # look for players / the shuttle only on and around the tapped court (calibration/roi.py)
        from rallyos.calibration import roi as court_roi

        player_poly = court_roi.player_region(H, cfg, W, Hh, camera) if H is not None else None
        ball_poly = court_roi.ball_region(H, cfg, W, Hh, camera) if H is not None else None
        pose_box = court_roi.bbox(player_poly, W, Hh) if player_poly is not None else None
        ball_mask = court_roi.mask(ball_poly, W, Hh) if ball_poly is not None else None
        _dump(out / "stage_roi.json", {"player_region_px": player_poly.round(1).tolist() if player_poly is not None else None,
                                       "pose_crop_px": pose_box,
                                       "ball_region_px": ball_poly.round(1).tolist() if ball_poly is not None else None})

        # -- players + ball candidates (one decode pass) ------------------------------------------------
        # a smaller pose input was tried and rejected: at 704 px the far player was tracked in 6% of frames and at
        # 896 px in 95% (Macau clip), so the full 1280 stays the default; RALLYOS_MAX_WIDTH lowers it on purpose
        pose_note = "fixed by RALLYOS_MAX_WIDTH / imgsz" if self.imgsz_fixed else "default 1280 (keeps the far player)"
        emit("players", 0.0, "loading the pose model")
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
                dets = court_roi.cropped(detector, frame, pose_box) if pose_box else detector(frame)
                sampled.append((f, dets))
                last_boxes = [d["bbox"] for d in dets]   # mask everyone (players and officials) for the ball search
            window.append((balls_det.prepare(frame), last_boxes))
            if len(window) == 3:
                (g0, _), (g1, boxes), (g2, _) = window
                cands.append(balls_det.candidates(g0, g1, g2, boxes, roi=ball_mask))
            elif f == 0:
                cands.append([])
            f += 1
            if f % 10 == 0:
                emit("players", min(0.98, f / n_total), f"frame {f} of {n_total}")
        cap.release()
        n = f
        if n == 0:
            raise IOError(f"no frames decoded from {video}")
        cands.append([])                           # last frame has no successor
        cands = cands[:n]

        # -- who is a player: drop static people (officials), then court + size checks per frame --------
        emit("players", 0.99, "choosing the two players")
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

        # -- audio onsets ---------------------------------------------------------------------------------
        emit("audio", 0.1, "reading the soundtrack")
        acfg = cfg.get("audio", {})
        samples, audio_status = load_audio(video)
        onsets = detect_onsets(samples, 44100, min_gap_s=acfg.get("min_gap_s", 0.15),
                               band_hz=acfg.get("band_hz", (1500, 10000))) if samples is not None else []
        _dump(out / "stage_audio.json", {"status": audio_status, "sample_rate": 44100, "onsets": onsets})

        emit("audio", 1.0, f"skipped: {audio_status}" if audio_status != "ok" else f"{len(onsets)} hit sounds found")

        # -- ball track -----------------------------------------------------------------------------------
        emit("ball", 0.0, "linking shuttle candidates into a path")
        raw = link_candidates(cands, width=W, fps=fps)
        balls = fill_short_gaps(raw, max_gap=5)
        for fr, b in zip(frames, balls):
            fr["ball"] = b
        tracks = {"fps": fps, "frames": frames}
        _dump(out / "tracks.json", tracks, compact=True)

        # -- events ---------------------------------------------------------------------------------------
        emit("rallies", 0.0, "finding hits and splitting rallies")
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
        emit("outcome", 0.0, "finding landings and making calls")
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
        from rallyos.analytics.speed import annotate_speeds, player_speed_stats

        speed_summary = annotate_speeds(events, fps, cfg) if H is not None else None
        from rallyos.analytics.shots import classify_shots, shot_mix

        shot_summary = classify_shots(events, frames, fps, cfg) if H is not None else None
        score = score_rallies(cfg, rallies, {1: 0, 2: 1}) if H is not None else             {"games": [], "winner_track_id": None, "confirmed_by_human": False, "source": None,
             "unresolved_rallies": len(rallies)}
        _dump(out / "stage_outcome.json", {"landings": landings, "disputes": disputes, "score": score,
                                          "rallies": rallies})

        # -- analytics ------------------------------------------------------------------------------------
        emit("analytics", 0.0, "distance, speed and coverage")
        from rallyos.analytics.movement import movement_stats, zone_time

        per_player: dict[str, dict] = {}
        for tid in (1, 2):
            seen = [(fr["f"] / fps, fr["players"]) for fr in frames if fr["f"] % self.stride == 0]
            pts = [(t, tuple(p["court"])) for t, ps in seen for p in ps if p["track_id"] == tid and p.get("court")]
            frames_seen = sum(1 for _, ps in seen if any(p["track_id"] == tid for p in ps))
            stats = {"tracked_pct": round(frames_seen / max(1, len(seen)), 3),
                     "hits": sum(1 for e in events if e["track_id"] == tid)}
            stats.update(movement_stats(pts))
            stats.update(zone_time([c for _, c in pts], cfg, "near" if tid == 1 else "far"))
            stats.update(player_speed_stats(events).get(tid, {}))
            if shot_summary:
                stats["shot_mix"] = shot_mix(events, tid)
            per_player[str(tid)] = stats
        rally_hits = [r["hits"] for r in rallies]
        players_meta = [{"track_id": tid, "player_id": None, "name": self.names[tid], "side": side,
                         "color": PLAYER_COLORS[tid]} for tid, side in ((1, "near"), (2, "far"))
                        if per_player[str(tid)]["tracked_pct"] > 0]

        # -- render ---------------------------------------------------------------------------------------
        emit("render", 0.0, "writing the match record")
        match = {
            "schema_version": "1.0", "match_id": match_id, "title": None, "sport": self.sport,
            "sport_confidence": auto["sport_confidence"] if auto and self.sport == auto["sport"] else None,
            "sport_source": "chosen by user" if self.sport_given else
                            ("auto-detected (Court Fingerprint)" if auto and self.sport == auto["sport"] else "default (not detected)"),
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
                "speed": speed_summary,
                "shots": shot_summary,
                "audio": {**audio_info, "method": "band-limited spectral flux, sample-precise onsets (no training)"},
                "pipeline": {"device": self.device, "imgsz": self.imgsz, "imgsz_basis": pose_note, "player_stride": self.stride,
                             "players_backend": pose_backend if detector is not None else None,
                             "static_people_ignored": statics,
                             "ignored_detections": ignored_counts,
                             "players_skipped_reason": None if detector is not None else pose_backend,
                             "processing_s": round(time.time() - t0, 1), "stage_seconds": stage_seconds,
                             "not_computed": self.NOT_COMPUTED + ([] if detector is not None else ["players + pose"])
                             + ([] if H is not None else ["speeds, shot types, line calls and score (need the court: automatic detection or 4 corners)"])},
            },
            "disputes": disputes,
            "insights": [],
        }
        write_outputs(out, match, tracks, video=video)
        emit("render", 1.0, "done")
        emit("done", 1.0)
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
        args.video, out_dir=args.out, progress=lambda s, p, note=None: print(f"\r{s:<10} {p:4.0%} {note or '':<44}", end="", flush=True))
    print(f"\nwrote {out} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
