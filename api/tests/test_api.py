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


def test_there_is_no_booking_api_any_more_and_a_tournament_draw_still_works(client):
    assert client.post("/v1/bookings", json={}).status_code == 404 and client.get("/v1/courts").status_code == 404
    assert client.post("/v1/tournaments/1/register", json={"player_id": "p_anika"}).status_code == 201
    client.post("/v1/tournaments/1/register", json={"player_id": "p_rohan"})
    draw = client.post("/v1/tournaments/1/draw")
    assert draw.status_code == 200 and draw.json()[0]["p1"] in {"p_anika", "p_rohan"}


def test_ball_only_clip_import(client, tmp_path):
    """A RacketVision-style clip (ball track only, no players/calibration) imports and serves cleanly."""
    from sqlmodel import Session

    from api.db import engine
    from api.services.importer import import_folder
    from rallyos.export import ball_only_match, write_outputs

    balls = [{"px": [500.0 + 2 * i, 300.0 + 10 * i], "court": None, "conf": 0.9, "interp": False} for i in range(15)]
    balls += [{"px": [530.0 + 4 * i, 450.0 - 30 * i + 0.6 * i * i], "court": None, "conf": 0.9, "interp": False} for i in range(30)]
    match, tracks = ball_only_match(match_id="rv_test_000", title="RacketVision clip · test", sport="badminton", balls=balls,
                                    fps=25, width=1920, height=1080, video_src=None, sha256=None,
                                    tracker={"tracker": "racketvision"})
    folder = write_outputs(tmp_path / "rv_test_000", match, tracks)
    with Session(engine) as s:
        assert import_folder(folder, s) == "rv_test_000"

    m = client.get("/v1/matches/rv_test_000").json()
    assert m["players"] == [] and m["stats"]["ball"]["tracker"] == "racketvision" and m["events"]
    assert len(client.get("/v1/matches/rv_test_000/tracks").json()["frames"]) == 45
    summary = next(x for x in client.get("/v1/matches").json() if x["match_id"] == "rv_test_000")
    assert summary["title"] == "RacketVision clip · test" and summary["ball_tracker"] == "racketvision"
    rep = client.get("/v1/matches/rv_test_000/report").json()
    assert rep["insights"] == [] and rep["note"]


def test_recalibrate_validates_and_queues(client, monkeypatch):
    """Calibrating an uploaded match: bad taps are rejected; good taps queue a re-run of the same match id."""
    from api.config import settings
    from api.services import jobs

    good = [[330, 948], [1583, 948], [1253, 333], [638, 333]]
    assert client.post("/v1/matches/rv_test_000/recalibrate", json={"taps": good}).status_code == 404   # no video
    (settings.media_dir / "rv_test_000").mkdir(parents=True, exist_ok=True)
    (settings.media_dir / "rv_test_000" / "source.mp4").write_bytes(b"x")
    crossed = [[330, 948], [1253, 333], [1583, 948], [638, 333]]
    assert client.post("/v1/matches/rv_test_000/recalibrate", json={"taps": crossed}).status_code == 400
    seen = {}
    monkeypatch.setattr(jobs, "submit", lambda video, sport, taps, names, match_id=None: seen.update(
        video=video, sport=sport, taps=taps, match_id=match_id) or "j_test")
    r = client.post("/v1/matches/rv_test_000/recalibrate", json={"taps": good})
    assert r.status_code == 202 and r.json() == {"job_id": "j_test"}
    assert seen["match_id"] == "rv_test_000" and seen["taps"] == good and seen["video"].is_file()


def _court_jpeg() -> bytes:
    import sys
    from pathlib import Path

    import cv2

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))
    from test_court_fit import camera_g, render                      # noqa: E402  (generated court, known camera)
    from rallyos.sports import load_sport

    cfg = load_sport("badminton")
    return cv2.imencode(".jpg", render(cfg, camera_g(cfg)))[1].tobytes()


def test_calibrate_finds_the_court_automatically(client):
    jpg = _court_jpeg()
    r = client.post("/v1/calibrate", files={"frame": ("f.jpg", jpg, "image/jpeg")}, data={"sport": "badminton"})
    d = r.json()
    assert r.status_code == 200 and d["found"] and d["sport"] == "badminton" and d["method"] == "auto"
    nl, nr, fr, fl = d["corners_px"]
    assert nl[1] > fl[1] and nl[0] < nr[0]                           # near = bottom, left < right
    assert d["quality"] in ("high", "check") and d["focal_px"] and d["camera_position_m"][2] > 0.8
    assert d["width"] == 1280 and d["height"] == 720


def test_calibrate_with_taps_blank_frame_and_bad_input(client):
    import cv2
    import numpy as np

    blank = cv2.imencode(".jpg", np.full((360, 640, 3), 90, np.uint8))[1].tobytes()
    r = client.post("/v1/calibrate", files={"frame": ("f.jpg", blank, "image/jpeg")}, data={"sport": "auto"})
    assert r.status_code == 200 and r.json()["found"] is False and "tap" in r.json()["message"].lower()
    taps = "[[330,948],[1583,948],[1253,333],[638,333]]"
    r = client.post("/v1/calibrate", files={"frame": ("f.jpg", blank, "image/jpeg")}, data={"taps": taps})
    assert r.json()["used_taps"] and r.json()["method"] == "4-tap" and len(r.json()["homography"]) == 3
    assert client.post("/v1/calibrate", files={"frame": ("f.jpg", blank, "image/jpeg")}, data={"taps": "[[1,1]]"}).status_code == 400
    assert client.post("/v1/calibrate", files={"frame": ("f.jpg", b"not an image", "image/jpeg")}).status_code == 400
    assert client.post("/v1/calibrate", files={"frame": ("f.jpg", blank, "image/jpeg")}, data={"sport": "curling"}).status_code == 404


def test_reimport_replaces_rows_children_first(client):
    """Importing the same match twice must delete disputes before the events they point at (Postgres enforces it)."""
    from sqlmodel import Session, select

    from api.config import settings
    from api.db import engine
    from api.models import Dispute, Event, Rally
    from api.services.importer import import_folder

    with Session(engine) as s:
        for _ in range(2):
            assert import_folder(settings.mock_dir, s) == "m_001"
        assert len(s.exec(select(Dispute).where(Dispute.match_id == "m_001")).all()) >= 1
        rallies = s.exec(select(Rally.id).where(Rally.match_id == "m_001")).all()
        assert rallies and len(s.exec(select(Event).where(Event.rally_id.in_(rallies))).all()) >= 2


def test_migrate_copies_every_table_and_keeps_ids_growing(tmp_path):
    from sqlalchemy import create_engine, func, select
    from sqlmodel import Session, SQLModel

    import os

    from api.migrate_db import migrate
    from api.models import Venue

    dst = f"sqlite:///{(tmp_path / 'copy.db').as_posix()}"
    src = os.environ["DATABASE_URL"]                              # the database the tests run on
    counts = migrate(src, dst)
    assert counts["venue"] >= 1 and counts["player"] >= 1 and set(counts) == {t.name for t in SQLModel.metadata.sorted_tables}
    with Session(create_engine(dst)) as s:
        top = s.exec(select(func.max(Venue.id))).scalar()
        v = Venue(name="New hall", city="Pune", lat=18.5, lng=73.8)
        s.add(v)
        s.commit()
        assert v.id == top + 1
    again = migrate(src, dst, replace=True)
    assert again == counts                                        # --replace empties the target first


def test_postgres_tables_have_row_level_security(client):
    """On Postgres (Supabase) every table must have RLS on, so the auto-generated REST API can't reach it."""
    from sqlalchemy import text
    from sqlmodel import SQLModel

    from api.db import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no row level security; run with RALLYOS_TEST_DATABASE_URL to check Postgres")
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")).all())
    assert all(rows[t.name] for t in SQLModel.metadata.sorted_tables)
