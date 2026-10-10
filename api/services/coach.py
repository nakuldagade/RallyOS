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


def _hit_time(data: dict, track_id: int, **where) -> list[float]:
    """Times of this player's hit events matching all of the given field values (for clip links)."""
    return [e["t"] for e in data["events"]
            if e["type"] == "hit" and e.get("track_id") == track_id and all(e.get(k) == v for k, v in where.items())]


def template_insights(data: dict) -> list[dict]:
    """Offline, deterministic insights. Every number written is in the stats, every insight cites its stat ids and
    links to the moments that show it (the slowest returns, the hits with no split-step, the fastest shot...)."""
    out = []
    names = _names(data)
    for tid, st in data["stats"].get("per_player", {}).items():
        t = int(tid)
        who = names.get(t)
        base = f"per_player.{tid}"
        fallback = _moments(data, t, 3)

        def add(text: str, ids: list[str], clip: list[float] | None) -> None:
            out.append({"player_track_id": t, "stat_ids": [f"{base}.{i}" for i in ids], "clip_t": clip or fallback, "text": text})

        if "avg_return_to_base_s" in st:
            if "pulled_away_n" in st and "returned_pct" in st:
                add(f"{who} takes {st['avg_return_to_base_s']} s on average to get back to base after being pulled out of position "
                    f"({st['pulled_away_n']} such shots) and is back in time after {round(st['returned_pct'] * 100)}% of them. "
                    "Drill: shadow footwork with a push-off and recovery step straight after every shot.",
                    ["avg_return_to_base_s", "pulled_away_n", "returned_pct"], st.get("slowest_return_t"))
            else:                                                    # older match files: the average alone
                add(f"{who} takes {st['avg_return_to_base_s']} s on average to return to base. "
                    "Drill: shadow footwork with a recovery step after every shot.", ["avg_return_to_base_s"], st.get("slowest_return_t"))
        fat = st.get("fatigue") or {}
        if fat.get("enough_data") and fat.get("return_change_pct") is not None:
            word = "slows" if fat["return_change_pct"] > 0 else "speeds up"
            add(f"{who}'s recovery {word} over the match: {fat['first_third_return_s']} s in the first third of their shots against "
                f"{fat['last_third_return_s']} s in the last third ({fat['return_change_pct']}%). "
                + ("That points to endurance rather than technique: add interval footwork work." if fat["return_change_pct"] > 15
                   else "No sign of fading."),
                ["fatigue.first_third_return_s", "fatigue.last_third_return_s", "fatigue.return_change_pct"],
                [fat["first_t"], fat["last_t"]])
        if "split_step_pct" in st:
            if "split_step_detected" in st and "split_step_n" in st:
                add(f"A split-step (both feet off the ground together as the opponent hits) was seen before {st['split_step_detected']} of "
                    f"{st['split_step_n']} opponent shots against {who}. Focus: time a small hop to land as the opponent makes contact. "
                    "This is read from ankle height at ordinary video frame rates, so treat it as a guide, not a count.",
                    ["split_step_detected", "split_step_n"], st.get("split_step_clip_t"))
            else:                                                    # older match files: the rate alone
                add(f"{who} uses a split-step on {round(st['split_step_pct'] * 100)}% of opponent shots. "
                    "Focus: time the split-step to the opponent's contact.", ["split_step_pct"], None)
        if st.get("most_zone"):
            add(f"{who} spends the most time in the {st['most_zone'].replace('-', ' ')} zone ({round(st['most_zone_pct'] * 100)}% of the tracked time).",
                ["most_zone", "most_zone_pct"], fallback)
        if st.get("fastest_shot_kmh") is not None:
            fast = next((e["t"] for e in data["events"] if e.get("track_id") == t and e.get("speed_kmh") == st["fastest_shot_kmh"]), None)
            add(f"{who}'s fastest shot averaged about {st['fastest_shot_kmh']} km/h from contact to the next contact or landing "
                "(an average horizontal speed, so the shuttle's peak speed is higher).",
                ["fastest_shot_kmh"], [fast] if fast is not None else None)
        mix = st.get("shot_mix") or {}
        if mix:
            top = max(mix, key=mix.get)
            add(f"{who}'s most-used shot is the {top} ({mix[top]} times).", [f"shot_mix.{top}"], _hit_time(data, t, shot=top)[:3])
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
