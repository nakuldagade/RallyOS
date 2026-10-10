"""Rally outcome (§4.7): landing detection, height-corrected projection, IN/OUT probability + ellipse,
suggested winner, score through the rules engine, review clips."""

import numpy as np
import pytest

from rallyos.analytics.linecall import (ellipse_from_cov, line_call, make_call, prob_in, rally_winner,
                                        resolve_rally_ends, score_rallies)
from rallyos.audio.onsets import ffmpeg_exe
from rallyos.calibration.camera import camera_from_homography
from rallyos.events.landings import find_landing, in_polygon, net_polygon_px, project_landing, project_world
from rallyos.render.clips import render_review_clip
from rallyos.sports import load_sport

W, HH = 1920, 1080
CAM = (3.05, -4.0, 3.0)


def camera_matrices(f=1500.0, pos=CAM, look=(3.05, 6.7, 0.0)):
    C, L = np.array(pos, float), np.array(look, float)
    z = (L - C) / np.linalg.norm(L - C)
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])
    K = np.array([[f, 0, W / 2], [0, f, HH / 2], [0, 0, 1]])
    P = K @ np.column_stack([R, -R @ C])
    return P


def to_px(P, X):
    h = P @ np.array([X[0], X[1], X[2], 1.0])
    return [float(h[0] / h[2]), float(h[1] / h[2])]


P = camera_matrices()
H = np.linalg.inv(P[:, [0, 1, 3]] / P[2, 3])            # image px -> court floor
CFG = load_sport("badminton")
CAMERA = camera_from_homography(H, W, HH)


def test_camera_recovered_from_this_rig():
    cam = camera_from_homography(H, W, HH)
    assert cam["position_m"] == pytest.approx(list(CAM), abs=0.05)


def test_height_correction_moves_point_back_along_the_ray():
    ground = (2.0, 10.0)
    px = to_px(P, (ground[0], ground[1], 0.25))           # shuttle 25 cm above the floor
    naive, _, _ = project_landing(px, H)
    fixed, u, m_per_h = project_landing(px, H, CAM, height_m=0.25)
    assert np.hypot(naive[0] - ground[0], naive[1] - ground[1]) > 0.5      # uncorrected: far too deep
    assert fixed == pytest.approx(list(ground), abs=0.01)
    assert m_per_h > 1 and abs(np.hypot(*u) - 1) < 1e-9


def test_line_calls_in_out_and_too_close():
    mid_fall = 6.7 / 60 / 2                                # last frame before contact: half a frame of fall up

    def call_at(x, y):
        return line_call(to_px(P, (x, y, mid_fall)), H, CFG, fps=60, width=W, camera_m=CAM)

    inside = call_at(3.0, 10.0)
    assert inside["call"] == "IN" and inside["call_prob"] > 0.99 and inside["margin_m"] > 2
    out = call_at(3.0, 14.4)                               # 1 m past the far baseline
    assert out["call"] == "OUT" and out["call_prob"] > 0.98 and out["margin_m"] == pytest.approx(-1.0, abs=0.02)
    assert out["ellipse_m"][0] > 0.5                       # far court from a 3 m high camera: depth is uncertain
    line = call_at(5.64, 10.0)                             # right on the singles sideline
    assert line["call"] == "TOO CLOSE TO CALL" and 0.3 < line["p_in"] < 0.7
    a, b, _ = line["ellipse_m"]
    assert 0 < b <= a < 0.6


def test_make_call_and_prob_in():
    assert make_call(0.95) == ("IN", 0.95) and make_call(0.1) == ("OUT", 0.9)
    assert make_call(0.5)[0] == "TOO CLOSE TO CALL"
    cov = np.diag([0.01, 0.01])
    assert prob_in([1.0, 1.0], cov, [0, 2, 0, 2]) > 0.999
    assert prob_in([0.0, 1.0], cov, [0, 2, 0, 2]) == pytest.approx(0.5, abs=0.01)


def test_ellipse_from_cov():
    assert ellipse_from_cov(np.diag([0.04, 0.01])) == [0.4, 0.2, 0.0]
    a, b, ang = ellipse_from_cov(np.array([[0.01, 0.0], [0.0, 0.04]]))
    assert (a, b) == (0.4, 0.2) and abs(abs(ang) - 90) < 1e-6


SIDES = {1: "near", 2: "far"}


def test_rally_winner_rules():
    far_in = {"court": [3.0, 11.0], "p_in": 0.95, "call": "IN"}
    far_out = {"court": [3.0, 14.0], "p_in": 0.05, "call": "OUT"}
    w = rally_winner(far_in, 6.7, 1, 0.8, SIDES)
    assert w["winner_track_id"] == 1 and w["end_reason"] == "landing_in" and w["confidence"] == pytest.approx(0.76)
    w = rally_winner(far_out, 6.7, 1, 0.8, SIDES)
    assert w["winner_track_id"] == 2 and w["end_reason"] == "landing_out"
    w = rally_winner(far_in, 6.7, 2, 0.8, SIDES)           # deep on the far side, far player "hit last":
    assert w["winner_track_id"] == 1 and w["end_reason"] == "landing_in" and w["hitter_conflict"]   # missed near hit
    assert w["confidence"] < 0.6
    near_net = {"court": [3.0, 7.5], "p_in": 0.1, "call": "OUT"}
    w = rally_winner(near_net, 6.7, 2, 0.8, SIDES)         # far player's shot dropped on their side of the net
    assert w["winner_track_id"] == 1 and w["end_reason"] == "net_fault"
    w = rally_winner(far_in, 6.7, None, 0.8, SIDES)        # unknown hitter: same winner, lower confidence
    assert w["winner_track_id"] == 1 and w["confidence"] < 0.76


def test_score_rallies_badminton_and_unresolved():
    rallies = [{"winner_track_id": t, "winner_confidence": 0.8} for t in (1, 1, 2, None, 1)]
    s = score_rallies(CFG, rallies, {1: 0, 2: 1})
    assert s["games"] == [[3, 1]] and s["unresolved_rallies"] == 1 and not s["confirmed_by_human"]
    assert [r["score_after"] for r in rallies] == ["1-0", "2-0", "2-1", None, "3-1"]


def test_score_rallies_tennis_uses_sets_and_games():
    rallies = [{"winner_track_id": 1, "winner_confidence": 0.9} for _ in range(5)]
    s = score_rallies(load_sport("tennis"), rallies, {1: 0, 2: 1})
    assert s["games"] == [[1, 0]] and "15-0" in s["score_str"]


def ball(x, y):
    return {"px": [float(x), float(y)], "court": None, "conf": 0.8, "interp": False}


def test_find_landing_shuttle_last_falling_detection():
    balls = [None] * 10 + [ball(900, 300 + 15 * i) for i in range(20)] + [None] * 20
    frames = [{"players": []} for _ in balls]
    land = find_landing(balls, frames, last_hit_frame=8, end_frame=50, fps=25)
    assert land["frame"] == 29 and land["falling"] and not land["near_player"] and land["confidence"] > 0.7
    frames[29] = {"players": [{"bbox": [850, 500, 1000, 800]}]}   # ends inside a player: caught / hit
    assert find_landing(balls, frames, 8, 50, 25)["confidence"] < 0.5
    assert find_landing([None] * 50, frames, 8, 50, 25) is None
    assert find_landing(balls[:30], frames, 8, 30, 25)["clip_ended"]          # video ends while it's flying


def test_find_landing_ball_bounce_turn():
    down = [ball(900, 300 + 20 * i) for i in range(10)]
    up = [ball(900, 480 - 12 * i) for i in range(1, 10)]
    balls = [None] * 5 + down + up + [None] * 10
    frames = [{"players": []} for _ in balls]
    land = find_landing(balls, frames, 3, len(balls), 25, bounces=True)
    assert land["frame"] == 14 and land["px"] == [900.0, 480.0]


def test_resolve_rally_ends_end_to_end():
    fps = 60
    land_px = to_px(P, (3.0, 11.0, 0.0))
    start = to_px(P, (3.0, 3.0, 2.5))
    track = [ball(start[0] + (land_px[0] - start[0]) * k / 40, start[1] + (land_px[1] - start[1]) * k / 40) for k in range(41)]
    balls = [None] * 20 + track + [None] * 60
    frames = [{"players": []} for _ in balls]
    rallies = [{"idx": 0, "t_start": 0.0, "t_end": 1.0, "hit_frames": [5, 20]}]
    hits = [{"frame": 5, "track_id": 2}, {"frame": 20, "track_id": 1}]
    lands = resolve_rally_ends(rallies, hits, balls, frames, CFG, fps, W, H=H, camera=CAMERA)
    assert len(lands) == 1 and lands[0]["call"] == "IN" and lands[0]["court"][1] == pytest.approx(11.0, abs=0.3)
    assert rallies[0]["winner_track_id"] == 1 and rallies[0]["end_reason"] == "landing_in"
    far_px = to_px(P, (3.0, 25.0, 0.0))                    # 11 m past the baseline: still in the air
    balls3 = [None] * 20 + [ball(far_px[0], far_px[1] + k) for k in range(20)] + [None] * 60
    rallies3 = [{"idx": 0, "t_start": 0.0, "t_end": 1.0, "hit_frames": [5, 20]}]
    lands3 = resolve_rally_ends(rallies3, hits, balls3, frames, CFG, fps, W, H=H, camera=CAMERA)
    assert rallies3[0]["end_reason"] == "landing_implausible" and "call" not in lands3[0]
    rallies2 = [{"idx": 0, "t_start": 0.0, "t_end": 1.0, "hit_frames": [5, 20]}]
    lands2 = resolve_rally_ends(rallies2, hits, balls, frames, CFG, fps, W, H=None)
    assert "call" not in lands2[0] and rallies2[0]["winner_track_id"] is None


@pytest.mark.skipif(ffmpeg_exe() is None, reason="ffmpeg not available")
def test_render_review_clip(tmp_path):
    import cv2

    src = tmp_path / "src.avi"
    vw = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"MJPG"), 25, (640, 360))
    for i in range(75):
        fr = np.full((360, 640, 3), 40, np.uint8)
        cv2.circle(fr, (100 + 5 * i, 100 + 2 * i), 5, (255, 255, 255), -1)
        vw.write(fr)
    vw.release()
    balls = [ball(100 + 5 * i, 100 + 2 * i) for i in range(75)]
    out = tmp_path / "d_001.mp4"
    assert render_review_clip(src, out, 1.5, 25, balls, balls[50]["px"], 50, "TOO CLOSE TO CALL", 0.55)
    cap = cv2.VideoCapture(str(out))
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) >= 70
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(12.5, abs=0.1)


def test_project_world_matches_true_camera():
    for X in [(1.0, 2.0, 0.0), (3.05, 6.7, 1.55), (5.0, 12.0, 0.8)]:
        assert project_world(CAMERA, *X) == pytest.approx(to_px(P, X), abs=1.0)


def test_shuttle_lost_against_the_net_gets_no_call():
    poly = net_polygon_px(CAMERA, CFG)
    lost = to_px(P, (4.5, 5.5, 0.9))                       # in the air in front of the net, over the mesh
    assert in_polygon(lost, poly) and not in_polygon(to_px(P, (3.0, 2.0, 0.0)), poly)
    fps = 60
    start = to_px(P, (4.5, 2.0, 3.0))
    track = [ball(start[0] + (lost[0] - start[0]) * k / 30, start[1] + (lost[1] - start[1]) * k / 30) for k in range(31)]
    balls = [None] * 20 + track + [None] * 60
    frames = [{"players": []} for _ in balls]
    rallies = [{"idx": 0, "t_start": 0.0, "t_end": 1.0, "hit_frames": [5, 20]}]
    lands = resolve_rally_ends(rallies, [{"frame": 20, "track_id": 2}], balls, frames, CFG, fps, W, H=H, camera=CAMERA)
    assert rallies[0]["end_reason"] == "landing_hidden_by_net" and rallies[0]["winner_track_id"] is None
    assert "call" not in lands[0] and lands[0]["confidence"] < 0.3
