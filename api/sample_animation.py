"""Top-down animation of a SIMULATED table-tennis game (used only by api/make_sample_tt.py). Not footage: it carries a watermark."""
from pathlib import Path

import cv2
import numpy as np

W, H = 960, 540
SCALE, Y_OFF, OY = 150.0, 1.8, 155.0
LENGTH, WIDTH = 2.74, 1.525


def _px(x: float, y: float) -> tuple[int, int]:
    return int(SCALE * (y + Y_OFF)), int(SCALE * x + OY)


def _background() -> np.ndarray:
    img = np.full((H, W, 3), (30, 24, 20), np.uint8)
    cv2.rectangle(img, _px(0, 0), _px(WIDTH, LENGTH), (125, 80, 20), -1)               # table (BGR: a blue top)
    cv2.rectangle(img, _px(0, 0), _px(WIDTH, LENGTH), (255, 255, 255), 2)
    cv2.line(img, _px(0, LENGTH / 2), _px(WIDTH, LENGTH / 2), (240, 240, 240), 3)       # the net
    cv2.line(img, _px(WIDTH / 2, 0), _px(WIDTH / 2, LENGTH), (255, 255, 255), 1)        # centre line
    return img


def render(path: Path, frames: list[dict], rallies: list[dict], opponent: str) -> None:
    import imageio_ffmpeg

    bg = _background()
    colours = {1: (246, 130, 59), 2: (68, 68, 239)}
    names = {1: "Tara", 2: opponent}
    writer = imageio_ffmpeg.write_frames(str(path), (W, H), fps=30, codec="libx264", pix_fmt_in="bgr24", quality=7,
                                         macro_block_size=2, output_params=["-movflags", "+faststart"])
    writer.send(None)
    trail: list[tuple[int, int]] = []
    try:
        for fr in frames:
            t = fr["f"] / 30.0
            img = bg.copy()
            for p in fr["players"]:
                c = p["court"]
                x, y = _px(c[0], c[1])
                cv2.circle(img, (x, y), 14, colours[p["track_id"]], -1, cv2.LINE_AA)
                cv2.putText(img, names[p["track_id"]], (x - 22, y - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            b = fr["ball"]
            if b:
                bx, by = _px(b["court"][0], b["court"][1])
                trail.append((bx, by))
                trail = trail[-8:]
                for i in range(1, len(trail)):
                    cv2.line(img, trail[i - 1], trail[i], (0, 220, 255), 2, cv2.LINE_AA)
                cv2.circle(img, (bx, by), 6, (255, 255, 255), -1, cv2.LINE_AA)
            else:
                trail = []
            done = [r for r in rallies if r["t_end"] <= t]
            score = done[-1]["score_after"] if done else "0-0"
            cv2.rectangle(img, (0, 0), (W, 38), (20, 20, 20), -1)
            cv2.putText(img, f"Tara {score.replace('-', '  :  ')} {opponent}", (14, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.rectangle(img, (0, H - 30), (W, H), (20, 20, 20), -1)
            cv2.putText(img, "SAMPLE DATA: simulated game, top-down animation, not real footage", (14, H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 1, cv2.LINE_AA)
            writer.send(np.ascontiguousarray(img))
    finally:
        writer.close()
