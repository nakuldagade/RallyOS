"""The player chat: same access rules as the analysis, grounded template answers, nothing invented without data."""
from api.services import player_chat
from api.tests.test_accounts import client, headers, matches  # noqa: F401 (fixtures)


def ask(client, who, player, text, history=None):
    msgs = (history or []) + [{"role": "user", "content": text}]
    return client.post(f"/v1/players/{player}/chat", json={"messages": msgs}, headers=who)


def test_chat_needs_login_and_follows_the_analysis_access_rules(client, matches):
    assert client.post("/v1/players/p_anika/chat", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401
    anika, rohan = headers(client, "anika@rallyos.demo"), headers(client, "rohan@rallyos.demo")
    assert ask(client, anika, "p_anika", "how am I doing?").status_code == 200
    assert ask(client, rohan, "p_anika", "how is she doing?").status_code == 403
    assert ask(client, headers(client, "coach.vikram@rallyos.demo"), "p_anika", "summary").status_code == 200


def test_chat_rejects_a_conversation_that_does_not_end_with_the_user(client, matches):
    anika = headers(client, "anika@rallyos.demo")
    r = client.post("/v1/players/p_anika/chat", json={"messages": [{"role": "assistant", "content": "hello"}]}, headers=anika)
    assert r.status_code == 422


def test_answers_are_templated_from_the_facts_and_cite_matches(client, matches):
    anika = headers(client, "anika@rallyos.demo")
    for q in ("Am I improving?", "What should I improve?", "What is my best strength?", "Where do I position myself?", "Which shots do I use?", "Tell me about my games"):
        body = ask(client, anika, "p_anika", q).json()
        assert body["answer"] and body["source"] == "template"
        assert body["match_ids"]


def test_a_player_without_matches_gets_no_made_up_analysis(client):
    r = client.post("/v1/auth/register", json={"name": "Chat Newbie", "email": "chatnew@example.com", "password": "longenough1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    body = ask(client, h, r["user"]["player_id"], "Am I improving?").json()
    assert "nothing to analyse" in body["answer"] and body["match_ids"] == []


def test_every_number_in_a_template_answer_is_in_the_facts(client, matches):
    from api.db import get_session
    from api.main import app
    from api.services import coach

    session = next(app.dependency_overrides.get(get_session, get_session)())
    f = player_chat.facts(session, "p_anika")
    for q in ("Am I improving?", "What should I improve?", "best", "position", "shots"):
        text = player_chat.template_answer(q, f)
        assert coach.numbers_grounded(text, f), text


def test_a_match_gets_a_summary_from_its_own_stats(client, matches):
    r = client.get("/v1/matches/m_001/summary")
    assert r.status_code == 200 and r.json()["summary"] and r.json()["source"] == "template"
    assert client.get("/v1/matches/nope/summary").status_code == 404
