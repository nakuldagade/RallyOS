"""A plain-language summary of one analysed match, from its own stats only (same grounding rule as the coach).

With ANTHROPIC_API_KEY Claude writes it and any number not in the facts discards the text; otherwise (or on failure)
a template builds it from the same facts.
"""
import json
import logging

from api.config import settings
from api.services import coach

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RallyOS Analyst. You receive the computed facts of ONE analysed racket-sports match as JSON.
Write a short match summary (about 120 words, plain sentences, no headings): how the match went, who controlled it, how the rallies looked, each player's standout numbers, and what each should work on.
Use only numbers that appear in the facts; never compute or invent another. If something was not measured, say so."""


def facts(data: dict) -> dict:
    names = {p["track_id"]: p.get("name") or f"Player {p['track_id']}" for p in data.get("players", [])}
    per = (data.get("stats", {}).get("per_player") or {})
    players = {}
    for tid, name in names.items():
        s = per.get(str(tid)) or {}
        players[name] = {k: s[k] for k in ("hits", "distance_m", "avg_return_to_base_s", "returned_pct", "split_step_pct", "fastest_shot_kmh", "top_speed_mps") if s.get(k) is not None}
        if s.get("shot_mix"):
            players[name]["shot_mix"] = s["shot_mix"]
        if s.get("zone_pct"):
            players[name]["zone_pct"] = {z: round(100 * v) for z, v in s["zone_pct"].items()}
    score = data.get("score") or {}
    win = score.get("winner_track_id")
    return {
        "sport": data.get("sport"), "duration_s": round(float((data.get("video") or {}).get("duration_s") or 0)),
        "games": score.get("games") or [], "winner": names.get(win) if win else None,
        "match": data.get("stats", {}).get("match") or {}, "rallies": len(data.get("rallies", [])), "players": players,
        "insights": [i["text"] for i in data.get("insights", [])][:4],
    }


def template(f: dict) -> str:
    parts = [f"A {f['sport']} match of {f['duration_s']} s with {f['rallies']} rally{'s' if f['rallies'] != 1 else ''} analysed."]
    if f["games"]:
        parts.append("Score " + ", ".join("-".join(str(x) for x in g) for g in f["games"]) + (f"; {f['winner']} won." if f["winner"] else "."))
    else:
        parts.append("No score could be worked out from this clip.")
    m = f["match"]
    if m.get("avg_rally_hits"):
        parts.append(f"Rallies averaged {m['avg_rally_hits']} hits, the longest {m.get('longest_rally_hits', '—')}.")
    for name, s in f["players"].items():
        bits = []
        if "hits" in s:
            bits.append(f"{s['hits']} hits")
        if "distance_m" in s:
            bits.append(f"{s['distance_m']} m covered")
        if "fastest_shot_kmh" in s:
            bits.append(f"fastest shot about {s['fastest_shot_kmh']} km/h")
        if "avg_return_to_base_s" in s:
            bits.append(f"{s['avg_return_to_base_s']} s to return to base")
        if s.get("zone_pct"):
            z, v = max(s["zone_pct"].items(), key=lambda kv: kv[1])
            bits.append(f"{v}% of the time in the {z.replace('_', ' ')}")
        if bits:
            parts.append(f"{name}: " + ", ".join(bits) + ".")
    parts.extend(f["insights"][:2])
    if f["rallies"] < 3:
        parts.append("This is a short clip, so treat the numbers as indications.")
    return " ".join(parts)


def summarize(data: dict) -> dict:
    f = facts(data)
    if settings.anthropic_key:
        try:
            import anthropic

            r = anthropic.Anthropic(api_key=settings.anthropic_key).messages.create(
                model=settings.coach_model, max_tokens=500, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(f, sort_keys=True)}])
            text = next((b.text for b in r.content if b.type == "text"), "").strip()
            if text and coach.numbers_grounded(text, f):
                return {"summary": text, "source": "claude"}
        except Exception as e:
            log.warning("match summary: Claude failed (%s); using template", e)
    return {"summary": template(f), "source": "template"}
