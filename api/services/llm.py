"""One door to the language model, for the chatbot, the match summary and the coach report.

Order: the Elevate AI gateway (an OpenAI Chat Completions endpoint, `Authorization: Bearer <team key>`, no streaming, text only,
at most 48 KB a request) when AI_GATEWAY_KEY is set; else Anthropic when ANTHROPIC_API_KEY is set; else nothing, and the callers
use their templates. Callers still check every number the model writes against the stats, so which model answers does not
change the grounding rule.
"""
import json
import logging

import httpx

from api.config import settings

log = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 48 * 1024
MAX_OUTPUT_TOKENS = 4000                  # the gateway refuses anything above this


def available() -> bool:
    return bool(settings.ai_key or settings.anthropic_key)


def provider() -> str:
    return "gateway" if settings.ai_key else "anthropic" if settings.anthropic_key else "none"


def _gateway(system: str, messages: list[dict], max_tokens: int, model: str) -> str:
    """One gateway call. A reasoning model (gpt-5-mini) can spend the whole budget thinking and return nothing
    (finish_reason "length", empty text): it is asked once more with the largest budget the gateway allows."""
    for budget in (min(max_tokens, MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS):
        body = {"model": model, "messages": [{"role": "system", "content": system}, *messages], "stream": False}
        # DeepSeek names the output limit max_tokens, the GPT models max_completion_tokens
        body["max_tokens" if model.startswith("deepseek") else "max_completion_tokens"] = budget
        raw = json.dumps(body)
        if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("request larger than the gateway's 48 KB limit")
        r = httpx.post(settings.ai_url, content=raw, timeout=90.0,
                       headers={"Authorization": f"Bearer {settings.ai_key}", "Content-Type": "application/json"})
        r.raise_for_status()
        choice = r.json()["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if text or choice.get("finish_reason") != "length" or budget >= MAX_OUTPUT_TOKENS:
            return text
    return ""


def _anthropic(system: str, messages: list[dict], max_tokens: int) -> str:
    import anthropic

    r = anthropic.Anthropic(api_key=settings.anthropic_key).messages.create(
        model=settings.coach_model, max_tokens=max_tokens, system=system, messages=messages)
    return next((b.text for b in r.content if b.type == "text"), "").strip()


def complete(system: str, messages: list[dict], max_tokens: int = 800, report: bool = False) -> str:
    """The model's text answer. Raises on any network / key / size problem (callers fall back to templates)."""
    if settings.ai_key:
        return _gateway(system, messages, max_tokens, settings.ai_report_model if report else settings.ai_model)
    if settings.anthropic_key:
        return _anthropic(system, messages, max_tokens)
    raise RuntimeError("no AI key configured")


def parse_json(text: str) -> dict:
    """The first JSON object in a model answer (models sometimes wrap it in a code fence or a sentence)."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[a:b + 1])
