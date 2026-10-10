"""Fair-Play Replay review clips (§4.7): 6 s around a close call, slow motion, shuttle trail and call drawn.

Frames are read with OpenCV, annotated, and encoded to H.264 with the ffmpeg binary bundled by
imageio-ffmpeg (browsers can't play OpenCV's mp4v). Returns False instead of raising if encoding fails,
so a missing clip never breaks the pipeline.
"""

from __future__ import annotations

from pathlib import Path

COLORS = {"IN": (94, 197, 34), "OUT": (94, 63, 244), "TOO CLOSE TO CALL": (11, 158, 245)}   # BGR


def render_review_clip(video: str | Path, out_path: str | Path, t_center: float, fps: float,
                       balls: list[dict | None], landing_px, landing_frame: int, call: str, prob: float,
                       half_window_s: float = 3.0, slow: float = 0.5, max_width: int = 960) -> bool:
    import cv2

    try:
        import imageio_ffmpeg
    except ImportError:
        return False
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return False
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(balls)
    f0, f1 = max(0, int((t_center - half_window_s) * fps)), min(n, int((t_center + half_window_s) * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    s = min(1.0, max_width / W)
    size = (int(W * s) // 2 * 2, int(H * s) // 2 * 2)
    color = COLORS.get(call, (255, 255, 255))
    label = f"{call} {prob:.0%}" if call != "TOO CLOSE TO CALL" else f"TOO CLOSE TO CALL (P in {prob:.0%})"
    writer = imageio_ffmpeg.write_frames(str(out_path), size, fps=max(1.0, fps * slow), codec="libx264",
                                         pix_fmt_in="bgr24", quality=7, macro_block_size=2,
                                         output_params=["-movflags", "+faststart"])
    try:
        writer.send(None)
        for f in range(f0, f1):
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, size)
            trail = [balls[i]["px"] for i in range(max(0, f - 12), min(f + 1, len(balls))) if balls[i] is not None]
            for k in range(1, len(trail)):
                p, q = trail[k - 1], trail[k]
                cv2.line(frame, (int(p[0] * s), int(p[1] * s)), (int(q[0] * s), int(q[1] * s)), (0, 230, 255), 2, cv2.LINE_AA)
            if f >= landing_frame and landing_px is not None:
                c = (int(landing_px[0] * s), int(landing_px[1] * s))
                cv2.circle(frame, c, 14, color, 2, cv2.LINE_AA)
                cv2.drawMarker(frame, c, color, cv2.MARKER_CROSS, 10, 2)
            cv2.rectangle(frame, (0, 0), (size[0], 34), (20, 20, 20), -1)
            cv2.putText(frame, f"Fair-Play Replay  {label}  x{slow:g} speed  t={f / fps:5.2f}s", (10, 23),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
            writer.send(frame)
    except Exception:
        return False
    finally:
        cap.release()
        try:
            writer.close()
        except Exception:
            pass
    return Path(out_path).is_file() and Path(out_path).stat().st_size > 0
