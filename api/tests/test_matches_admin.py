"""Removing analysed matches: rows, files, protection of the demo match, and what is kept."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.config import settings
from api.db import engine
from api.main import app
from api.models import Dispute, Event, Insight, Match, Rally, RatingHistory
from api.seed import main as seed
from api.services import matches_admin
from api.services.importer import import_folder


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


def make_match(tmp_path, match_id: str, names=("Near player", "Far player")):
    """Import a small match with a rally, events, a dispute and an insight, and give it every kind of file."""
    from rallyos.export import ball_only_match, write_outputs

    balls = [{"px": [500.0 + 2 * i, 300.0 + 10 * i], "court": None, "conf": 0.9, "interp": False} for i in range(15)]
    balls += [{"px": [530.0 + 4 * i, 450.0 - 30 * i + 0.6 * i * i], "court": None, "conf": 0.9, "interp": False} for i in range(30)]
    match, tracks = ball_only_match(match_id=match_id, title=None, sport="badminton", balls=balls, fps=25, width=1920, height=1080,
                                    video_src=None, sha256=None, tracker={"tracker": "geometric"})
    match["players"] = [{"track_id": 1, "player_id": None, "name": names[0], "side": "near", "color": "#3b82f6"},
                        {"track_id": 2, "player_id": None, "name": names[1], "side": "far", "color": "#ef4444"}]
    match["disputes"] = [{"id": "d_x", "event_id": match["events"][0]["id"], "clip_url": None, "call": "IN", "prob": 0.8, "status": "open"}]
    match["insights"] = [{"player_track_id": 1, "text": "x", "stat_ids": ["a"], "clip_t": [1.0]}]
    folder = write_outputs(tmp_path / match_id, match, tracks)
    with Session(engine) as s:
        import_folder(folder, s)
    (settings.out_dir / match_id).mkdir(parents=True, exist_ok=True)
    (settings.out_dir / match_id / "stage.json").write_text("{}")
    (settings.runtime_dir / f"{match_id}.json").write_text(json.dumps(match))
    (settings.runtime_dir / f"{match_id}.report.abc.json").write_text("[]")
    live = settings.live_dir / f"s_{match_id[2:]}"
    (live / "chunks").mkdir(parents=True, exist_ok=True)
    (live / "chunks" / "chunk_0000.webm").write_bytes(b"x")
    return match_id


def rows(match_id):
    with Session(engine) as s:
        rids = s.exec(select(Rally.id).where(Rally.match_id == match_id)).all()
        return {"match": s.get(Match, match_id) is not None, "rallies": len(rids),
                "events": len(s.exec(select(Event.id).where(Event.rally_id.in_(rids))).all()) if rids else 0,
                "disputes": len(s.exec(select(Dispute.id).where(Dispute.match_id == match_id)).all()),
                "insights": len(s.exec(select(Insight.id).where(Insight.match_id == match_id)).all())}


def test_deleting_a_match_removes_its_rows_and_its_files_but_not_the_ratings(client, tmp_path):
    mid = make_match(tmp_path, "m_del_one")
    with Session(engine) as s:
        s.add(RatingHistory(player_id="p_anika", match_id=mid, rating=1500.0, rd=80.0, at="2026-01-01T00:00:00"))
        s.commit()
    before = rows(mid)
    assert before["match"] and before["rallies"] >= 1 and before["events"] >= 1 and before["disputes"] == 1 and before["insights"] == 1
    r = client.delete(f"/v1/matches/{mid}")
    assert r.status_code == 200 and r.json()["match_id"] == mid and r.json()["files_removed"] >= 4
    assert rows(mid) == {"match": False, "rallies": 0, "events": 0, "disputes": 0, "insights": 0}
    assert not (settings.media_dir / mid).exists() and not (settings.out_dir / mid).exists()
    assert not (settings.runtime_dir / f"{mid}.json").exists() and not list(settings.runtime_dir.glob(f"{mid}.report.*"))
    assert not (settings.live_dir / f"s_{mid[2:]}").exists()                                   # the live session folder went too
    with Session(engine) as s:                                                                    # the rating point stays, unlinked
        kept = s.exec(select(RatingHistory).where(RatingHistory.rating == 1500.0, RatingHistory.rd == 80.0)).all()
        assert kept and all(k.match_id is None for k in kept)
    assert mid not in [m["match_id"] for m in client.get("/v1/matches").json()]
    assert client.get(f"/v1/matches/{mid}").status_code == 404 or client.get(f"/v1/matches/{mid}").json()["match_id"] != mid


def test_the_demo_match_and_unknown_ids_are_handled_safely(client):
    assert client.delete("/v1/matches/m_001").status_code == 403
    assert client.delete("/v1/matches/m_does_not_exist").status_code == 404
    assert client.post("/v1/matches/delete", json={"ids": []}).status_code == 400
    r = client.post("/v1/matches/delete", json={"ids": ["m_001", "m_nope"]}).json()
    assert r["deleted"] == [] and {s["match_id"]: s["reason"] for s in r["skipped"]} == {"m_001": "the demo match is protected", "m_nope": "not found"}
    assert rows("m_001")["match"]                                                                  # still there


def test_several_matches_are_removed_in_one_call_and_skips_are_reported(client, tmp_path):
    a, b = make_match(tmp_path, "m_del_a"), make_match(tmp_path, "m_del_b")
    r = client.post("/v1/matches/delete", json={"ids": [a, b, "m_001", a]}).json()                # a repeated id is only removed once
    assert sorted(d["match_id"] for d in r["deleted"]) == [a, b] and [s["match_id"] for s in r["skipped"]] == ["m_001"]
    assert not rows(a)["match"] and not rows(b)["match"]


def test_matches_still_carrying_the_placeholder_names_are_found(client, tmp_path):
    generic = make_match(tmp_path, "m_gen_1")
    named = make_match(tmp_path, "m_gen_2", names=("Anika", "Rohan"))
    with Session(engine) as s:
        found = matches_admin.default_named(s)
    assert generic in found and named not in found and "m_001" not in found
    client.post("/v1/matches/delete", json={"ids": [generic, named]})
