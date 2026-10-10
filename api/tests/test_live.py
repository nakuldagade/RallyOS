"""Live mode: the event log, the mock replay, and the SSE stream. (Later phases add the real session endpoints.)"""
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.seed import main as seed
from api.services import live_hub, live_mock, store


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


def test_event_log_ids_are_increasing_and_resumable():
    log = live_hub.SessionLog("s_t")
    ids = [log.emit("chunk_received", seq=i) for i in range(5)]
    assert ids == [0, 1, 2, 3, 4]
    assert [e["seq"] for e in log.since(2)] == [3, 4]                  # a reconnecting client gets only what it missed
    assert log.since(4) == [] and len(log.since(-1)) == 5
    assert not log.closed
    log.emit("finalised", match_id="m")
    assert log.closed


def test_event_log_keeps_the_newest_when_capped(monkeypatch):
    monkeypatch.setattr(live_hub, "MAX_EVENTS", 10)
    log = live_hub.SessionLog("s_cap")
    for i in range(25):
        log.emit("lag", i=i)
    kept = log.all()
    assert len(kept) == 10 and kept[-1]["i"] == 24 and kept[0]["id"] == 15
    assert [e["i"] for e in log.since(20)] == [21, 22, 23, 24]         # ids stay valid after trimming


def test_mock_replay_releases_a_match_chunk_by_chunk(client):
    from sqlmodel import Session

    from api.db import engine

    with Session(engine) as s:
        match, tracks = store.load_match("m_001", s), store.load_tracks("m_001")
    log = live_hub.SessionLog("s_mock")
    live_mock.replay(log, match, tracks, speed=1000.0, sleep=lambda s: None)
    ev = log.all()
    types = [e["type"] for e in ev]
    assert types[0] == "session" and types[1] == "calibration_status" and types[-2:] == ["finalising", "finalised"]
    n_chunks = types.count("chunk_received")
    assert n_chunks == types.count("chunk_processed") == types.count("positions") >= 1
    seqs = [e["seq"] for e in ev if e["type"] == "chunk_processed"]
    assert seqs == sorted(seqs) == list(range(n_chunks))                # strictly in order
    sent = [e for x in ev if x["type"] == "new_events" for e in x["events"]]
    assert sent and all(e["provisional"] for e in sent)
    assert [e["id"] for e in sent] == [e["id"] for e in sorted(match["events"], key=lambda e: e["t"])]   # every event, once, in order
    assert all(x.get("provisional") for x in ev if x["type"] in ("stats", "positions"))
    assert sum(1 for x in ev if x["type"] == "rally_closed") == len(match["rallies"])


def test_sse_stream_delivers_events_and_resumes(client):
    r = client.post("/v1/live/mock", json={"match_id": "m_001", "speed": 500.0, "chunk_seconds": 5})
    assert r.status_code == 201
    sid = r.json()["session_id"]
    with client.stream("GET", f"/v1/live/sessions/{sid}/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "session" and types[-1] == "finalised" and "chunk_processed" in types
    assert [e["id"] for e in events] == list(range(len(events)))        # every event, exactly once, in order
    mid = events[len(events) // 2]["id"]
    with client.stream("GET", f"/v1/live/sessions/{sid}/stream", headers={"Last-Event-ID": str(mid)}) as resp:
        resumed = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    assert [e["id"] for e in resumed] == [e["id"] for e in events if e["id"] > mid]
    assert client.get(f"/v1/live/sessions/{sid}").json()["closed"] is True


def test_unknown_session_and_match_are_404(client):
    assert client.get("/v1/live/sessions/s_nope/stream").status_code == 404
    assert client.post("/v1/live/mock", json={"match_id": "m_nope"}).status_code == 404
