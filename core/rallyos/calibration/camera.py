"""Camera self-calibration from the court homography (§4.2). No checkerboard, no training.

The court is a plane, so the court -> image homography G equals K [r1 r2 t] up to scale. With square
pixels and the principal point at the image centre, K has one unknown (the focal length f), and the two
rotation constraints r1.r2 = 0 and |r1| = |r2| (Zhang's single-plane method) give two linear equations in
1/f^2. From f, R and t follow, and with them the camera centre C = -R^T t in court metres.

The camera centre is what the audio stage needs (speed-of-sound delay = distance(hitter, camera) / 343).
"""

from __future__ import annotations

import numpy as np


def focal_from_homography(G: np.ndarray, width: int, height: int) -> float | None:
    """Focal length in px from a court -> image homography G, or None if the view is degenerate.

    A fronto-parallel view (no perspective) leaves f undetermined; that returns None.
    """
    T = np.array([[1, 0, -width / 2], [0, 1, -height / 2], [0, 0, 1]], float)
    h = T @ np.asarray(G, float)
    h1, h2 = h[:, 0], h[:, 1]
    # each constraint reads  a / f^2 + b = 0
    a = np.array([h1[0] * h2[0] + h1[1] * h2[1],
                  h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    if float(a @ a) < 1e-18:
        return None
    w = -float(a @ b) / float(a @ a)                 # least squares for w = 1/f^2
    if not np.isfinite(w) or w <= 0:
        return None
    f = 1.0 / np.sqrt(w)
    return float(f) if 0.2 * width < f < 20 * width else None


def camera_from_homography(H_img_to_court, width: int, height: int) -> dict | None:
    """Full pinhole camera from the calibration homography (image px -> court m, as in match.json).

    Returns {"focal_px", "K", "R", "t", "position_m": [x, y, height]} or None when f can't be estimated.
    position_m is in court metres (origin near-left corner, y along the length); height is above the floor.
    """
    G = np.linalg.inv(np.asarray(H_img_to_court, float))   # court -> image
    f = focal_from_homography(G, width, height)
    if f is None:
        return None
    K = np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1]], float)
    B = np.linalg.inv(K) @ G
    lam = 2.0 / (np.linalg.norm(B[:, 0]) + np.linalg.norm(B[:, 1]))
    if B[2, 2] * lam < 0:                           # court must be in front of the camera (t_z > 0)
        lam = -lam
    r1, r2, t = lam * B[:, 0], lam * B[:, 1], lam * B[:, 2]
    R = np.column_stack([r1, r2, np.cross(r1, r2)])
    u, _, vt = np.linalg.svd(R)                     # nearest true rotation
    R = u @ vt
    C = -R.T @ t
    return {"focal_px": round(f, 1), "K": K.round(3).tolist(), "R": R.round(6).tolist(), "t": t.round(4).tolist(),
            "position_m": [round(float(C[0]), 2), round(float(C[1]), 2), round(abs(float(C[2])), 2)]}
