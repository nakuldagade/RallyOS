"""Rule-based shot types (§4.6): every label is explained, and a rule that cannot be checked never fires."""

import pytest

from rallyos.analytics.shots import apex_estimate_m, classify_shots, shot_mix, wrist_above_head, zone_by_net_distance
from rallyos.sports import load_sport

CFG = load_sport("badminton")
NET = 6.7


def hit(t, tid, y, rally=0, conf=0.9, speed=None):
    return {"rally_idx": rally, "t": t, "type": "hit", "track_id": tid, "court": [3.0, y], "confidence": conf,
            "source": ["audio", "vision"], "speed_kmh": speed}


def landing(t, y, rally=0):
    return {"rally_idx": rally, "t": t, "type": "landing", "track_id": None, "court": [3.0, y], "call": "IN",
            "confidence": 0.8, "ellipse_m": [0.2, 0.1, 0.0]}


def kp(wrist_y, eye_y=200.0):
    k = [[0.0, 0.0, 0.0] for _ in range(17)]
    k[0] = [100, eye_y + 10, 0.9]
    k[1], k[2] = [95, eye_y, 0.9], [105, eye_y, 0.9]
    k[9], k[10] = [90, wrist_y, 0.9], [110, wrist_y + 50, 0.9]
    return k


def frames(n, tid=1, wrist_y=150.0):
    return [{"players": [{"track_id": tid, "kp": kp(wrist_y)}]} for _ in range(n)]


def test_zones_by_distance_from_the_net_on_either_side():
    assert zone_by_net_distance(NET - 1.0, CFG) == "front" and zone_by_net_distance(NET + 1.0, CFG) == "front"
    assert zone_by_net_distance(NET - 3.0, CFG) == "mid" and zone_by_net_distance(NET + 6.0, CFG) == "rear"
    assert zone_by_net_distance(NET - 6.6, CFG) == "rear"
    assert zone_by_net_distance(NET + 7.4, CFG) == "rear"                       # behind the baseline is still the rear court
    assert zone_by_net_distance(3.0, load_sport("squash")) is None              # zones not measured from a net


def test_apex_proxy_grows_with_flight_time():
    assert apex_estimate_m(0.5) == pytest.approx(0.31, abs=0.01) and apex_estimate_m(1.8) == pytest.approx(3.97, abs=0.05)


def test_wrist_above_head_from_pose_and_unknown_without_it():
    assert wrist_above_head(frames(10, wrist_y=150), 5, 1) is True        # wrist higher (smaller y) than the eyes
    assert wrist_above_head(frames(10, wrist_y=300), 5, 1) is False
    assert wrist_above_head(frames(10), 5, 2) is None                      # that player has no pose
    assert wrist_above_head([{"players": []}] * 10, 5, 1) is None


def test_badminton_shots_from_zones_flight_and_wrist():
    fr = frames(400, 1, wrist_y=300) + []
    smash_fr = frames(400, 1, wrist_y=150)
    cases = [
        ("serve", [hit(1.0, 1, 2.0), hit(1.9, 2, 11.0)], fr),                                   # first hit of the rally
        ("smash", [hit(0.5, 2, 9.0), hit(5.0, 1, 3.0), landing(5.5, 11.5)], smash_fr),         # wrist up, 0.5 s flight
        ("clear", [hit(0.5, 2, 9.0), hit(5.0, 1, 1.5), hit(6.8, 2, 13.0)], fr),                # rear -> rear, 1.8 s
        ("drop", [hit(0.5, 2, 9.0), hit(5.0, 1, 1.5), landing(6.0, 7.6)], fr),                 # rear -> front, 1.0 s
        ("net", [hit(0.5, 2, 9.0), hit(5.0, 1, 5.5), landing(5.9, 7.6)], fr),                  # front -> front
        ("lift", [hit(0.5, 2, 9.0), hit(5.0, 1, 5.5), landing(6.2, 13.0)], fr),                # front -> rear, 1.2 s
        ("drive", [hit(0.5, 2, 9.0), hit(5.0, 1, 3.0), hit(5.45, 2, 9.0)], fr),                # mid -> mid, 0.45 s
    ]
    for want, evs, fr_ in cases:
        classify_shots(evs, fr_, fps=25, cfg=CFG)
        shot_hit = evs[0] if want == "serve" else evs[1]
        assert shot_hit["shot"] == want, (want, shot_hit.get("shot"), shot_hit["shot_why"])
        assert shot_hit["shot_why"].lower().startswith(want) and 0 < shot_hit["shot_conf"] <= 0.9


def test_labels_are_honest_about_proxies_and_missing_evidence():
    evs = [hit(0.5, 2, 9.0), hit(5.0, 1, 1.5), hit(6.8, 2, 13.0)]
    classify_shots(evs, frames(400, 1, 300), 25, CFG)
    clear, serve = evs[1], evs[0]
    assert "estimated apex" in clear["shot_why"] and "from the flight time" in clear["shot_why"]
    assert clear["shot_conf"] < serve["shot_conf"]                                   # a proxy lowers the confidence
    smash = [hit(0.5, 2, 9.0), hit(5.0, 1, 3.0), landing(5.5, 11.5)]
    classify_shots(smash, frames(400, 1, 150), 25, CFG)
    assert smash[1]["shot"] == "smash" and smash[1]["shot_unchecked"] == ["descent_deg_min"]
    nopose = [hit(0.5, 2, 9.0), hit(5.0, 1, 3.0), landing(5.5, 11.5)]
    classify_shots(nopose, [{"players": []}] * 400, 25, CFG)
    assert nopose[1]["shot"] != "smash"                                              # no pose: never assumed
    last = [hit(0.5, 2, 9.0), hit(5.0, 1, 3.0)]
    classify_shots(last, frames(400, 1, 300), 25, CFG)
    assert last[1]["shot"] is None and last[1]["shot_why"] == "no landing or next contact to measure the flight"


def test_rules_that_need_bounces_or_walls_never_fire():
    tennis = load_sport("tennis")
    evs = [hit(0.5, 2, 20.0), hit(3.0, 1, 5.0), landing(4.5, 18.0)]
    summary = classify_shots(evs, frames(400, 1, 300), 25, tennis)
    assert evs[0]["shot"] == "serve"
    assert evs[1]["shot"] not in ("volley", "groundstroke")                          # needs bounce detection
    assert "no_bounce_before_hit" in summary["rules_that_need_bounce_or_wall_data"]
    padel = load_sport("padel")
    p = [hit(0.5, 2, 15.0), hit(3.0, 1, 4.0)]
    classify_shots(p, frames(400, 1, 300), 25, padel)
    assert p[0]["shot"] == "serve"                                                    # underarm is a soft condition


def test_shot_mix_counts_per_player_and_other_sports_use_their_own_zones():
    evs = [hit(0.5, 1, 2.0, rally=0), hit(2.4, 2, 11.5, rally=0), hit(9.0, 1, 2.0, rally=1), hit(10.9, 2, 11.5, rally=1)]
    s = classify_shots(evs, frames(600, 1, 300), 25, CFG)
    assert shot_mix(evs, 1) == {"serve": 2} and shot_mix(evs, 2) == {} and s["labelled"] == 2
    pb = load_sport("pickleball")
    dink = [hit(0.5, 1, 2.5), hit(1.0, 2, 8.8, speed=None)]
    dink[0]["rally_idx"] = dink[1]["rally_idx"] = 3
    classify_shots(dink, frames(100, 1, 300), 25, pb)
    assert dink[0]["shot"] == "serve"


def test_a_hit_with_a_negative_confidence_does_not_crash_the_classifier():
    # found by a real browser run: an old bridging formula could give a confidence below 0, and `** 0.5` made it complex
    ev = [hit(1.0, 1, 2.0, conf=-0.77), hit(1.6, 2, 11.0), landing(2.4, 3.0)]
    classify_shots(ev, frames(100), 25.0, CFG)
    assert all(e.get("shot_conf") is None or isinstance(e["shot_conf"], float) for e in ev)
