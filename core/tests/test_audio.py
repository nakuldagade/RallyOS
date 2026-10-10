"""Audio hit onsets (§4.4), camera self-calibration (§4.2) and audio + vision hit fusion."""

import math
import subprocess
import wave

import numpy as np
import pytest

from rallyos.audio.onsets import detect_onsets, ffmpeg_exe, load_audio, sound_delay_s
from rallyos.calibration.camera import camera_from_homography
from rallyos.calibration.template_fit import apply_h
from rallyos.events.hits import fuse_audio

SR = 44100


def click_track(times, dur=6.0, noise=0.01, seed=0, thumps=()):
    """White noise floor + short broadband clicks at `times` + low-frequency thumps (footsteps) at `thumps`."""
    rng = np.random.default_rng(seed)
    y = noise * rng.standard_normal(int(dur * SR)).astype(np.float32)
    for t in times:
        i = int(round(t * SR))
        n = int(0.004 * SR)
        y[i:i + n] += (0.6 * rng.standard_normal(n) * np.exp(-np.arange(n) / (0.0008 * SR))).astype(np.float32)
    for t in thumps:
        i = int(t * SR)
        n = int(0.08 * SR)
        y[i:i + n] += (0.5 * np.sin(2 * np.pi * 120 * np.arange(n) / SR) * np.hanning(n)).astype(np.float32)
    return y


def test_onsets_are_sample_precise_and_ignore_low_thumps():
    hits = [0.8123, 1.6542, 2.2017, 3.5005, 4.9871]
    y = click_track(hits, thumps=[1.2, 3.0, 4.4])
    on = detect_onsets(y, SR)
    assert len(on) == len(hits)
    for o, t in zip(on, hits):
        assert abs(o["t"] - t) < 0.0015                 # ~1 ms, vs 40 ms per frame at 25 fps
        assert 0.3 <= o["confidence"] <= 0.95


def test_onsets_respect_min_gap_and_silence():
    assert detect_onsets(np.zeros(SR * 2, np.float32), SR) == []
    on = detect_onsets(click_track([1.0, 1.05, 2.0]), SR, min_gap_s=0.15)
    assert len(on) == 2


def test_sound_delay():
    assert sound_delay_s(13.0) == pytest.approx(0.0379, abs=1e-4)   # §4.4: ~38 ms for a far-court hit


def synthetic_camera(f=1500.0, w=1920, h=1080, pos=(3.05, -4.0, 3.0), look=(3.05, 6.7, 0.0)):
    """Image px -> court m homography for a pinhole camera at `pos` looking at `look` (court plane z = 0)."""
    C, L = np.array(pos, float), np.array(look, float)
    z = (L - C) / np.linalg.norm(L - C)
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.vstack([x, y, z])                            # world -> camera
    t = -R @ C
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    G = K @ np.column_stack([R[:, 0], R[:, 1], t])      # court (X, Y, 1) -> image
    return np.linalg.inv(G / G[2, 2])


@pytest.mark.parametrize("pos,f", [((3.05, -4.0, 3.0), 1500.0), ((1.0, -2.5, 2.2), 1100.0), ((5.0, -6.0, 4.5), 2200.0)])
def test_camera_from_homography_recovers_focal_and_position(pos, f):
    H = synthetic_camera(f=f, pos=pos)
    cam = camera_from_homography(H, 1920, 1080)
    assert cam is not None
    assert cam["focal_px"] == pytest.approx(f, rel=0.01)
    assert cam["position_m"] == pytest.approx(list(pos), abs=0.05)


def test_camera_from_homography_none_for_top_down_view():
    H = np.linalg.inv(np.array([[100.0, 0, 500], [0, 100.0, 200], [0, 0, 1]]))   # pure scaling: f undetermined
    assert camera_from_homography(H, 1920, 1080) is None


def test_camera_matches_tapped_corners_roundtrip():
    H = synthetic_camera()
    corners = np.array([[0, 0], [6.1, 0], [6.1, 13.4], [0, 13.4]])
    px = apply_h(np.linalg.inv(H), corners)
    assert np.allclose(apply_h(H, px), corners, atol=1e-6)


def frames_with_players(n=200, near=(3.0, 2.0), far=(3.0, 11.0)):
    return [{"f": i, "players": [{"track_id": 1, "court": list(near)}, {"track_id": 2, "court": list(far)}],
             "ball": {"px": [500.0, 300.0]}} for i in range(n)]


def vhit(frame, tid, conf=0.7, fps=25.0):
    return {"frame": frame, "t": frame / fps, "px": [500.0, 300.0], "dv": 40.0, "turn_deg": 120.0,
            "track_id": tid, "confidence": conf}


def test_fuse_estimates_av_offset_corrects_sound_delay_and_adds_gap_hits():
    fps, frames, cam = 25.0, frames_with_players(), (3.05, -4.0, 3.0)
    hits = [vhit(20, 1), vhit(45, 2), vhit(70, 1), vhit(120, 1)]
    offset = 0.12                                         # audio track lags the video
    d1 = math.dist((3.0, 2.0, 1.5), cam) / 343
    d2 = math.dist((3.0, 11.0, 1.5), cam) / 343
    onsets = [{"t": 20 / fps + offset + d1, "confidence": 0.9}, {"t": 45 / fps + offset + d2, "confidence": 0.9},
              {"t": 70 / fps + offset + d1, "confidence": 0.9},
              {"t": 95 / fps + offset + d2, "confidence": 0.85}]   # far player's hit lost by the tracker
    out, info = fuse_audio(hits, onsets, fps, frames, camera_m=cam)
    assert info["av_offset_s"] == pytest.approx(offset, abs=0.002)
    assert info["matched"] == 3 and info["audio_only"] == 1 and info["vision_only"] == 1
    assert [h["frame"] for h in out] == [20, 45, 70, 95, 120]
    a = out[1]
    assert a["source"] == ["audio", "vision"] and a["t"] == pytest.approx(45 / fps, abs=0.002)
    assert a["sound_delay_ms"] == pytest.approx(1000 * d2, abs=0.2) and a["confidence"] > 0.9
    gap = out[3]
    assert gap["source"] == ["audio"] and gap["track_id"] == 2 and gap["hitter_inferred"]
    assert gap["t"] == pytest.approx(95 / fps, abs=0.002)
    assert out[4]["source"] == ["vision"] and out[4]["confidence"] == pytest.approx(0.56)


def test_fuse_without_onsets_keeps_vision_hits():
    hits = [vhit(20, 1), vhit(45, 2)]
    out, info = fuse_audio(hits, [], 25.0, frames_with_players())
    assert [h["source"] for h in out] == [["vision"], ["vision"]] and info["onsets"] == 0
    assert out[0]["confidence"] == 0.7


def test_fuse_bouncing_sport_never_adds_audio_only_hits():
    onsets = [{"t": 2.0, "confidence": 0.95}]              # could be a bounce
    out, info = fuse_audio([vhit(20, 1)], onsets, 25.0, frames_with_players(), allow_audio_only=False)
    assert info["audio_only"] == 0 and len(out) == 1


def _write_wav(path, y):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


@pytest.mark.skipif(ffmpeg_exe() is None, reason="ffmpeg not available")
def test_load_audio_from_video_with_and_without_sound(tmp_path):
    exe = ffmpeg_exe()
    times = [0.5, 1.3, 2.1]
    _write_wav(tmp_path / "a.wav", click_track(times, dur=3.0))
    base = [exe, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x240:r=25:d=3"]
    subprocess.run(base + ["-i", str(tmp_path / "a.wav"), "-shortest", "-c:v", "libx264", "-c:a", "aac",
                           "-pix_fmt", "yuv420p", str(tmp_path / "with.mp4")], check=True, capture_output=True)
    subprocess.run(base + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "silent.mp4")],
                   check=True, capture_output=True)
    y, status = load_audio(tmp_path / "with.mp4")
    assert status == "ok" and y is not None and abs(len(y) / SR - 3.0) < 0.1
    on = detect_onsets(y, SR)
    assert len(on) == 3
    assert all(abs(o["t"] - t) < 0.06 for o, t in zip(on, times))   # AAC priming delay is a few tens of ms
    y2, status2 = load_audio(tmp_path / "silent.mp4")
    assert y2 is None and status2 == "no audio track"
