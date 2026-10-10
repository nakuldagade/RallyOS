"""Movement intelligence (§4.8): return to base, fatigue trend, split-step."""

import cv2
import numpy as np
import pytest

from rallyos.analytics.movement import base_for, fatigue_trend, movement_speed_between, return_stats, return_to_base
from rallyos.analytics.splitstep import collect_samples, detect_split_step, summarise, windows_for
from rallyos.sports import load_sport

CFG = load_sport("badminton")


def test_base_position_is_mirrored_for_the_far_player():
    assert base_for(CFG, "near") == (3.05, 3.4) and base_for(CFG, "far") == (3.05, pytest.approx(13.4 - 3.4))
    tennis = load_sport("tennis")
    assert base_for(tennis, "far")[1] == pytest.approx(23.77 + 1.0)                 # just behind the far baseline


def walk(points, dt=0.12):
    return [(i * dt, p) for i, p in enumerate(points)]


def test_return_to_base_times_hits_and_censors_late_returns():
    base = (3.05, 3.4)
    # player lunges to the front at t=1.0 (hit), is back within 1.2 m of base 0.9 s later
    track = walk([(3.0, 3.4)] * 8 + [(3.0, 5.5), (3.0, 5.4), (3.0, 5.0), (3.0, 4.6), (3.0, 4.2), (3.0, 3.9), (3.0, 3.6), (3.0, 3.4)] + [(3.0, 3.4)] * 20)
    res = return_to_base(track, [0.96], {0.96: 4.0}, base)
    assert res[0.96]["returned"] and res[0.96]["return_s"] == pytest.approx(0.60, abs=0.15) and not res[0.96]["was_at_base"]
    late = return_to_base(track, [0.96], {0.96: 1.2}, base)                          # the reply comes before they are back
    assert late[0.96]["returned"] is False and late[0.96]["return_s"] is None
    stay = return_to_base(track, [0.2], {0.2: 3.0}, base)                            # already central when hitting
    assert stay[0.2] == {"return_s": 0.0, "returned": True, "was_at_base": True}
    assert return_to_base([], [1.0], {1.0: None}, base)[1.0]["returned"] is False


def test_return_stats_leave_shots_hit_from_base_out_of_the_average():
    st = return_stats({1.0: {"return_s": 1.0, "was_at_base": False}, 3.0: {"return_s": 2.0, "was_at_base": False},
                       5.0: {"return_s": None, "was_at_base": False}, 7.0: {"return_s": 0.0, "was_at_base": True},
                       8.0: {"return_s": 0.0, "was_at_base": True}})
    assert st["avg_return_to_base_s"] == 1.5                                  # the two shots hit from base do not dilute it
    assert (st["return_to_base_n"], st["pulled_away_n"], st["stayed_central_n"]) == (5, 3, 2)
    assert st["returned_pct"] == pytest.approx(0.67, abs=0.01) and st["slowest_return_t"] == [3.0, 1.0]
    only_central = return_stats({1.0: {"return_s": 0.0, "was_at_base": True}})
    assert "avg_return_to_base_s" not in only_central and only_central["stayed_central_n"] == 1
    assert return_stats({}) == {}


def test_fatigue_needs_enough_shots_and_reports_the_change():
    few = [{"t": i, "return_s": 1.0} for i in range(5)]
    f = fatigue_trend(few)
    assert f["enough_data"] is False and "at least 9" in f["note"]
    shots = [{"t": 10.0 * i, "return_s": 1.0 + 0.1 * i, "speed_mps": 3.0 - 0.2 * i} for i in range(9)]
    f = fatigue_trend(shots)
    assert f["enough_data"] and f["first_third_return_s"] == pytest.approx(1.1) and f["last_third_return_s"] == pytest.approx(1.7)
    assert f["return_change_pct"] == 55 and f["speed_change_pct"] < 0


def test_movement_speed_between_two_times():
    track = walk([(3.0, 3.0 + 0.3 * i) for i in range(20)])                          # 0.3 m per 0.12 s = 2.5 m/s
    assert movement_speed_between(track, 0.0, 2.0) == pytest.approx(2.5, abs=0.2)
    assert movement_speed_between(track, 5.0, 6.0) is None


def sample(t, ly, ry, h=300.0):
    return {"t": t, "ay": (ly, ry), "h": h}


def drift(n, start, per_frame, h=300.0, bump=None):
    """Ankles that drift steadily (the player running up the court), with an optional hop on top: {frame: lift_px}."""
    return [sample(i * 0.04, start + per_frame * i - (bump or {}).get(i, 0), start + per_frame * i - (bump or {}).get(i, 0), h) for i in range(n)]


def test_split_step_is_a_bump_on_top_of_the_motion_not_the_motion_itself():
    """Real windows were mostly steady drift (487 -> 401 px as the player ran): that must not count as a hop."""
    assert detect_split_step(drift(12, 480, -7.5))["split_step"] is False                  # running up the court
    assert detect_split_step(drift(12, 220, +2.0))["split_step"] is False                  # slowly retreating
    curved = [sample(i * 0.04, 450 - 0.35 * i * i, 450 - 0.35 * i * i) for i in range(12)]   # accelerating
    assert detect_split_step(curved)["split_step"] is False
    hop_on_drift = drift(12, 480, -3.0, bump={5: 14, 6: 18, 7: 12})                         # the same running, plus a hop
    r = detect_split_step(hop_on_drift)
    assert r["split_step"] is True and r["run"] >= 2
    assert detect_split_step(drift(12, 300, 0.0, bump={9: 14, 10: 16, 11: 15}))["split_step"] is False   # rises and never lands
    noise = np.random.default_rng(1).normal(0, 1.5, (12, 2))
    assert detect_split_step([sample(i * 0.04, 800 + noise[i, 0], 800 + noise[i, 1]) for i in range(12)])["split_step"] is False


def test_split_step_needs_both_feet_up_together_for_two_frames():
    planted = [sample(i * 0.04, 800, 800) for i in range(8)]
    hop = planted[:3] + [sample(0.12, 780, 781), sample(0.16, 776, 778), sample(0.20, 783, 784)] + planted[:3]
    hop = [sample(i * 0.04, y1, y2) for i, (y1, y2) in enumerate([(800, 800)] * 3 + [(782, 783), (777, 779), (781, 782)] + [(800, 800)] * 4)]
    r = detect_split_step(hop)
    assert r["split_step"] is True and r["run"] >= 2 and r["max_lift"] >= 0.03
    assert detect_split_step(planted)["split_step"] is False
    one_foot = planted[:3] + [sample(0.12, 770, 800), sample(0.16, 768, 800)] + planted[:3]
    assert detect_split_step(one_foot)["split_step"] is False                         # a stride, not a hop
    single_frame = planted[:3] + [sample(0.12, 775, 775)] + planted[:4]
    assert detect_split_step(single_frame)["split_step"] is False
    r = detect_split_step(hop, moving_mps=4.0)
    assert r["split_step"] is False and "running" in r["why"]
    assert detect_split_step(planted[:3])["split_step"] is None


def test_lift_threshold_scales_with_body_height():
    def hop_px(px, h):
        ys = [800] * 4 + [800 - px, 800 - px] + [800] * 4
        return [sample(i * 0.04, y, y, h=h) for i, y in enumerate(ys)]

    assert detect_split_step(hop_px(3, 80))["split_step"] is True        # 3 px is 3.75% of an 80 px player: the same hop as 11 px of 300
    assert detect_split_step(hop_px(3, 300))["split_step"] is False      # 3 px of 300 px is only 1%: noise


def test_windows_and_summary():
    hits = [{"t": 1.0, "id": "e1"}, {"t": 2.0, "id": "e2"}]
    w = windows_for(hits, fps=25, n_frames=100)
    assert w[0]["f0"] == 15 and w[0]["f1"] == 26 and w[0]["event_id"] == "e1"
    assert len(windows_for([{"t": i * 0.5} for i in range(100)], 25, 5000, limit=10)) == 10
    s = summarise([{"split_step": True}, {"split_step": False}, {"split_step": None}, {"split_step": True}])
    assert s == {"split_step_pct": 0.67, "split_step_n": 3, "split_step_detected": 2}
    assert summarise([{"split_step": None}]) == {}


def test_collect_samples_reads_the_window_and_crops_to_the_player(tmp_path):
    """A fake pose model reads a hop out of pixel values; the code must crop, shift back and time it right."""
    path = tmp_path / "hop.avi"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 25, (320, 240))
    lift = {10: 10, 11: 14, 12: 14, 13: 10}                                           # frames whose ankles are raised
    for f in range(30):
        img = np.full((240, 320, 3), 40, np.uint8)
        img[0:4, 0:4] = (200 if f in lift else 50)                                    # marker the fake model can read
        vw.write(img)
    vw.release()

    def fake_pose(crop):
        raised = crop[0:1, 0:1].mean() > 100 if crop.shape[0] and crop[0:1, 0:1].size else False
        kp = [[0.0, 0.0, 0.0] for _ in range(17)]
        dy = -12.0 if raised else 0.0
        kp[15], kp[16] = [30, 150 + dy, 0.9], [50, 150 + dy, 0.9]
        return [{"bbox": [20, 20, 70, 170], "conf": 0.9, "kp": kp}]

    frames = [{"players": [{"track_id": 2, "bbox": [0, 0, 80, 200]}]} for _ in range(30)]
    wins = [{"t_hit": 0.5, "f0": 6, "f1": 16, "event_id": "e"}]
    got = collect_samples(path, fake_pose, 2, wins, frames, pad=0.0)
    s = got[0]
    assert len(s) == 11 and s[0]["t"] == pytest.approx(6 / 25)
    r = detect_split_step(s)
    assert r["split_step"] is True and r["n"] == 11
    assert collect_samples(path, fake_pose, 9, wins, frames)[0] == []                 # unknown player: nothing to read
