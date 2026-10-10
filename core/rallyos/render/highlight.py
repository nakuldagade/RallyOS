"""The match highlight: one clip of about 8 seconds around the best shot of the whole match.

"Best" is decided by analytics/bestshot.py (what the shot achieved first, technique inside it); this module picks the single best
rated shot of both players and cuts the clip. The clip is the original footage at normal speed with the shuttle trail, a ring
at the moment of contact and a caption (shot, score, how it ended), encoded as H.264 so a browser plays it. No audio: frames are
read with OpenCV, which drops the soundtrack.

    window  = 8 s, starting 3 s before the contact (moved earlier or later to stay inside the video; a video shorter than 8 s
              is used whole)
"""

from __future__ import annotations

from pathlib import Path

WINDOW_S = 8.0
LEAD_S = 3.0
MIN_CONFIDENCE = 0.25
OUTCOME_TEXT = {"winner": "won the point", "forced_error": "forced an error", "kept_going": "kept the rally going",
                "unknown": "outcome not seen", "error": "lost the point"}


def pick_best(per_player: dict, events: list[dict]) -> dict | None:
    """The best rated shot of the match: {"track_id", "t", "shot", "score", "outcome", "technique", "confidence", "why", "basis", "px"}
    from the two players' own best shots (highest score, then confidence), or None when no shot was rated."""
    best = None
    for tid_s, stats in (per_player or {}).items():
        b = stats.get("best_shot")
        if not b or (b.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        if best is None or (b["score"], b["confidence"]) > (best["score"], best["confidence"]):
            best = {**b, "track_id": int(tid_s)}
    if best is None:
        return None
    hit = min((e for e in events if e["type"] == "hit" and e.get("track_id") == best["track_id"]), key=lambda e: abs(e["t"] - best["t"]), default=None)
    best["px"] = hit.get("px") if hit else None
    best["basis"] = best.get("basis") or "outcome"
    return best


def window_for(t_hit: float, duration_s: float, window_s: float = WINDOW_S, lead_s: float = LEAD_S) -> tuple[float, float]:
    """(start, end) in seconds: window_s long, lead_s before the contact, kept inside [0, duration_s]; the whole video if shorter."""
    if duration_s <= window_s:
        return 0.0, duration_s
    start = min(max(0.0, t_hit - lead_s), duration_s - window_s)
    return start, start + window_s


def render_highlight(video: str | Path, out_path: str | Path, best: dict, fps: float, balls: list[dict | None],
                     max_width: int = 960) -> dict | None:
    """Cut and annotate the clip. Returns {"clip_start", "clip_end", "duration_s"} or None if it could not be made (never raises)."""
    import cv2

    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(balls)
    start, end = window_for(best["t"], n / fps)
    f0, f1 = int(round(start * fps)), min(n, int(round(end * fps)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = min(1.0, max_width / W)
    size = (int(W * s) // 2 * 2, int(H * s) // 2 * 2)
    f_hit = int(round(best["t"] * fps))
    top = f"BEST SHOT  {str(best.get('shot') or 'shot').upper()}  {best['score']:.0f}/100"
    bottom = OUTCOME_TEXT.get(best.get("outcome"), "") + ("" if best.get("basis", "outcome") == "outcome" else " (ranked by technique: no point-ending shot seen)")
    ring = None
    if best.get("px"):
        ring = (int(best["px"][0] * s), int(best["px"][1] * s))
    ok_out = False
    writer = imageio_ffmpeg.write_frames(str(out_path), size, fps=max(1.0, fps), codec="libx264", pix_fmt_in="bgr24", quality=7,
                                         macro_block_size=2, output_params=["-movflags", "+faststart"])
    try:
        writer.send(None)
        written = 0
        for f in range(f0, f1):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, size)
            for i in range(max(1, f - 10), min(f + 1, len(balls))):
                a, b = balls[i - 1], balls[i]
                # only measured positions in consecutive frames, and no jump across the picture: a gap-filled or jumping track is
                # not a shuttle path and is not drawn (a highlight must not show a made-up trail)
                if a is None or b is None or a.get("interp") or b.get("interp") or (a.get("conf") or 0) < 0.5 or (b.get("conf") or 0) < 0.5:
                    continue
                if abs(a["px"][0] - b["px"][0]) + abs(a["px"][1] - b["px"][1]) > 0.12 * W:
                    continue
                cv2.line(frame, (int(a["px"][0] * s), int(a["px"][1] * s)), (int(b["px"][0] * s), int(b["px"][1] * s)), (0, 230, 255), 2, cv2.LINE_AA)
            if ring is not None and abs(f - f_hit) <= int(0.35 * fps):                    # a ring that shrinks onto the contact
                r = 10 + int(30 * abs(f - f_hit) / max(1, 0.35 * fps))
                cv2.circle(frame, ring, r, (0, 200, 255), 3, cv2.LINE_AA)
            cv2.rectangle(frame, (0, 0), (size[0], 36), (20, 20, 20), -1)
            cv2.putText(frame, top, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 215, 255), 2, cv2.LINE_AA)
            if bottom:
                cv2.rectangle(frame, (0, size[1] - 32), (size[0], size[1]), (20, 20, 20), -1)
                cv2.putText(frame, bottom, (12, size[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
            writer.send(frame)
            written += 1
        ok_out = written > 0
    except Exception:
        ok_out = False
    finally:
        cap.release()
        try:
            writer.close()
        except Exception:
            pass
    if not (ok_out and Path(out_path).is_file() and Path(out_path).stat().st_size > 0):
        return None
    return {"clip_start": round(start, 2), "clip_end": round(f1 / fps, 2), "duration_s": round((f1 - f0) / fps, 2)}
