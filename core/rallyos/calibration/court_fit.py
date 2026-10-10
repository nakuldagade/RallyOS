"""Automatic Court Fingerprint (§4.1): find the court and the sport from line pixels, no taps, no training.

  1. line pixels (top-hat) -> merged straight lines                          (calibration/court_lines.py)
  2. every rectangle formed by two "long" and two "cross" image lines is a hypothesis for the outer court
     boundary of a sport template (end-on and side-on views both tried)
  3. each hypothesis gives a homography; it is kept only if it implies a physically sensible camera (focal
     length, height above the floor): the self-calibration of §4.2 doubles as a plausibility check
  4. score = how much of the template's lines land on line pixels (precision) x how much of the line pixels
     inside the court the template explains (recall). The sport whose template fits best wins: badminton and
     pickleball share an outline, but the inner lines (singles / long-service vs kitchen) fit only one.
  5. the 4 corners are refined by a local search on the line-pixel distance map (sub-pixel)

The result is the same 4 outer corners a user would tap, so the pipeline continues through homography_from_taps.
"""

from __future__ import annotations

import cv2
import numpy as np

from rallyos.calibration.template_fit import court_corners

TOL_PX = 3.0            # a template point "hits" a line pixel if it lands within this distance (working px)
MIN_SCORE = 0.15        # below this no court is reported: the caller falls back to 4 taps
HIGH_PRECISION = 0.88   # measured on broadcast clips: placements with >= 88% of template points on line pixels were within
                        # 6 px; below that (net tape, banners and graphics hide parts of the lines) corners were off by 45-300 px


def template_points(cfg: dict, step_m: float = 0.1) -> np.ndarray:
    """Points sampled along the template's floor lines (the net is not a floor line)."""
    pts = []
    for ln in (l for l in cfg["court"]["lines"] if l["id"] != "net"):
        p1, p2 = np.array(ln["p1"], float), np.array(ln["p2"], float)
        n = max(2, int(np.linalg.norm(p2 - p1) / step_m))
        pts.append(p1 + (p2 - p1) * np.linspace(0, 1, n)[:, None])
    return np.vstack(pts)


def project(G: np.ndarray, pts: np.ndarray) -> np.ndarray:
    h = np.c_[pts, np.ones(len(pts))] @ G.T
    return h[:, :2] / np.where(np.abs(h[:, 2:3]) < 1e-9, 1e-9, h[:, 2:3])


def sample_dt(dt: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Bilinear lookup of the distance map; points outside the image get a large distance."""
    hh, ww = dt.shape
    x, y = xy[:, 0], xy[:, 1]
    inside = (x >= 0) & (x <= ww - 1.001) & (y >= 0) & (y <= hh - 1.001)
    xi, yi = np.clip(x, 0, ww - 1.001), np.clip(y, 0, hh - 1.001)
    x0, y0 = xi.astype(int), yi.astype(int)
    fx, fy = xi - x0, yi - y0
    d = (dt[y0, x0] * (1 - fx) * (1 - fy) + dt[y0, x0 + 1] * fx * (1 - fy)
         + dt[y0 + 1, x0] * (1 - fx) * fy + dt[y0 + 1, x0 + 1] * fx * fy)
    return np.where(inside, d, 1e3)


def _pairs(lines: list[dict], key, min_sep: float) -> list[tuple[dict, dict]]:
    ordered = sorted(lines, key=key)
    return [(a, b) for i, a in enumerate(ordered) for b in ordered[i + 1:] if abs(key(b) - key(a)) >= min_sep]


def _reaches(line: dict, pt, slack_frac: float = 0.25, slack_min: float = 25.0) -> bool:
    """A court corner lies at the end of its two boundary segments: pt must be on the line's extent (+ slack)."""
    t = (pt[0] - line["p"][0]) * line["d"][0] + (pt[1] - line["p"][1]) * line["d"][1]
    slack = max(slack_min, slack_frac * (line["ext"][1] - line["ext"][0]))
    return line["ext"][0] - slack <= t <= line["ext"][1] + slack


def hypotheses(lines: list[dict], shape: tuple[int, int], max_per_family: int = 30, side_on: bool = False):
    """Yield (quad 4x2 in tap order NL, NR, FR, FL, orientation) for every rectangle of two long + two cross lines.

    Only rectangles whose corners fall on the detected extent of the two long lines are proposed, which keeps a
    long list of lines (short baselines included) tractable.

    End-on views only (court length running away from the camera, near side at the bottom of the image), which is
    what the rest of the pipeline assumes for near/far players. side_on=True also proposes views from the side of
    the court; those corners are in a rotated order and need the taps path for now.
    """
    from rallyos.calibration.court_lines import intersect, line_angle_deg

    hh, ww = shape
    steep = [l for l in lines if line_angle_deg(l) >= 30][:max_per_family]
    shallow = [l for l in lines if line_angle_deg(l) < 30][:max_per_family]

    def x_at_mid(l):
        dy = l["d"][1] if abs(l["d"][1]) > 1e-6 else 1e-6
        return l["p"][0] + l["d"][0] * ((hh / 2 - l["p"][1]) / dy)

    def y_at_mid(l):
        dx = l["d"][0] if abs(l["d"][0]) > 1e-6 else 1e-6
        return l["p"][1] + l["d"][1] * ((ww / 2 - l["p"][0]) / dx)

    families = [("end-on", steep, shallow, x_at_mid, y_at_mid, 0.06 * ww, 0.06 * hh)]
    if side_on:
        families.append(("side-on", shallow, steep, y_at_mid, x_at_mid, 0.06 * hh, 0.06 * ww))
    for tag, longs, crosses, lkey, ckey, lsep, csep in families:
        X = {(id(a), id(b)): intersect(a, b) for a in longs for b in crosses}      # each pair of lines meets once
        intersect_ = lambda a, b: X[(id(a), id(b))] if (id(a), id(b)) in X else X[(id(b), id(a))]  # noqa: E731
        for l1, l2 in _pairs(longs, lkey, lsep):
            for c1, c2 in _pairs(crosses, ckey, csep):
                if tag == "end-on":      # c1 = top (far), c2 = bottom (near); l1 = left, l2 = right
                    pts = [intersect_(l1, c2), intersect_(l2, c2), intersect_(l2, c1), intersect_(l1, c1)]
                else:                    # the court length runs sideways
                    pts = [intersect_(l1, c1), intersect_(l1, c2), intersect_(l2, c2), intersect_(l2, c1)]
                if any(p is None for p in pts):
                    continue
                # the long boundary lines run corner to corner, so the corners lie on their detected extent; the
                # cross lines (baselines) are often only partly visible (net, logos, players) and are not checked
                touch = ((l1, (0, 3)), (l2, (1, 2))) if tag == "end-on" else ((l1, (0, 1)), (l2, (2, 3)))
                if not all(_reaches(line, pts[i], slack_frac=0.3) for line, ids in touch for i in ids):
                    continue
                quad = np.array(pts, float)
                if np.abs(quad).max() > 4 * max(ww, hh):
                    continue
                yield quad, tag


def is_convex(q: np.ndarray) -> bool:
    e = [q[(i + 1) % 4] - q[i] for i in range(4)]
    c = [e[i][0] * e[(i + 1) % 4][1] - e[i][1] * e[(i + 1) % 4][0] for i in range(4)]
    return all(x > 0 for x in c) or all(x < 0 for x in c)


def quad_area(q: np.ndarray) -> float:
    x, y = q[:, 0], q[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def camera_ok(H_img2court: np.ndarray, ww: int, hh: int) -> bool:
    from rallyos.calibration.camera import camera_from_homography

    cam = camera_from_homography(H_img2court, ww, hh)
    if cam is None:
        return False
    return 0.35 * ww <= cam["focal_px"] <= 12 * ww and 0.8 <= cam["position_m"][2] <= 60


def court_to_image(cfg: dict, quad: np.ndarray) -> np.ndarray:
    return cv2.getPerspectiveTransform(court_corners(cfg).astype(np.float32), quad.astype(np.float32)).astype(float)


def _line_recall(cfg: dict, quad: np.ndarray, G: np.ndarray, lines: list[dict], shape: tuple[int, int]) -> float:
    """Of all the long straight lines detected in the image, how much of their length does the template explain?

    Pixel-level recall is flattered by clutter (logos, shadows) inside the court. Straight, continuous lines are
    what a court is made of, so this measures them directly: a table-tennis rectangle cannot explain the long
    sidelines of a badminton court, while the right badminton placement explains all of them. Lines that are
    not court lines (ad boards) are in every fit's denominator, so they lower all scores equally.
    """
    canvas = np.full(shape, 255, np.uint8)
    for ln in (l for l in cfg["court"]["lines"] if l["id"] != "net"):
        a, b = project(G, np.array([ln["p1"], ln["p2"]], float))
        if np.abs([a, b]).max() < 1e5:
            cv2.line(canvas, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), 0, 1)
    tdt = cv2.distanceTransform(canvas, cv2.DIST_L2, 3)
    total = hit = 0.0
    for l in lines:                                   # every detected long line: the denominator is the same for all fits
        t0, t1 = l["ext"]
        ts = np.linspace(t0, t1, max(8, int(t1 - t0) // 2))
        xy = np.array(l["p"])[None, :] + ts[:, None] * np.array(l["d"])[None, :]
        ix = np.clip(np.round(xy[:, 0]).astype(int), 0, shape[1] - 1)
        iy = np.clip(np.round(xy[:, 1]).astype(int), 0, shape[0] - 1)
        total += len(xy) * l["cover"]
        hit += float(np.sum(tdt[iy, ix] <= TOL_PX)) * l["cover"]
    return hit / total if total > 0 else 0.0


def _score(cfg: dict, quad: np.ndarray, mask: np.ndarray, dt: np.ndarray, pts: np.ndarray, lines: list[dict]) -> dict:
    """Precision (template points on line pixels), line recall and their harmonic mean (the score)."""
    G = court_to_image(cfg, quad)
    d = sample_dt(dt, project(G, pts))
    prec = float(np.mean(d <= TOL_PX))
    rec = _line_recall(cfg, quad, G, lines, mask.shape)
    # a template must be on the lines (precision) AND account for them (recall): a simple template such as a
    # table-tennis rectangle fits anywhere (precision) but explains almost none of a badminton court (recall)
    return {"score": prec * rec, "precision": prec, "recall": rec, "visible": float((d < 1e2).mean())}


def fit_sport(cfg: dict, lines: list[dict], mask: np.ndarray, dt: np.ndarray, top_k: int = 50, refine_k: int = 10,
              recall_lines: list[dict] | None = None, hyps: list | None = None) -> dict | None:
    """Best placement of one sport template on the detected lines, or None.

    Rectangles of detected lines are ranked by precision, the best few are refined (wide-to-narrow local search,
    which also repairs a boundary that was hidden by the net tape or a player), then scored on precision x recall.
    """
    hh, ww = mask.shape
    pts = template_points(cfg)
    scored = []
    for quad, tag in (hyps if hyps is not None else hypotheses(lines, mask.shape)):
        G = court_to_image(cfg, quad)
        d = sample_dt(dt, project(G, pts))
        if (d < 1e2).mean() < 0.55:                  # at least 55% of the template must be inside the frame
            continue
        scored.append((float(np.mean(d <= 2 * TOL_PX)), quad, tag))
    scored.sort(key=lambda s: -s[0])
    best, tried = None, []
    for _, quad, tag in scored[:top_k]:
        if len(tried) >= refine_k:
            break
        if any(np.abs(quad - t).max() < 12 for t in tried):          # near-duplicate of one already refined
            continue
        if not camera_ok(np.linalg.inv(court_to_image(cfg, quad)), ww, hh):
            continue
        tried.append(quad)
        q = refine(cfg, quad, dt, coarse=True)
        if not camera_ok(np.linalg.inv(court_to_image(cfg, q)), ww, hh):
            continue
        sc = _score(cfg, q, mask, dt, pts, recall_lines if recall_lines is not None else lines)
        if sc["visible"] < 0.55:
            continue
        if best is None or sc["score"] > best["score"]:
            best = {**sc, "quad": q, "orientation": tag}
    return best


def _objective(cfg: dict, q: np.ndarray, dt: np.ndarray, pts: np.ndarray, sigma: float) -> float:
    if not is_convex(q):
        return -1.0
    d = sample_dt(dt, project(court_to_image(cfg, q), pts))
    return float(np.mean(np.exp(-(np.minimum(d, 3 * sigma) / sigma) ** 2)))


def refine(cfg: dict, quad: np.ndarray, dt: np.ndarray, coarse: bool = False) -> np.ndarray:
    """Line search of the 4 boundary lines (sub-pixel), wide to narrow.

    Each round tries, for every edge of the quad, shifting it along its normal and tilting it about either end
    over a range of +-r px, keeps the best, then halves r while the match sigma tightens. Sweeping a whole range
    (instead of taking small steps) lets a boundary that was proposed 40-60 px off - hidden by the net tape, a
    banner or a player - jump onto its true line, pulled there by the template's other lines.
    coarse=False starts at r = 6 px for polishing an already good quad.
    """
    pts = template_points(cfg, 0.12)
    schedule = [(10.0, 60), (6.0, 30), (4.0, 16), (3.0, 8), (2.0, 4), (2.0, 2), (2.0, 1), (1.5, 0.5)]
    if not coarse:
        schedule = schedule[3:]
    q = quad.copy()
    for sigma, r in schedule:
        for _ in range(2):
            changed = False
            for i in range(4):
                j = (i + 1) % 4
                e = q[j] - q[i]
                n = np.array([-e[1], e[0]]) / max(np.linalg.norm(e), 1e-9)
                best_v, best_q = _objective(cfg, q, dt, pts, sigma), q
                for mode in ("shift", "tilt_i", "tilt_j"):
                    for dlt in np.linspace(-r, r, 13):
                        t = q.copy()
                        if mode == "shift":
                            t[i] += n * dlt
                            t[j] += n * dlt
                        elif mode == "tilt_i":
                            t[i] += n * dlt
                        else:
                            t[j] += n * dlt
                        v = _objective(cfg, t, dt, pts, sigma)
                        if v > best_v + 1e-6:
                            best_v, best_q, changed = v, t, True
                q = best_q
            if not changed:
                break
    return q


def detect_court(frames: list[np.ndarray], sports: list[str] | None = None) -> dict | None:
    """The sport and the 4 outer court corners found from line pixels alone.

    frames: BGR frames of a fixed camera (a median of several removes the players). sports: templates to try
    (default: every sports/*.yaml). Returns None when nothing fits well enough, else
    {"sport", "sport_confidence", "fit_score", "precision", "recall", "orientation", "corners_px" (original
    pixels, tap order NL NR FR FL), "reprojection_error_px", "ranking": [(sport, score), ...]}.
    sport_confidence is a heuristic (precision, scaled by the margin over the runner-up sport), not a probability.
    """
    from rallyos.calibration import court_lines as cl
    from rallyos.sports import list_sports, load_sport

    bg = cl.background_frame(frames)
    mask = cl.line_mask(bg)                       # thin lines: where the court lines are (hypotheses, recall)
    _, scale = cl.resize_to_work(bg)
    lines = cl.detect_lines(mask)
    if len(lines) < 4:
        return None
    wide = cl.line_mask(bg, wide=True)                 # + merged far-court bands: where template points land
    dt = cl.mask_distance(wide)
    prop_lines = cl.union_lines(lines, cl.detect_lines(wide))   # rectangles are proposed from these; recall counts `lines`
    names = sports or list_sports()
    # the rectangles of line pairs depend on the image only, so they are built once and shared by every sport
    hyps = [(q, t) for q, t in hypotheses(prop_lines, mask.shape) if is_convex(q) and quad_area(q) >= 0.04 * mask.size]
    results = []
    for name in names:                                 # pass 1: cheap, two refinements per sport
        cfg = load_sport(name)
        fit = fit_sport(cfg, prop_lines, mask, dt, refine_k=2, recall_lines=lines, hyps=hyps)
        if fit:
            results.append((name, cfg, fit))
    if not results:
        return None
    results.sort(key=lambda r: -r[2]["score"])
    top = results[0][2]["score"]
    for k, (name, cfg, _) in enumerate(results[:2]):   # pass 2: the best sport, and the runner-up if it is close
        if results[k][2]["score"] < 0.75 * top:
            continue
        fit = fit_sport(cfg, prop_lines, mask, dt, refine_k=6, recall_lines=lines, hyps=hyps)
        if fit and fit["score"] >= results[k][2]["score"]:
            results[k] = (name, cfg, fit)
    results.sort(key=lambda r: -r[2]["score"])
    name, cfg, fit = results[0]
    if fit["score"] < MIN_SCORE:
        return None
    quality = "high" if fit["precision"] >= HIGH_PRECISION else "check"
    quad = fit["quad"]
    d = sample_dt(dt, project(court_to_image(cfg, quad), template_points(cfg, 0.12)))
    hit = d[d <= TOL_PX]
    base = fit["precision"]
    if len(results) > 1:
        margin = (fit["score"] - results[1][2]["score"]) / max(fit["score"], 1e-6)
        conf = base * (0.4 + 0.6 * min(1.0, margin / 0.3))
    else:
        conf = base
    return {"sport": name, "sport_confidence": round(float(conf), 2), "fit_score": round(float(fit["score"]), 3),
            "precision": round(float(fit["precision"]), 3), "recall": round(float(fit["recall"]), 3),
            "orientation": fit["orientation"], "quality": quality, "corners_px": (quad / scale).round(1).tolist(),
            "reprojection_error_px": round(float(hit.mean() / scale), 2) if len(hit) else None,
            "ranking": [(n, round(float(f["score"]), 3)) for n, _, f in results]}
