"""The stages of the analysis pipeline as functions, shared by the batch Analyzer (pipeline.py) and the live
StreamAnalyzer (live/stream.py). The code here is the body of the former Analyzer.run, moved unchanged; the two
analyzers differ only in how they feed it (a whole file, or chunk after chunk).

    build_scene      calibrate once: corners or automatic court fit -> homography, camera, regions of interest
    FrameScanner     per frame: pose (every Nth frame, on the court crop) + shuttle candidates (three-frame difference)
    PlayerTracker    who is a player (drop officials, court margins, size) and the per-frame players list
    link_ball        shuttle candidates -> a physics-consistent path, short gaps filled and flagged
    find_events      hits (path + wrist + audio fusion) -> rallies -> hit events
    resolve_outcome  landings -> IN/OUT calls -> winners -> score; speeds; shot types; dispute clips
    movement_analytics   return to base, split-step, fatigue, zones, per-player stats
    make_match       the match.json dictionary
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from rallyos.sports import load_sport

PLAYER_COLORS = {1: "#3b82f6", 2: "#ef4444"}


# ---------------------------------------------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------------------------------------------

@dataclass
class Scene:
    """Everything fixed once the court is known: reused for every frame of every chunk."""
    sport: str
    sport_given: bool
    cfg: dict
    fps: float
    width: int
    height: int
    calib: dict
    H: np.ndarray | None
    camera: dict | None
    auto: dict | None
    auto_note: str | None
    taps: list | None
    pose_box: tuple | None
    ball_mask: np.ndarray | None
    player_poly: np.ndarray | None = None
    ball_poly: np.ndarray | None = None
    user_taps: bool = False
    extra: dict = field(default_factory=dict)


def build_scene(*, sport: str, sport_given: bool, taps: list | None, auto_calibrate: bool,
                detect_frames: Callable[[], list], fps: float, width: int, height: int,
                emit: Callable[[str, float, str | None], None] | None = None) -> Scene:
    """The user's 4 taps, else the automatic Court Fingerprint on frames from `detect_frames()`, else no court."""
    from rallyos.calibration import roi as court_roi
    from rallyos.calibration.camera import camera_from_homography
    from rallyos.calibration.template_fit import homography_from_taps
    from rallyos.export import NO_CALIBRATION

    emit = emit or (lambda s, f, n=None: None)
    user_taps = taps is not None
    auto, auto_note = None, None
    if taps is None and auto_calibrate:
        from rallyos.calibration.court_fit import detect_court

        emit("calibrate", 0.15, "reading frames to find the court lines")
        try:
            auto = detect_court(detect_frames(), [sport] if sport_given else None)
        except Exception as exc:                      # never let the optional auto step stop the analysis
            auto, auto_note = None, f"automatic court detection failed: {exc}"
        if auto is None and auto_note is None:
            auto_note = "no court found automatically: tap the 4 corners on the match page"
        elif auto is not None and auto["quality"] == "high":
            taps = auto["corners_px"]
            if not sport_given:
                sport = auto["sport"]
        elif auto is not None:
            auto_note = (f"court proposed but not certain (precision {auto['precision']:.0%}): "
                         "not applied, check or tap the corners on the match page")
    emit("calibrate", 0.8, "building the court model")
    cfg = load_sport(sport)
    calib = homography_from_taps(taps, cfg) if taps else dict(NO_CALIBRATION)
    if auto is not None and taps is not None and not user_taps:
        calib["method"] = "auto"
        calib["reprojection_error_px"] = auto["reprojection_error_px"]
    if auto is not None:
        calib["auto"] = {k: auto[k] for k in ("sport", "sport_confidence", "fit_score", "precision", "recall",
                                              "quality", "corners_px", "ranking")}
    if auto_note:
        calib["note"] = auto_note
    H = np.array(calib["homography"]) if taps else None
    camera = camera_from_homography(H, width, height) if H is not None else None
    if camera:
        calib["focal_px"] = camera["focal_px"]
        calib["camera_position_m"] = camera["position_m"]
    # look for players / the shuttle only on and around the court (calibration/roi.py)
    player_poly = court_roi.player_region(H, cfg, width, height, camera) if H is not None else None
    ball_poly = court_roi.ball_region(H, cfg, width, height, camera) if H is not None else None
    pose_box = court_roi.bbox(player_poly, width, height) if player_poly is not None else None
    ball_mask = court_roi.mask(ball_poly, width, height) if ball_poly is not None else None
    return Scene(sport=sport, sport_given=sport_given, cfg=cfg, fps=fps, width=width, height=height, calib=calib, H=H,
                 camera=camera, auto=auto, auto_note=auto_note, taps=taps, pose_box=pose_box, ball_mask=ball_mask,
                 player_poly=player_poly, ball_poly=ball_poly, user_taps=user_taps)


def scene_files(scene: Scene) -> tuple[dict, dict]:
    """(stage_calibration.json, stage_roi.json) contents."""
    pp, bp = scene.player_poly, scene.ball_poly
    return scene.calib, {"player_region_px": pp.round(1).tolist() if pp is not None else None, "pose_crop_px": scene.pose_box,
                         "ball_region_px": bp.round(1).tolist() if bp is not None else None}


# ---------------------------------------------------------------------------------------------------------------
# per-frame scan: pose + shuttle candidates
# ---------------------------------------------------------------------------------------------------------------

_POOLS: dict[str, object] = {}


def _pool(name: str, workers: int):
    """Process-wide worker threads. Pose and the shuttle search spend their time inside torch / OpenVINO / OpenCV, which
    release the GIL, so they run truly in parallel with each other and with the decoding on the main thread."""
    if name not in _POOLS:
        from concurrent.futures import ThreadPoolExecutor

        _POOLS[name] = ThreadPoolExecutor(max(1, workers), thread_name_prefix=name)
    return _POOLS[name]


POSE_WORKERS = int(os.environ.get("RALLYOS_POSE_WORKERS") or 2)       # pose calls in flight at once
SEARCH_WORKERS = int(os.environ.get("RALLYOS_SEARCH_WORKERS") or 3)   # shuttle searches in flight at once
MAX_SEARCH_PENDING = 24


class FrameScanner:
    """Feed frames in order; it keeps the pose samples and the shuttle candidates of every frame it has seen.

    State carried between calls (and so between live chunks): the 3-frame window, the last pose boxes (used to mask
    people out of the shuttle search) and the global frame counter that decides which frames get pose.

    Three things run at once, with exactly the results of doing them one after the other:
      * pose of the next pose frames runs on worker threads while the frames before them are searched for the shuttle
        (each frame is masked with the people found on the pose frame at or before it, so a frame waits for that one result);
      * the per-frame shuttle search (frame differences, connected components) is independent between frames and runs on a pool;
      * the main thread only decodes and prepares frames.
    `flush()` finishes everything still waiting; every reader of the results (`sampled`, `candidates()`, `skip()`) calls it first.
    """

    def __init__(self, scene: Scene, detector, stride: int = 3):
        from rallyos.detect.ball_candidates import BallCandidateDetector

        self.scene, self.detector, self.stride = scene, detector, max(1, stride)
        self.balls_det = BallCandidateDetector()
        self.window: deque = deque(maxlen=3)
        self.last_boxes: list = []
        self._sampled: list[tuple[int, list[dict]]] = []    # (frame index, every person detected) on pose frames
        self._cands: list = []                               # per frame, best shuttle candidates (or a future of them)
        self._resolved = 0                                   # _cands[:_resolved] are plain lists
        self._queue: deque = deque()                         # (frame index, frame, pose future or None), not yet searched
        self._pose_fs: list[int] = []                        # pose frames in the queue, oldest first
        self.f = 0                                           # frames fed so far = index of the next frame

    @property
    def sampled(self) -> list[tuple[int, list[dict]]]:
        self.flush()
        return self._sampled

    def _pose(self, frame: np.ndarray) -> list[dict]:
        from rallyos.calibration import roi as court_roi

        sc = self.scene
        return court_roi.cropped(self.detector, frame, sc.pose_box) if sc.pose_box else self.detector(frame)

    def feed(self, frame: np.ndarray) -> None:
        f = self.f
        job = None
        if self.detector is not None and f % self.stride == 0:
            job = _pool("pose", POSE_WORKERS).submit(self._pose, frame)
            self._pose_fs.append(f)
        self._queue.append((f, frame, job))
        self.f += 1
        ahead = max(1, POSE_WORKERS)
        if job is not None and len(self._pose_fs) >= ahead:
            self._drain(before=self._pose_fs[-ahead])        # the frames whose pose has had the longest to finish

    def _drain(self, before: int | None = None) -> None:
        while self._queue and (before is None or self._queue[0][0] < before):
            f, frame, job = self._queue.popleft()
            sc = self.scene
            if job is not None:
                dets = job.result()
                self._pose_fs.remove(f)
                self._sampled.append((f, dets))
                self.last_boxes = [d["bbox"] for d in dets]  # mask everyone (players and officials) for the shuttle search
            self.window.append((self.balls_det.prepare(frame), self.last_boxes))
            if len(self.window) == 3:
                (g0, _), (g1, boxes), (g2, _) = self.window
                if sc.ball_mask is not None:
                    self.balls_det.roi_for(sc.ball_mask, g1.shape)    # resolve the mask once, before the threads need it
                self._cands.append(_pool("search", SEARCH_WORKERS).submit(self.balls_det.candidates, g0, g1, g2, boxes, roi=sc.ball_mask))
                self._settle(keep=MAX_SEARCH_PENDING)
            elif f == 0:
                self._cands.append([])

    def _settle(self, keep: int = 0) -> None:
        """Turn finished futures into lists, oldest first, leaving at most `keep` unresolved (bounds the frames held in memory)."""
        while self._resolved < len(self._cands) - keep:
            c = self._cands[self._resolved]
            if hasattr(c, "result"):
                self._cands[self._resolved] = c.result()
            self._resolved += 1

    def flush(self) -> None:
        """Finish every frame still waiting for its pose result and every shuttle search still running."""
        self._drain()
        self._settle()

    def skip(self, n: int = 1) -> None:
        """Frames that never arrived (dropped): keep indices aligned with empty entries and a broken window."""
        self.flush()
        for _ in range(n):
            self.window.clear()
            self._cands.append([])
            self.f += 1
        self._settle()

    def candidates(self) -> list[list]:
        """Per-frame candidates for all frames fed so far; the newest frame has no successor yet, so it is empty."""
        self.flush()
        out = list(self._cands)
        while len(out) < self.f:
            out.append([])
        return out[: self.f]


# ---------------------------------------------------------------------------------------------------------------
# who is a player
# ---------------------------------------------------------------------------------------------------------------

class PlayerTracker:
    """Drops static people (officials), applies court and size checks per pose frame, and holds the last pose
    frame's players in between: the `frames` list every later stage reads."""

    def __init__(self, scene: Scene):
        self.scene = scene
        self.statics: list[dict] = []
        self.selector = None
        self.ignored_counts: dict[str, int] = {}
        self.roles_at: dict[int, tuple[list, list]] = {}
        self.frames: list[dict] = []
        self._held: tuple[list, list] = ([], [])
        self._done = 0                                       # sampled entries already selected

    def set_statics(self, sampled: list[tuple[int, list[dict]]]) -> None:
        from rallyos.detect.players import PlayerSelector, find_static_people

        sc = self.scene
        self.statics = find_static_people([d for _, d in sampled], sc.height)
        self.selector = PlayerSelector(sc.H, sc.cfg["court"], sc.height, self.statics)
        self._done = 0
        self.roles_at.clear()
        self.ignored_counts.clear()
        self.frames.clear()
        self._held = ([], [])

    def extend(self, sampled: list[tuple[int, list[dict]]], n_frames: int) -> list[dict]:
        """Select players for pose samples not yet seen and extend `frames` to n_frames (holding the last result)."""
        for fi, dets in sampled[self._done:]:
            roles, ignored = self.selector.select(dets)
            self.roles_at[fi] = ([p for _, p in sorted(roles.items())], ignored)
            for ig in ignored:
                self.ignored_counts[ig["reason"]] = self.ignored_counts.get(ig["reason"], 0) + 1
        self._done = len(sampled)
        for fi in range(len(self.frames), n_frames):         # hold the last pose frame's result in between
            self._held = self.roles_at.get(fi, self._held)
            self.frames.append({"f": fi, "players": [dict(p) for p in self._held[0]], "others": self._held[1], "ball": None})
        return self.frames


def link_ball(scene: Scene, cands: list[list]) -> tuple[list, list]:
    """(raw, balls): the linked shuttle path, and the same with short gaps filled (flagged interpolated)."""
    from rallyos.track.ball_dp import link_candidates
    from rallyos.track.kalman import fill_short_gaps

    raw = link_candidates(cands, width=scene.width, fps=scene.fps)
    return raw, fill_short_gaps(raw, max_gap=5)


# ---------------------------------------------------------------------------------------------------------------
# hits -> rallies -> events
# ---------------------------------------------------------------------------------------------------------------

def find_events(scene: Scene, balls: list, frames: list[dict], onsets: list[dict], audio_status: str, duration: float,
                extra_hits: list[dict] | None = None):
    """(hits, audio_info, rallies, events). `extra_hits`: earlier, frozen hits to keep when re-running a tail window."""
    from rallyos.events.hits import attribute_hits, detect_hits, fuse_audio
    from rallyos.events.rallies import segment_rallies

    cfg, fps, W, Hh, camera = scene.cfg, scene.fps, scene.width, scene.height, scene.camera
    acfg = cfg.get("audio", {})
    hits = attribute_hits(detect_hits(balls, fps=fps, width=W), frames, Hh)
    hits, audio_info = fuse_audio(hits, onsets, fps, frames, camera_m=camera["position_m"] if camera else None,
                                  allow_audio_only=not cfg["projectile"].get("bounces", False),
                                  min_gap_s=acfg.get("min_gap_s", 0.15), contact_h=acfg.get("contact_height_m", 1.5))
    audio_info = {"status": audio_status, **audio_info}
    if extra_hits:
        hits = sorted(list(extra_hits) + hits, key=lambda h: h["t"])
    rallies = segment_rallies(hits, duration)
    rally_of = {fr: r["idx"] for r in rallies for fr in r["hit_frames"]}
    events = []
    for h in hits:
        if h["frame"] not in rally_of:
            continue
        hitter = next((p for p in frames[h["frame"]]["players"] if p["track_id"] == h["track_id"]), None) \
            if h["frame"] < len(frames) else None
        events.append({
            "id": f"e_{len(events) + 1:04d}", "rally_idx": rally_of[h["frame"]], "t": h["t"], "type": "hit",
            "track_id": h["track_id"], "px": h["px"], "court": hitter["court"] if hitter else None,
            "shot": None, "speed_kmh": None, "speed_err_pct": None, "confidence": h["confidence"],
            "source": h.get("source", ["vision"]),
            **{k: h[k] for k in ("t_audio", "sound_delay_ms", "hitter_inferred") if h.get(k) is not None},
        })
    return hits, audio_info, rallies, events


def resolve_outcome(scene: Scene, rallies: list[dict], hits: list[dict], balls: list, frames: list[dict],
                    events: list[dict], *, video=None, out: Path | None = None, match_id: str = ""):
    """(events, landings, disputes, score, speed_summary, shot_summary). With `video`, close calls get review clips."""
    from rallyos.analytics.linecall import DISPUTE_BELOW, resolve_rally_ends, score_rallies
    from rallyos.analytics.shots import classify_shots
    from rallyos.analytics.speed import annotate_speeds
    from rallyos.render.clips import render_review_clip

    cfg, fps, W, H, camera = scene.cfg, scene.fps, scene.width, scene.H, scene.camera
    landings = resolve_rally_ends(rallies, hits, balls, frames, cfg, fps, W, H=H, camera=camera)
    for r in rallies:
        r.pop("hit_frames", None)
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
        ok = bool(video is not None and out is not None and
                  render_review_clip(video, out / f"{did}.mp4", e["t"], fps, balls, e["px"], e["frame"], e["call"], e["call_prob"]))
        e["dispute_id"] = did
        disputes.append({"id": did, "event_id": e["id"], "clip_url": f"/media/{match_id}/{did}.mp4" if ok else None,
                         "call": e["call"], "prob": e["call_prob"], "status": "open"})
    for e in landings:
        e.pop("frame", None)
    speed_summary = annotate_speeds(events, fps, cfg, frames) if H is not None else None
    shot_summary = classify_shots(events, frames, fps, cfg) if H is not None else None
    score = score_rallies(cfg, rallies, {1: 0, 2: 1}) if H is not None else \
        {"games": [], "winner_track_id": None, "confirmed_by_human": False, "source": None,
         "unresolved_rallies": len(rallies)}
    return events, landings, disputes, score, speed_summary, shot_summary


# ---------------------------------------------------------------------------------------------------------------
# movement analytics and per-player stats
# ---------------------------------------------------------------------------------------------------------------

def movement_analytics(scene: Scene, frames: list[dict], events: list[dict], rallies: list[dict], *, stride: int, pose_frames: set | None = None,
                       names: dict[int, str], shot_summary, n_frames: int, video=None, detector=None, device=None,
                       emit: Callable[[str, float, str | None], None] | None = None, split_step: bool = True):
    """(per_player, players_meta, split_note). Return to base, split-step (needs `video` and a pose model), fatigue."""
    from rallyos.analytics.movement import (base_for, fatigue_trend, movement_speed_between, movement_stats,
                                            return_stats, return_to_base, zone_time)
    from rallyos.analytics.shots import shot_mix
    from rallyos.analytics.speed import player_speed_stats
    from rallyos.analytics.splitstep import collect_samples, detect_split_step, summarise, windows_for
    from rallyos.detect.players import load_pose_detector

    emit = emit or (lambda s, f, n=None: None)
    cfg, fps, H = scene.cfg, scene.fps, scene.H
    side_of = {1: "near", 2: "far"}
    hit_events = sorted((e for e in events if e["type"] == "hit"), key=lambda e: e["t"])
    track_pts: dict[int, list] = {}
    seen = [(fr["f"] / fps, fr["players"]) for fr in frames if (fr["f"] in pose_frames if pose_frames is not None else fr["f"] % stride == 0)]
    for tid in (1, 2):
        track_pts[tid] = [(t, tuple(p["court"])) for t, ps in seen for p in ps if p["track_id"] == tid and p.get("court")]

    # return to base after each of the player's own hits (needs the court: positions in metres)
    returns: dict[int, dict[float, dict]] = {1: {}, 2: {}}
    if H is not None:
        for tid in (1, 2):
            mine = [e for e in hit_events if e.get("track_id") == tid]
            nxt = {}
            for e in mine:
                reply = next((o for o in hit_events if o["rally_idx"] == e["rally_idx"] and o["t"] > e["t"]
                              and o.get("track_id") not in (None, tid)), None)
                nxt[e["t"]] = reply["t"] if reply else None
            returns[tid] = return_to_base(track_pts[tid], [e["t"] for e in mine], nxt, base_for(cfg, side_of[tid]))
            for e in mine:
                r = returns[tid].get(e["t"])
                if r:
                    e["return_to_base_s"], e["returned_to_base"] = r["return_s"], r["returned"]

    # split-step: re-read the frames just before each opponent hit at full frame rate (targeted pose pass)
    split: dict[int, list[dict]] = {1: [], 2: []}
    split_note = "not computed (needs the court and the pose model)"
    if H is not None and video is not None and detector is not None and split_step and os.environ.get("RALLYOS_SPLIT_STEP", "1") != "0":
        sd, _ = load_pose_detector(device=device, imgsz=480)
        if sd is not None:
            split_note = "ankle lift of both feet, re-read at full frame rate before each opponent hit"
            for tid in (1, 2):
                opp = [e for e in hit_events if e.get("track_id") not in (None, tid)]
                wins = windows_for(opp, fps, n_frames)
                emit("analytics", 0.1 + 0.4 * (tid - 1) / 2, f"split-step windows for player {tid}: {len(wins)}")
                got = collect_samples(video, sd, tid, wins, frames) if wins else {}
                for wi, w in enumerate(wins):
                    w0, w1 = w["f0"] / fps, w["f1"] / fps
                    res = detect_split_step(got.get(wi, []), movement_speed_between(track_pts[tid], w0 - 0.3, w1))
                    res["t"] = w["t_hit"]
                    split[tid].append(res)
                    ev = next((e for e in events if e.get("id") == w["event_id"]), None)
                    if ev is not None:
                        ev.setdefault("receiver_split_step", {})[str(tid)] = res["split_step"]

    per_player: dict[str, dict] = {}
    for tid in (1, 2):
        pts = track_pts[tid]
        frames_seen = sum(1 for _, ps in seen if any(p["track_id"] == tid for p in ps))
        stats = {"tracked_pct": round(frames_seen / max(1, len(seen)), 3),
                 "hits": sum(1 for e in events if e["track_id"] == tid)}
        stats.update(movement_stats(pts))
        stats.update(zone_time([c for _, c in pts], cfg, "near" if tid == 1 else "far"))
        stats.update(player_speed_stats(events).get(tid, {}))
        if shot_summary:
            stats["shot_mix"] = shot_mix(events, tid)
        stats.update(return_stats(returns[tid]))
        stats.update(summarise(split[tid]))
        if split[tid] and "split_step_pct" in stats:
            stats["split_step_clip_t"] = [round(r["t"], 2) for r in split[tid] if r["split_step"] is False][:3]
        if returns[tid]:
            shots = [{"t": t, "return_s": None if r.get("was_at_base") else r["return_s"],
                      "speed_mps": movement_speed_between(pts, t, t + (r["return_s"] or 1.0) + 0.5)} for t, r in returns[tid].items()]
            stats["fatigue"] = fatigue_trend(shots)
        per_player[str(tid)] = stats
    players_meta = [{"track_id": tid, "player_id": None, "name": names[tid], "side": side, "color": PLAYER_COLORS[tid]}
                    for tid, side in ((1, "near"), (2, "far")) if per_player[str(tid)]["tracked_pct"] > 0]
    from rallyos.analytics.bestshot import rate_shots

    rate_shots(events, rallies, frames, fps, cfg, per_player)      # best shot per player: outcome first, technique inside it
    return per_player, players_meta, split_note


def movement_note() -> dict:
    return {"base_radius_m": 1.2,
            "return_to_base": "time from the player's own hit until their feet are within 1.2 m of base, "
                              "ending at the opponent's reply; shots hit from base are counted apart and "
                              "left out of the average; a late arrival counts as not returned"}


def make_match(scene: Scene, *, match_id: str, video: dict, players_meta: list, tracks_url: str, rallies: list, events: list,
               score: dict, disputes: list, per_player: dict, raw: list, balls: list, hits: list, speed_summary, split_note: str,
               shot_summary, audio_info: dict, pipeline: dict, insights: list | None = None, title=None,
               live: dict | None = None, highlight: dict | None = None) -> dict:
    """The §11.3 match.json dictionary (batch and live build it the same way)."""
    from rallyos.export import ball_stats

    rally_hits = [r["hits"] for r in rallies]
    auto = scene.auto
    return {
        "schema_version": "1.1", "match_id": match_id, "title": title, "sport": scene.sport,
        "sport_confidence": auto["sport_confidence"] if auto and scene.sport == auto["sport"] else None,
        "sport_source": "chosen by user" if scene.sport_given else
                        ("auto-detected (Court Fingerprint)" if auto and scene.sport == auto["sport"] else "default (not detected)"),
        "video": video, "calibration": scene.calib, "players": players_meta, "tracks_url": tracks_url,
        "rallies": rallies, "events": events, "score": score,
        "stats": {
            "per_player": {k: v for k, v in per_player.items() if v["tracked_pct"] > 0},
            "match": {"rallies": len(rallies), "avg_rally_hits": round(sum(rally_hits) / len(rallies), 1) if rallies else 0.0,
                      "longest_rally_hits": max(rally_hits, default=0)},
            "ball": {**ball_stats(raw, balls, scene.fps), "hit_candidates": len(hits), "tracker": "geometric",
                     "model": "three-frame differencing + physics-consistent tracklets (no trained ball detector)"},
            "speed": speed_summary,
            "movement": {**movement_note(), "split_step": split_note},
            "shots": shot_summary,
            "audio": {**audio_info, "method": "band-limited spectral flux, sample-precise onsets (no training)"},
            "pipeline": pipeline,
        },
        "disputes": disputes, "insights": insights or [],
        **({"live": live} if live else {}),
        **({"highlight": highlight} if highlight else {}),
    }


def make_highlight(video, out: Path, match_id: str, per_player: dict, events: list[dict], balls: list, fps: float,
                   frames: list[dict] | None = None) -> dict | None:
    """The match highlight: an ~8 s clip around the best rated shot of both players (render/highlight.py). Returns the match.json
    "highlight" block, or None when no shot could be rated or the clip could not be written (a missing clip never breaks a run)."""
    from rallyos.render.highlight import pick_best, render_highlight

    best = pick_best(per_player, events)
    if best is None:
        return None
    if best.get("px") and frames:                         # the contact ring is only drawn where the hitter really is
        fr = frames[min(max(0, round(best["t"] * fps)), len(frames) - 1)]
        box = next((p.get("bbox") for p in fr["players"] if p["track_id"] == best["track_id"]), None)
        if box:
            w, h = box[2] - box[0], box[3] - box[1]
            x, y = best["px"]
            if not (box[0] - 0.6 * w <= x <= box[2] + 0.6 * w and box[1] - 0.6 * h <= y <= box[3] + 0.6 * h):
                best["px"] = None
    info = render_highlight(video, Path(out) / "highlight.mp4", best, fps, balls)
    if info is None:
        return None
    return {"clip_url": f"/media/{match_id}/highlight.mp4", **info, "track_id": best["track_id"], "t": best["t"], "shot": best.get("shot"),
            "score": best["score"], "outcome": best["outcome"], "technique": best.get("technique"), "confidence": best["confidence"],
            "why": best["why"], "basis": best["basis"]}


def stage_clock() -> tuple[dict, Callable]:
    """A tiny helper both analyzers use to time stages: returns (stage_seconds, mark(stage))."""
    seconds: dict[str, float] = {}
    state = {"stage": None, "t": time.time()}

    def mark(stage: str) -> None:
        now = time.time()
        if state["stage"] and stage != state["stage"]:
            seconds[state["stage"]] = round(seconds.get(state["stage"], 0.0) + now - state["t"], 2)
        if stage != state["stage"]:
            state.update(stage=stage, t=now)

    return seconds, mark
