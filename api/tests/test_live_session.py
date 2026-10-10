"""Live sessions over the API (phase C): chunks uploaded like a browser would, analysed in order, finalised and imported.

The footage is generated (a shuttle on a green court written as MJPG chunks) and the pose model is switched off, so these tests
prove the session machinery (ordering, duplicates, missing chunks, stop, corners, URL registration, resume, import), not the
quality of the vision on real footage.
"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))
from test_live_stream import FPS, TAPS, make_chunks  # noqa: E402

from api.config import settings  # noqa: E402
from api.main import app  # noqa: E402
from api.seed import main as seed  # noqa: E402
from api.services import live as live_service  # noqa: E402
from api.services import live_hub  # noqa: E402

N_FRAMES = 160            # 6.4 s: chunks of 2 s + 0.4 s overlap -> 4 chunks


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    import rallyos.detect.players as players

    base = tmp_path_factory.mktemp("liveapi")
    mp = pytest.MonkeyPatch()
    mp.setattr(players, "load_pose_detector", lambda **kw: (None, "disabled in test"))
    mp.setattr(settings, "live_dir", base / "live")
    mp.setattr(settings, "out_dir", base / "out")
    mp.setattr(settings, "live_missing_wait_s", 1.0)
    mp.setattr(settings, "storage", "local")            # the tests must not depend on what .env says (it may select Cloudinary)
    metas = make_chunks(base / "chunks", n=N_FRAMES)
    seed()
    with TestClient(app) as client:
        yield {"client": client, "metas": metas, "base": base}
    mp.undo()


def new_session(env, **body):
    r = env["client"].post("/v1/live/sessions", json={"sport": "badminton", "corners": TAPS, "chunk_seconds": 2.0, **body})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def upload(env, sid, meta, **extra):
    data = Path(meta.path).read_bytes()
    form = {"seq": meta.seq, "t0": meta.t0, "duration": meta.duration, **extra}
    return env["client"].post(f"/v1/live/sessions/{sid}/chunks", files={"chunk": (f"c{meta.seq}.avi", data, "video/x-msvideo")}, data=form)


def types(sid):
    return [e["type"] for e in live_hub.get_session(sid).all()]


def wait_for(sid, kind, count=1, timeout=120.0):
    end = time.time() + timeout
    while time.time() < end:
        got = [e for e in live_hub.get_session(sid).all() if e["type"] == kind]
        if len(got) >= count:
            return got
        if live_hub.get_session(sid).closed and kind not in ("finalised", "error"):
            break
        time.sleep(0.15)
    raise AssertionError(f"timed out waiting for {count} x {kind}; saw {types(sid)}")


def test_a_whole_match_from_create_to_the_imported_match(env):
    c, metas = env["client"], env["metas"]
    sid = new_session(env)
    sign = c.post(f"/v1/live/sessions/{sid}/sign").json()
    assert sign["mode"] == "local" and sign["upload_url"] == f"/v1/live/sessions/{sid}/chunks" and sign["file_field"] == "chunk"
    for m in metas:
        assert upload(env, sid, m, upload_s=0.2).json() == {"seq": m.seq, "duplicate": False}
    assert c.post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": metas[-1].seq}).status_code == 202
    fin = wait_for(sid, "finalised")[0]
    t = types(sid)
    assert t[0] == "session" and t.index("calibration_status") < t.index("chunk_processed")
    done = [e for e in live_hub.get_session(sid).all() if e["type"] == "chunk_processed"]
    assert [e["seq"] for e in done] == [m.seq for m in metas]                                 # analysed in order
    assert all(e["lag_s"] >= 0 and e["latency_s"] >= 0.2 and e["rtf"] > 0 for e in done)      # latency includes the upload
    assert all(e.get("provisional") for e in live_hub.get_session(sid).all() if e["type"] in ("positions", "stats"))
    assert t.index("finalising") < t.index("finalised") and t[-1] == "finalised"
    match = c.get(f"/v1/matches/{fin['match_id']}").json()                                    # the existing app reads it
    assert match["schema_version"] == "1.1" and match["live"]["chunks"] == len(metas) and match["live"]["session_id"] == sid
    assert match["live"]["avg_latency_s"] >= 0.2 and match["video"]["sha256"] and match["calibration"]["method"] == "4-tap"
    assert c.get(f"/v1/matches/{fin['match_id']}/tracks").status_code == 200
    assert (settings.media_dir / fin["match_id"] / "source.mp4").is_file()
    assert c.get(f"/v1/live/sessions/{sid}").json()["state"] == "done"
    snap = c.get(f"/v1/live/sessions/{sid}/snapshot").json()
    assert snap["match_id"] == fin["match_id"] and snap["events"]


def test_chunks_that_arrive_out_of_order_are_analysed_in_order(env):
    sid = new_session(env)
    metas = env["metas"][:3]
    for m in (metas[1], metas[2], metas[0]):
        upload(env, sid, m)
    wait_for(sid, "chunk_processed", 3)
    log = live_hub.get_session(sid).all()
    assert [e["seq"] for e in log if e["type"] == "chunk_received"] == [1, 2, 0]              # arrival order
    assert [e["seq"] for e in log if e["type"] == "chunk_processed"] == [0, 1, 2]             # analysis order
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 2})
    wait_for(sid, "finalised")


def test_a_retried_chunk_is_acknowledged_and_analysed_once(env):
    sid = new_session(env)
    m = env["metas"][0]
    assert upload(env, sid, m).json()["duplicate"] is False
    assert upload(env, sid, m).json() == {"seq": 0, "duplicate": True}                       # same seq again: no second copy
    wait_for(sid, "chunk_processed")
    assert upload(env, sid, m).json()["duplicate"] is True                                    # ... even after it was analysed
    log = live_hub.get_session(sid).all()
    assert sum(1 for e in log if e["type"] == "chunk_received") == 1 == sum(1 for e in log if e["type"] == "chunk_processed")
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 0})
    wait_for(sid, "finalised")


def test_a_chunk_that_never_comes_is_reported_and_counted_as_dropped(env):
    sid = new_session(env)
    metas = env["metas"]
    for m in (metas[0], metas[2], metas[3]):                                                 # chunk 1 is lost
        upload(env, sid, m)
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 3})
    missing = wait_for(sid, "chunk_missing")[0]
    assert missing["seq"] == 1
    fin = wait_for(sid, "finalised")[0]
    match = env["client"].get(f"/v1/matches/{fin['match_id']}").json()
    assert match["live"]["dropped_frames"] > 0 and match["live"]["chunks"] == 3               # the loss is in the record
    assert [e["seq"] for e in live_hub.get_session(sid).all() if e["type"] == "chunk_processed"] == [0, 2, 3]


def test_stop_waits_for_the_last_chunk_still_in_flight_but_not_for_new_ones(env):
    sid = new_session(env)
    metas = env["metas"]
    upload(env, sid, metas[0])
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 1})                 # the client says chunk 1 is still uploading
    time.sleep(0.4)
    assert upload(env, sid, metas[1]).status_code == 200                                      # allowed: it is within last_seq
    r = upload(env, sid, metas[2])
    assert r.status_code == 409                                                                # beyond last_seq: refused
    wait_for(sid, "finalised")
    assert [e["seq"] for e in live_hub.get_session(sid).all() if e["type"] == "chunk_processed"] == [0, 1]


def test_new_corners_rerun_the_stored_chunks_and_the_session_goes_on(env):
    sid = new_session(env)
    metas = env["metas"]
    for m in metas[:2]:
        upload(env, sid, m)
    wait_for(sid, "chunk_processed", 2)
    shifted = [[x + (8 if i in (1, 2) else 0), y] for i, (x, y) in enumerate(TAPS)]
    assert env["client"].post(f"/v1/live/sessions/{sid}/corners", json={"taps": shifted}).status_code == 202
    ev = wait_for(sid, "recomputed")[0]
    assert ev["chunks"] == 2 and "events" in ev and "stats" in ev
    cal = [e for e in live_hub.get_session(sid).all() if e["type"] == "calibration_status"][-1]
    assert cal["corners_px"] == [[float(x), float(y)] for x, y in shifted]
    upload(env, sid, metas[2])                                                                 # the session was not restarted
    wait_for(sid, "chunk_processed", 3)
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 2})
    wait_for(sid, "finalised")
    assert env["client"].post(f"/v1/live/sessions/{sid}/corners", json={"taps": [[1, 1]]}).status_code == 400


def test_a_chunk_stored_elsewhere_is_fetched_only_from_allowed_hosts(env, monkeypatch):
    import httpx

    sid = new_session(env)
    m = env["metas"][0]
    body = {"seq": 0, "t0": 0.0, "duration": m.duration}
    bad = env["client"].post(f"/v1/live/sessions/{sid}/chunks/register", json={**body, "url": "https://evil.example.com/c0.avi"})
    assert bad.status_code == 400 and "not allowed" in bad.json()["detail"]
    monkeypatch.setattr(settings, "chunk_url_hosts", ["res.cloudinary.com"])
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return httpx.Response(200, content=Path(m.path).read_bytes())

    monkeypatch.setattr(httpx, "get", fake_get)
    ok = env["client"].post(f"/v1/live/sessions/{sid}/chunks/register", json={**body, "url": "https://res.cloudinary.com/demo/video/upload/c0.avi"})
    assert ok.status_code == 200 and seen == ["https://res.cloudinary.com/demo/video/upload/c0.avi"]
    wait_for(sid, "chunk_processed")
    again = env["client"].post(f"/v1/live/sessions/{sid}/chunks/register", json={**body, "url": "https://res.cloudinary.com/demo/video/upload/c0.avi"})
    assert again.json()["duplicate"] is True and len(seen) == 1                                # a retry does not download twice
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 0})
    wait_for(sid, "finalised")


def test_a_session_is_rebuilt_from_disk_after_the_server_restarts(env):
    sid = new_session(env)
    metas = env["metas"]
    for m in metas[:2]:
        upload(env, sid, m)
    wait_for(sid, "chunk_processed", 2)
    live_service.LIVE.pop(sid)                                                                  # "the server restarted"
    live_hub.SESSIONS.pop(sid)
    assert env["client"].get(f"/v1/live/sessions/{sid}/snapshot").status_code == 404
    assert env["client"].post(f"/v1/live/sessions/{sid}/resume").status_code == 201
    ev = wait_for(sid, "recomputed")[0]
    assert ev["chunks"] == 2
    assert live_service.get(sid).next_seq == 2
    assert upload(env, sid, metas[2]).status_code == 200                                        # and it carries on
    wait_for(sid, "chunk_processed", 1)
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 2})
    fin = wait_for(sid, "finalised")[0]
    assert env["client"].get(f"/v1/matches/{fin['match_id']}").json()["live"]["chunks"] == 3
    assert env["client"].post("/v1/live/sessions/s_never_existed/resume").status_code == 404


def test_bad_requests_get_clear_errors(env):
    c = env["client"]
    assert c.post("/v1/live/sessions", json={"sport": "curling"}).status_code == 404
    assert c.post("/v1/live/sessions", json={"sport": "badminton", "corners": [[1, 1], [2, 2]]}).status_code == 400
    assert c.post("/v1/live/sessions/s_nope/chunks", files={"chunk": ("c.avi", b"x")}, data={"seq": 0}).status_code == 404
    sid = new_session(env)
    assert c.post(f"/v1/live/sessions/{sid}/chunks", files={"chunk": ("c.avi", b"")}, data={"seq": 0}).status_code == 400
    assert c.post(f"/v1/live/sessions/{sid}/chunks", files={"chunk": ("c.avi", b"x")}, data={"seq": -1}).status_code == 400
    c.post(f"/v1/live/sessions/{sid}/stop")                                                    # stopped with nothing analysed
    err = wait_for(sid, "error")[0]
    assert "before any chunk" in err["message"]


def test_a_broken_chunk_is_reported_and_the_session_survives_it(env):
    sid = new_session(env)
    metas = env["metas"]
    upload(env, sid, metas[0])
    bad = env["client"].post(f"/v1/live/sessions/{sid}/chunks", files={"chunk": ("c1.avi", b"not a video at all", "video/x-msvideo")},
                             data={"seq": 1, "t0": metas[1].t0, "duration": metas[1].duration})
    assert bad.status_code == 200
    upload(env, sid, metas[2])
    failed = wait_for(sid, "chunk_failed")[0]
    assert failed["seq"] == 1
    wait_for(sid, "chunk_processed", 2)                                                         # chunks 0 and 2 still got analysed
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 2})
    wait_for(sid, "finalised")


def test_the_stream_replays_the_whole_session_to_a_late_viewer(env):
    sid = new_session(env)
    upload(env, sid, env["metas"][0])
    wait_for(sid, "chunk_processed")
    env["client"].post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": 0})
    wait_for(sid, "finalised")
    import json

    with env["client"].stream("GET", f"/v1/live/sessions/{sid}/stream") as resp:
        got = [json.loads(line[6:]) for line in resp.iter_lines() if line.startswith("data: ")]
    assert [e["id"] for e in got] == list(range(len(got))) and got[0]["type"] == "session" and got[-1]["type"] == "finalised"
