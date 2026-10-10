"""Router tests against the seeded temp DB and the §11.3 mock match (see conftest.py)."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.seed import main as seed


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json()["ok"]


def test_match_contract(client):
    r = client.get("/v1/matches/m_001")
    assert r.status_code == 200
    d = r.json()
    assert d["sport"] == "badminton" and d["rallies"] and d["events"] and d["tracks_url"]


def test_list_and_404(client):
    assert client.get("/v1/matches").json()[0]["match_id"] == "m_001"
    assert client.get("/v1/matches/nope").status_code == 404


def test_events_filter_and_tracks(client):
    landings = client.get("/v1/matches/m_001/events?type=landing").json()
    assert landings and all(e["type"] == "landing" for e in landings)
    assert client.get("/v1/matches/m_001/tracks").json()["frames"]


def test_media_served_after_import(client):
    assert client.get("/media/m_001/match.json").status_code == 200


def test_dispute_and_report(client):
    d = client.get("/v1/disputes/d_001").json()
    assert d["call"] == "IN" and d["event"]["type"] == "landing"
    rep = client.get("/v1/matches/m_001/report").json()
    assert rep["source"] == "pipeline"
    assert rep["insights"] and all(i["stat_ids"] and i["clip_t"] for i in rep["insights"])
    tpl = client.get("/v1/matches/m_001/report?source=template").json()
    assert tpl["source"] == "template" and tpl["insights"]


def test_confirm_score_updates_rating_once(client):
    before = client.get("/v1/players/p_anika").json()["rating"]
    r = client.post("/v1/matches/m_001/score/confirm", json={"games": [[21, 10], [21, 12]], "winner_track_id": 1})
    body = r.json()
    assert body["confirmed_by_human"] is True
    assert {c["player_id"] for c in body["rating_update"]} == {"p_anika", "p_rohan"}
    assert client.get("/v1/players/p_anika").json()["rating"] > before
    assert client.get("/v1/matches/m_001").json()["score"]["games"] == [[21, 10], [21, 12]]
    again = client.post("/v1/matches/m_001/score/confirm", json={"games": [[21, 10], [21, 12]], "winner_track_id": 1})
    assert again.json()["rating_update"] == []          # rated once per match
    assert client.get("/v1/matches").json()[0]["evidence_level"] == "video_verified"


def test_network(client):
    mm = client.get("/v1/matchmaking?player_id=p_anika").json()
    assert all(m["player_id"] != "p_anika" for m in mm)
    pred = client.get("/v1/predict?a=p_anika&b=p_kabir").json()
    assert 0 < pred["p_a_wins"] < 1 and 1 <= len(pred["factors"]) <= 3


def test_sports_come_from_core_yaml(client):
    sports = client.get("/v1/sports").json()
    assert {s["sport"] for s in sports} >= {"badminton", "tennis", "table_tennis", "pickleball", "padel", "squash"}
    assert "yaml" in client.get("/v1/sports/badminton").json()
    assert client.post("/v1/sports", json={"yaml_text": "sport: badminton\ncourt: {}\nprojectile: {}\nscoring: {type: rally_point}"}).status_code == 409
    assert client.post("/v1/sports", json={"yaml_text": "not: [valid"}).status_code == 400


def test_booking_and_tournament(client):
    body = {"court_id": 1, "player_id": "p_anika", "slot_start": "2026-11-01T10:00:00", "slot_end": "2026-11-01T11:00:00"}
    assert client.post("/v1/bookings", json=body).status_code == 201
    assert client.post("/v1/bookings", json=body).status_code == 409
    assert client.post("/v1/tournaments/1/register", json={"player_id": "p_anika"}).status_code == 201
    client.post("/v1/tournaments/1/register", json={"player_id": "p_rohan"})
    draw = client.post("/v1/tournaments/1/draw")
    assert draw.status_code == 200 and draw.json()[0]["p1"] in {"p_anika", "p_rohan"}
