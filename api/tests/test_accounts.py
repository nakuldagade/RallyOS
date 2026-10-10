"""Logins (player / coach), what each may see, a player's history and full analysis, and the coach dashboard.

The three matches are small hand-written match files with different stats per match (so each comparison has a known answer);
the analysis itself only reads what the matches hold.
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.config import settings
from api.db import engine
from api.main import app
from api.models import Match
from api.seed import DEMO_PASSWORD, main as seed
from api.services import auth
from api.services.importer import import_folder

W, L = 6.1, 13.4


@pytest.fixture(scope="module")
def client():
    seed()
    with TestClient(app) as c:
        yield c


OTHER = {"email": "other.coach@example.com", "password": "longenough1"}


def other_coach(client):
    """A second coach with an empty roster, made by registering (the demo database has only one coach)."""
    r = client.post("/v1/auth/register", json={"name": "Other Coach", **OTHER, "role": "coach"})
    if r.status_code == 409:
        r = client.post("/v1/auth/login", json={**OTHER, "role": "coach"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def login(client, email, role=None, password=DEMO_PASSWORD):
    r = client.post("/v1/auth/login", json={"email": email, "password": password, **({"role": role} if role else {})})
    return r


def headers(client, email, role=None):
    r = login(client, email, role)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def write_match(tmp_path, match_id: str, p1_stats: dict, p2_stats: dict, far_at=(1.0, 12.0), near_at=(3.0, 3.0), winner=1):
    base = json.loads((settings.mock_dir / "match.json").read_text(encoding="utf-8"))
    base.update(match_id=match_id, sport="badminton")
    base["players"] = [{"track_id": 1, "player_id": None, "name": "Near player", "side": "near", "color": "#3b82f6"},
                       {"track_id": 2, "player_id": None, "name": "Far player", "side": "far", "color": "#ef4444"}]
    base["stats"] = {"per_player": {"1": p1_stats, "2": p2_stats}, "match": {}}
    base["score"] = {"games": [], "winner_track_id": winner, "confirmed_by_human": False}
    base["video"] = {**base["video"], "duration_s": 60.0, "src": f"/media/{match_id}/source.mp4"}
    base["disputes"], base["insights"] = [], []
    folder = tmp_path / match_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "match.json").write_text(json.dumps(base), encoding="utf-8")
    frames = [{"f": i, "players": [{"track_id": 1, "court": list(near_at)}, {"track_id": 2, "court": list(far_at)}], "ball": None} for i in range(40)]
    (folder / "tracks.json").write_text(json.dumps({"fps": 25, "frames": frames}), encoding="utf-8")
    with Session(engine) as s:
        import_folder(folder, s)


def stats(ret, split, fastest, dist=120.0, best=70.0):
    return {"hits": 10, "distance_m": dist, "avg_return_to_base_s": ret, "returned_pct": 0.6, "split_step_pct": split,
            "fastest_shot_kmh": fastest, "fastest_shot_err_pct": 25, "top_speed_mps": 4.0, "shot_mix": {"drive": 3, "clear": 2},
            "zone_pct": {"rear-left": 0.5, "front-right": 0.5},
            "best_shot": {"t": 5.0, "shot": "clear", "outcome": "kept_going", "score": best, "technique": 0.5, "confidence": 0.6, "why": "x"},
            "best_shots": [{"t": 5.0, "shot": "clear", "outcome": "kept_going", "score": best, "technique": 0.5, "confidence": 0.6, "why": "x"}]}


@pytest.fixture(scope="module")
def matches(client, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("acct")
    # Anika is side 1 in matches a and c and side 2 in b, so both a near-side and a far-side history are used
    write_match(tmp, "m_acct_a", stats(1.4, 0.40, 200), stats(1.0, 0.5, 150))
    write_match(tmp, "m_acct_b", stats(1.2, 0.5, 180), stats(1.2, 0.55, 210), winner=2)
    write_match(tmp, "m_acct_c", stats(0.8, 0.70, 230), stats(1.3, 0.3, 160))
    h = headers(client, "anika@rallyos.demo")
    for mid, s1, s2 in (("m_acct_a", "p_anika", "p_rohan"), ("m_acct_b", "p_kabir", "p_anika"), ("m_acct_c", "p_anika", "p_rohan")):
        with Session(engine) as s:                                    # keep created_at in the order a, b, c
            m = s.get(Match, mid)
            m.created_at = "2026-10-0" + mid[-1].translate(str.maketrans("abc", "123")) + "T10:00:00"
            s.add(m)
            s.commit()
        assert client.post(f"/v1/matches/{mid}/players", json={"side1": s1, "side2": s2}, headers=h).status_code == 200
    return ["m_acct_a", "m_acct_b", "m_acct_c"]


# -- logins ----------------------------------------------------------------------------------------------------------------

def test_a_player_and_a_coach_log_in_and_the_token_says_who_they_are(client):
    p = login(client, "anika@rallyos.demo", "player")
    assert p.status_code == 200 and p.json()["user"]["role"] == "player" and p.json()["user"]["player_id"] == "p_anika"
    c = login(client, "coach.vikram@rallyos.demo", "coach")
    assert c.status_code == 200 and c.json()["user"]["role"] == "coach" and c.json()["user"]["player_id"] is None
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {p.json()['token']}"})
    assert me.status_code == 200 and me.json()["email"] == "anika@rallyos.demo"


def test_wrong_password_unknown_email_and_the_wrong_door_are_refused(client):
    assert login(client, "anika@rallyos.demo", password="nope-nope").status_code == 401
    assert login(client, "nobody@rallyos.demo").status_code == 401
    wrong_door = login(client, "anika@rallyos.demo", "coach")
    assert wrong_door.status_code == 403 and "player account" in wrong_door.json()["detail"]
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer abc.def"}).status_code == 401


def test_tokens_cannot_be_forged_or_reused_after_they_expire():
    t = auth.make_token(7, "coach")
    assert auth.read_token(t)["uid"] == 7
    body, sig = t.split(".")
    assert auth.read_token(f"{body}.{sig[:-2]}xx") is None                       # altered signature
    player_sig = auth.make_token(7, "player").split(".")[1]
    assert auth.read_token(f"{body}.{player_sig}") is None                           # a coach payload with a player's signature
    assert auth.read_token(auth.make_token(7, "coach", ttl=-5)) is None            # expired
    assert auth.verify_password("secret-pass", auth.hash_password("secret-pass")) and not auth.verify_password("x", auth.hash_password("y"))


def test_registering_makes_a_player_with_a_profile_or_a_coach(client):
    r = client.post("/v1/auth/register", json={"name": "Tara Singh", "email": "Tara@Example.com", "password": "longenough1", "role": "player"})
    assert r.status_code == 201 and r.json()["user"]["player_id"] == "p_tara_singh"
    assert client.get("/v1/players/p_tara_singh").json()["name"] == "Tara Singh"
    assert login(client, "tara@example.com", "player", "longenough1").status_code == 200       # the email is case-insensitive
    assert client.post("/v1/auth/register", json={"name": "T", "email": "tara@example.com", "password": "longenough1"}).status_code == 409
    assert client.post("/v1/auth/register", json={"name": "T", "email": "x@example.com", "password": "short"}).status_code == 400
    assert client.post("/v1/auth/register", json={"name": "T", "email": "bad", "password": "longenough1"}).status_code == 400
    assert client.post("/v1/auth/register", json={"name": "T", "email": "y@example.com", "password": "longenough1", "role": "admin"}).status_code == 400
    c = client.post("/v1/auth/register", json={"name": "Coach Z", "email": "z@example.com", "password": "longenough1", "role": "coach"})
    assert c.status_code == 201 and c.json()["user"]["role"] == "coach"


# -- who may see what ----------------------------------------------------------------------------------------------------------

def test_a_player_sees_only_their_own_analysis_and_a_coach_only_their_roster(client, matches):
    assert client.get("/v1/players/p_anika/analysis").status_code == 401
    anika, rohan = headers(client, "anika@rallyos.demo"), headers(client, "rohan@rallyos.demo")
    assert client.get("/v1/players/p_anika/analysis", headers=anika).status_code == 200
    assert client.get("/v1/players/p_anika/analysis", headers=rohan).status_code == 403
    vikram, other = headers(client, "coach.vikram@rallyos.demo"), other_coach(client)
    assert client.get("/v1/players/p_anika/analysis", headers=vikram).status_code == 200            # the demo coach has every player
    assert client.get("/v1/players/p_meera/analysis", headers=vikram).status_code == 200
    assert client.get("/v1/players/p_anika/analysis", headers=other).status_code == 403             # a coach who did not add her: no
    assert client.get("/v1/players/p_nobody/analysis", headers=vikram).status_code == 403


def test_only_coaches_reach_the_coach_dashboard_and_roster(client):
    assert client.get("/v1/coach/dashboard").status_code == 401
    assert client.get("/v1/coach/dashboard", headers=headers(client, "anika@rallyos.demo")).status_code == 403
    assert client.post("/v1/coach/roster", json={"player_id": "p_meera"}, headers=headers(client, "anika@rallyos.demo")).status_code == 403


# -- the analysis ---------------------------------------------------------------------------------------------------------------

def test_the_history_lists_only_the_players_own_matches_oldest_first_with_their_own_stats(client, matches):
    a = client.get("/v1/players/p_anika/analysis", headers=headers(client, "anika@rallyos.demo")).json()
    assert [m["match_id"] for m in a["matches"]] == matches
    assert [m["opponent"] for m in a["matches"]] == ["Rohan", "Kabir", "Rohan"]
    # Anika is side 1 in a and c (return 1.4 and 0.8) and side 2 in b (return 1.2): her own numbers, not her opponent's
    assert [m["metrics"]["avg_return_to_base_s"] for m in a["matches"]] == [1.4, 1.0 + 0.2, 0.8] or \
        [m["metrics"]["avg_return_to_base_s"] for m in a["matches"]] == [1.4, 1.2, 0.8]
    assert [m["result"] for m in a["matches"]] == ["won", "won", "won"]               # b was won by track 2, which is Anika there
    assert a["summary"]["matches"] == 3 and a["summary"]["wins"] == 3
    assert a["data_note"].startswith("Built from the matches")


def test_the_latest_match_is_compared_with_the_earlier_ones_in_the_right_direction(client, matches):
    a = client.get("/v1/players/p_anika/analysis", headers=headers(client, "anika@rallyos.demo")).json()
    c = {x["metric"]: x for x in a["compare"]}
    assert c["avg_return_to_base_s"]["verdict"] == "better" and c["avg_return_to_base_s"]["latest"] == 0.8     # lower is better
    assert c["avg_return_to_base_s"]["earlier"] == pytest.approx((1.4 + 1.2) / 2) and c["avg_return_to_base_s"]["n_earlier"] == 2
    assert c["split_step_pct"]["verdict"] == "better"
    assert any("Return to base improved" in i["text"] for i in a["insights"])


def test_the_heatmap_adds_up_every_match_in_the_players_own_half(client, matches):
    a = client.get("/v1/players/p_anika/analysis", headers=headers(client, "anika@rallyos.demo")).json()
    h = a["heatmap"]
    assert h["cell"] == 0.5 and h["frames"] == 3 * 40 and h["court"] == {"length": L, "width": W}
    # side 1 (near) matches a and c: she stood at (3.0, 3.0). Side 2 (far) match b: she stood at (1.0, 12.0) -> turned round: (5.1, 1.4)
    near_cell = h["all"][int(3.0 // 0.5)][int(3.0 // 0.5)]
    far_turned = h["all"][int(1.4 // 0.5)][int(5.1 // 0.5)]
    assert near_cell == 1.0 and far_turned == pytest.approx(40 / 80, abs=0.01)         # 80 frames at the near spot, 40 at the turned one
    assert h["latest"][int(3.0 // 0.5)][int(3.0 // 0.5)] == 1.0 and h["earlier"] is not None


def test_an_old_average_fastest_shot_is_not_compared_with_a_launch_speed_and_tiny_changes_are_not_announced(client, tmp_path):
    old = stats(0.18, 0.40, 90)
    old.pop("fastest_shot_err_pct")                                   # an older analysis: the average over the flight, no band
    write_match(tmp_path, "m_acct_old", old, stats(1.0, 0.5, 150))
    write_match(tmp_path, "m_acct_new", stats(0.26, 0.42, 230), stats(1.0, 0.5, 150))
    h = headers(client, "anika@rallyos.demo")
    with Session(engine) as s:
        for mid, day in (("m_acct_old", "04"), ("m_acct_new", "05")):
            m = s.get(Match, mid)
            m.created_at = f"2026-10-{day}T10:00:00"
            s.add(m)
        s.commit()
    pid = client.post("/v1/auth/register", json={"name": "Dev Patel", "email": "dev@example.com", "password": "longenough1"}).json()
    assert client.post("/v1/matches/m_acct_old/players", json={"side1": pid["user"]["player_id"]}, headers=h).status_code == 200
    assert client.post("/v1/matches/m_acct_new/players", json={"side1": pid["user"]["player_id"]}, headers=h).status_code == 200
    a = client.get(f"/v1/players/{pid['user']['player_id']}/analysis", headers={"Authorization": f"Bearer {pid['token']}"}).json()
    assert a["matches"][0]["metrics"]["fastest_shot_kmh"] is None and a["matches"][1]["metrics"]["fastest_shot_kmh"] == 230
    c = {x["metric"]: x for x in a["compare"]}
    assert "fastest_shot_kmh" not in c                                # nothing earlier to compare a launch speed with
    assert c["avg_return_to_base_s"]["verdict"] == "steady"           # 0.18 s -> 0.26 s is +44% but only 0.08 s: not announced
    assert c["split_step_pct"]["verdict"] == "steady"


def test_a_player_with_no_analysed_match_gets_nothing_made_up(client):
    r = client.post("/v1/auth/register", json={"name": "New Player", "email": "new@example.com", "password": "longenough1"}).json()
    a = client.get(f"/v1/players/{r['user']['player_id']}/analysis", headers={"Authorization": f"Bearer {r['token']}"}).json()
    assert a["matches"] == [] and a["compare"] == [] and a["insights"] == [] and a["best_shots"] == [] and a["shot_mix"] == {}
    assert a["heatmap"]["all"] is None and a["summary"]["matches"] == 0


def test_two_players_have_different_histories(client, matches):
    a = client.get("/v1/players/p_anika/analysis", headers=headers(client, "anika@rallyos.demo")).json()
    k = client.get("/v1/players/p_kabir/analysis", headers=headers(client, "coach.vikram@rallyos.demo")).json()
    assert [m["match_id"] for m in k["matches"]] == ["m_acct_b"] and len(a["matches"]) == 3
    assert k["matches"][0]["metrics"]["avg_return_to_base_s"] == 1.2 and k["compare"] == []        # one match: nothing to compare yet


# -- the coach dashboard ----------------------------------------------------------------------------------------------------------

def test_there_is_one_demo_coach_with_every_player_and_an_old_second_coach_is_removed(client):
    from sqlmodel import select
    from api.models import CoachPlayer, User

    with Session(engine) as s:
        old = User(email="coach.neha@rallyos.demo", name="Coach Neha", role="coach")      # a database from before: it still has her
        s.add(old)
        s.commit()
        s.add(CoachPlayer(coach_user_id=old.id, player_id="p_meera"))
        s.commit()
    seed()
    with Session(engine) as s:
        coaches = [u.email for u in s.exec(select(User).where(User.role == "coach", User.email.like("%@rallyos.demo"))).all()]
        assert coaches == ["coach.vikram@rallyos.demo"]
        roster = {r.player_id for r in s.exec(select(CoachPlayer)).all() if r.coach_user_id == s.exec(select(User).where(User.email == coaches[0])).first().id}
        assert roster == {"p_anika", "p_rohan", "p_meera", "p_kabir", "p_isha"}


def test_the_coach_dashboard_lists_the_roster_with_what_changed(client, matches):
    d = client.get("/v1/coach/dashboard", headers=headers(client, "coach.vikram@rallyos.demo")).json()
    assert {p["player_id"] for p in d["players"]} == {"p_anika", "p_rohan", "p_meera", "p_kabir", "p_isha"}
    anika = next(p for p in d["players"] if p["player_id"] == "p_anika")
    assert anika["matches"] == 3 and anika["latest"]["match_id"] == "m_acct_c" and anika["improving"] and anika["rating_is_sample"] is True
    rohan = next(p for p in d["players"] if p["player_id"] == "p_rohan")
    assert rohan["matches"] == 2 and any(a["metric"] == "avg_return_to_base_s" for a in rohan["attention"])    # Rohan's return got slower
    assert client.get("/v1/coach/dashboard", headers=other_coach(client)).json()["players"] == []         # another coach sees none of them


def test_a_coach_manages_their_roster(client):
    h = other_coach(client)
    assert client.post("/v1/coach/roster", json={"player_id": "p_kabir"}, headers=h).status_code == 201
    assert client.get("/v1/players/p_kabir/analysis", headers=h).status_code == 200
    assert client.delete("/v1/coach/roster/p_kabir", headers=h).status_code == 200
    assert client.get("/v1/players/p_kabir/analysis", headers=h).status_code == 403
    assert client.post("/v1/coach/roster", json={"player_id": "p_ghost"}, headers=h).status_code == 404


# -- assigning players to a match ---------------------------------------------------------------------------------------------------

def test_assigning_players_changes_the_names_the_match_shows(client, matches):
    h = headers(client, "anika@rallyos.demo")
    m = client.get("/v1/matches/m_acct_a").json()
    assert [p["name"] for p in m["players"]] == ["Anika", "Rohan"] and m["players"][0]["player_id"] == "p_anika"
    assert client.post("/v1/matches/m_acct_a/players", json={"side1": "p_anika", "side2": "p_anika"}, headers=h).status_code == 400
    assert client.post("/v1/matches/m_acct_a/players", json={"side1": "p_ghost"}, headers=h).status_code == 404
    assert client.post("/v1/matches/m_nope/players", json={}, headers=h).status_code == 404
    assert client.post("/v1/matches/m_acct_a/players", json={"side1": "p_anika"}).status_code == 401
