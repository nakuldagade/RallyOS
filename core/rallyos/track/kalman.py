"""Gap filling for ball tracks. Filled frames are always flagged interpolated with lower confidence (rule 5).

Ball frames use the tracks.json shape: {"px": [x, y], "court": None, "conf": c, "interp": bool} or None.
fill_short_gaps is the simple linear version; the Kalman + physics filler (§4.3 step 5) will replace it
behind the same interface.
"""

from __future__ import annotations

INTERP_CONF_SCALE = 0.5


def fill_short_gaps(balls: list[dict | None], max_gap: int = 5) -> list[dict | None]:
    """Linearly bridge gaps of at most max_gap missing frames between two detections.

    Longer gaps (shuttle out of frame, hidden for long) stay empty: guessing them would be false precision.
    """
    out = list(balls)
    known = [i for i, b in enumerate(balls) if b is not None]
    for a, b in zip(known, known[1:]):
        gap = b - a - 1
        if gap == 0 or gap > max_gap:
            continue
        (xa, ya), (xb, yb) = balls[a]["px"], balls[b]["px"]
        conf = INTERP_CONF_SCALE * min(balls[a]["conf"], balls[b]["conf"])
        for k in range(1, gap + 1):
            t = k / (gap + 1)
            out[a + k] = {"px": [round(xa + t * (xb - xa), 1), round(ya + t * (yb - ya), 1)],
                          "court": None, "conf": round(conf, 3), "interp": True}
    return out
