"""Event-timing speed (§4.5): a number only when both ends and the timing support it, always with an error band."""

import math

import pytest

from rallyos.analytics.speed import annotate_speeds, player_speed_stats
from rallyos.sports import load_sport

CFG = load_sport("badminton")


def hit(t, tid, court, audio=False, rally=0):
    return {"rally_idx": rally, "t": t, "type": "hit", "track_id": tid, "court": court,
            "source": ["audio", "vision"] if audio else ["vision"], "speed_kmh": None, "speed_err_pct": None}


def landing(t, court, ellipse=(0.3, 0.1, 0.0), conf=0.8, rally=0, **extra):
    return {"rally_idx": rally, "t": t, "type": "landing", "track_id": None, "court": court, "call": "IN",
            "ellipse_m": list(ellipse), "confidence": conf, **extra}


def test_hit_to_hit_speed_with_audio_timing():
    ev = [hit(1.0, 1, [3.0, 3.0], audio=True), hit(1.5, 2, [3.0, 11.0], audio=True)]
    s = annotate_speeds(ev, fps=25, cfg=CFG)
    assert ev[0]["speed_kmh"] == round(8 / 0.5 * 3.6) == 58 and ev[0]["speed_basis"] == "hit-to-hit"
    # error: positions 0.7 m each end (0.99 m over 8 m = 12%), timing 5.7 ms over 0.5 s (1%)
    assert ev[0]["speed_err_pct"] == round(100 * math.hypot(math.hypot(0.7, 0.7) / 8, 0.0057 / 0.5))
    assert ev[1]["speed_kmh"] is None and ev[1]["speed_why_not"] == "no landing or next hit"
    assert s["computed"] == 1 and s["skipped"] == 1 and "lower bound" in s["what"]


def test_video_only_timing_widens_the_band_on_short_flights():
    slow = [hit(1.0, 1, [3.0, 3.0]), hit(1.6, 2, [3.0, 10.0])]
    fast = [hit(1.0, 1, [3.0, 3.0]), hit(1.2, 2, [3.0, 10.0])]
    annotate_speeds(slow, 25, CFG), annotate_speeds(fast, 25, CFG)
    assert fast[0]["speed_kmh"] == 126 and slow[0]["speed_kmh"] == 42
    assert fast[0]["speed_err_pct"] > slow[0]["speed_err_pct"]          # one frame is 20% of a 0.2 s flight


def test_hit_to_landing_uses_the_landing_ellipse():
    ev = [hit(2.0, 1, [3.0, 2.0], audio=True), landing(2.6, [3.0, 12.0], ellipse=(1.2, 0.3, 0.0))]
    annotate_speeds(ev, 25, CFG)
    assert ev[0]["speed_basis"] == "hit-to-landing" and ev[0]["speed_kmh"] == 60
    tight = [hit(2.0, 1, [3.0, 2.0], audio=True), landing(2.6, [3.0, 12.0], ellipse=(0.1, 0.05, 0.0))]
    annotate_speeds(tight, 25, CFG)
    assert tight[0]["speed_err_pct"] < ev[0]["speed_err_pct"]


@pytest.mark.parametrize("name,events,why", [
    ("same player twice", [hit(1.0, 1, [3, 3]), hit(1.5, 1, [3, 11])], "the two hits are not clearly by different players"),
    ("unknown hitter", [hit(1.0, None, [3, 3]), hit(1.5, 2, [3, 11])], "the two hits are not clearly by different players"),
    ("no court position", [hit(1.0, 1, None), hit(1.5, 2, [3, 11])], "hitter's court position unknown (needs calibration)"),
    ("landing with no call (lost at the net)", [hit(1.0, 1, [3, 3]), {**landing(1.5, None), "court": [3, 5.0], "note": "lost at net"}],
     "landing not reliable enough"),
    ("weak landing", [hit(1.0, 1, [3, 3]), landing(1.5, [3, 11], conf=0.3)], "landing not reliable enough"),
    ("too short to time", [hit(1.0, 1, [3, 3]), hit(1.08, 2, [3, 9])], "flight too short to time"),
    ("barely moved", [hit(1.0, 1, [3, 3]), hit(1.4, 2, [3, 3.5])], "flight too short to time"),
    ("impossibly fast", [hit(1.0, 1, [3, -3], audio=True), hit(1.13, 2, [3, 13], audio=True)], "outside the plausible speed range"),
])
def test_no_number_when_the_evidence_is_missing(name, events, why):
    annotate_speeds(events, 25, CFG)
    assert events[0]["speed_kmh"] is None and events[0]["speed_why_not"] == why, name


def test_rallies_are_separate_and_player_stats_summarise():
    ev = [hit(1.0, 1, [3, 3], audio=True, rally=0), hit(1.5, 2, [3, 11], audio=True, rally=0),
          hit(9.0, 2, [3, 11], audio=True, rally=1), hit(9.4, 1, [3, 3], audio=True, rally=1)]
    annotate_speeds(ev, 25, CFG)
    assert [e["speed_kmh"] for e in ev] == [58, None, 72, None]          # the last hit of a rally has no next contact
    st = player_speed_stats(ev)
    assert st == {1: {"shots_with_speed": 1, "avg_shot_kmh": 58, "fastest_shot_kmh": 58},
                  2: {"shots_with_speed": 1, "avg_shot_kmh": 72, "fastest_shot_kmh": 72}}
