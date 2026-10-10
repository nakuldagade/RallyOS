"""Ball / shuttle candidates without a trained detector (§4.3 steps 1-3).

Three-frame differencing finds small things that moved in both directions around frame t. Players are
masked out twice: by their pose boxes when available, and by any large moving blob (works even with no
person detector). Candidates must be small, compact and bright (shuttles and balls are light).

Defaults were tuned on two RacketVision badminton clips against the RacketVision tracker's output (which
scores F1 0.98-0.99 vs ground truth on those clips). With the tracklet linker (track/ball_dp.py):
track F1 0.82 (recall 0.72, precision 0.94), hits F1 0.74 (recall 0.67, precision 0.83).
Size limits are generous on purpose: a fast shuttle near the camera blurs into a 15-40 px streak, and the
linker's physics check removes the extra noise. Thresholds are defined at 960 px width and scale with it.
"""

from __future__ import annotations

import cv2
import numpy as np

REF_WIDTH = 960


class BallCandidateDetector:
    def __init__(self, work_width: int = 1920, diff_thr: int = 15, min_brightness: int = 140,
                 max_area: int = 180, big_blob_area: int = 600, max_side: int = 26, top_k: int = 8,
                 box_pad: float = 0.12, blob_pad: float = 0.3):
        self.work_width = work_width
        self.diff_thr = diff_thr
        self.min_brightness = min_brightness
        self.max_area = max_area
        self.big_blob_area = big_blob_area
        self.max_side = max_side
        self.top_k = top_k
        self.box_pad = box_pad           # pose-box enlargement (fraction of box width; height uses 2/3 of it)
        self.blob_pad = blob_pad         # big-moving-blob enlargement (fraction of blob width)
        self.scale = 1.0

    def prepare(self, frame_bgr: np.ndarray) -> np.ndarray:
        h, w = frame_bgr.shape[:2]
        self.scale = min(1.0, self.work_width / w)
        small = cv2.resize(frame_bgr, (round(w * self.scale), round(h * self.scale)), interpolation=cv2.INTER_AREA) \
            if self.scale < 1 else frame_bgr
        return cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)

    def candidates(self, prev: np.ndarray, cur: np.ndarray, nxt: np.ndarray, player_boxes: list,
                   x_range: tuple[float, float] | None = None) -> list[tuple[float, float, float]]:
        """[(x, y, score)] in original pixels for the middle frame `cur`, best first."""
        s = self.scale
        hh, ww = cur.shape
        lin = ww / REF_WIDTH
        motion = cv2.min(cv2.absdiff(cur, prev), cv2.absdiff(nxt, cur))
        _, mask = cv2.threshold(motion, self.diff_thr, 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)

        blocked = np.zeros((hh, ww), np.uint8)
        for i in range(1, n):                                   # large moving blobs = people
            x, y, w, h, area = stats[i]
            if area > self.big_blob_area * lin * lin:
                px, py = int(w * self.blob_pad) + 6, int(h * self.blob_pad / 2) + 6
                blocked[max(0, y - py):y + h + py, max(0, x - px):x + w + px] = 1
        for b in player_boxes:                                  # pose boxes, slightly enlarged
            x1, y1, x2, y2 = (np.array(b) * s).tolist()
            pw, ph = (x2 - x1) * self.box_pad, (y2 - y1) * self.box_pad * 2 / 3
            blocked[max(0, int(y1 - ph)):min(hh, int(y2 + ph)), max(0, int(x1 - pw)):min(ww, int(x2 + pw))] = 1

        out = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 2 or area > self.max_area * lin * lin or max(w, h) > self.max_side * lin:
                continue
            if max(w, h) / max(1, min(w, h)) > 4:              # long thin streaks are lines/rackets
                continue
            cx, cy = cents[i]
            if blocked[int(cy), int(cx)] or cy > hh * 0.98:
                continue
            bright = float(cur[y:y + h, x:x + w].max())
            if bright < self.min_brightness:
                continue
            ox, oy = cx / s, cy / s
            if x_range and not (x_range[0] <= ox <= x_range[1]):
                continue
            score = float(motion[y:y + h, x:x + w].mean()) * (0.5 + bright / 510.0)
            out.append((round(float(ox), 1), round(float(oy), 1), round(score, 2)))
        out.sort(key=lambda c: -c[2])
        return out[: self.top_k]
