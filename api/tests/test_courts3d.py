"""The 3D court viewer's data: the shot paths, and who may see which side of a match (the server filters, not the page)."""
import json
import math

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.config import settings
from api.db import engine
from api.main import app
from api.models import Match
from api.seed import main as seed
from api.services.court3d import color_for
from api.services.importer import import_folder
from api.tests.test_accounts import headers, other_coach


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


def hit(i, t, tid, court):
    return {"id": f"e_{i}", "rally_idx": 0, "t": t, "type": "hit", "track_id": tid, "px": [100, 100], "court": court, "confidence": 0.9, "shot": "drive",
            "source": ["audio", "vision"]}


def make_match(tmp_path, match_id, sport="badminton", p1="p_anika", p2="p_rohan"):
    base = json.loads((settings.mock_dir / "match.json").read_text(encoding="utf-8"))
    base.update(match_id=match_id, sport=sport)
    base["players"] = [{"track_id": 1, "player_id": None, "name": "Near player", "side": "near", "color": "#3b82f6"},
                       {"track_id": 2, "player_id": None, "name": "Far player", "side": "far", "color": "#ef4444"}]
    base["events"] = [hit(1, 1.0, 1, [3.0, 3.0]), hit(2, 1.6, 2, [3.0, 11.0]), hit(3, 2.4, 1, [3.0, 3.0]),
                      {"id": "e_4", "rally_idx": 0, "t": 3.2, "type": "landing", "track_id": None, "px": [1, 1], "court": [3.0, 12.0], "call": "IN",
                       "call_prob": 0.9, "confidence": 0.9, "ellipse_m": [0.1, 0.05, 0]}]
    base["rallies"] = [{"idx": 0, "t_start": 0.5, "t_end": 3.5, "hits": 3, "winner_track_id": 1, "end_reason": "landing_in", "confidence": 0.8}]
    base["stats"] = {"per_player": {"1": {}, "2": {}}, "match": {}}
    base["disputes"], base["insights"] = [], []
    base["video"] = {**base["video"], "duration_s": 4.0, "fps": 25.0, "src": f"/media/{match_id}/source.mp4"}
    folder = tmp_path / match_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "match.json").write_text(json.dumps(base), encoding="utf-8")
    frames = [{"f": i, "players": [{"track_id": 1, "court": [3.0, 3.0 + 0.01 * i]}, {"track_id": 2, "court": [2.0, 11.0]}], "ball": None} for i in range(100)]
    (folder / "tracks.json").write_text(json.dumps({"fps": 25.0, "frames": frames}), encoding="utf-8")
    with Session(engine) as s:
        import_folder(folder, s)
        m = s.get(Match, match_id)
        m.p1, m.p2 = p1, p2
        s.add(m)
        s.commit()


@pytest.fixture(scope="module")
def matches(client, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("c3d")
    make_match(tmp, "m_3d_a")                                          # Anika (side 1) vs Rohan
    make_match(tmp, "m_3d_b", p1="p_kabir", p2="p_anika")              # Kabir vs Anika (side 2)
    make_match(tmp, "m_3d_c", p1="p_meera", p2="p_isha")               # a match with nobody the others share
    return tmp


def test_a_player_sees_both_sides_of_their_own_matches_the_opponent_they_faced_included(client, matches):
    h = headers(client, "anika@rallyos.demo")
    a = client.get("/v1/courts3d/matches/m_3d_a", headers=h).json()
    assert [p["player_id"] for p in a["players"]] == ["p_anika", "p_rohan"] and set(a["positions"]) == {"1", "2"} and set(a["heat"]) == {"1", "2"}
    assert {f["track_id"] for f in a["flights"]} == {1, 2}                                        # her shots and her opponent's
    assert a["players"][0]["color"] != a["players"][1]["color"]                                    # told apart by colour
    b = client.get("/v1/courts3d/matches/m_3d_b", headers=h).json()
    assert [p["player_id"] for p in b["players"]] == ["p_kabir", "p_anika"] and {f["track_id"] for f in b["flights"]} == {1, 2}


def test_a_player_cannot_open_a_match_they_were_not_in(client, matches):
    h = headers(client, "anika@rallyos.demo")
    assert client.get("/v1/courts3d/matches/m_3d_c", headers=h).status_code == 403
    assert client.get("/v1/courts3d/matches/m_nope", headers=h).status_code == 404
    other = client.get("/v1/courts3d/matches/m_3d_c", headers=headers(client, "meera@rallyos.demo")).json()      # Meera was in that one
    assert [p["player_id"] for p in other["players"]] == ["p_meera", "p_isha"]
    assert "p_meera" not in json.dumps(client.get("/v1/courts3d/matches/m_3d_a", headers=h).json())            # and none of her data is in Anika's matches
    assert client.get("/v1/courts3d/matches/m_3d_a").status_code == 401


def test_a_coach_sees_both_sides_of_a_match_with_one_of_their_players_and_nothing_of_other_matches(client, matches):
    h = headers(client, "coach.vikram@rallyos.demo")
    a = client.get("/v1/courts3d/matches/m_3d_a", headers=h).json()
    assert [p["player_id"] for p in a["players"]] == ["p_anika", "p_rohan"] and {f["track_id"] for f in a["flights"]} == {1, 2}
    assert set(a["positions"]) == {"1", "2"} and a["heat"]["1"] and a["heat"]["2"]
    assert client.get("/v1/courts3d/matches/m_3d_c", headers=h).status_code == 200              # Meera and Isha are on the demo coach's roster
    assert client.get("/v1/courts3d/matches/m_3d_a", headers=other_coach(client)).status_code == 403      # a coach with nobody on the roster


def test_the_match_list_is_filtered_the_same_way(client, matches):
    mine = {m["match_id"] for m in client.get("/v1/courts3d/matches", headers=headers(client, "anika@rallyos.demo")).json()}
    assert {"m_3d_a", "m_3d_b"} <= mine and "m_3d_c" not in mine
    coach = {m["match_id"] for m in client.get("/v1/courts3d/matches", headers=headers(client, "coach.vikram@rallyos.demo")).json()}
    assert {"m_3d_a", "m_3d_b", "m_3d_c"} <= coach
    assert client.get("/v1/courts3d/matches", headers=other_coach(client)).json() == []
    assert client.get("/v1/courts3d/matches").status_code == 401
    assert "m_001" not in coach                                                                  # the sample match is never listed


def test_flights_are_in_court_metres_start_and_end_where_the_events_say_and_say_what_they_are(client, matches):
    a = client.get("/v1/courts3d/matches/m_3d_a", headers=headers(client, "coach.vikram@rallyos.demo")).json()
    f = a["flights"][0]
    assert f["track_id"] == 1 and f["t0"] == 1.0 and f["t1"] == 1.6 and f["kind"] in ("physics", "estimate")
    assert f["samples"][0][1:3] == [3.0, 3.0] and f["samples"][-1][1:3] == [3.0, 11.0]            # from the hitter's feet to the next contact
    zs = [s[3] for s in f["samples"]]
    assert min(zs) >= 0 and 0.5 < max(zs) < 6 and all(math.isfinite(z) for z in zs)
    ts = [s[0] for s in f["samples"]]
    assert ts == sorted(ts) and ts[0] == 1.0 and abs(ts[-1] - 1.6) < 1e-6
    landing = next(x for x in a["flights"] if x["t0"] == 2.4)
    assert landing["samples"][-1][3] == 0.0 and landing["to"][:2] == [3.0, 12.0]                  # a landing is on the ground
    assert a["court"]["length"] == 13.4 and a["court"]["lines"] and "heights" in a["notes"]


def test_a_tennis_match_uses_the_tennis_court_and_bounces_its_ball(client, tmp_path):
    make_match(tmp_path, "m_3d_tennis", sport="tennis")
    d = client.get("/v1/courts3d/matches/m_3d_tennis", headers=headers(client, "coach.vikram@rallyos.demo")).json()
    assert d["court"]["length"] == 23.77 and d["court"]["net"]["height_center"] == 0.914
    f = next(x for x in d["flights"] if x["t0"] == 1.0)                                          # contact to contact: one bounce in between
    assert f["kind"] == "estimate" and min(s[3] for s in f["samples"][2:-2]) < 0.2
    assert f["samples"][-1][1:3] == [3.0, 11.0]


def test_a_person_has_the_same_colour_everywhere():
    assert color_for("p_anika", 1) == color_for("p_anika", 2) != color_for("p_rohan", 1)
    assert color_for(None, 1) != color_for(None, 2) and color_for("p_new_player", 1) == color_for("p_new_player", 2)


# -- the 3D view on a match's own page -----------------------------------------------------------------------------------------

def test_a_match_nobody_was_assigned_to_opens_in_3d_for_anyone_and_an_assigned_one_only_for_its_people(client, matches, tmp_path):
    make_match(tmp_path, "m_3d_free", p1=None, p2=None)
    d = client.get("/v1/matches/m_3d_free/scene3d")                                          # no login at all
    assert d.status_code == 200 and {p["track_id"] for p in d.json()["players"]} == {1, 2} and d.json()["flights"]
    assert client.get("/v1/matches/m_3d_a/scene3d").status_code == 401                          # assigned: log in first
    assert client.get("/v1/matches/m_3d_a/scene3d", headers=headers(client, "kabir@rallyos.demo")).status_code == 403      # Kabir was not in match a
    assert client.get("/v1/matches/m_3d_a/scene3d", headers=headers(client, "rohan@rallyos.demo")).status_code == 200      # he was
    assert client.get("/v1/matches/m_3d_a/scene3d", headers=headers(client, "coach.vikram@rallyos.demo")).status_code == 200
    assert client.get("/v1/matches/m_nope/scene3d").status_code == 404


def test_every_sport_comes_with_its_own_3d_look_and_walls_and_a_table_top_height(client, tmp_path):
    for sport in ("tennis", "badminton", "pickleball", "padel", "squash", "table_tennis"):
        make_match(tmp_path, f"m_3d_{sport}", sport=sport, p1=None, p2=None)
        d = client.get(f"/v1/matches/m_3d_{sport}/scene3d").json()
        assert d["court"]["view3d"]["surface"]["inner"].startswith("#"), sport
    assert client.get("/v1/matches/m_3d_padel/scene3d").json()["court"]["walls"][0]["material"] == "glass"
    assert any(w["id"] == "front" for w in client.get("/v1/matches/m_3d_squash/scene3d").json()["court"]["walls"])
    tt = client.get("/v1/matches/m_3d_table_tennis/scene3d").json()
    assert tt["court"]["view3d"]["plane_height_m"] == 0.76
    zs = [s[3] for f in tt["flights"] for s in f["samples"]]
    assert zs and min(zs) >= 0.76 - 1e-6 and max(zs) < 0.76 + 1.0                              # the ball flies above the table top, not the floor
