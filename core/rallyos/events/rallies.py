"""Rally segmentation from hit events (§4.4): a new rally starts after a long pause between hits."""

from __future__ import annotations


def segment_rallies(hits: list[dict], duration_s: float, max_pause_s: float = 4.0, min_hits: int = 2,
                    lead_s: float = 0.5, tail_s: float = 1.5) -> list[dict]:
    """Group time-ordered hits into rallies. Returns rallies with their hit list and a confidence."""
    groups: list[list[dict]] = []
    for h in sorted(hits, key=lambda x: x["t"]):
        if groups and h["t"] - groups[-1][-1]["t"] <= max_pause_s:
            groups[-1].append(h)
        else:
            groups.append([h])
    rallies = []
    for g in groups:
        if len(g) < min_hits:
            continue
        rallies.append({
            "idx": len(rallies),
            "t_start": round(max(0.0, g[0]["t"] - lead_s), 2),
            "t_end": round(min(duration_s, g[-1]["t"] + tail_s), 2),
            "hits": len(g),
            "winner_track_id": None, "end_reason": None, "score_after": None,
            # mean hit confidence; hits not confirmed by audio + vision together are discounted
            "confidence": round(sum(h["confidence"] * (1.0 if len(h.get("source", ())) > 1 else 0.8)
                                    for h in g) / len(g), 2),
            "hit_frames": [h["frame"] for h in g],
        })
    return rallies
