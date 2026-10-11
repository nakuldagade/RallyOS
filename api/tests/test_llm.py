"""The AI gateway door: request shape, grounding of what comes back, and the fall-back to templates. No network: httpx is faked."""
import json

import pytest

from api.config import settings
from api.services import llm
from api.tests.test_accounts import client, headers, matches  # noqa: F401 (fixtures)


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.text}}]}


@pytest.fixture
def gateway(monkeypatch):
    sent = []

    def install(answer):
        def fake_post(url, content=None, headers=None, timeout=None):
            sent.append({"url": url, "body": json.loads(content), "headers": headers})
            if isinstance(answer, Exception):
                raise answer
            return FakeResponse(answer)
        monkeypatch.setattr(llm.httpx, "post", fake_post)
        monkeypatch.setattr(settings, "ai_key", "team-key")
        return sent
    return install


def test_the_request_is_openai_chat_completions_with_the_right_token_parameter(gateway):
    sent = gateway("hello")
    assert llm.complete("sys", [{"role": "user", "content": "hi"}], max_tokens=50) == "hello"
    b = sent[0]["body"]
    assert sent[0]["headers"]["Authorization"] == "Bearer team-key" and b["stream"] is False
    assert b["model"] == settings.ai_model and b["max_completion_tokens"] == 50 and "max_tokens" not in b
    assert b["messages"][0] == {"role": "system", "content": "sys"}
    settings.ai_model, old = "deepseek-v4-pro", settings.ai_model
    try:
        llm.complete("sys", [{"role": "user", "content": "hi"}], max_tokens=50)
    finally:
        settings.ai_model = old
    assert sent[1]["body"]["max_tokens"] == 50 and "max_completion_tokens" not in sent[1]["body"]


def test_a_request_over_48_kb_is_refused_before_it_is_sent(gateway):
    sent = gateway("x")
    with pytest.raises(ValueError):
        llm.complete("sys", [{"role": "user", "content": "a" * 50000}])
    assert sent == []


def test_json_is_found_inside_a_fenced_answer():
    assert llm.parse_json('Sure:\n```json\n{"insights": []}\n```') == {"insights": []}


def test_the_summary_uses_the_ai_only_when_every_number_is_in_the_stats(client, matches, gateway):
    gateway("Tara played 66 hits and covered 9999 m.")                   # 9999 is not in the stats
    assert client.get("/v1/matches/m_001/summary").json()["source"] == "template"
    from api.services import match_summary, store
    f = match_summary.facts(store.load_match("m_001"))
    ok = f"The match had {f['rallies']} rallies."
    gateway(ok)
    r = client.get("/v1/matches/m_001/summary").json()
    assert r == {"summary": ok, "source": "claude"}


def test_the_chat_falls_back_to_the_template_when_the_gateway_fails(client, matches, gateway):
    gateway(RuntimeError("gateway down"))
    r = client.post("/v1/players/p_anika/chat", json={"messages": [{"role": "user", "content": "Am I improving?"}]}, headers=headers(client, "anika@rallyos.demo"))
    assert r.status_code == 200 and r.json()["source"] == "template"
