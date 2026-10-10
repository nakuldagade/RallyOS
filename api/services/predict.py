"""Explainable win probability: logistic model over rating gap, style matchup and head-to-head.
Each factor's contribution is in log-odds, so the top-3 list says exactly what moved the prediction."""
import math

Q = math.log(10) / 400
STYLE_WEIGHT = 0.8
H2H_WEIGHT = 0.6


def _g(rd: float) -> float:
    return 1 / math.sqrt(1 + 3 * (Q * rd) ** 2 / math.pi ** 2)


def win_probability(a, b, h2h: tuple[int, int] = (0, 0)) -> dict:
    """a, b are Player rows; h2h = (wins of a over b, wins of b over a)."""
    diff = a.rating - b.rating
    rd = math.sqrt(a.rd ** 2 + b.rd ** 2)
    factors = [{"factor": "rating_gap", "value": round(diff, 1),
                "contribution": Q * _g(rd) * diff,
                "explanation": f"{a.name or a.id} is rated {abs(round(diff))} {'above' if diff >= 0 else 'below'} "
                               f"{b.name or b.id} (combined uncertainty ±{round(rd)})"}]
    if a.style_vec and b.style_vec:
        edge = (sum(a.style_vec) - sum(b.style_vec)) / len(a.style_vec)
        factors.append({"factor": "style_matchup", "value": round(edge, 2), "contribution": STYLE_WEIGHT * edge,
                        "explanation": "style profile favours " + (a.name or a.id if edge >= 0 else b.name or b.id)})
    wins_a, wins_b = h2h
    if wins_a or wins_b:
        edge = (wins_a - wins_b) / (wins_a + wins_b + 2)
        factors.append({"factor": "head_to_head", "value": f"{wins_a}-{wins_b}", "contribution": H2H_WEIGHT * edge,
                        "explanation": f"head-to-head {wins_a}-{wins_b}"})
    logit = sum(f["contribution"] for f in factors)
    p = min(max(1 / (1 + math.exp(-logit)), 0.01), 0.99)
    factors.sort(key=lambda f: -abs(f["contribution"]))
    for f in factors:
        f["contribution"] = round(f["contribution"], 3)
    return {"a": a.id, "b": b.id, "p_a_wins": round(p, 3), "factors": factors[:3]}
