"""Match highlights over the API: listing them, and cutting them for matches analysed before the feature (backfill)."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.config import settings
from api.db import engine
from api.main import app
from api.seed import main as seed
from api.services import highlights
from api.services.importer import import_folder

cv2 = pytest.importorskip("cv2")
FPS = 25.0


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


def make_match(tmp_path, match_id, with_video=True, highlight=None, rated=True):
    base = json.loads((settings.mock_dir / "match.json").read_text(encoding="utf-8"))
    base.update(match_id=match_id, sport="badminton")
    base["players"] = [{"track_id": 1, "player_id": None, "name": "Near player", "side": "near", "color": "#3b82f6"},
                       {"track_id": 2, "player_id": None, "name": "Far player", "side": "far", "color": "#ef4444"}]
    ev = lambda i, t, tid, **kw: {"id": f"e_{i}", "rally_idx": 0, "t": t, "type": "hit", "track_id": tid, "px": [160, 120], "court": [3.0, 3.0 if tid == 1 else 11.0],
                                  "confidence": 0.9, "shot": "drive", "source": ["vision"], **kw}
    base["events"] = [ev(1, 2.0, 1), ev(2, 2.6, 2), {**ev(3, 3.4, None), "type": "landing", "court": [3.0, 1.5], "call": "IN", "call_prob": 0.9}]
    base["rallies"] = [{"idx": 0, "t_start": 1.5, "t_end": 4.0, "hits": 2, "winner_track_id": 2, "end_reason": "landing_in", "confidence": 0.8, "winner_confidence": 0.8}]
    base["stats"] = {"per_player": {"1": {"hits": 1}, "2": {"hits": 1}} if rated else {}, "match": {}}
    base["disputes"], base["insights"] = [], []
    base["video"] = {**base["video"], "duration_s": 12.0, "fps": FPS, "src": f"/media/{match_id}/source.mp4"}
    base.pop("highlight", None)
    if highlight:
        base["highlight"] = highlight
    folder = tmp_path / match_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "match.json").write_text(json.dumps(base), encoding="utf-8")
    frames = [{"f": i, "players": [{"track_id": 1, "court": [3.0, 3.0], "bbox": [140, 100, 180, 200]}, {"track_id": 2, "court": [3.0, 11.0], "bbox": [140, 20, 180, 100]}],
               "ball": None} for i in range(int(12 * FPS))]
    (folder / "tracks.json").write_text(json.dumps({"fps": FPS, "frames": frames}), encoding="utf-8")
    if with_video:
        w = cv2.VideoWriter(str(folder / "source.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (320, 240))
        for _ in range(int(12 * FPS)):
            w.write(np.full((240, 320, 3), (50, 110, 50), np.uint8))
        w.release()
    with Session(engine) as s:
        import_folder(folder, s)


def test_the_listing_has_only_matches_with_a_highlight_and_counts_the_rest(client, tmp_path):
    hl = {"clip_url": "/media/m_hl_a/highlight.mp4", "clip_start": 1.0, "clip_end": 9.0, "duration_s": 8.0, "track_id": 2, "t": 4.0, "shot": "smash",
          "score": 91.0, "outcome": "winner", "technique": 0.7, "confidence": 0.8, "why": "x", "basis": "outcome"}
    make_match(tmp_path, "m_hl_a", highlight=hl)
    make_match(tmp_path, "m_hl_none", with_video=False)
    out = client.get("/v1/highlights").json()
    ids = [h["match_id"] for h in out["highlights"]]
    assert "m_hl_a" in ids and "m_hl_none" not in ids and out["matches_without"] >= 1
    a = next(h for h in out["highlights"] if h["match_id"] == "m_hl_a")
    assert a["highlight"]["score"] == 91.0 and a["best_player"] == "Far player" and a["players"] == ["Near player", "Far player"]
    assert "m_001" not in ids                                           # the repository's sample match is never listed
    assert client.get("/v1/matches/m_hl_a").json()["highlight"]["clip_url"] == "/media/m_hl_a/highlight.mp4"


def test_backfill_cuts_a_highlight_for_an_old_match_from_its_own_stored_data(client, tmp_path):
    make_match(tmp_path, "m_hl_old")
    with Session(engine) as s:
        res = dict(highlights.backfill(s, only="m_hl_old"))
    assert res == {"m_hl_old": "made"}
    data = json.loads((settings.media_dir / "m_hl_old" / "match.json").read_text(encoding="utf-8"))
    hl = data["highlight"]
    assert hl["duration_s"] == 8.0 and hl["track_id"] == 2 and hl["outcome"] == "winner"           # the winning shot (player 2) is the best of the match
    assert (settings.media_dir / "m_hl_old" / "highlight.mp4").stat().st_size > 1000
    assert all("shot_rating" in e for e in data["events"] if e["type"] == "hit")                    # the stored events were rated with the same rules
    assert next(h for h in client.get("/v1/highlights").json()["highlights"] if h["match_id"] == "m_hl_old")["highlight"]["clip_url"].endswith("highlight.mp4")


def test_backfill_is_idempotent_and_says_why_it_skips(client, tmp_path):
    make_match(tmp_path, "m_hl_twice")
    make_match(tmp_path, "m_hl_novideo", with_video=False)
    make_match(tmp_path, "m_hl_uncal", rated=False)
    with Session(engine) as s:
        first = dict(highlights.backfill(s))
        second = dict(highlights.backfill(s))
    assert first["m_hl_twice"] == "made" and second["m_hl_twice"] == "already has one"
    assert first["m_hl_novideo"] == "no source video"
    assert first["m_hl_uncal"] == "no player stats (court not calibrated)"
