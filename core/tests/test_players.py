"""Player selection: only the two players count; officials and spectators are ignored (no training)."""

import numpy as np

from rallyos.calibration.template_fit import apply_h, homography_from_taps
from rallyos.detect.players import PlayerSelector, find_static_people, foot_px
from rallyos.sports import load_sport

CFG = load_sport("badminton")
TAPS = [[330, 948], [1583, 948], [1253, 333], [638, 333]]      # real broadcast frame, 1920x1080
H = np.array(homography_from_taps(TAPS, CFG)["homography"])
H_INV = np.linalg.inv(H)
FRAME_H = 1080


def person_at(x_m, y_m, height_m=1.75):
    """A standing person's detection at court position (metres), sized with the local court scale."""
    fx, fy = apply_h(H_INV, [(x_m, y_m)])[0]
    a, b = apply_h(H_INV, [(x_m - 0.5, y_m), (x_m + 0.5, y_m)])
    h = height_m * float(np.hypot(*(b - a)))
    return {"bbox": [fx - 0.2 * h, fy - h, fx + 0.2 * h, fy], "conf": 0.9, "kp": None}


def person_px(fx, fy, h):
    return {"bbox": [fx - 0.2 * h, fy - h, fx + 0.2 * h, fy], "conf": 0.6, "kp": None}


def test_foot_uses_ankles_when_visible():
    kp = [[0, 0, 0]] * 17
    kp = [list(k) for k in kp]
    kp[15], kp[16] = [100, 500, 0.9], [120, 505, 0.9]
    assert foot_px({"bbox": [80, 300, 140, 507], "kp": kp}) == (110, 505)
    assert foot_px({"bbox": [80, 300, 140, 507], "kp": None}) == (110, 507)


def test_off_court_people_are_ignored():
    sel = PlayerSelector(H, CFG["court"], FRAME_H)
    near, far = person_at(2.3, 2.0), person_at(3.0, 10.7)
    service_judge = person_at(-2.2, 8.9, 1.2)        # seated beside the court
    line_judge = person_at(7.6, 1.0, 1.2)            # 1.5 m outside the right sideline
    roles, ignored = sel.select([service_judge, near, line_judge, far])
    assert roles[1]["bbox"] == near["bbox"] and roles[2]["bbox"] == far["bbox"]
    assert sorted(i["reason"] for i in ignored) == ["off court", "off court"]


def test_players_behind_the_baseline_still_count():
    roles, _ = PlayerSelector(H, CFG["court"], FRAME_H).select([person_at(3.0, -1.8), person_at(3.0, 14.9)])
    assert set(roles) == {1, 2}


def test_static_umpire_is_ignored_even_if_it_projects_onto_the_court():
    # A raised umpire's chair can project inside the court: only "stays put all clip" gives it away.
    umpire = person_px(1100, 420, 170)
    frames = []
    for i in range(30):
        near = person_at(1.5 + 0.1 * i, 1.5 + 0.08 * i)
        far = person_at(4.5 - 0.1 * i, 11.5 - 0.05 * i)
        jitter = person_px(1100 + (i % 3) - 1, 420 + (i % 2), 170)
        frames.append([near, far, jitter])
    statics = find_static_people(frames, FRAME_H)
    assert len(statics) == 1 and abs(statics[0]["head_px"][0] - 1100) < 3
    sel = PlayerSelector(H, CFG["court"], FRAME_H, statics)
    for dets in frames:
        roles, ignored = sel.select(dets)
        assert all(r["bbox"] != dets[2]["bbox"] for r in roles.values())
        assert any(i["reason"].startswith("static") for i in ignored)
    assert apply_h(H, [(1100, 420)])[0][1] > 6.7            # it really does land in the far half
    del umpire


def test_seated_official_with_flickering_legs_is_static():
    # legs drop in and out of the box (box bottom jumps 50 px) but the head stays put
    frames = []
    for i in range(30):
        h = 160 if i % 2 else 210
        official = {"bbox": [1580, 207, 1630, 207 + h], "conf": 0.5, "kp": None}
        frames.append([person_at(1 + 0.1 * i, 2), person_at(5 - 0.1 * i, 11), official])
    statics = find_static_people(frames, FRAME_H)
    assert len(statics) == 1 and statics[0]["frames_pct"] == 1.0


def test_moving_players_are_never_static():
    frames = [[person_at(1 + 0.15 * i, 2 + 0.1 * i), person_at(5 - 0.15 * i, 11 - 0.1 * i)] for i in range(30)]
    assert find_static_people(frames, FRAME_H) == []


def test_missing_player_is_not_replaced_by_someone_off_court():
    sel = PlayerSelector(H, CFG["court"], FRAME_H)
    roles, _ = sel.select([person_at(2.0, 2.0), person_at(-2.5, 10.0)])   # far player not detected this frame
    assert set(roles) == {1}


def test_implausible_size_is_rejected_after_learning():
    sel = PlayerSelector(H, CFG["court"], FRAME_H)
    for i in range(20):
        sel.select([person_at(2 + 0.05 * i, 2.0), person_at(3.0, 11.0)])
    giant = person_at(3.0, 10.0, height_m=4.0)       # e.g. a raised chair umpire projecting into the court
    roles, ignored = sel.select([person_at(2.5, 2.2), giant])
    assert 2 not in roles and ignored[0]["reason"].startswith("implausible")


def test_uncalibrated_picks_two_largest_non_static():
    sel = PlayerSelector(None, CFG["court"], FRAME_H, statics=[{"head_px": [1600, 88], "spread_px": 2, "height_px": 300, "frames_pct": 1}])
    big_static = person_px(1600, 370, 300)
    near, far = person_px(800, 800, 290), person_px(930, 400, 190)
    roles, ignored = sel.select([big_static, near, far, person_px(100, 200, 40)])
    assert roles[1]["bbox"] == near["bbox"] and roles[2]["bbox"] == far["bbox"]
    assert {i["reason"] for i in ignored} == {"static (official / spectator)", "too small (far spectator)"}


def test_zone_time_from_players_point_of_view():
    from rallyos.analytics.movement import zone_of, zone_time
    from rallyos.sports import load_sport

    cfg = load_sport("badminton")
    assert zone_of((0.5, 0.5), cfg, "near") == "rear-left"       # near player, deep on camera-left
    assert zone_of((0.5, 12.9), cfg, "far") == "rear-right"      # far player faces the camera: mirrored
    assert zone_of((3.05, 6.0), cfg, "near") == "front-centre"
    assert zone_of((3.0, 10.0), cfg, "near") is None             # opponent's half
    z = zone_time([(0.5, 0.5)] * 6 + [(3.05, 6.0)] * 2 + [(5.5, 3.0)] * 2, cfg, "near")
    assert z["most_zone"] == "rear-left" and z["most_zone_pct"] == 0.6 and z["zone_pct"]["mid-right"] == 0.2
    assert zone_time([], cfg, "near") == {}
