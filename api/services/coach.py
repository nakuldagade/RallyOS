"""Grounded AI coach (AGENTS.md §4.9, rule 6).

Order: valid pipeline insights -> Claude (only if ANTHROPIC_API_KEY is set) -> deterministic templates.
Every insight must cite stat_ids that exist in the stats JSON and carry clip_t. Claude output is
additionally checked number-by-number: any number in the text that isn't in the stats is rejected.
Claude reports are cached per match + stats hash in RUNTIME_DIR so the demo doesn't re-call the API.
"""
import hashlib
import json
import logging
import re
from typing import Any

from api.config import settings

log = logging.getLogger(__name__)

_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")

SYSTEM_PROMPT = """You are RallyOS Coach, a racket-sports coach writing for a player and their coach.
You receive one match's computed statistics as JSON. Write 3 to 5 short, specific coaching insights.

Grounding rules (a validator enforces them; insights that break them are discarded):
- Use only numbers that appear in the stats JSON. You may write a fraction such as 0.61 as 61%. Never compute, estimate or invent any other number, and don't write clip times in the text.
- For each insight, list in stat_ids the dotted paths of every stat you used, e.g. "per_player.1.split_step_pct".
- For each insight, pick 1 to 3 clip_t values from the candidate moments provided for that player, so the viewer can watch the evidence.
- Name players by name, not track id. Explain what the number means for their game and suggest one drill or focus."""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "player_track_id": {"type": "integer"},
                    "text": {"type": "string"},
                    "stat_ids": {"type": "array", "items": {"type": "string"}},
                    "clip_t": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["player_track_id", "text", "stat_ids", "clip_t"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}


# -- grounding --------------------------------------------------------------

def resolve_stat(stats: dict, stat_id: str) -> Any:
    cur: Any = stats
    for part in stat_id.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def allowed_numbers(stats: dict) -> set[float]:
    """Every number in the stats, plus the usual ways of writing it (rounded, fraction as %)."""
    out: set[float] = set()
    for n in _numbers(stats):
        out |= {n, round(n), round(n, 1), round(n, 2)}
        if 0 <= n <= 1:
            out |= {round(n * 100), round(n * 100, 1)}
    return out


def numbers_grounded(text: str, stats: dict) -> bool:
    allowed = allowed_numbers(stats)
    return all(float(m) in allowed for m in _NUM.findall(text))


def validate(insight: dict, stats: dict) -> bool:
    ids = insight.get("stat_ids") or []
    return bool(ids) and bool(insight.get("clip_t")) and all(resolve_stat(stats, s) is not None for s in ids)


def validate_llm(insight: dict, data: dict) -> bool:
    duration = data.get("video", {}).get("duration_s") or float("inf")
    return (validate(insight, data.get("stats", {}))
            and all(0 <= t <= duration for t in insight["clip_t"])
            and numbers_grounded(insight.get("text", ""), data.get("stats", {})))


# -- sources ----------------------------------------------------------------

def _names(data: dict) -> dict[int, str]:
    return {p["track_id"]: p.get("name") or f"Player {p['track_id']}" for p in data["players"]}


def _moments(data: dict, track_id: int, limit: int = 8) -> list[float]:
    ts = [e["t"] for e in data["events"] if e.get("track_id") == track_id]
    return ts[:limit] or [e["t"] for e in data["events"][:limit]]


def template_insights(data: dict) -> list[dict]:
    out = []
    names = _names(data)
    for tid, st in data["stats"].get("per_player", {}).items():
        t = int(tid)
        clip = _moments(data, t, 3)
        if "avg_return_to_base_s" in st:
            out.append({"player_track_id": t, "stat_ids": [f"per_player.{tid}.avg_return_to_base_s"], "clip_t": clip,
                        "text": f"{names.get(t)} takes {st['avg_return_to_base_s']} s on average to return to base. "
                                "Drill: shadow footwork with a recovery step after every shot."})
        if "split_step_pct" in st:
            out.append({"player_track_id": t, "stat_ids": [f"per_player.{tid}.split_step_pct"], "clip_t": clip,
                        "text": f"{names.get(t)} uses a split-step on {round(st['split_step_pct'] * 100)}% of opponent shots. "
                                "Focus: time the split-step to the opponent's contact."})
        mix = st.get("shot_mix") or {}
        if mix:
            top = max(mix, key=mix.get)
            out.append({"player_track_id": t, "stat_ids": [f"per_player.{tid}.shot_mix.{top}"], "clip_t": clip,
                        "text": f"{names.get(t)}'s most-used shot is the {top} ({mix[top]} times)."})
    return out


def claude_insights(data: dict) -> list[dict]:
    """Ask Claude for insights; returns only the ones that pass validation. Raises on API errors."""
    import anthropic

    names = _names(data)
    payload = {
        "sport": data["sport"],
        "players": {str(t): n for t, n in names.items()},
        "stats": data.get("stats", {}),
        "candidate_clip_t": {str(t): _moments(data, t) for t in names},
    }
    client = anthropic.Anthropic(api_key=settings.anthropic_key)
    response = client.beta.messages.create(
        model=settings.coach_model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": REPORT_SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True)}],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        log.warning("coach: Claude stopped with %s; using templates", response.stop_reason)
        return []
    text = next((b.text for b in response.content if b.type == "text"), "")
    proposed = json.loads(text).get("insights", [])
    kept = [i for i in proposed if validate_llm(i, data)]
    if len(kept) < len(proposed):
        log.info("coach: rejected %d ungrounded insight(s)", len(proposed) - len(kept))
    return kept


# -- report -----------------------------------------------------------------

def _cached_claude(data: dict) -> list[dict]:
    key = hashlib.sha256(json.dumps(data.get("stats", {}), sort_keys=True).encode()).hexdigest()[:16]
    path = settings.runtime_dir / f"{data['match_id']}.report.{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    insights = claude_insights(data)
    if insights:
        path.write_text(json.dumps(insights, indent=2), encoding="utf-8")
    return insights


def build_report(data: dict, prefer: str = "auto") -> dict:
    """prefer: auto (pipeline -> claude -> template) | claude (skip pipeline insights) | template."""
    stats = data.get("stats", {})
    good = [i for i in data.get("insights", []) if validate(i, stats)] if prefer == "auto" else []
    source = "pipeline"
    if not good and prefer != "template" and settings.anthropic_key:
        try:
            good, source = _cached_claude(data), "claude"
        except Exception as exc:  # network down, bad key, bad JSON -> offline fallback
            log.warning("coach: Claude unavailable (%s); using templates", exc)
            good = []
    if not good:
        good, source = template_insights(data), "template"
    note = None
    if not good and not data.get("stats", {}).get("per_player"):
        note = ("No player stats in this match yet (e.g. a ball-only clip), so there is nothing to coach from. "
                "Insights appear once players and pose are tracked.")
    return {"match_id": data["match_id"], "source": source, "note": note,
            "insights": [{**i, "grounded": True} for i in good]}
