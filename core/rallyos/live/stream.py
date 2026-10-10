"""StreamAnalyzer: the incremental version of Analyzer. Feed it chunks in order; after each one it returns what is new.

It reuses the stages in rallyos/stages.py. What it adds is state and a window:

  * the court is calibrated ONCE (the first ~30 frames, or the corners given); the Scene (homography, camera, regions of
    interest) is reused for every later frame;
  * a FrameScanner and a PlayerTracker live across chunks, so the 3-frame difference window, the last pose boxes and the
    player roles continue seamlessly over a chunk boundary;
  * per-frame raw detections (pose samples, shuttle candidates) are kept for the whole session; everything downstream
    (shuttle linking, hits, audio fusion, rallies, landings, speeds, shots, stats) is recomputed over a TAIL WINDOW only.
    Hits older than the window are frozen. The window always contains the open rally;
  * a rally is CLOSED when no hit has happened for the sport's pause; only closed rallies get a landing, a line call, a
    winner and a score, so no call is made before the footage that shows the landing has been processed;
  * events keep stable ids (a hit found again in the next window is the same hit), and every live number is provisional.

feed_chunk() processes the whole chunk including its trailing overlap as soon as it arrives; the next chunk's repeated
frames are skipped by TIME (never by count), so a dropped frame cannot shift later events.
"""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import numpy as np

from rallyos import stages
from rallyos.live.segments import ChunkMeta, StableIds, dedupe_times, stitch

POSE_INTERVAL_S = 0.12      # seconds between pose samples (about 8 per second)
ADAPT_UP = 0.9             # a chunk that takes more than this share of its length makes pose rarer
ADAPT_DOWN = 0.6           # ...and one under this share lets it recover
MAX_ADAPT_STEPS = 3        # at most base + 6 frames between pose samples
PAUSE_S = 4.0              # the rally-closing pause (events/rallies.py splits rallies on gaps longer than this)
WINDOW_MIN_S = 6.0         # the tail window is never shorter than this
FREEZE_MARGIN_S = 2.0      # a frozen boundary stays this far before the first hit of the open rally
CALIB_FRAMES = 30          # frames of the first chunk the court is calibrated from
POSITION_HZ = 5.0
STATICS_EVERY = 12         # re-evaluate which detected people are static officials every N chunks
MAX_GAP_FRAMES_FILL = 250  # a gap longer than this (10 s at 25 fps) is filled with empty frames in one go


def _pts_fps(path) -> float:
    """Frame rate of a file with no usable header rate, from the mean rate over the first frames' timestamps."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    ts = []
    while len(ts) < 60:
        ok, _ = cap.read()
        if not ok:
            break
        ts.append(cap.get(cv2.CAP_PROP_POS_MSEC))
    cap.release()
    if len(ts) < 3 or ts[-1] <= ts[0]:
        return 25.0
    fps = (len(ts) - 1) / ((ts[-1] - ts[0]) / 1000.0)          # mean rate: robust to jittery per-frame timestamps
    return float(min(120.0, max(5.0, round(fps))))


def pose_stride_for(fps: float, minimum: int = 3) -> int:
    """Frames between pose samples so that a sample comes about every POSE_INTERVAL_S: 3 at 25 fps, 4 at 30, 7 at 60."""
    return max(minimum, round(fps * POSE_INTERVAL_S))


class _AudioJob:
    """Decode a chunk's audio track on a worker thread (an ffmpeg process: about a second of mostly waiting on Windows), so it
    overlaps the frame loop instead of adding to it. `result()` joins and returns what `load_audio` returned."""

    def __init__(self, path):
        import threading

        self._out: tuple = (None, "audio not loaded")
        self._t = threading.Thread(target=self._run, args=(str(path),), daemon=True)
        self._t.start()

    def _run(self, path: str) -> None:
        from rallyos.audio.onsets import load_audio

        try:
            self._out = load_audio(path)
        except Exception as exc:                                  # noqa: BLE001 - audio is optional: report, never fail the chunk
            self._out = (None, f"audio failed: {exc}")

    def result(self) -> tuple:
        self._t.join()
        return self._out


class StreamAnalyzer:
    def __init__(self, sport: str = "auto", device: str | None = None, taps: list | None = None,
                 names: dict[int, str] | None = None, session_id: str | None = None, out_dir: str | Path | None = None,
                 stride: int = 3, imgsz: int | None = None, chunk_seconds: float = 5.0, auto_calibrate: bool = True):
        from rallyos.device import get_device

        self.sport_arg = "badminton" if sport in (None, "", "auto") else sport
        self.sport_given = sport not in (None, "", "auto")
        self.device = get_device(device)
        self.taps_arg = taps
        self.names = {1: "Near player", 2: "Far player", **(names or {})}
        self.session_id = session_id or f"s_{int(time.time())}"
        self.out_dir = Path(out_dir) if out_dir else Path("demo/out/live") / self.session_id
        self.stride_arg = max(1, stride)
        self._slow_streak = 0
        self.stride = self.base_stride = self.stride_arg
        self.imgsz = imgsz or int(os.environ.get("RALLYOS_MAX_WIDTH") or 1280)
        self.chunk_seconds = chunk_seconds
        self.auto_calibrate = auto_calibrate
        self.reset()

    # -- lifecycle ---------------------------------------------------------------------------------------------
    def reset(self) -> None:
        """Forget everything analysed so far (the stored chunk list is kept, so a session can be re-fed)."""
        self.scene = self.scanner = self.tracker = self.detector = None
        self.pose_backend = None
        self.fps = self.width = self.height = None
        self.onsets: list[dict] = []
        self.audio_status = "no chunks yet"
        self.balls: list = []
        self.raw: list = []
        self.frozen_hits: list[dict] = []
        self.freeze_frame = 0
        self.ids = StableIds("l")
        self.sent_event_ids: set[str] = set()
        self.closed_sent = 0
        self.dropped_frames = 0
        self.processed_until = 0.0
        self.chunks_done: list[dict] = []
        self.hits: list[dict] = []
        self.events: list[dict] = []
        self.rallies: list[dict] = []
        self.score: dict = {}
        self.per_player: dict = {}
        self.speed_summary = self.shot_summary = None
        self.audio_info: dict = {}
        self.calibration_quality = "none"
        if not hasattr(self, "chunk_files"):
            self.chunk_files: list[ChunkMeta] = []

    def start(self, session: dict | None = None) -> dict:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._write_session()
        return {"session_id": self.session_id, "out_dir": str(self.out_dir)}

    # -- one chunk ---------------------------------------------------------------------------------------------
    def feed_chunk(self, path: str | Path, seq: int, t0: float, duration: float | None = None,
                   t_ready: float | None = None) -> dict:
        """Analyse one chunk (a standalone video file starting `t0` seconds into the session). Returns what is new."""
        import cv2

        started = time.time()
        meta = ChunkMeta(seq=seq, path=str(path), t0=float(t0), duration=duration or 0.0, t_ready=t_ready)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise IOError(f"cannot open chunk {path}")
        fps_c = cap.get(cv2.CAP_PROP_FPS)
        # Browser (MediaRecorder) WebM reports 1000 fps and a "frame count" in milliseconds: use the frames' own timestamps
        use_pts = not 5 <= fps_c <= 120
        if use_pts:
            fps_c = _pts_fps(path)
        if self.scene is None:
            self._calibrate(cap, fps_c)
            cap.release()
            cap = cv2.VideoCapture(str(path))
        first_g = self.scanner.f
        audio_job = _AudioJob(meta.path)                              # ffmpeg runs while the frames are analysed
        processed = skipped = 0
        i = 0
        pos0 = 0.0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if use_pts:
                pos = cap.get(cv2.CAP_PROP_POS_MSEC)
                pos0 = pos if i == 0 else pos0
                t = meta.t0 + max(0.0, (pos - pos0) / 1000.0)
            else:
                t = meta.t0 + i / fps_c
            i += 1
            g = int(round(t * self.fps))
            if g < self.scanner.f:                                    # already seen in the previous chunk's overlap
                skipped += 1
                continue
            if g > self.scanner.f:                                    # frames that never arrived: keep indices aligned
                gap = g - self.scanner.f
                self.scanner.skip(min(gap, MAX_GAP_FRAMES_FILL))
                self.dropped_frames += gap
            self.scanner.feed(frame)
            processed += 1
        cap.release()
        meta.duration = meta.duration or i / fps_c
        if processed == 0 and skipped == 0:
            raise IOError(f"no frames decoded from chunk {seq}")
        self.chunk_files.append(meta)
        self.processed_until = max(self.processed_until, meta.t0 + i / fps_c)

        self._ingest_audio(meta, audio_job.result())
        self._refresh_tracks(len(self.chunks_done))
        result = self._analyse_window()
        positions = self._positions(first_g, self.scanner.f)
        process_s = time.time() - started
        info = {"seq": seq, "t0": round(meta.t0, 2), "t1": round(meta.t1, 2), "process_s": round(process_s, 2),
                "frames": processed, "overlap_frames_skipped": skipped, "dropped_frames": self.dropped_frames,
                "rtf": round(process_s / max(1e-6, processed / self.fps), 2), "reduced_quality": self.stride > self.base_stride, "pose_stride": self.stride,
                "latency_s": round(time.time() - t_ready, 2) if t_ready else None}
        self.chunks_done.append(info)
        self._adapt(process_s, meta.duration or self.chunk_seconds)
        out = {**info, "positions": positions, **result, "calibration": self.calibration_status()}
        self._write_chunk(seq, out)
        return out

    # -- court, once -------------------------------------------------------------------------------------------
    def _calibrate(self, cap, fps_c: float) -> None:
        from rallyos.detect.players import load_pose_detector

        frames = []
        i = 0
        while len(frames) < max(1, CALIB_FRAMES // 3):
            ok, frame = cap.read()
            if not ok:
                break
            if i % 3 == 0:
                frames.append(frame)
            i += 1
            if i >= CALIB_FRAMES:
                break
        if not frames:
            raise IOError("the first chunk has no frames to calibrate the court from")
        self.fps = fps_c
        self.height, self.width = frames[0].shape[:2]
        scene = stages.build_scene(sport=self.sport_arg, sport_given=self.sport_given, taps=self.taps_arg,
                                   auto_calibrate=self.auto_calibrate, detect_frames=lambda: frames, fps=fps_c,
                                   width=self.width, height=self.height)
        scene = self._provisional_court(scene, frames)
        self.scene = scene
        self.calibration_quality = self._quality(scene)
        self.detector, self.pose_backend = load_pose_detector(device=self.device, imgsz=self.imgsz)
        # pose every ~0.12 s whatever the frame rate (a 60 fps phone does not need 2.4x the pose work of a 25 fps clip)
        self.base_stride = pose_stride_for(self.fps, self.stride_arg)
        self.stride = self.base_stride
        self.scanner = stages.FrameScanner(scene, self.detector, self.stride)
        self.tracker = stages.PlayerTracker(scene)

    def _provisional_court(self, scene, frames):
        """A court the automatic fit found but was not sure of (quality "check") is NOT applied by the batch pipeline. Live
        results are provisional anyway and the UI asks the user to check the corners, so apply it, flagged, rather than
        analysing the first minutes without a court."""
        if scene.H is None and scene.auto and scene.auto.get("quality") == "check":
            fixed = stages.build_scene(sport=scene.auto["sport"] if not self.sport_given else self.sport_arg,
                                       sport_given=self.sport_given, taps=scene.auto["corners_px"], auto_calibrate=False,
                                       detect_frames=lambda: frames, fps=scene.fps, width=scene.width, height=scene.height)
            fixed.calib["method"] = "auto-provisional"
            fixed.calib["auto"] = scene.calib.get("auto")
            fixed.calib["note"] = "court proposed but not certain: check the corners (live results are provisional)"
            fixed.auto, fixed.user_taps = scene.auto, False
            return fixed
        return scene

    @staticmethod
    def _quality(scene) -> str:
        if scene.H is None:
            return "none"
        if scene.user_taps:
            return "high"
        return (scene.auto or {}).get("quality", "high") if scene.calib.get("method") == "auto" else "check"

    def calibration_status(self) -> dict:
        sc = self.scene
        if sc is None:
            return {"quality": "none", "note": "no chunk yet"}
        auto = sc.auto or {}
        return {"quality": self.calibration_quality, "sport": sc.sport, "method": sc.calib.get("method"),
                "precision": auto.get("precision"), "corners_px": sc.calib.get("taps_px") or auto.get("corners_px"),
                "note": sc.calib.get("note") or sc.auto_note}

    def set_corners(self, taps: list) -> list[dict]:
        """The user corrected the court. Re-run everything from the stored chunks with the new corners (no restart)."""
        files = sorted(self.chunk_files, key=lambda c: c.seq)
        self.taps_arg = taps
        self.reset()
        self.chunk_files = []
        return [self.feed_chunk(c.path, c.seq, c.t0, c.duration, c.t_ready) for c in files]

    # -- per-chunk steps ---------------------------------------------------------------------------------------
    def _adapt(self, process_s: float, chunk_len: float) -> None:
        """Graceful degradation: when chunks keep taking nearly as long as they last, run pose less often (the shuttle search
        and the hit detection are untouched); when there is room again, go back. Everything produced at a reduced rate is
        flagged. The first chunk is ignored (court search, model compile: one-time costs) and one slow chunk is not enough."""
        if len(self.chunks_done) <= 1:
            return
        ratio = process_s / max(1e-6, chunk_len)
        self._slow_streak = self._slow_streak + 1 if ratio > ADAPT_UP else 0
        if self._slow_streak >= 2:
            self.stride = min(self.stride + 2, self.base_stride + 2 * MAX_ADAPT_STEPS)
            self._slow_streak = 0
        elif ratio < ADAPT_DOWN and self.stride > self.base_stride:
            self.stride = max(self.base_stride, self.stride - 2)
        if self.scanner is not None:
            self.scanner.stride = self.stride

    def _ingest_audio(self, meta: ChunkMeta, loaded: tuple | None = None) -> None:
        from rallyos.audio.onsets import detect_onsets, load_audio

        acfg = self.scene.cfg.get("audio", {})
        samples, status = loaded if loaded is not None else load_audio(meta.path)
        if status == "ok" or self.audio_status in ("no chunks yet",):
            self.audio_status = status
        if samples is None:
            return
        min_gap = acfg.get("min_gap_s", 0.15)
        fresh = [{**o, "t": round(o["t"] + meta.t0, 4)} for o in
                 detect_onsets(samples, 44100, min_gap_s=min_gap, band_hz=acfg.get("band_hz", (1500, 10000)))]
        self.onsets += dedupe_times([o["t"] for o in self.onsets], fresh, min_gap)      # the overlap repeats its sounds
        self.onsets.sort(key=lambda o: o["t"])

    def _refresh_tracks(self, chunk_index: int) -> None:
        sc = self.scanner
        rebuilt = False
        if self.tracker.selector is None or (chunk_index and chunk_index % STATICS_EVERY == 0):
            self.tracker.set_statics(sc.sampled)
            rebuilt = True
        frames = self.tracker.extend(sc.sampled, sc.f)
        if rebuilt:                                                   # the frames list was rebuilt: put the shuttle back
            for fr, b in zip(frames, self.balls):
                fr["ball"] = b

    def _analyse_window(self) -> dict:
        sc, scn = self.scene, self.scanner
        n = scn.f
        fps = self.fps
        frames = self.tracker.frames
        fw = self.freeze_frame
        # 1. shuttle path over the tail window only; earlier frames keep what they had
        cands = scn.candidates()
        raw_w, balls_w = stages.link_ball(sc, [[] for _ in range(fw)] + cands[fw:])
        self.balls = self.balls[:fw] + balls_w[fw:]
        self.raw = self.raw[:fw] + raw_w[fw:]
        for fi in range(fw, n):
            frames[fi]["ball"] = self.balls[fi]
        # 2. hits, audio fusion, rallies, events
        t_now = n / fps
        window_balls = [None] * fw + self.balls[fw:]
        onsets_w = [o for o in self.onsets if o["t"] >= fw / fps - 0.3]
        hits, audio_info, rallies, events = stages.find_events(sc, window_balls, frames, onsets_w, self.audio_status,
                                                               round(t_now, 3), extra_hits=self.frozen_hits)
        self.audio_info = audio_info
        self.hits = hits
        # 3. a rally is closed once its pause has passed: only then is its ending looked for
        last_hit_t: dict[int, float] = {}
        for e in events:
            last_hit_t[e["rally_idx"]] = max(last_hit_t.get(e["rally_idx"], 0.0), e["t"])
        n_closed = sum(1 for r in rallies if t_now - last_hit_t.get(r["idx"], t_now) > PAUSE_S or r["idx"] < len(rallies) - 1)
        closed_events = [e for e in events if e["rally_idx"] < n_closed]
        open_events = [e for e in events if e["rally_idx"] >= n_closed]
        closed_rallies = copy.deepcopy(rallies[:n_closed])
        if n_closed:
            closed_events, landings, _d, score, speed_sum, shot_sum = stages.resolve_outcome(
                sc, closed_rallies, hits, self.balls, frames, closed_events)
        else:
            landings, score, speed_sum, shot_sum = [], {"games": [], "winner_track_id": None, "confirmed_by_human": False,
                                                         "source": None, "unresolved_rallies": 0}, None, None
        all_events = sorted(closed_events + open_events, key=lambda e: (e["t"], e["type"] != "hit"))
        self.ids.assign(all_events)
        for e in all_events:
            e["provisional"] = True
        all_rallies = closed_rallies + [r for r in rallies[n_closed:]]
        for r in all_rallies:
            r.pop("hit_frames", None)
            r["provisional"] = True
            r["closed"] = r["idx"] < n_closed
        self.events, self.rallies, self.score = all_events, all_rallies, score
        self.speed_summary, self.shot_summary = speed_sum, shot_sum
        # 4. per-player stats (the heavy split-step pass waits for finalize)
        self.per_player, _meta, _note = stages.movement_analytics(
            sc, frames, all_events, all_rallies, stride=self.stride, pose_frames=set(self.tracker.roles_at), names=self.names, shot_summary=shot_sum, n_frames=n,
            video=None, detector=None, split_step=False)
        # 5. move the freeze boundary forward, never into the open rally
        open_first = min((e["t"] for e in open_events if e["type"] == "hit"), default=None)
        limit = t_now - WINDOW_MIN_S
        if open_first is not None:
            limit = min(limit, open_first - FREEZE_MARGIN_S)
        new_fw = max(fw, int(max(0.0, limit) * fps))
        self.freeze_frame = min(new_fw, n)
        self.frozen_hits = [h for h in hits if h["frame"] < self.freeze_frame]
        # what is new for the client
        fresh = [e for e in all_events if e["id"] not in self.sent_event_ids]
        self.sent_event_ids |= {e["id"] for e in fresh}
        newly_closed = [r for r in all_rallies if r["closed"] and r["idx"] >= self.closed_sent]
        self.closed_sent = n_closed
        return {"new_events": fresh, "closed_rallies": newly_closed, "stats": self.stats()}

    def stats(self) -> dict:
        rally_hits = [r["hits"] for r in self.rallies if r.get("closed")]
        sc = self.score or {}
        return {"provisional": True, "rallies": sum(1 for r in self.rallies if r.get("closed")),
                "hits": sum(1 for e in self.events if e["type"] == "hit"),
                "score": {"suggested": sc.get("score_str") if sc.get("games") else None, "games": sc.get("games", []),
                          "unresolved_rallies": sc.get("unresolved_rallies"), "provisional": True},
                "per_player": {k: {kk: vv for kk, vv in v.items() if kk in ("distance_m", "top_speed_mps", "tracked_pct", "hits",
                                                                              "avg_return_to_base_s", "most_zone")}
                               for k, v in self.per_player.items()},
                "match": {"rallies": len(rally_hits), "avg_rally_hits": round(sum(rally_hits) / len(rally_hits), 1) if rally_hits else 0.0,
                          "longest_rally_hits": max(rally_hits, default=0)},
                "audio": {"status": self.audio_status, "onsets": len(self.onsets)}}

    def _positions(self, g0: int, g1: int) -> list[dict]:
        step = max(1, round(self.fps / POSITION_HZ))
        out = []
        frames = self.tracker.frames
        for g in range(g0, min(g1, len(frames)), step):
            fr = frames[g]
            ball = fr.get("ball")
            out.append({"t": round(g / self.fps, 2),
                        "players": [{"track_id": p["track_id"], "court": p.get("court"),
                                     "px": [round((p["bbox"][0] + p["bbox"][2]) / 2), round(p["bbox"][3])]} for p in fr["players"]],
                        "ball": {"px": ball["px"], "court": ball.get("court"), "conf": ball.get("conf"), "interp": ball.get("interp")} if ball else None})
        return out

    def snapshot(self) -> dict:
        """The provisional match so far (events, rallies, score, stats, court)."""
        return {"provisional": True, "session_id": self.session_id, "duration_s": round(self.scanner.f / self.fps, 2) if self.scanner else 0.0,
                "calibration": self.calibration_status(), "events": self.events, "rallies": self.rallies, "score": self.score,
                "stats": self.stats(), "chunks": self.chunks_done}

    # -- the end of the match ----------------------------------------------------------------------------------
    def finalize(self, match_id: str | None = None, out_dir: str | Path | None = None, *, render_clips: bool = True,
                 split_step: bool = True) -> dict:
        """Stop: recompute everything over the WHOLE match from the stored detections, add what the live path skips (dispute
        clips, the split-step pass), stitch the chunks into one source video, and write the same match.json the batch
        pipeline writes (plus a `live` block). Every provisional number is replaced by this result."""
        from rallyos.export import write_outputs
        from rallyos.live.segments import to_mp4
        from rallyos.videoio import sha256_file

        if self.scene is None or not self.chunk_files:
            raise RuntimeError("nothing to finalise: no chunk was analysed")
        t_start = time.time()
        match_id = match_id or f"m_{self.session_id.removeprefix('s_')}"
        out = Path(out_dir) if out_dir else self.out_dir / "final"
        out.mkdir(parents=True, exist_ok=True)
        sc, scn = self.scene, self.scanner
        n, fps = scn.f, self.fps
        chunks = sorted(self.chunk_files, key=lambda c: c.seq)
        video = stitch(chunks, out / f"source{Path(chunks[0].path).suffix}", self.chunk_seconds)
        if video.suffix != ".mp4":
            video = to_mp4(video, out / "source.mp4")
        self.tracker.set_statics(scn.sampled)
        frames = self.tracker.extend(scn.sampled, n)
        raw, balls = stages.link_ball(sc, scn.candidates())
        for fr, b in zip(frames, balls):
            fr["ball"] = b
        duration = round(n / fps, 3)
        hits, audio_info, rallies, events = stages.find_events(sc, balls, frames, self.onsets, self.audio_status, duration)
        events, landings, disputes, score, speed_summary, shot_summary = stages.resolve_outcome(
            sc, rallies, hits, balls, frames, events, video=video if render_clips else None, out=out, match_id=match_id)
        per_player, players_meta, split_note = stages.movement_analytics(
            sc, frames, events, rallies, stride=self.stride, pose_frames=set(self.tracker.roles_at), names=self.names, shot_summary=shot_summary, n_frames=n,
            video=video, detector=self.detector, device=self.device, split_step=split_step)
        lat = [c["latency_s"] for c in self.chunks_done if c.get("latency_s") is not None]
        live = {"session_id": self.session_id, "chunk_seconds": self.chunk_seconds, "chunks": len(chunks),
                "avg_latency_s": round(sum(lat) / len(lat), 2) if lat else None, "max_lag_s": round(max(lat), 2) if lat else None,
                "dropped_frames": self.dropped_frames, "reduced_quality_chunks": sum(1 for c in self.chunks_done if c.get("reduced_quality")),
                "avg_process_s": round(sum(c["process_s"] for c in self.chunks_done) / len(self.chunks_done), 2),
                "finalise_s": None}
        match = stages.make_match(
            sc, match_id=match_id,
            video={"src": f"/media/{match_id}/source.mp4", "overlay": None, "fps": fps, "width": self.width, "height": self.height,
                   "duration_s": duration, "sha256": sha256_file(video)},
            players_meta=players_meta, tracks_url=f"/media/{match_id}/tracks.json", rallies=rallies, events=events, score=score,
            disputes=disputes, per_player=per_player, raw=raw, balls=balls, hits=hits, speed_summary=speed_summary,
            split_note=split_note, shot_summary=shot_summary, audio_info=audio_info,
            pipeline={"device": self.device, "imgsz": self.imgsz, "player_stride": self.stride, "live": True,
                      "players_backend": self.pose_backend if self.detector is not None else None,
                      "static_people_ignored": self.tracker.statics, "ignored_detections": self.tracker.ignored_counts,
                      "processing_s": None, "not_computed": []}, live=live)
        live["finalise_s"] = round(time.time() - t_start, 1)
        match["live"] = live
        write_outputs(out, match, {"fps": fps, "frames": frames}, video=video)
        (out / "match.json").write_text(json.dumps(match, indent=2, ensure_ascii=False, default=_jsonable), encoding="utf-8")
        return match

    # -- persistence -------------------------------------------------------------------------------------------
    def _write_session(self) -> None:
        data = {"session_id": self.session_id, "sport": self.sport_arg, "sport_given": self.sport_given, "taps": self.taps_arg,
                "chunk_seconds": self.chunk_seconds, "stride": self.stride_arg, "chunks": [c.to_json() for c in self.chunk_files]}
        (self.out_dir / "session.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def _write_chunk(self, seq: int, result: dict) -> None:
        d = self.out_dir / f"chunk_{seq:04d}"
        d.mkdir(parents=True, exist_ok=True)
        slim = {k: v for k, v in result.items() if k != "positions"}
        (d / "summary.json").write_text(json.dumps(slim, default=_jsonable), encoding="utf-8")
        self._write_session()

    @classmethod
    def resume(cls, out_dir: str | Path, **kw) -> "StreamAnalyzer":
        """Rebuild a session from its folder after a crash: same settings, chunks re-fed in order."""
        out = Path(out_dir)
        s = json.loads((out / "session.json").read_text(encoding="utf-8"))
        an = cls(sport=s["sport"] if s["sport_given"] else "auto", taps=s.get("taps"), session_id=s["session_id"], out_dir=out,
                 stride=s.get("stride", 3), chunk_seconds=s.get("chunk_seconds", 5.0), **kw)
        for c in s["chunks"]:
            if Path(c["path"]).exists():
                an.feed_chunk(c["path"], c["seq"], c["t0"], c["duration"], None)
        return an


def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)
