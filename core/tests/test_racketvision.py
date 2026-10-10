"""RacketVision plug-in: CSV parsing (frame offset), gap filling, trajectory hits, match.json output."""

import json
import math
from pathlib import Path

import pytest

from rallyos.events.hits import trajectory_hits
from rallyos.export import ball_only_match
from rallyos.track.kalman import fill_short_gaps
from rallyos.track.plugins import racketvision as rv

REAL_CSV = Path(__file__).resolve().parents[2] / "demo" / "racketvision" / "extracted" / "balltrack_badminton_test_predictions.csv"


def ball(x, y, conf=0.9, interp=False):
    return {"px": [float(x), float(y)], "court": None, "conf": conf, "interp": interp}


def test_per_video_csv_applies_frame_offset(tmp_path):
    p = tmp_path / "results.csv"
    p.write_text("Frame,X,Y,Visibility,Confidence\n0,0,0,0,0.0\n1,0,0,0,0.0\n2,100,200,1,0.8\n3,110,190,1,0.7\n")
    balls = rv.read_predictions(p)["clip"]
    assert len(balls) == 3                         # Frame 0 -> video_frame -1 is dropped
    assert balls[0] is None and balls[1]["px"] == [100.0, 200.0] and balls[2]["conf"] == 0.7


def test_combined_csv_uses_video_frame_and_splits_clips(tmp_path):
    p = tmp_path / "all.csv"
    p.write_text("video_frame,Frame,X,Y,Visibility,Confidence,match,rally\n"
                 "-1,0,0,0,0,0.0,m1,000\n0,1,5,6,1,0.5,m1,000\n1,2,0,0,0,0.0,m1,000\n0,1,7,8,1,0.9,m2,003\n")
    preds = rv.read_predictions(p)
    assert set(preds) == {"m1_000", "m2_003"}
    assert preds["m1_000"][0]["px"] == [5.0, 6.0] and preds["m1_000"][1] is None
    assert rv.clip_summary(preds)[0] == {"clip": "m1_000", "frames": 2, "detected_pct": 0.5}


def test_fill_short_gaps_flags_interpolated_and_skips_long_gaps():
    track = [ball(0, 0), None, None, ball(30, 30), None, None, None, None, None, None, ball(100, 100)]
    out = fill_short_gaps(track, max_gap=5)
    assert out[1]["interp"] and out[1]["px"] == [10.0, 10.0] and out[1]["conf"] < 0.9
    assert all(out[i] is None for i in range(4, 10))   # 6-frame gap is left empty


def _flight(n, start, vel, g=1.2):
    """Parabolic-ish image path: smooth apex, no abrupt change."""
    return [ball(start[0] + vel[0] * i, start[1] + vel[1] * i + 0.5 * g * i * i) for i in range(n)]


def test_trajectory_hits_finds_reversal_not_apex():
    # down the screen, then an abrupt hit sending it back up, then a smooth apex
    track = _flight(15, (500, 300), (2, 10)) + _flight(30, (530, 560), (4, -30))
    hits = trajectory_hits(track, fps=25, width=1920)
    assert len(hits) == 1 and abs(hits[0]["frame"] - 14) <= 1
    assert 0 < hits[0]["confidence"] <= 0.9


def test_trajectory_hits_ignores_single_outlier():
    track = _flight(30, (500, 300), (3, -20))
    track[12] = ball(900, 100)                       # one wild detection
    assert trajectory_hits(track, fps=25) == []


def test_ball_only_match_contract():
    track = _flight(15, (500, 300), (2, 10)) + [None] * 3 + _flight(30, (530, 560), (4, -30))
    m, tr = ball_only_match(match_id="rv_x", title="t", sport="badminton", balls=track, fps=25, width=1920,
                            height=1080, video_src=None, sha256=None, tracker={"tracker": "racketvision"})
    for key in ("schema_version", "match_id", "sport", "video", "calibration", "players", "rallies", "events", "score", "stats"):
        assert key in m
    assert m["players"] == [] and m["score"]["games"] == [] and m["calibration"]["method"] == "none"
    assert m["stats"]["ball"]["tracker"] == "racketvision" and m["stats"]["ball"]["interpolated_frames"] == 3
    assert all(e["speed_kmh"] is None and e["court"] is None for e in m["events"])   # nothing uncalibrated is invented
    assert len(tr["frames"]) == len(track) and tr["frames"][16]["ball"]["interp"]
    json.dumps(m)


def test_use_plugin_selection(monkeypatch):
    monkeypatch.delenv("RALLYOS_RACKETVISION_ROOT", raising=False)
    assert not rv.use_plugin("badminton", "auto")    # not installed on this machine
    assert rv.use_plugin("badminton", "racketvision")
    assert not rv.use_plugin("tennis", "geometric")
    with pytest.raises(ValueError):
        rv.use_plugin("squash", "racketvision")
    monkeypatch.setenv("RALLYOS_RACKETVISION_ROOT", "/x")
    assert rv.use_plugin("table_tennis") and not rv.use_plugin("pickleball")


def test_entry_like_matches_existing_format():
    assert rv._entry_like("match1_000", "m9", "001") == "m9_001"
    assert rv._entry_like({"match": "a", "rally": "b", "fps": 25}, "m9", "001") == {"fps": 25, "match": "m9", "rally": "001"}
    with pytest.raises(RuntimeError):
        rv._entry_like(42, "m", "r")


@pytest.mark.skipif(not REAL_CSV.is_file(), reason="RacketVision predictions CSV not present")
def test_real_predictions_csv():
    preds = rv.read_predictions(REAL_CSV)
    assert len(preds) == 46
    balls = preds["match117_000"]
    assert 240 <= len(balls) <= 250
    hits = trajectory_hits(fill_short_gaps(balls), fps=25, width=1920)
    assert 4 <= len(hits) <= 15 and all(not math.isnan(h["dv"]) for h in hits)
