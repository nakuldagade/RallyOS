"""End-to-end pipeline on a computer-generated clip (pose model disabled so the test needs no weights)."""

import json

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from rallyos.calibration.template_fit import apply_h, homography_from_taps  # noqa: E402
from rallyos.sports import load_sport  # noqa: E402

TAPS = [[200, 680], [1080, 680], [880, 140], [400, 140]]


def test_taps_homography_maps_corners_to_court():
    cfg = load_sport("badminton")
    cal = homography_from_taps(TAPS, cfg)
    corners = apply_h(np.array(cal["homography"]), TAPS)
    assert np.allclose(corners, [[0, 0], [6.1, 0], [6.1, 13.4], [0, 13.4]], atol=1e-6)
    assert cal["method"] == "4-tap"


def test_taps_must_be_a_proper_quad():
    with pytest.raises(ValueError):
        homography_from_taps([[200, 680], [880, 140], [1080, 680], [400, 140]], load_sport("badminton"))  # crossed


def _synthetic_clip(path, n=60, fps=25.0, size=(1280, 720)):
    """Green court, a small white shuttle falling then struck back up at frame 30 (an abrupt reversal)."""
    w, h = size
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(n):
        img = np.full((h, w, 3), (60, 140, 60), np.uint8)
        if i < 30:
            x, y = 500 + 4 * i, 200 + 9 * i
        else:
            k = i - 30
            x, y = 620 + 6 * k, 470 - 22 * k + 0.4 * k * k
        cv2.circle(img, (int(x), int(y)), 4, (255, 255, 255), -1)
        out.write(img)
    out.release()


def test_pipeline_end_to_end_without_pose(tmp_path, monkeypatch):
    import rallyos.detect.players as players
    from rallyos.pipeline import Analyzer

    monkeypatch.setattr(players, "load_pose_detector", lambda **kw: (None, "disabled in test"))
    clip = tmp_path / "clip.mp4"
    _synthetic_clip(clip)
    stages = []
    out = Analyzer(sport="badminton", taps=TAPS, match_id="m_test").run(
        str(clip), out_dir=str(tmp_path / "out"), progress=lambda s, p: stages.append(s))

    m = json.loads((tmp_path / "out" / "match.json").read_text(encoding="utf-8"))
    tracks = json.loads((tmp_path / "out" / "tracks.json").read_text(encoding="utf-8"))
    assert out.endswith("out") and (tmp_path / "out" / "source.mp4").is_file()
    assert m["match_id"] == "m_test" and m["calibration"]["method"] == "4-tap"
    assert m["players"] == [] and "players + pose" in m["stats"]["pipeline"]["not_computed"]
    assert m["stats"]["ball"]["detected_pct"] > 0.6
    assert m["stats"]["ball"]["hit_candidates"] >= 1                     # the reversal at frame 30
    assert any(abs(e["t"] * 25 - 30) <= 3 for e in m["events"]) or not m["rallies"]  # 1 hit alone is not a rally
    assert len(tracks["frames"]) == 60 and m["video"]["sha256"]
    assert stages[0] == "calibrate" and stages[-1] == "render"
