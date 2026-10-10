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
