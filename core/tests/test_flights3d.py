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
    assert len(f) == 1 and f[0]["kind"] == "physics" and f[0]["track_id"] == 1
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


def test_unusable_pairs_make_no_flight():
    assert reconstruct([hit(1.0, 1, [3, 3]), hit(1.05, 2, [3, 9])], 25.0, BAD) == []            # too short to time
    assert reconstruct([hit(1.0, 1, [3, 3]), hit(5.0, 2, [3, 9])], 25.0, BAD) == []             # too long
    assert reconstruct([hit(1.0, 1, None), hit(1.8, 2, [3, 9])], 25.0, BAD) == []               # no court position
    assert reconstruct([hit(1.0, 1, [3, 3]), hit(1.8, 1, [3, 9])], 25.0, BAD) == []             # not clearly two different players
    assert reconstruct([hit(1.0, 1, [3, 3])], 25.0, BAD) == []
