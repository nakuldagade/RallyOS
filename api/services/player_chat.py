"""Conversational analyst for one player (AGENTS.md §4.9 rules apply: grounded numbers only).

Facts come from `player_analysis.analysis` (real analysed matches only). With ANTHROPIC_API_KEY, Claude answers from
those facts and any number it writes that is not in them is rejected; without a key, or on any failure, a templated
answer is built from the same facts. Every answer lists the matches it drew on.
"""
import json
import logging
import re

from sqlmodel import Session

from api.config import settings
from api.services import coach, player_analysis

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are RallyOS Analyst, a friendly racket-sports analyst talking to a player or their coach about ONE player.
You receive that player's facts as JSON (all their analysed matches, oldest first, the latest against the earlier ones, shot mix, time by court zone, best shots).
Rules (a validator enforces the first one; an answer that breaks it is discarded):
- Use only numbers that appear in the facts. Never compute, estimate or invent another number.
- Say so plainly when the data is thin (for example only 1 or 2 matches): do not claim a trend you cannot support.
- Cover what was asked: how they play, where they position themselves, what is strongest, what to improve (with one concrete drill or focus), and whether they are improving, using 'compare' (verdict better / worse / steady).
- If sample_data is true, say these are simulated sample matches.
- Keep it short: at most about 120 words, plain sentences, no markdown headings."""


def facts(session: Session, player_id: str) -> dict:
    a = player_analysis.analysis(session, player_id)
    heat = (a["heatmap"] or {}).get("all")
    side = None
    if heat:
        half = len(heat[0]) / 2
        left = sum(v for row in heat for c, v in enumerate(row) if c < half)
        total = sum(v for row in heat for v in row) or 1.0
        side = {"left_pct": round(100 * left / total), "right_pct": 100 - round(100 * left / total)}
    return {
        "player": a["player"], "summary": a["summary"], "sample_data": bool(a.get("sample_data")),
        "matches": [{"match_id": r["match_id"], "opponent": r["opponent"], "result": r["result"], "hits": r["hits"],
                     "distance_m": r["distance_m"], "metrics": {k: v for k, v in r["metrics"].items() if v is not None}} for r in a["matches"]],
        "compare": [{k: c[k] for k in ("metric", "label", "unit", "earlier", "latest", "change_pct", "verdict", "n_earlier")} for c in a["compare"]],
        "shot_mix": a["shot_mix"],
        "zones_pct": {z: round(100 * v) for z, v in a["zones"].items()},
        "left_right_share": side,
        "best_shots": [{k: b.get(k) for k in ("shot", "score", "outcome", "match_id")} for b in a["best_shots"][:3]],
    }


def _thin(f: dict) -> str:
    n = f["summary"]["matches"]
    return f" This rests on only {n} analysed match{'es' if n != 1 else ''}, so read it as a pointer, not a verdict." if n < 4 else ""


def _val(c: dict, key: str) -> str:
    return f"{c[key]:g}%" if c["unit"] == "%" else f"{c[key]:g} {c['unit']}"


def template_answer(question: str, f: dict) -> str:
    q = question.lower()
    name = f["player"]["name"]
    n = f["summary"]["matches"]
    if n == 0:
        return f"No analysed match has {name} assigned to a side yet, so there is nothing to analyse. Assign the players on a match page ('Who played?') and ask again."
    cmp_ = f["compare"]
    better = [c for c in cmp_ if c["verdict"] == "better"]
    worse = [c for c in cmp_ if c["verdict"] == "worse"]
    zones = sorted(f["zones_pct"].items(), key=lambda kv: -kv[1])
    shots = sorted(f["shot_mix"].items(), key=lambda kv: -kv[1])
    parts: list[str] = []
    if re.search(r"improv(ing|ement)|progress|trend|getting|past|history|compare|better or worse", q):
        if n < 2:
            parts.append(f"{name} has one analysed match, so there is no past to compare with yet.")
        else:
            if better:
                parts.append("Improving: " + "; ".join(f"{c['label']} {_val(c, 'earlier')} to {_val(c, 'latest')}" for c in better) + ".")
            if worse:
                parts.append("Slipping: " + "; ".join(f"{c['label']} {_val(c, 'earlier')} to {_val(c, 'latest')}" for c in worse) + ".")
            if not better and not worse:
                parts.append("No metric has moved beyond normal match-to-match noise: the latest match is steady against the earlier ones.")
            else:
                parts.append("Overall: " + ("mostly improving." if len(better) > len(worse) else "mostly slipping." if len(worse) > len(better) else "about level."))
    elif re.search(r"improve|weak|work on|fix|drill|focus|bad", q):
        if worse:
            c = worse[0]
            parts.append(f"The clearest thing to work on is {c['label']}: {_val(c, 'earlier')} before, {_val(c, 'latest')} in the latest match.")
        elif cmp_:
            parts.append("Nothing has got clearly worse. Latest values to keep pushing: " + ", ".join(f"{c['label']} ({_val(c, 'latest')})" for c in cmp_[:3]) + ".")
        else:
            parts.append("There is not enough measured data to single out a weakness.")
        if any(c["metric"] in ("avg_return_to_base_s", "returned_pct") and c["verdict"] != "better" for c in cmp_):
            parts.append("Drill: shadow footwork back to the base position after every shot, in several short sets.")
    elif re.search(r"best|strong|good|strength|top", q):
        if better:
            parts.append(f"Strongest signal: {better[0]['label']} has improved ({_val(better[0], 'earlier')} to {_val(better[0], 'latest')}).")
        if f["best_shots"]:
            b = f["best_shots"][0]
            parts.append(f"Best shot: a {b['shot'] or 'shot'} with a best-shot score of {round(b['score'])}" + (f" ({b['outcome']})" if b.get("outcome") else "") + ".")
        if shots:
            parts.append(f"Most-used shot: {shots[0][0]} ({shots[0][1]} times).")
        if not parts:
            parts.append("No standout strength is measurable yet.")
    elif re.search(r"position|where|zone|court|heat|move|cover", q):
        if zones:
            parts.append("Time on court: " + ", ".join(f"{z.replace('_', ' ')} {v}%" for z, v in zones[:3]) + ".")
        lr = f["left_right_share"]
        if lr:
            parts.append(f"Left / right split: {lr['left_pct']}% / {lr['right_pct']}%.")
        parts.append(f"Distance covered across {n} match{'es' if n != 1 else ''}: {f['summary']['distance_m']} m.")
    elif re.search(r"shot|smash|clear|drop|serve", q):
        parts.append("Shots used: " + (", ".join(f"{s} {c}" for s, c in shots) if shots else "no shot types could be labelled") + ".")
    else:
        s = f["summary"]
        parts.append(f"{name}: {s['matches']} analysed match{'es' if s['matches'] != 1 else ''}, {s['wins']} won and {s['losses']} lost, {s['hits']} hits, {s['distance_m']} m covered.")
        if zones:
            parts.append(f"Mostly in {zones[0][0].replace('_', ' ')} ({zones[0][1]}%).")
        if better:
            parts.append(f"Improving: {better[0]['label']}.")
        if worse:
            parts.append(f"To work on: {worse[0]['label']}.")
    return " ".join(parts) + _thin(f) + (" These are generated sample matches, not real video." if f.get("sample_data") else "")


def claude_answer(history: list[dict], f: dict) -> str | None:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_key)
    msgs = [{"role": "user", "content": "FACTS:\n" + json.dumps(f, sort_keys=True)},
            {"role": "assistant", "content": "Understood. Ask me anything about this player."}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in history[-8:]]
    r = client.messages.create(model=settings.coach_model, max_tokens=600, system=SYSTEM_PROMPT, messages=msgs)
    text = next((b.text for b in r.content if b.type == "text"), "").strip()
    return text if text and coach.numbers_grounded(text, f) else None


def answer(session: Session, player_id: str, history: list[dict]) -> dict:
    f = facts(session, player_id)
    question = history[-1]["content"] if history else ""
    text, source = None, "template"
    if settings.anthropic_key and f["summary"]["matches"]:
        try:
            text = claude_answer(history, f)
            source = "claude"
        except Exception as e:  # network, quota, bad key: the templates still answer
            log.warning("player chat: Claude failed (%s); using templates", e)
    if not text:
        text, source = template_answer(question, f), "template"
    return {"answer": text, "source": source, "match_ids": [m["match_id"] for m in f["matches"]]}
