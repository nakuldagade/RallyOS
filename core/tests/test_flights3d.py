"""3D shot paths for the court viewer: reconstructed between two measured ends, never below the floor, honest about their kind."""
import math

import pytest

from rallyos.analytics import flight
from rallyos.analytics.flights3d import reconstruct
from rallyos.sports import load_sport

BAD, TEN = load_sport("badminton"), load_sport("tennis")
VT = BAD["projectile"]["terminal_velocity_mps"]


def hit(t, tid, court, rally=0):
    return {"rally_idx": rally, "t": t, "type": "hit", "track_id": tid, "court": court, "source": ["audio"]}


def landing(t, court, rally=0):
    return {"rally_idx": rally, "t": t, "type": "landing", "track_id": None, "court": court, "call": "IN", "confidence": 0.9, "ellipse_m": [0.1, 0.05, 0]}


def test_the_path_function_matches_the_integrator_and_ends_exactly_at_T():
    path = flight.trajectory(60.0, math.radians(-8), 0.4, VT, dt=1 / 60)
    assert path[0] == (0.0, 0.0, 0.0) and path[-1][0] == pytest.approx(0.4)
    x, z = flight.simulate(60.0, math.radians(-8), 0.4, VT, 800)
    assert path[-1][1] == pytest.approx(x, rel=0.01) and path[-1][2] == pytest.approx(z, abs=0.02)
    assert [p[0] for p in path] == sorted(p[0] for p in path)


def test_a_shuttle_flight_is_a_physics_path_from_one_end_to_the_other_above_the_floor():
    ev = [hit(1.0, 1, [3.0, 3.0]), hit(1.8, 2, [3.0, 11.0])]
    f = reconstruct(ev, 25.0, BAD)
    assert len(f) == 2 and f[0]["kind"] == "physics" and f[0]["track_id"] == 1 and f[0]["placement"] == "measured"    # the last hit gets a path too (open end)
    assert f[1]["open_end"] is True and f[1]["kind"] == "estimate"
    s = f[0]["samples"]
    assert s[0][:3] == [1.0, 3.0, 3.0] and s[-1][:3] == [1.8, 3.0, 11.0]
    assert all(p[3] >= 0 for p in s) and f[0]["peak_z"] > 1.2
    assert [p[2] for p in s] == sorted(p[2] for p in s)                       # it moves steadily away from the hitter along the line
    # the shuttle slows down: the first quarter of the flight covers more ground than the last quarter
    n = len(s)
    assert s[n // 4][2] - s[0][2] > s[-1][2] - s[3 * n // 4][2]


def test_a_landing_ends_on_the_floor():
    f = reconstruct([hit(1.0, 1, [3.0, 3.0]), landing(1.9, [3.0, 12.0])], 25.0, BAD)[0]
    assert f["samples"][-1][3] == pytest.approx(0.0, abs=0.01) and f["to"][:2] == [3.0, 12.0]


def test_a_flight_nothing_could_fly_is_an_estimate_not_a_physics_path():
    f = reconstruct([hit(1.0, 1, [3.0, 3.0]), hit(1.15, 2, [3.0, 13.0])], 25.0, BAD)[0]      # 10 m in 0.15 s: faster than any smash
    assert f["kind"] == "estimate" and f["speed_kmh"] is None


def test_a_tennis_ball_bounces_between_two_contacts_and_a_landing_is_one_arc():
    f = reconstruct([hit(1.0, 1, [4.0, 2.0]), hit(2.0, 2, [4.0, 20.0])], 25.0, TEN)[0]
    assert f["kind"] == "estimate"
    zs = [p[3] for p in f["samples"]]
    bounce = zs.index(min(zs[3:-3]))
    assert min(zs[3:-3]) < 0.1 and 0.3 * len(zs) < bounce < 0.8 * len(zs)                 # one bounce in the middle of the flight
    ys = [p[2] for p in f["samples"]]
    assert ys == sorted(ys) and f["samples"][-1][1:3] == [4.0, 20.0]
    one = reconstruct([hit(1.0, 1, [4.0, 2.0]), landing(1.9, [4.0, 18.0])], 25.0, TEN)[0]
    assert one["samples"][-1][3] == pytest.approx(0.0, abs=0.01) and min(p[3] for p in one["samples"][3:-1]) > 0.0


def test_every_hit_gets_a_path_even_when_the_data_is_poor():
    short = reconstruct([hit(1.0, 1, [3, 3]), hit(1.05, 2, [3, 9])], 25.0, BAD)                 # too short to time: drawn as the shortest flight
    assert len(short) == 2 and short[0]["t1"] - short[0]["t0"] == pytest.approx(0.12)
    long = reconstruct([hit(1.0, 1, [3, 3]), hit(5.0, 2, [3, 9])], 25.0, BAD)                   # a missed hit in between: a 2.4 s flight, flagged
    assert len(long) == 2 and long[0]["gap"] is True and long[0]["t1"] - long[0]["t0"] == pytest.approx(2.4) and long[0]["kind"] == "estimate"
    nopos = reconstruct([hit(1.0, 1, None), hit(1.8, 2, [3, 9])], 25.0, BAD)                    # no court position and no tracks: the side's base
    assert len(nopos) == 2 and nopos[0]["placement"] == "base" and nopos[0]["kind"] == "estimate"
    same = reconstruct([hit(1.0, 1, [3, 3]), hit(1.8, 1, [3, 9])], 25.0, BAD)                   # same player twice and no tracks: the other player's base
    assert len(same) == 2 and same[0]["receiver_inferred"] is True and same[0]["placement"] == "base"
    one = reconstruct([hit(1.0, 1, [3, 3])], 25.0, BAD)
    assert len(one) == 1 and one[0]["open_end"] is True and one[0]["t1"] - one[0]["t0"] == pytest.approx(0.8)


def test_a_hit_nobody_was_credited_with_goes_to_the_player_who_did_not_hit_before_it():
    ev = [hit(1.0, 1, [3.0, 3.0]), hit(1.8, None, [3.0, 11.0]), hit(2.6, None, None)]
    f = reconstruct(ev, 25.0, BAD, frames_with((3.0, 3.0), (3.0, 11.0)))
    assert [x["track_id"] for x in f] == [1, 2, 1] and f[1]["hitter_inferred"] is True and f[0]["hitter_inferred"] is False


def test_a_player_not_tracked_at_that_frame_is_placed_from_the_nearest_tracked_moment():
    frames = frames_with((3.0, 3.0), (3.0, 11.0), n=120)
    for fr in frames[40:60]:                                                         # player 2 is lost for 0.8 s around the second hit (t = 1.8 s)
        fr["players"] = [q for q in fr["players"] if q["track_id"] != 2]
    f = reconstruct([hit(1.0, 1, [3.0, 3.0]), hit(1.8, None, None)], 25.0, BAD, frames)
    assert f[0]["placement"] == "nearest" and f[0]["kind"] == "estimate" and f[0]["to"][:2] == [3.0, 11.0]


def test_a_physics_path_needs_both_ends_measured():
    ev = [hit(1.0, 1, [3.0, 3.0]), hit(1.8, 2, [3.0, 11.0])]
    assert reconstruct(ev, 25.0, BAD)[0]["kind"] == "physics"
    assert reconstruct([hit(1.0, 1, None), ev[1]], 25.0, BAD)[0]["kind"] == "estimate"


def test_whatever_the_video_gives_every_hit_gets_one_finite_bounded_path():
    """Random events with random holes (no court, no hitter, no tracks, odd gaps, same-time events): never a crash, never a missing hit."""
    import random

    rng = random.Random(7)
    for sport in ("badminton", "tennis", "table_tennis", "pickleball", "padel", "squash"):
        cfg = load_sport(sport)
        L, W = cfg["court"]["length"], cfg["court"]["width"]
        for trial in range(25):
            t, events = 0.0, []
            for k in range(rng.randint(1, 14)):
                t += rng.choice([0.0, 0.05, 0.4, 0.9, 1.6, 3.0, 8.0])
                kind = "landing" if rng.random() < 0.12 else "hit"
                tid = rng.choice([1, 2, None])
                court = None if rng.random() < 0.3 else [rng.uniform(-1, W + 1), rng.uniform(-1, L + 1)]
                ev = {"rally_idx": rng.choice([0, 0, 1]), "t": t, "type": kind, "track_id": tid, "court": court}
                if kind == "landing":
                    ev.update(call=rng.choice(["IN", "OUT"]), confidence=rng.random())
                    if rng.random() < 0.3:
                        ev["note"] = "projected outside"
                events.append(ev)
            frames = None if rng.random() < 0.3 else [{"players": [p for p in ({"track_id": 1, "court": [W / 2, 1.0]}, {"track_id": 2, "court": [W / 2, L - 1.0]}) if rng.random() < 0.6]}
                                                      for _ in range(int(t * 25) + 30)]
            flights = reconstruct(events, 25.0, cfg, frames)
            hits = [e for e in events if e["type"] == "hit"]
            assert len(flights) == len(hits), (sport, trial)
            for f in flights:
                assert f["t1"] > f["t0"] and f["track_id"] in (1, 2) and f["placement"] in ("measured", "nearest", "base")
                assert all(math.isfinite(v) for sm in f["samples"] for v in sm) and all(sm[3] >= 0 for sm in f["samples"])
                assert f["peak_z"] < 40 and all(abs(v) < 80 for sm in f["samples"] for v in sm[1:3])


def frames_with(pos1, pos2, n=200):
    return [{"players": [{"track_id": 1, "court": list(pos1)}, {"track_id": 2, "court": list(pos2)}]} for _ in range(n)]


def test_a_hit_attributed_to_the_same_player_twice_still_crosses_to_the_other_player():
    ev = [hit(1.0, 1, [3.0, 3.0]), hit(1.8, 1, [3.0, 3.0])]            # the opponent's hit was missed: both say player 1
    f = reconstruct(ev, 25.0, BAD, frames_with((3.0, 3.0), (2.0, 11.0)))
    assert len(f) == 2 and f[0]["track_id"] == 1 and f[0]["receiver_inferred"] is True
    assert f[0]["samples"][-1][1:3] == [2.0, 11.0]                     # it ends where the OTHER player was standing, not on the hitter
    assert all(x["placement"] == "base" for x in reconstruct(ev, 25.0, BAD))               # without tracked positions the side's base stands in, flagged


def test_a_hit_without_a_court_position_uses_the_tracked_position_of_its_hitter():
    ev = [{**hit(1.0, 1, None)}, hit(1.8, 2, [3.0, 11.0])]
    f = reconstruct(ev, 25.0, BAD, frames_with((3.0, 3.0), (3.0, 11.0)))
    assert len(f) == 2 and f[0]["samples"][0][1:3] == [3.0, 3.0] and f[0]["receiver_inferred"] is False
    nobody = reconstruct([hit(1.0, None, None), hit(1.8, 2, [3.0, 11.0])], 25.0, BAD, frames_with((3, 3), (3, 11)))
    assert len(nobody) == 2 and nobody[0]["track_id"] == 1 and nobody[0]["hitter_inferred"] is True and nobody[0]["samples"][0][1:3] == [3.0, 3.0]    # given to the side by elimination
