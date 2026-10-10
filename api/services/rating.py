"""Glicko-2 (Glickman, "Example of the Glicko-2 system") + evidence multiplier.

Video-verified matches move a rating fully; assisted and self-reported matches move it less.
This is what links the camera to trust in the rating network (AGENTS.md §4.10).
"""
import math

from sqlmodel import Session, select

from api.models import Match, Player, RatingHistory

SCALE = 173.7178
TAU = 0.5
EVIDENCE_WEIGHT = {"self": 0.5, "assisted": 0.8, "video_verified": 1.0}


def _g(phi: float) -> float:
    return 1 / math.sqrt(1 + 3 * phi * phi / math.pi ** 2)


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1 / (1 + math.exp(-_g(phi_j) * (mu - mu_j)))


def glicko2(rating: float, rd: float, vol: float, results: list[tuple[float, float, float]],
            tau: float = TAU) -> tuple[float, float, float]:
    """One rating period. results = [(opp_rating, opp_rd, score 1/0.5/0), ...] -> (rating, rd, vol)."""
    mu, phi = (rating - 1500) / SCALE, rd / SCALE
    if not results:
        return rating, math.sqrt(phi * phi + vol * vol) * SCALE, vol

    opps = [((r - 1500) / SCALE, d / SCALE, s) for r, d, s in results]
    v = 1 / sum(_g(pj) ** 2 * _e(mu, mj, pj) * (1 - _e(mu, mj, pj)) for mj, pj, _ in opps)
    delta = v * sum(_g(pj) * (s - _e(mu, mj, pj)) for mj, pj, s in opps)

    # volatility: Illinois iteration (step 5 of the paper)
    a = math.log(vol * vol)

    def f(x: float) -> float:
        ex = math.exp(x)
        return ex * (delta ** 2 - phi ** 2 - v - ex) / (2 * (phi ** 2 + v + ex) ** 2) - (x - a) / tau ** 2

    lo = a
    if delta ** 2 > phi ** 2 + v:
        hi = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        hi = a - k * tau
    f_lo, f_hi = f(lo), f(hi)
    while abs(hi - lo) > 1e-6:
        c = lo + (lo - hi) * f_lo / (f_hi - f_lo)
        f_c = f(c)
        if f_c * f_hi <= 0:
            lo, f_lo = hi, f_hi
        else:
            f_lo /= 2
        hi, f_hi = c, f_c
    new_vol = math.exp(lo / 2)

    phi_star = math.sqrt(phi ** 2 + new_vol ** 2)
    new_phi = 1 / math.sqrt(1 / phi_star ** 2 + 1 / v)
    new_mu = mu + new_phi ** 2 * sum(_g(pj) * (s - _e(mu, mj, pj)) for mj, pj, s in opps)
    return new_mu * SCALE + 1500, new_phi * SCALE, new_vol


def weighted_update(player: Player, results: list[tuple[float, float, float]], evidence: str) -> tuple[float, float, float]:
    """Glicko-2 step scaled by how trustworthy the match record is."""
    w = EVIDENCE_WEIGHT.get(evidence, EVIDENCE_WEIGHT["self"])
    r, rd, vol = glicko2(player.rating, player.rd, player.vol, results)
    return (player.rating + w * (r - player.rating), player.rd + w * (rd - player.rd),
            player.vol + w * (vol - player.vol))


def apply_match(session: Session, match: Match) -> list[dict]:
    """Rate a decided singles match once. Returns the changes ([] if not rateable or already rated)."""
    if not (match.p1 and match.p2 and match.winner_player_id):
        return []
    if session.exec(select(RatingHistory).where(RatingHistory.match_id == match.id)).first():
        return []
    a, b = session.get(Player, match.p1), session.get(Player, match.p2)
    if not a or not b:
        return []
    s_a = 1.0 if match.winner_player_id == a.id else 0.0
    new_a = weighted_update(a, [(b.rating, b.rd, s_a)], match.evidence_level)
    new_b = weighted_update(b, [(a.rating, a.rd, 1 - s_a)], match.evidence_level)
    changes = []
    for p, (r, rd, vol) in ((a, new_a), (b, new_b)):
        changes.append({"player_id": p.id, "before": round(p.rating, 1), "after": round(r, 1),
                        "rd": round(rd, 1), "evidence_level": match.evidence_level})
        p.rating, p.rd, p.vol = r, rd, vol
        session.add(p)
        session.add(RatingHistory(player_id=p.id, match_id=match.id, rating=r, rd=rd,
                                  evidence_level=match.evidence_level))
    session.commit()
    return changes
