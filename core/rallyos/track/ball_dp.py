"""Link per-frame ball candidates into one trajectory (§4.3 step 4).

Physics-consistency linking instead of a fixed search gate (a gate loses fast smashes and then locks onto
noise):
  1. seeds: triples of candidates in consecutive frames whose motion is smooth (velocity change small
     relative to speed) and below the maximum shuttle speed. Random noise almost never forms such triples.
  2. tracklets: each seed is extended forwards and backwards with constant-velocity prediction, allowing
     gaps of up to `max_skip` frames. Tracklets break at hits (abrupt reversals), which is fine: hit
     detection bridges the gap between the incoming and the outgoing tracklet.
  3. selection: the set of non-overlapping tracklets with the most supporting points is chosen over the
     whole clip (weighted interval scheduling), so long consistent flights win over short noise.
Frames not covered by a chosen tracklet stay empty; the gap filler flags any bridged frames as interpolated.
"""

from __future__ import annotations

import bisect
import math

REF_WIDTH = 1920
REF_FPS = 25.0


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def link_candidates(cands: list[list[tuple[float, float, float]]], width: int, fps: float = REF_FPS,
                    max_skip: int = 2, min_len: int = 4) -> list[dict | None]:
    """cands[t] = [(x, y, score), ...] in pixels -> per-frame ball dicts (tracks.json shape) or None."""
    n = len(cands)
    k = (width / REF_WIDTH) * (REF_FPS / fps)
    vmax = 160.0 * k                       # px/frame: faster than any smash seen at 1080p / 25 fps
    abs_tol = 6.0 * (width / REF_WIDTH)

    def smooth(v1, v2) -> bool:
        s1, s2 = math.hypot(*v1), math.hypot(*v2)
        if s1 > vmax or s2 > vmax or max(s1, s2) < 0.5:
            return False
        return math.hypot(v2[0] - v1[0], v2[1] - v1[1]) <= abs_tol + 0.3 * max(s1, s2)

    # 1. seeds
    seeds = []
    for t in range(1, n - 1):
        for c in cands[t]:
            for p in cands[t - 1]:
                v1 = (c[0] - p[0], c[1] - p[1])
                if math.hypot(*v1) > vmax:
                    continue
                for q in cands[t + 1]:
                    v2 = (q[0] - c[0], q[1] - c[1])
                    if smooth(v1, v2):
                        seeds.append((p[2] + c[2] + q[2], t, p, c, q))
    seeds.sort(key=lambda s: -s[0])

    # 2. tracklets
    def extend(track: list[tuple[int, tuple]], direction: int) -> None:
        while True:
            (ta, a), (tb, b) = (track[-2], track[-1]) if direction > 0 else (track[1], track[0])
            span = tb - ta
            v = ((b[0] - a[0]) / span, (b[1] - a[1]) / span)
            speed = math.hypot(*v)
            best = None
            for step in range(1, max_skip + 2):
                t = tb + direction * step
                if t < 0 or t >= n:
                    break
                pred = (b[0] + v[0] * step, b[1] + v[1] * step)
                tol = abs_tol * step + 0.35 * speed * step
                for c in cands[t]:
                    d = _dist(c, pred)
                    if d <= tol and _dist(c, b) / step <= vmax and (best is None or d < best[0]):
                        best = (d, t, c)
                if best:
                    break
            if best is None:
                return
            if direction > 0:
                track.append((best[1], best[2]))
            else:
                track.insert(0, (best[1], best[2]))

    used: set[tuple[int, float, float]] = set()
    tracklets = []
    for _, t, p, c, q in seeds:
        if (t, c[0], c[1]) in used:
            continue
        track = [(t - 1, p), (t, c), (t + 1, q)]
        extend(track, +1)
        extend(track, -1)
        for tt, cc in track:
            used.add((tt, cc[0], cc[1]))
        if len(track) >= min_len:
            tracklets.append(track)

    # 3. best non-overlapping set (weighted interval scheduling, weight = supporting points)
    tracklets.sort(key=lambda tr: tr[-1][0])
    ends = [tr[-1][0] for tr in tracklets]
    best = [0.0] * (len(tracklets) + 1)
    take = [False] * len(tracklets)
    for i, tr in enumerate(tracklets):
        j = bisect.bisect_left(ends, tr[0][0], 0, i)    # tracklets ending before this one starts
        with_it = best[j] + len(tr) + 0.01 * sum(c[2] for _, c in tr) / len(tr)
        take[i] = with_it > best[i]
        best[i + 1] = max(best[i], with_it)
    chosen = []
    i = len(tracklets) - 1
    while i >= 0:
        if take[i]:
            chosen.append(tracklets[i])
            i = bisect.bisect_left(ends, tracklets[i][0][0], 0, i) - 1
        else:
            i -= 1

    scores = sorted(c[2] for tr in chosen for _, c in tr)
    ref = scores[len(scores) // 2] if scores else 1.0
    out: list[dict | None] = [None] * n
    for seg, tr in enumerate(sorted(chosen, key=lambda tr: tr[0][0])):
        length_conf = min(1.0, 0.55 + 0.03 * len(tr))
        for t, c in tr:
            conf = length_conf * min(0.95, 0.35 + 0.6 * c[2] / (c[2] + ref))
            # "seg" = tracklet index: hits are where one flight ends and the next begins (events/hits.py)
            out[t] = {"px": [c[0], c[1]], "court": None, "conf": round(conf, 3), "interp": False, "seg": seg}
    return out
