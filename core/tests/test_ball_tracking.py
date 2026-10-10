"""Tracklet linker + hit detection: fast smashes stay tracked, noise is rejected, hidden contacts still count."""

import random

from rallyos.events.hits import detect_hits, tracklet_hits
from rallyos.track.ball_dp import link_candidates


def flight(n, start, vel, acc=(0.0, 0.0)):
    return [(start[0] + vel[0] * i + 0.5 * acc[0] * i * i, start[1] + vel[1] * i + 0.5 * acc[1] * i * i) for i in range(n)]


def to_cands(points, noise_per_frame=0, seed=0):
    rng = random.Random(seed)
    out = []
    for p in points:
        frame = [] if p is None else [(p[0], p[1], 50.0)]
        frame += [(rng.uniform(0, 1920), rng.uniform(0, 1080), rng.uniform(10, 60)) for _ in range(noise_per_frame)]
        out.append(frame)
    return out


def test_fast_smash_is_tracked():
    pts = flight(20, (800, 200), (12, 110))                     # ~110 px/frame: a smash at 1080p / 25 fps
    track = link_candidates(to_cands(pts), width=1920)
    assert sum(b is not None for b in track) >= 18


def test_random_noise_is_rejected():
    track = link_candidates(to_cands([None] * 60, noise_per_frame=4), width=1920)
    assert sum(b is not None for b in track) <= 6               # noise almost never forms smooth flights


def test_shuttle_among_noise():
    pts = flight(40, (500, 300), (8, -15), (0, 0.8))
    track = link_candidates(to_cands(pts, noise_per_frame=4, seed=3), width=1920)
    hits = [b for b, p in zip(track, pts) if b and abs(b["px"][0] - p[0]) < 2 and abs(b["px"][1] - p[1]) < 2]
    assert len(hits) >= 34 and sum(b is not None for b in track) <= len(hits) + 4


def test_hit_hidden_by_the_hitter_is_found_at_the_tracklet_boundary():
    incoming = flight(15, (600, 200), (4, 18))
    outgoing = flight(15, (700, 470), (6, -28), (0, 0.9))
    pts = incoming + [None] * 5 + outgoing                      # 5 frames hidden behind the racket arm
    track = link_candidates(to_cands(pts), width=1920)
    assert len({b["seg"] for b in track if b}) == 2
    hits = tracklet_hits(track, fps=25)
    assert len(hits) == 1 and 14 <= hits[0]["frame"] <= 20
    assert len(detect_hits(track, fps=25)) == 1                 # merged with reversal hits: still one contact
