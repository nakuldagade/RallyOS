"""Glicko-2 against Glickman's published example (AGENTS.md §20.2), coach grounding, prediction."""
from types import SimpleNamespace

import pytest

from api.services import coach, predict, rating


def test_glicko2_matches_glickman_reference():
    # Glickman, "Example of the Glicko-2 system": 1500/200 vs 1400/30 (W), 1550/100 (L), 1700/300 (L)
    r, rd, vol = rating.glicko2(1500, 200, 0.06, [(1400, 30, 1), (1550, 100, 0), (1700, 300, 0)])
    assert r == pytest.approx(1464.06, abs=0.05)
    assert rd == pytest.approx(151.52, abs=0.05)
    assert vol == pytest.approx(0.05999, abs=1e-5)


def test_glicko2_no_games_only_inflates_rd():
    r, rd, vol = rating.glicko2(1500, 200, 0.06, [])
    assert r == 1500 and rd > 200 and vol == 0.06


def test_evidence_weight_orders_rating_moves():
    p = SimpleNamespace(rating=1500.0, rd=200.0, vol=0.06)
    moves = {ev: rating.weighted_update(p, [(1500, 100, 1)], ev)[0] - 1500 for ev in rating.EVIDENCE_WEIGHT}
    assert moves["video_verified"] > moves["assisted"] > moves["self"] > 0


STATS = {"per_player": {"1": {"split_step_pct": 0.61, "avg_return_to_base_s": 1.24}}}


def test_numbers_must_come_from_stats():
    assert coach.numbers_grounded("Split-step on 61% of shots, recovery 1.24 s.", STATS)
    assert coach.numbers_grounded("Split-step rate is 0.61.", STATS)
    assert not coach.numbers_grounded("Recovery is 1.9 s.", STATS)
    assert not coach.numbers_grounded("Smash speed 180 km/h.", STATS)


def test_llm_insight_validation():
    data = {"video": {"duration_s": 100}, "stats": STATS}
    good = {"text": "Split-step on 61% of shots.", "stat_ids": ["per_player.1.split_step_pct"], "clip_t": [12.0]}
    assert coach.validate_llm(good, data)
    assert not coach.validate_llm({**good, "stat_ids": ["per_player.1.made_up"]}, data)
    assert not coach.validate_llm({**good, "clip_t": []}, data)
    assert not coach.validate_llm({**good, "clip_t": [500.0]}, data)


def test_report_falls_back_to_templates_offline():
    data = {"match_id": "m_x", "players": [{"track_id": 1, "name": "Anika"}],
            "events": [{"t": 3.0, "track_id": 1, "type": "hit"}], "stats": STATS, "insights": []}
    rep = coach.build_report(data)
    assert rep["source"] == "template" and rep["insights"]
    assert all(coach.validate(i, STATS) for i in rep["insights"])


def test_prediction_symmetry_and_factors():
    a = SimpleNamespace(id="a", name="A", rating=1700.0, rd=80.0, style_vec=[0.5] * 4)
    b = SimpleNamespace(id="b", name="B", rating=1500.0, rd=80.0, style_vec=[0.5] * 4)
    ab, ba = predict.win_probability(a, b), predict.win_probability(b, a)
    assert ab["p_a_wins"] > 0.5 and ab["p_a_wins"] + ba["p_a_wins"] == pytest.approx(1, abs=1e-3)
    assert ab["factors"][0]["factor"] == "rating_gap"
    with_h2h = predict.win_probability(a, b, (0, 3))
    assert with_h2h["p_a_wins"] < ab["p_a_wins"]


def test_job_progress_bar_and_stage_list_move_together():
    """The bar is the weighted sum of finished stages; stages that finish between two polls still show as done."""
    from api.services import jobs
    from rallyos.pipeline import Analyzer

    job = {"stages": jobs._fresh_stages(), "taps_given": True, "progress": 0.0, "stage": None}
    ids = [s for s, _ in Analyzer.STAGES]
    jobs.apply_progress(job, "calibrate", 0.5, "reading frames")
    assert job["stages"][0]["state"] == "active" and job["progress"] == pytest.approx(0.005, abs=1e-3)
    jobs.apply_progress(job, "players", 0.5, "frame 5 of 10")
    w = Analyzer.STAGE_WEIGHTS
    assert job["stages"][0]["state"] == "done" and job["progress"] == pytest.approx(w["calibrate"] + 0.5 * w["players"], abs=1e-3)
    jobs.apply_progress(job, "audio", 1.0, "skipped: no audio track")      # a skipped stage still counts as passed
    assert job["stages"][2]["state"] == "skipped" and job["stages"][2]["note"] == "no audio track"
    jobs.apply_progress(job, "outcome", 0.0, "finding landings")           # ball + rallies finished between polls
    assert [s["state"] for s in job["stages"][3:5]] == ["done", "done"] and job["stages"][5]["state"] == "active"
    jobs.apply_progress(job, "done", 1.0)
    assert job["progress"] == 1.0 and all(s["state"] in ("done", "skipped") for s in job["stages"])
    assert ids[0] == "calibrate" and sum(Analyzer.STAGE_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(Analyzer.STAGE_WEIGHTS_AUTO.values()) == pytest.approx(1.0)
    auto = {"stages": jobs._fresh_stages(), "taps_given": False, "progress": 0.0}
    jobs.apply_progress(auto, "players", 0.0)                              # finding the court takes real time
    assert auto["progress"] == pytest.approx(Analyzer.STAGE_WEIGHTS_AUTO["calibrate"], abs=1e-3)


def _movement_match():
    stats = {"per_player": {"1": {
        "avg_return_to_base_s": 1.08, "pulled_away_n": 4, "returned_pct": 0.75, "slowest_return_t": [2.16, 6.16],
        "split_step_n": 6, "split_step_detected": 2, "split_step_pct": 0.33, "split_step_clip_t": [1.0, 4.2],
        "most_zone": "rear-centre", "most_zone_pct": 0.38, "fastest_shot_kmh": 74, "shot_mix": {"smash": 1, "serve": 2},
        "fatigue": {"enough_data": True, "n_shots": 12, "first_third_return_s": 1.1, "last_third_return_s": 1.6,
                    "return_change_pct": 45, "first_t": 12.0, "last_t": 95.0}}}}
    events = [{"id": "e1", "type": "hit", "track_id": 1, "t": 2.16, "shot": "smash", "speed_kmh": 74},
              {"id": "e2", "type": "hit", "track_id": 1, "t": 6.16, "shot": "serve", "speed_kmh": 40}]
    return {"sport": "badminton", "players": [{"track_id": 1, "name": "Anika"}], "stats": stats, "events": events,
            "video": {"duration_s": 120.0}}


def test_template_coach_cites_movement_stats_with_evidence_clips():
    data = _movement_match()
    ins = coach.template_insights(data)
    by_stat = {i["stat_ids"][0].split(".", 2)[2]: i for i in ins}
    assert {"avg_return_to_base_s", "fatigue.first_third_return_s", "split_step_detected", "most_zone", "fastest_shot_kmh",
            "shot_mix.serve"} <= set(by_stat)
    for i in ins:                                                    # grounded: stats exist, clips given, numbers in the stats
        assert coach.validate_llm(i, data), i["text"]
    assert by_stat["avg_return_to_base_s"]["clip_t"] == [2.16, 6.16]                       # the slowest returns
    assert by_stat["fatigue.first_third_return_s"]["clip_t"] == [12.0, 95.0]
    assert by_stat["fastest_shot_kmh"]["clip_t"] == [2.16]                                  # the fastest shot itself
    assert "endurance" in by_stat["fatigue.first_third_return_s"]["text"] and "lower bound" not in by_stat["fastest_shot_kmh"]["text"]
    assert "guide, not a count" in by_stat["split_step_detected"]["text"]


def test_template_coach_says_nothing_it_cannot_support():
    data = _movement_match()
    data["stats"]["per_player"]["1"].update(fatigue={"enough_data": False, "n_shots": 3, "note": "needs 9"}, fastest_shot_kmh=None)
    del data["stats"]["per_player"]["1"]["avg_return_to_base_s"]
    texts = " ".join(i["text"] for i in coach.template_insights(data))
    assert "recovery" not in texts and "fastest shot" not in texts and "get back to base" not in texts


def test_the_job_carries_the_detected_court_from_the_moment_calibration_is_over(tmp_path, monkeypatch):
    """The upload page draws the detected sport's court as soon as it appears on the job, long before the analysis is done."""
    import json
    import sys
    import types

    from api.config import settings
    from api.services import jobs

    seen = {}
    jobs_ref = {}

    from rallyos.pipeline import Analyzer as RealAnalyzer

    class FakeAnalyzer(RealAnalyzer):                                  # keeps the real stage table
        def __init__(self, **kw):
            pass

        def run(self, video, out_dir, progress):
            out = __import__("pathlib").Path(out_dir)
            progress("calibrate", 0.5, "reading frames")
            (out / "stage_court.json").write_text(json.dumps({"sport": "squash", "calibrated": False, "sport_source": "auto-detected (Court Fingerprint)",
                                                              "sport_confidence": 0.8}), encoding="utf-8")
            progress("calibrate", 1.0, "done")
            seen["during_calibrate"] = "detected" in jobs_ref["job"]
            progress("players", 0.0, "loading the pose model")
            seen["at_next_stage"] = dict(jobs_ref["job"].get("detected") or {})
            raise NotImplementedError                                 # the job then falls back to the simulated run: enough for this test

    monkeypatch.setitem(sys.modules, "rallyos.pipeline", types.SimpleNamespace(Analyzer=FakeAnalyzer))
    monkeypatch.setattr(settings, "out_dir", tmp_path)
    monkeypatch.setattr(jobs, "_simulate", lambda job: job.update(simulated=True, match_id="m_001"))
    job = {"stages": jobs._fresh_stages(), "taps_given": False, "progress": 0.0, "stage": None, "status": "queued"}
    jobs_ref["job"] = job
    jobs._run_locked("j_x", job, tmp_path / "v.mp4", "auto", None, None, "m_det")
    assert seen["during_calibrate"] is False                          # not before the calibration is over...
    assert seen["at_next_stage"]["sport"] == "squash" and seen["at_next_stage"]["sport_confidence"] == 0.8   # ...and there when the next stage starts
