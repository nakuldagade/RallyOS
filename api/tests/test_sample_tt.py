"""The generated table-tennis sample matches: legal games, labelled as sample data, statistics from the real analytics code."""
from api.make_sample_tt import SPECS, build_match


def _all(tmp_path):
    return [build_match(s, tmp_path / s["id"], "Dev", render_video=False) for s in SPECS]


def test_every_game_is_a_legal_table_tennis_game_and_labelled_sample_data(tmp_path):
    for d in _all(tmp_path):
        a, b = d["score"]["games"][0]
        assert max(a, b) >= 11 and abs(a - b) >= 2                        # to 11, win by 2
        assert d["score"]["winner_track_id"] == (1 if a > b else 2)
        assert d["synthetic"] is True and "(sample data)" in d["title"] and d["stats"]["pipeline"]["synthetic"] is True
        assert d["rallies"][-1]["score_after"] == f"{a}-{b}"
        assert d["sport"] == "table_tennis" and d["video"]["fps"] == 30.0


def test_rallies_alternate_hitters_and_end_with_a_consistent_winner(tmp_path):
    for d in _all(tmp_path):
        for r in d["rallies"]:
            hits = [e for e in d["events"] if e["type"] == "hit" and e["rally_idx"] == r["idx"]]
            assert len(hits) == r["hits"] >= 1
            assert all(hits[i]["track_id"] != hits[i + 1]["track_id"] for i in range(len(hits) - 1))
            last = hits[-1]["track_id"]
            assert r["winner_track_id"] == (last if r["end_reason"] == "landing_in" else 3 - last)
        assert not any(e.get("speed_kmh") for e in d["events"])           # no shot speed is invented


def test_statistics_are_computed_and_tara_improves_from_match_to_match(tmp_path):
    ds = _all(tmp_path)
    for d in ds:
        for tid in ("1", "2"):
            s = d["stats"]["per_player"][tid]
            assert s["hits"] > 20 and s["distance_m"] > 0 and s["zone_pct"] and s["shot_mix"] and s["best_shot"]
    back = [d["stats"]["per_player"]["1"]["avg_return_to_base_s"] for d in ds]
    assert back[0] > back[1] > back[2]                                        # she recovers faster each match (by construction)


def test_the_generation_is_repeatable(tmp_path):
    a = build_match(SPECS[0], tmp_path / "a", "Dev", render_video=False)
    b = build_match(SPECS[0], tmp_path / "b", "Dev", render_video=False)
    assert a["events"] == b["events"] and a["stats"]["per_player"] == b["stats"]["per_player"]


def test_a_live_session_gets_the_same_3d_payload_as_a_finished_match(tmp_path):
    import json

    from api.services import court3d

    d = build_match(SPECS[2], tmp_path / "m", "Dev", render_video=False)
    tracks = json.loads((tmp_path / "m" / "tracks.json").read_text(encoding="utf-8"))
    scene = court3d.live_scene(d, tracks["frames"], tracks["fps"], "s_test")
    assert scene["match_id"] == "live:s_test" and scene["sport"] == "table_tennis"
    assert len(scene["flights"]) > 20 and {p["track_id"] for p in scene["players"]} == {1, 2}
    assert scene["positions"]["1"] and scene["heat"]["1"]["frames"] > 0
    assert scene["court"]["view3d"] and scene["duration_s"] == round(len(tracks["frames"]) / tracks["fps"], 2)


def test_the_live_3d_endpoint_says_so_for_an_unknown_session():
    from fastapi.testclient import TestClient

    from api.main import app
    assert TestClient(app).get("/v1/live/sessions/s_nope/scene3d").status_code == 404
