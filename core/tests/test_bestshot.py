"""Best shot: the outcome sets the band, the technique only places a shot inside it (analytics/bestshot.py)."""

import pytest

from rallyos.analytics.bestshot import BANDS, rate_shots
from rallyos.sports import load_sport

CFG = load_sport("badminton")
NET = 6.7


def hit(t, tid, y, x=3.05, rally=0, shot="drive", speed=None, err=20, returned=True, overhead=None, conf=0.9):
    e = {"rally_idx": rally, "t": t, "type": "hit", "track_id": tid, "court": [x, y], "confidence": conf, "shot": shot,
         "speed_kmh": speed, "speed_err_pct": err if speed else None, "returned_to_base": returned, "source": ["audio", "vision"]}
    if overhead is not None:
        e["shot_features"] = {"wrist_above_head": overhead}
    return e


def landing(t, x, y, rally=0, call="IN"):
    return {"rally_idx": rally, "t": t, "type": "landing", "track_id": None, "court": [x, y], "call": call, "confidence": 0.8}


def frames_with(opp_court, n=300):
    return [{"players": [{"track_id": 1, "court": [3.0, 3.0]}, {"track_id": 2, "court": list(opp_court)}]} for _ in range(n)]


def rally(idx, winner, reason, conf=0.8):
    return {"idx": idx, "winner_track_id": winner, "end_reason": reason, "winner_confidence": conf}


def run(events, rallies, opp=(3.0, 11.0)):
    per_player = {"1": {}, "2": {}}
    summary = rate_shots(events, rallies, frames_with(opp), 25.0, CFG, per_player)
    return summary, per_player


def test_a_rear_court_shot_that_won_beats_a_smash_that_hit_the_net_whatever_the_speed():
    # rally 0: player 1's plain clear from the back wins the point. rally 1: player 1's 380 km/h smash hits the net.
    ev = [hit(1.0, 2, 11.0, rally=0), hit(1.6, 1, 1.0, rally=0, shot="clear", speed=60, overhead=False), landing(2.5, 3.0, 12.9, rally=0),
          hit(10.0, 2, 11.0, rally=1), hit(10.5, 1, 6.0, rally=1, shot="smash", speed=380, err=15, overhead=True)]
    rl = [rally(0, 1, "landing_in"), rally(1, 2, "net_fault")]
    _, pp = run(ev, rl)
    clear = next(e for e in ev if e["t"] == 1.6)["shot_rating"]
    smash = next(e for e in ev if e["t"] == 10.5)["shot_rating"]
    assert clear["outcome"] == "winner" and smash["outcome"] == "error"
    assert clear["score"] > smash["score"]
    assert smash["score"] <= BANDS["error"][1] < BANDS["winner"][0] <= clear["score"]
    assert pp["1"]["best_shot"]["shot"] == "clear" and pp["1"]["best_shot"]["t"] == 1.6


def test_technique_moves_a_shot_only_inside_its_band():
    ev = []
    for k, (y, opp_y) in enumerate([(12.9, 3.0), (9.0, 9.0)]):                 # a tight, far-from-the-opponent shot and a loose one
        base = 100 * k
        ev += [hit(base + 1.0, 2, 11.0, rally=k), hit(base + 1.6, 1, 1.0, rally=k, shot="clear"), landing(base + 2.5, 3.05, y, rally=k)]
    rl = [rally(0, 1, "landing_in"), rally(1, 1, "landing_in")]
    frames = [{"players": [{"track_id": 1, "court": [3.0, 3.0]}, {"track_id": 2, "court": [3.0, 3.0]}]} for _ in range(3000)]
    rate_shots(ev, rl, frames, 25.0, CFG, None)
    good, loose = (next(e for e in ev if e["t"] == 1.6)["shot_rating"], next(e for e in ev if e["t"] == 101.6)["shot_rating"])
    assert good["outcome"] == loose["outcome"] == "winner"
    assert 80 <= loose["score"] < good["score"] <= 100 and good["technique"] > loose["technique"]


def test_a_shot_that_forced_the_opponents_error_ranks_between_a_winner_and_a_rally_shot():
    ev = [hit(1.0, 1, 1.0, shot="lift"), hit(1.7, 2, 11.0, shot="drive"), landing(2.4, 3.0, 5.0)]
    rl = [rally(0, 1, "landing_out")]                     # player 2's reply went out: player 1 wins
    # make the landing out on player 2's own side so the winner is player 1
    ev[2]["call"] = "OUT"
    rate_shots(ev, rl, frames_with((3.0, 11.0)), 25.0, CFG, None)
    forced, error = ev[0]["shot_rating"], ev[1]["shot_rating"]
    assert forced["outcome"] == "forced_error" and error["outcome"] == "error"
    assert BANDS["forced_error"][0] <= forced["score"] <= BANDS["forced_error"][1]


def test_when_the_rally_end_is_not_seen_no_shot_is_called_a_winner_or_an_error():
    ev = [hit(1.0, 1, 1.0), hit(1.6, 2, 11.0), hit(2.2, 1, 1.0)]
    for end in ("shuttle_lost", "clip_ended", "too_close", "landing_hidden_by_net"):
        rl = [rally(0, None, end)]
        for e in ev:
            e.pop("shot_rating", None)
        s, pp = run(ev, rl)
        assert {e["shot_rating"]["outcome"] for e in ev} <= {"kept_going", "unknown"} and s["with_known_outcome"] == 0, end
    assert "technique only" in pp["1"]["best_shot"]["basis"]


def test_too_little_measured_gives_no_technique_and_says_so():
    ev = [hit(1.0, 1, 1.0, returned=None), hit(1.6, 2, 11.0, returned=None)]
    ev[0]["court"], ev[1]["court"] = [3.0, 1.0], None
    rate_shots(ev, [rally(0, None, "shuttle_lost")], [], 25.0, CFG, None)
    r = ev[0]["shot_rating"]
    assert r["technique"] is None and "too little measured" in r["why"] and r["score"] == pytest.approx(50.0)   # the middle of the "kept going" band


def test_power_is_a_rank_not_a_threshold_and_needs_a_trustworthy_speed():
    ev = []
    for k, (spd, err) in enumerate([(100, 20), (150, 20), (200, 20), (250, 20), (400, 70)]):
        ev += [hit(100 * k + 1.0, 1, 1.0, rally=k, speed=spd, err=err), hit(100 * k + 1.6, 2, 11.0, rally=k)]
    rl = [rally(k, None, "shuttle_lost") for k in range(5)]
    rate_shots(ev, rl, frames_with((3.0, 11.0), 600 * 25), 25.0, CFG, None)
    power = {e["speed_kmh"]: e["shot_rating"]["parts"].get("power") for e in ev if e.get("speed_kmh")}
    assert power[250] == 1.0 and power[100] == 0.25 and power[400] is None            # the +-70% reading earns no power credit


def test_every_player_gets_a_best_shot_card_with_a_reason_and_a_clip_time():
    ev = [hit(1.0, 2, 11.0), hit(1.6, 1, 1.0, shot="clear"), landing(2.5, 3.0, 12.9)]
    _, pp = run(ev, [rally(0, 1, "landing_in")])
    b = pp["1"]["best_shot"]
    assert b["t"] == 1.6 and b["outcome"] == "winner" and b["why"].startswith("Clear that won the point") and "basis" in b
    assert len(pp["1"]["best_shots"]) <= 3
