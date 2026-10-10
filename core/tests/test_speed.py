"""Shot speed (§4.5): the equations of the flight, and a number only when both ends and the timing support it, always with a band."""

import math

import pytest

from rallyos.analytics import flight
from rallyos.analytics.speed import annotate_speeds, player_speed_stats
from rallyos.sports import load_sport

CFG = load_sport("badminton")
TENNIS = load_sport("tennis")
VT = CFG["projectile"]["terminal_velocity_mps"]


def hit(t, tid, court, audio=False, rally=0):
    return {"rally_idx": rally, "t": t, "type": "hit", "track_id": tid, "court": court,
            "source": ["audio", "vision"] if audio else ["vision"], "speed_kmh": None, "speed_err_pct": None}


def landing(t, court, ellipse=(0.3, 0.1, 0.0), conf=0.8, rally=0, **extra):
    return {"rally_idx": rally, "t": t, "type": "landing", "track_id": None, "court": court, "call": "IN",
            "ellipse_m": list(ellipse), "confidence": conf, **extra}


def time_to_fall(v0, theta_deg, h):
    """Flight time until the shuttle has dropped by h metres, from the full model."""
    lo, hi = 0.05, 2.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if flight.simulate(v0, math.radians(theta_deg), mid, VT, 600)[1] > -h:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# -- the equations -------------------------------------------------------------------------------------------------------

def test_the_drag_law_gives_the_configured_terminal_velocity():
    # a shuttle dropped from rest ends up falling at v_t: the distance fallen per second tends to 6.7 m/s
    z3 = flight.simulate(0.0, -math.pi / 2, 3.0, VT, 900)[1]
    z4 = flight.simulate(0.0, -math.pi / 2, 4.0, VT, 900)[1]
    assert (z3 - z4) == pytest.approx(VT, rel=0.01)


def test_a_flat_shot_loses_speed_exponentially_with_distance():
    # horizontal, no gravity-dominated drop at this speed: v(x) = v0 exp(-k x) with k = g / vt^2, so the flight time over d is
    # (exp(k d) - 1) / (k v0): 10 m at 100 m/s takes 0.2 s * (exp(2.19)-1)/ (2.19) ... compare the integrator to the closed form
    k = flight.G / VT ** 2
    v0, d = 100.0, 6.0
    t_closed = (math.exp(k * d) - 1) / (k * v0)
    x, z = flight.simulate(v0, 0.0, t_closed, VT, 800)
    assert x == pytest.approx(d, rel=0.03)               # gravity bends the path a little, the speed law is the main term


@pytest.mark.parametrize("v0,theta,T", [(40, 10, 0.8), (100, -15, 0.35), (30, 55, 1.6), (70, -5, 0.5), (25, 70, 2.0)])
def test_the_solver_recovers_the_launch_that_made_a_flight(v0, theta, T):
    dx, dz = flight.simulate(v0, math.radians(theta), T, VT, 800)
    got = flight.solve_launch(dx, T, dz, VT)
    assert got is not None and got[0] == pytest.approx(v0, rel=0.02) and math.degrees(got[1]) == pytest.approx(theta, abs=1.0)


def test_no_launch_can_cover_ten_metres_in_less_than_the_record_smash_allows():
    t_min = flight.min_flight_time(10.0, VT, 157.0)       # 565 km/h, the fastest smash ever measured
    assert 0.2 < t_min < 0.26
    assert flight.solve_launch(10.0, 0.15, -1.0, VT) is None
    assert flight.solve_launch(10.0, 0.45, -1.0, VT) is not None


# -- the shuttle: launch speed, not the average ------------------------------------------------------------------------------

def test_launch_speed_is_recovered_from_distance_and_time_and_is_far_above_the_average():
    v0, theta = 80.0, -8.0                                 # a 288 km/h smash, from the height the "unknown" prior assumes
    T = time_to_fall(v0, theta, 1.6)
    d = flight.simulate(v0, math.radians(theta), T, VT, 800)[0]
    ev = [hit(2.0, 1, [3.0, 2.0], audio=True), landing(2.0 + T, [3.0, 2.0 + d], ellipse=(0.1, 0.05, 0.0))]
    s = annotate_speeds(ev, fps=30, cfg=CFG)
    assert ev[0]["speed_kind"] == "launch" and ev[0]["speed_basis"] == "hit-to-landing"
    assert ev[0]["speed_kmh"] == pytest.approx(v0 * 3.6, rel=0.04)
    assert ev[0]["avg_speed_kmh"] == round(d / T * 3.6) and ev[0]["avg_speed_kmh"] < ev[0]["speed_kmh"] / 2   # the old number: 2-4x too low
    assert 5 <= ev[0]["speed_err_pct"] <= 60
    assert s["computed"] == 1 and s["kind"] == "launch" and "air drag" in s["what"]


def test_the_92_kmh_average_of_the_old_card_is_a_much_faster_shot():
    ev = [hit(8.19, 2, [3.0, 11.0], audio=True), hit(8.60, 1, [3.0, 0.5], audio=True)]       # 10.5 m in 0.41 s
    annotate_speeds(ev, fps=30, cfg=CFG)
    assert ev[0]["avg_speed_kmh"] == 92 and 250 <= ev[0]["speed_kmh"] <= 450


def test_a_flight_no_shot_could_make_is_a_measurement_error_not_a_number():
    ev = [hit(1.0, 1, [3.0, 3.0]), hit(1.15, 2, [3.0, 13.0])]                                 # 10 m in 0.15 s: the old average said 240 km/h
    annotate_speeds(ev, 30, CFG)
    assert ev[0]["speed_kmh"] is None and "do not fit a real shot" in ev[0]["speed_why_not"]


def test_video_only_timing_widens_the_band_on_short_flights():
    slow = [hit(1.0, 1, [3.0, 3.0]), hit(1.9, 2, [3.0, 10.0])]
    fast = [hit(1.0, 1, [3.0, 3.0]), hit(1.35, 2, [3.0, 10.0])]
    annotate_speeds(slow, 25, CFG), annotate_speeds(fast, 25, CFG)
    assert fast[0]["speed_kmh"] > slow[0]["speed_kmh"]
    assert fast[0]["speed_err_pct"] > slow[0]["speed_err_pct"]          # one frame is a bigger share of a short flight


def test_sound_timing_narrows_the_band():
    video = [hit(1.0, 1, [3.0, 3.0]), hit(1.4, 2, [3.0, 11.0])]
    audio = [hit(1.0, 1, [3.0, 3.0], audio=True), hit(1.4, 2, [3.0, 11.0], audio=True)]
    annotate_speeds(video, 25, CFG), annotate_speeds(audio, 25, CFG)
    assert audio[0]["speed_kmh"] == video[0]["speed_kmh"] and audio[0]["speed_err_pct"] < video[0]["speed_err_pct"]


def test_hit_to_landing_uses_the_landing_ellipse():
    loose = [hit(2.0, 1, [3.0, 2.0], audio=True), landing(2.6, [3.0, 12.0], ellipse=(1.2, 0.3, 0.0))]
    tight = [hit(2.0, 1, [3.0, 2.0], audio=True), landing(2.6, [3.0, 12.0], ellipse=(0.1, 0.05, 0.0))]
    annotate_speeds(loose, 25, CFG), annotate_speeds(tight, 25, CFG)
    assert tight[0]["speed_err_pct"] < loose[0]["speed_err_pct"]


def test_an_overhead_contact_is_higher_than_a_low_one_and_changes_the_answer():
    def frames(wrist_y):                                   # eyes at y = 200: a wrist above them is an overhead contact
        kp = [[0.0, 0.0, 0.0] for _ in range(17)]
        kp[1], kp[2] = [95, 200.0, 0.9], [105, 200.0, 0.9]
        kp[9], kp[10] = [90, wrist_y, 0.9], [110, wrist_y + 40, 0.9]
        return [{"players": [{"track_id": 1, "kp": kp}]} for _ in range(100)]

    def run(fr):
        ev = [hit(1.0, 1, [3.0, 3.0], audio=True), landing(1.6, [3.0, 12.0], ellipse=(0.1, 0.05, 0.0))]
        annotate_speeds(ev, 25, CFG, fr)
        return ev[0]["speed_kmh"], ev[0]["launch_angle_deg"]

    (v_hi, a_hi), (v_lo, a_lo) = run(frames(150.0)), run(frames(400.0))
    assert a_hi < a_lo                                      # from higher up the same flight needs a flatter launch
    assert v_hi != v_lo


# -- ball sports keep the average, said as such ----------------------------------------------------------------------------

def test_ball_sports_report_the_average_horizontal_speed():
    ev = [hit(1.0, 1, [3.0, 3.0], audio=True), hit(1.5, 2, [3.0, 11.0], audio=True)]
    s = annotate_speeds(ev, fps=25, cfg=TENNIS)
    assert ev[0]["speed_kind"] == "average" and ev[0]["speed_kmh"] == round(8 / 0.5 * 3.6) == 58 and s["kind"] == "average"
    assert "lower bound" in s["what"]


# -- when there is no number -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,events,why", [
    ("same player twice", [hit(1.0, 1, [3, 3]), hit(1.5, 1, [3, 11])], "the two hits are not clearly by different players"),
    ("unknown hitter", [hit(1.0, None, [3, 3]), hit(1.5, 2, [3, 11])], "the two hits are not clearly by different players"),
    ("no court position", [hit(1.0, 1, None), hit(1.5, 2, [3, 11])], "hitter's court position unknown (needs calibration)"),
    ("landing with no call (lost at the net)", [hit(1.0, 1, [3, 3]), {**landing(1.5, None), "court": [3, 5.0], "note": "lost at net"}],
     "landing not reliable enough"),
    ("weak landing", [hit(1.0, 1, [3, 3]), landing(1.5, [3, 11], conf=0.3)], "landing not reliable enough"),
    ("too short to time", [hit(1.0, 1, [3, 3]), hit(1.08, 2, [3, 9])], "flight too short to time"),
    ("barely moved", [hit(1.0, 1, [3, 3]), hit(1.4, 2, [3, 3.5])], "flight too short to time"),
    ("too long to time", [hit(1.0, 1, [3, 3]), hit(4.0, 2, [3, 11])], "flight too long to time"),
])
def test_no_number_when_the_evidence_is_missing(name, events, why):
    annotate_speeds(events, 25, CFG)
    assert events[0]["speed_kmh"] is None and events[0]["speed_why_not"] == why, name


def test_the_last_hit_of_a_rally_has_no_next_contact():
    ev = [hit(1.0, 1, [3, 3], audio=True), hit(1.6, 2, [3, 11], audio=True)]
    annotate_speeds(ev, 25, CFG)
    assert ev[1]["speed_kmh"] is None and ev[1]["speed_why_not"] == "no landing or next hit"


# -- per player: the fastest is picked among shots we can trust ------------------------------------------------------------------

def test_the_fastest_shot_ignores_shots_whose_band_is_too_wide():
    ev = [{"type": "hit", "track_id": 1, "t": 1.0, "speed_kmh": 380, "speed_err_pct": 55},
          {"type": "hit", "track_id": 1, "t": 2.0, "speed_kmh": 250, "speed_err_pct": 25},
          {"type": "hit", "track_id": 1, "t": 3.0, "speed_kmh": 120, "speed_err_pct": 20},
          {"type": "hit", "track_id": 2, "t": 4.0, "speed_kmh": 300, "speed_err_pct": 60}]
    st = player_speed_stats(ev)
    assert st[1] == {"shots_with_speed": 3, "avg_shot_kmh": 250, "fastest_shot_kmh": 250, "fastest_shot_err_pct": 25, "fastest_shot_t": 2.0}
    assert st[2] == {"shots_with_speed": 1, "avg_shot_kmh": 300}          # no shot reliable enough: no "fastest"
