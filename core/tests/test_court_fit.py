"""Automatic Court Fingerprint (§4.1) on computer-generated courts with a known homography."""

import cv2
import numpy as np
import pytest

from rallyos.calibration.court_fit import detect_court
from rallyos.calibration.template_fit import court_corners
from rallyos.sports import load_sport

W, H = 1280, 720


def camera_g(cfg, f=1100.0, pos=None, look=None):
    """Court -> image homography of a pinhole camera behind the near baseline, looking down the court."""
    length, width = cfg["court"]["length"], cfg["court"]["width"]
    pos = pos or (width / 2, -0.55 * length, max(0.28 * length, 1.4))      # at least a tripod / spectator height
    look = look or (width / 2, 0.5 * length, 0.0)
    C, L = np.array(pos, float), np.array(look, float)
    z = (L - C) / np.linalg.norm(L - C)
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
    G = K @ np.column_stack([R[:, 0], R[:, 1], -R @ C])
    return G / G[2, 2]


def render(cfg, G, clutter=True, seed=0):
    """A floor-coloured frame with the template's lines painted white (4 px wide in the near field)."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), (70, 110, 60), np.uint8)
    img[: int(H * 0.12)] = (40, 30, 90)                                  # a dark ad-board strip at the top
    for ln in (l for l in cfg["court"]["lines"] if l["id"] != "net"):
        pts = np.array([ln["p1"] + [1.0], ln["p2"] + [1.0]]) @ G.T
        a, b = (pts[:, :2] / pts[:, 2:3])
        mid = 0.5 * (a + b)
        thick = max(2, int(round(3.5 * (1.0 + 0.8 * mid[1] / H))))
        cv2.line(img, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), (240, 240, 240), thick, cv2.LINE_AA)
    if clutter:                                                          # logos, a player blob, sensor noise
        cv2.putText(img, "SPONSOR", (W // 2 - 120, int(H * 0.08)), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 5)
        cv2.ellipse(img, (W // 2 + 40, int(H * 0.62)), (22, 55), 0, 0, 360, (30, 30, 200), -1)
        img = np.clip(img.astype(int) + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    return img


def corner_error(cfg, G, found):
    truth = np.array([[x, y] for x, y in (np.c_[court_corners(cfg), np.ones(4)] @ G.T)[:, :2] / (np.c_[court_corners(cfg), np.ones(4)] @ G.T)[:, 2:3]])
    return float(np.max(np.linalg.norm(np.array(found) - truth, axis=1)))


@pytest.mark.parametrize("sport", ["badminton", "tennis", "pickleball", "table_tennis"])
def test_court_and_sport_found_from_one_frame(sport):
    cfg = load_sport(sport)
    G = camera_g(cfg)
    # a bare table is a plain rectangle that other templates can mimic, so its sport is given; the others are fingerprinted
    det = detect_court([render(cfg, G)], [sport] if sport == "table_tennis" else None)
    assert det is not None, f"no court found for {sport}"
    assert det["sport"] == sport and det["quality"] == "high"
    assert corner_error(cfg, G, det["corners_px"]) < 10.0          # px on a 1280-wide frame
    assert det["precision"] > 0.9 and det["reprojection_error_px"] < 2.0


def test_inner_lines_tell_pickleball_from_badminton():
    """Same outline (13.4 x 6.1 m): only the inner lines differ (§4.1)."""
    for sport, other in (("badminton", "pickleball"), ("pickleball", "badminton")):
        cfg = load_sport(sport)
        det = detect_court([render(cfg, camera_g(cfg, f=1000.0, pos=(3.05, -7.0, 3.6)))])
        assert det["sport"] == sport
        assert dict(det["ranking"])[sport] > dict(det["ranking"]).get(other, 0.0)


def test_a_given_sport_is_used_and_other_cameras_work():
    cfg = load_sport("badminton")
    for f, pos in ((900.0, (3.05, -9.0, 4.5)), (1500.0, (2.0, -12.0, 6.0)), (1200.0, (4.4, -8.0, 3.0))):
        G = camera_g(cfg, f=f, pos=pos)
        det = detect_court([render(cfg, G, seed=int(f))], ["badminton"])
        assert det is not None and corner_error(cfg, G, det["corners_px"]) < 10.0
        assert det["ranking"] == [("badminton", det["fit_score"])]


def test_median_of_frames_removes_a_moving_player():
    cfg = load_sport("badminton")
    G = camera_g(cfg)
    frames = []
    for k in range(5):
        img = render(cfg, G, clutter=False)
        cv2.rectangle(img, (500 + 60 * k, 380), (560 + 60 * k, 560), (30, 30, 200), -1)    # crosses the court lines
        frames.append(img)
    det = detect_court(frames, ["badminton"])
    assert det is not None and corner_error(cfg, G, det["corners_px"]) < 10.0


def test_no_court_means_no_answer_not_a_guess():
    rng = np.random.default_rng(3)
    assert detect_court([np.full((H, W, 3), 90, np.uint8)]) is None
    assert detect_court([rng.integers(0, 255, (H, W, 3), dtype=np.uint8)]) is None


def test_corners_come_in_tap_order_near_left_first():
    cfg = load_sport("badminton")
    det = detect_court([render(cfg, camera_g(cfg))], ["badminton"])
    nl, nr, fr, fl = det["corners_px"]
    assert nl[1] > fl[1] and nr[1] > fr[1] and nl[0] < nr[0] and fl[0] < fr[0]     # near = bottom, left < right
