"""The match highlight: the best rated shot of the whole match, cut as an ~8 s clip."""
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("imageio_ffmpeg")

from rallyos.render.highlight import WINDOW_S, pick_best, render_highlight, window_for  # noqa: E402
from rallyos.stages import make_highlight  # noqa: E402

FPS = 25.0
W, H = 320, 240


def card(t, score, conf=0.6, outcome="kept_going", shot="drive", basis="outcome"):
    return {"t": t, "shot": shot, "outcome": outcome, "score": score, "technique": 0.5, "confidence": conf, "why": "x", "basis": basis}


def hit(t, tid, px=(160, 120)):
    return {"type": "hit", "t": t, "track_id": tid, "px": list(px), "rally_idx": 0}


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    p = tmp_path_factory.mktemp("hl") / "src.avi"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    for i in range(int(12 * FPS)):                                   # 12 s
        img = np.full((H, W, 3), (40, 120, 40), np.uint8)
        cv2.putText(img, str(i), (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        w.write(img)
    w.release()
    return p


def n_frames(path):
    c = cv2.VideoCapture(str(path))
    return int(c.get(cv2.CAP_PROP_FRAME_COUNT)), c.get(cv2.CAP_PROP_FPS)


def test_the_window_is_eight_seconds_three_before_the_contact_and_stays_inside_the_video():
    assert window_for(6.0, 20.0) == (3.0, 11.0)
    assert window_for(1.0, 20.0) == (0.0, 8.0)                       # contact near the start: starts at 0, still 8 s
    assert window_for(19.0, 20.0) == (12.0, 20.0)                    # near the end: ends at the end, still 8 s
    assert window_for(2.0, 5.0) == (0.0, 5.0)                        # a video shorter than 8 s is used whole


def test_the_best_shot_of_the_match_is_the_highest_score_of_either_player_then_the_surest():
    pp = {"1": {"best_shot": card(5.0, 71.0)}, "2": {"best_shot": card(9.0, 88.0, outcome="winner")}}
    b = pick_best(pp, [hit(5.0, 1), hit(9.02, 2, px=(10, 20))])
    assert b["track_id"] == 2 and b["t"] == 9.0 and b["score"] == 88.0 and b["px"] == [10, 20] and b["basis"] == "outcome"
    tie = {"1": {"best_shot": card(5.0, 70.0, conf=0.5)}, "2": {"best_shot": card(9.0, 70.0, conf=0.8)}}
    assert pick_best(tie, [])["track_id"] == 2
    assert pick_best({"1": {}, "2": {"best_shot": card(9.0, 99.0, conf=0.1)}}, []) is None        # too unsure to put in a highlight
    assert pick_best({}, []) is None


def test_the_clip_is_eight_seconds_and_playable(video, tmp_path):
    out = tmp_path / "h.mp4"
    best = {**card(6.0, 80.0), "px": [160, 120], "track_id": 1}
    info = render_highlight(video, out, best, FPS, [None] * 300)
    assert info == {"clip_start": 3.0, "clip_end": 11.0, "duration_s": 8.0}
    n, fps = n_frames(out)
    assert n == int(WINDOW_S * FPS) and fps == FPS and out.stat().st_size > 1000


@pytest.mark.parametrize("t,start", [(0.5, 0.0), (11.5, 4.0)])
def test_a_contact_at_either_end_of_the_video_still_gives_a_full_clip(video, tmp_path, t, start):
    info = render_highlight(video, tmp_path / "e.mp4", {**card(t, 60.0), "px": None, "track_id": 1}, FPS, [None] * 300)
    assert info["clip_start"] == start and info["duration_s"] == 8.0


def test_a_gap_filled_or_jumping_shuttle_track_is_not_drawn_as_a_trail(video, tmp_path):
    best = {**card(6.0, 80.0), "px": None, "track_id": 1}
    none = [None] * 300
    fake = [{"px": [10.0 + 8 * (i % 30), 100.0], "conf": 0.9, "interp": True} for i in range(300)]             # all gap-filled
    jump = [{"px": [10.0 if i % 2 else 300.0, 100.0], "conf": 0.9, "interp": False} for i in range(300)]       # jumps across the picture
    for name, balls in (("fake", fake), ("jump", jump)):
        render_highlight(video, tmp_path / f"{name}.mp4", best, FPS, balls)
    render_highlight(video, tmp_path / "none.mp4", best, FPS, none)
    assert (tmp_path / "none.mp4").read_bytes() == (tmp_path / "fake.mp4").read_bytes() == (tmp_path / "jump.mp4").read_bytes()
    real = [{"px": [20.0 + 4 * (i % 60), 100.0], "conf": 0.9, "interp": False} for i in range(300)]
    render_highlight(video, tmp_path / "real.mp4", best, FPS, real)
    assert (tmp_path / "real.mp4").read_bytes() != (tmp_path / "none.mp4").read_bytes()                       # a real path IS drawn


def test_make_highlight_gives_the_match_json_block_and_drops_a_contact_ring_that_is_not_on_the_hitter(video, tmp_path):
    pp = {"1": {"best_shot": card(6.0, 77.0)}, "2": {}}
    events = [hit(6.0, 1, px=(300, 20))]                              # nowhere near player 1
    frames = [{"players": [{"track_id": 1, "bbox": [100, 100, 160, 220]}]} for _ in range(300)]
    hl = make_highlight(video, tmp_path, "m_x", pp, events, [None] * 300, FPS, frames)
    assert hl["clip_url"] == "/media/m_x/highlight.mp4" and hl["track_id"] == 1 and hl["score"] == 77.0 and hl["duration_s"] == 8.0
    assert (tmp_path / "highlight.mp4").is_file()
    assert make_highlight(video, tmp_path, "m_x", {"1": {}, "2": {}}, [], [], FPS) is None        # nothing rated: no highlight, no error
    assert make_highlight(tmp_path / "missing.avi", tmp_path, "m_y", pp, events, [], FPS) is None  # unreadable video: no error either
