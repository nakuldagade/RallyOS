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

from rallyos.stages import PLAYER_COLORS  # noqa: E402,F401  (kept importable from here)


class Analyzer:
    # (id, label) in execution order, and each stage's share of the total time. progress callbacks report
    # (stage, fraction of that stage, note); a note starting with "skipped:" marks the stage as skipped.
    STAGES = (("calibrate", "Court calibration"), ("players", "Players, pose and shuttle search"),
              ("audio", "Hit sounds"), ("ball", "Shuttle trajectory"), ("rallies", "Hits and rallies"),
              ("outcome", "Landings, calls and score"), ("analytics", "Movement stats"), ("render", "Match record"))
    # share of the total time per stage, measured on 10 s clips on a CPU laptop. Finding the court automatically
    # takes several seconds; with the user's corners it is instant, so the bar uses the matching table.
    STAGE_WEIGHTS = {"calibrate": 0.01, "players": 0.74, "audio": 0.05, "ball": 0.01, "rallies": 0.01,
                     "outcome": 0.03, "analytics": 0.13, "render": 0.02}
    STAGE_WEIGHTS_AUTO = {"calibrate": 0.26, "players": 0.56, "audio": 0.05, "ball": 0.01, "rallies": 0.01,
                          "outcome": 0.02, "analytics": 0.08, "render": 0.01}
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
        """Process a clip, writing each stage's output (and finally match.json) into out_dir. Returns out_dir.

        The stages themselves live in rallyos/stages.py and are shared with the live StreamAnalyzer."""
        from rallyos import stages
        from rallyos.audio.onsets import detect_onsets, load_audio
        from rallyos.detect.players import load_pose_detector
        from rallyos.export import write_outputs
        from rallyos.videoio import sample_frames, sha256_file, video_info

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
        scene = stages.build_scene(sport=self.sport, sport_given=self.sport_given, taps=self.taps,
                                   auto_calibrate=self.auto_calibrate, fps=fps, width=W, height=Hh, emit=emit,
                                   detect_frames=lambda: sample_frames(video, 9, span_s=3.0))
        self.sport = scene.sport
        cal_file, roi_file = stages.scene_files(scene)
        _dump(out / "stage_calibration.json", cal_file)
        _dump(out / "stage_roi.json", roi_file)
        cfg, H = scene.cfg, scene.H

        # -- players + ball candidates (one decode pass) ------------------------------------------------
        # a smaller pose input was tried and rejected: at 704 px the far player was tracked in 6% of frames and at
        # 896 px in 95% (Macau clip), so the full 1280 stays the default; RALLYOS_MAX_WIDTH lowers it on purpose
        pose_note = "fixed by RALLYOS_MAX_WIDTH / imgsz" if self.imgsz_fixed else "default 1280 (keeps the far player)"
        emit("players", 0.0, "loading the pose model")
        detector, pose_backend = load_pose_detector(device=self.device, imgsz=self.imgsz)
        _dump(out / "stage_players_backend.json", {"available": detector is not None, "backend": pose_backend})
        import cv2

        scanner = stages.FrameScanner(scene, detector, self.stride)
        cap = cv2.VideoCapture(str(video))
        n_total = info["frames"] or 1
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            scanner.feed(frame)
            if scanner.f % 10 == 0:
                emit("players", min(0.98, scanner.f / n_total), f"frame {scanner.f} of {n_total}")
        cap.release()
        n = scanner.f
        if n == 0:
            raise IOError(f"no frames decoded from {video}")
        cands = scanner.candidates()

        # -- who is a player: drop static people (officials), then court + size checks per frame --------
        emit("players", 0.99, "choosing the two players")
        tracker = stages.PlayerTracker(scene)
        tracker.set_statics(scanner.sampled)
        frames = tracker.extend(scanner.sampled, n)
        _dump(out / "stage_players.json", {"static_people": tracker.statics, "ignored_counts": tracker.ignored_counts,
                                           "sampled_frames": len(scanner.sampled)})
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
        raw, balls = stages.link_ball(scene, cands)
        for fr, b in zip(frames, balls):
            fr["ball"] = b
        tracks = {"fps": fps, "frames": frames}
        _dump(out / "tracks.json", tracks, compact=True)

        # -- events ---------------------------------------------------------------------------------------
        emit("rallies", 0.0, "finding hits and splitting rallies")
        duration = round(n / fps, 3)
        hits, audio_info, rallies, events = stages.find_events(scene, balls, frames, onsets, audio_status, duration)
        _dump(out / "stage_hits.json", {"audio": audio_info, "hits": hits})

        # -- rally outcome: landing -> line call -> suggested winner -> score -------------------------------
        emit("outcome", 0.0, "finding landings and making calls")
        events, landings, disputes, score, speed_summary, shot_summary = stages.resolve_outcome(
            scene, rallies, hits, balls, frames, events, video=video, out=out, match_id=match_id)
        _dump(out / "stage_outcome.json", {"landings": landings, "disputes": disputes, "score": score, "rallies": rallies})

        # -- analytics ------------------------------------------------------------------------------------
        emit("analytics", 0.0, "distance, speed and coverage")
        per_player, players_meta, split_note = stages.movement_analytics(
            scene, frames, events, rallies, stride=self.stride, names=self.names, shot_summary=shot_summary, n_frames=n,
            video=video, detector=detector, device=self.device, emit=emit)

        # -- render ---------------------------------------------------------------------------------------
        emit("render", 0.0, "writing the match record")
        match = stages.make_match(
            scene, match_id=match_id,
            video={"src": f"/media/{match_id}/source.mp4", "overlay": None, "fps": fps, "width": W, "height": Hh,
                   "duration_s": duration, "sha256": sha256_file(video)},
            players_meta=players_meta, tracks_url=f"/media/{match_id}/tracks.json", rallies=rallies, events=events,
            score=score, disputes=disputes, per_player=per_player, raw=raw, balls=balls, hits=hits,
            speed_summary=speed_summary, split_note=split_note, shot_summary=shot_summary, audio_info=audio_info,
            pipeline={"device": self.device, "imgsz": self.imgsz, "imgsz_basis": pose_note, "player_stride": self.stride,
                      "players_backend": pose_backend if detector is not None else None,
                      "static_people_ignored": tracker.statics, "ignored_detections": tracker.ignored_counts,
                      "players_skipped_reason": None if detector is not None else pose_backend,
                      "processing_s": round(time.time() - t0, 1), "stage_seconds": stage_seconds,
                      "not_computed": self.NOT_COMPUTED + ([] if detector is not None else ["players + pose"])
                      + ([] if H is not None else ["speeds, shot types, line calls and score (need the court: automatic detection or 4 corners)"])})
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
