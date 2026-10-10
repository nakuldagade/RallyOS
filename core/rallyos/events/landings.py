"""Where a rally ended: landing (shuttle) or first bounce (ball) after the last hit (§4.7). Geometry only.

Shuttle (no bounce): the geometric tracker sees moving things, so a shuttle that has landed and lies still
disappears. The landing is therefore the last real detection after the last hit, provided the shuttle was
falling (moving down the image) and was not inside a player's box (caught, or hit again).
Ball (bounces): the first down -> up turn in the image after the last hit, away from the players.

The last detection is up to one frame of fall above the floor. With the camera position (self-calibration)
the court point is moved along the camera ray to the expected height, and the remaining height uncertainty
is passed on to the line call as an along-ray error.
"""

from __future__ import annotations

import numpy as np

from rallyos.calibration.template_fit import apply_h


def _inside(px, bbox, pad: float = 0.1) -> bool:
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    return x1 - pad * w <= px[0] <= x2 + pad * w and y1 - pad * h <= px[1] <= y2 + pad * h


def find_landing(balls: list[dict | None], frames: list[dict], last_hit_frame: int, end_frame: int,
                 fps: float, bounces: bool = False) -> dict | None:
    """Landing / bounce in frames (last_hit_frame, end_frame). Returns
    {"frame", "t", "px", "confidence", "falling", "near_player", "interpolated", "clip_ended"} or None (lost).
    clip_ended: the track runs into the last frames of the video, so the rally may not have finished."""
    start = last_hit_frame + 2
    end = min(end_frame, len(balls))
    real = [i for i in range(start, end) if balls[i] is not None and not balls[i].get("interp")]
    if not real:
        return None
    pick = None
    if bounces:
        for k in range(1, len(real) - 1):
            a, b, c = real[k - 1], real[k], real[k + 1]
            if c - a > 6:
                continue
            vy_in = (balls[b]["px"][1] - balls[a]["px"][1]) / (b - a)
            vy_out = (balls[c]["px"][1] - balls[b]["px"][1]) / (c - b)
            if vy_in > 0 and vy_out < 0 and not any(_inside(balls[b]["px"], p["bbox"]) for p in frames[b]["players"]):
                pick = b
                break
    fallback = pick is None
    if fallback:
        pick = real[-1]
    before = [i for i in real if pick - int(0.5 * fps) <= i <= pick]
    ys = [balls[i]["px"][1] for i in before[-4:]]
    falling = len(ys) >= 2 and ys[-1] > ys[0]
    near_player = any(_inside(balls[pick]["px"], p["bbox"]) for p in frames[pick]["players"]) if pick < len(frames) else False
    density = min(1.0, len(before) / max(1.0, 0.5 * fps * 0.6))   # 60% of the last half second tracked = full
    conf = 0.85 * (0.5 + 0.5 * density)
    if not falling:
        conf *= 0.6
    if near_player:
        conf *= 0.5
    if bounces and fallback:
        conf *= 0.5                                      # no bounce turn seen: last position only
    return {"frame": pick, "t": round(pick / fps, 3), "px": list(balls[pick]["px"]), "confidence": round(conf, 2),
            "falling": falling, "near_player": near_player, "interpolated": False,
            "clip_ended": pick >= len(balls) - max(3, int(0.1 * fps))}


def project_landing(px, H, camera_m=None, height_m: float = 0.0, width: int = 1920):
    """Court point (m) of an image point that is `height_m` above the floor.

    H maps image px -> floor. A point above the floor projects (through H) to where its camera ray meets
    the floor, which is farther from the camera; the true ground point lies back along that ray:
    P = C + (P0 - C) * (C_z - h) / C_z. Returns (court_xy, ray_unit_xy, metres_per_metre_of_height)
    where the last two describe how height uncertainty moves the point (None without a camera).
    """
    p0 = apply_h(H, [px])[0]
    if camera_m is None or camera_m[2] <= 0.5:
        return [float(p0[0]), float(p0[1])], None, None
    c = np.array(camera_m[:2], float)
    cz = float(camera_m[2])
    d = p0 - c
    dist = float(np.hypot(*d))
    p = c + d * (cz - height_m) / cz
    u = d / dist if dist > 0 else np.array([0.0, 1.0])
    return [float(p[0]), float(p[1])], u, dist / cz


def fall_per_frame_m(cfg: dict, fps: float) -> float:
    """How far the projectile can drop in one frame just before landing (sets the height uncertainty)."""
    proj = cfg["projectile"]
    v = proj.get("terminal_velocity_mps")
    if v is None:
        lo, hi = proj.get("speed_range_kmh", [10, 100])
        v = 0.3 * hi / 3.6                               # vertical part of a fast ball's descent
    return 0.0 if proj.get("bounces") else float(v) / fps


def px_jacobian(H, px, eps: float = 1.0) -> np.ndarray:
    """2x2 d(court m) / d(image px) at px: how pixel noise turns into metres at that spot."""
    base = apply_h(H, [px])[0]
    jx = (apply_h(H, [[px[0] + eps, px[1]]])[0] - base) / eps
    jy = (apply_h(H, [[px[0], px[1] + eps]])[0] - base) / eps
    return np.column_stack([jx, jy])


def project_world(camera: dict, X: float, Y: float, Z_up: float) -> list[float]:
    """Image px of a court point (m) at height Z_up, with the self-calibrated camera (K, R, t)."""
    K, R, t = (np.asarray(camera[k], float) for k in ("K", "R", "t"))
    C = -R.T @ t
    sign = 1.0 if C[2] > 0 else -1.0                     # which way the recovered z axis points
    x = K @ (R @ np.array([X, Y, sign * Z_up]) + t)
    return [float(x[0] / x[2]), float(x[1] / x[2])]


def net_polygon_px(camera: dict, cfg: dict) -> list[list[float]] | None:
    """Image quad covered by the net (floor to post height, post to post), or None if the sport has no net."""
    net = next((l for l in cfg["court"]["lines"] if l["id"] == "net"), None)
    if net is None or not cfg.get("net"):
        return None
    h = float(cfg["net"].get("height_post", cfg["net"].get("height_center", 1.0)))
    (x0, y0), (x1, y1) = net["p1"], net["p2"]
    return [project_world(camera, x0, y0, 0.0), project_world(camera, x1, y1, 0.0),
            project_world(camera, x1, y1, h), project_world(camera, x0, y0, h)]


def in_polygon(pt, poly) -> bool:
    """Point inside a convex polygon (either winding)."""
    sgn = 0
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
        c = (bx - ax) * (pt[1] - ay) - (by - ay) * (pt[0] - ax)
        if c != 0:
            if sgn == 0:
                sgn = 1 if c > 0 else -1
            elif (c > 0) != (sgn > 0):
                return False
    return True
