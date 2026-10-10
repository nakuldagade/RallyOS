"""Hit onsets from the soundtrack (§4.4 "Hear the Rally"). Signal processing only, no training.

A racket hitting a shuttle or ball is a sharp broadband click. Spectral flux (the summed increase of
log-magnitude across frequency bins between STFT frames) peaks at such clicks; restricting it to the
upper band (default 1.5-10 kHz) ignores voices, footsteps and hall hum. Peaks above a running
median + k * MAD threshold are onsets. Each onset is then refined to sample precision on the
high-passed waveform, so hit times are good to about 1 ms instead of one video frame (16-40 ms).

Audio is decoded with the ffmpeg binary bundled by imageio-ffmpeg (or ffmpeg on PATH). numpy only:
no librosa/numba, which keeps the install light and avoids DLLs that Windows Application Control may block.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

SPEED_OF_SOUND_MPS = 343.0


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def load_audio(path: str | Path, sr: int = 44100) -> tuple[np.ndarray | None, str]:
    """Mono float32 samples at `sr` Hz, and a status string ("ok", "no audio track", "ffmpeg not found", ...)."""
    exe = ffmpeg_exe()
    if exe is None:
        return None, "ffmpeg not found (pip install imageio-ffmpeg)"
    cmd = [exe, "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"ffmpeg failed: {exc}"
    y = np.frombuffer(res.stdout, dtype=np.float32)
    if y.size == 0:
        err = res.stderr.decode("utf-8", "replace")
        return None, "no audio track" if ("does not contain any stream" in err or res.returncode == 0 or not err) \
            else f"ffmpeg failed: {err.strip()[-200:]}"
    return y.copy(), "ok"


def sound_delay_s(distance_m: float) -> float:
    """Time for the hit sound to reach the microphone."""
    return float(distance_m) / SPEED_OF_SOUND_MPS


def onset_envelope(y: np.ndarray, sr: int, n_fft: int = 1024, hop: int = 256,
                   band_hz: tuple[float, float] = (1500.0, 10000.0)) -> np.ndarray:
    """Band-limited spectral flux, one value per hop (frame i covers samples [i*hop, i*hop + n_fft))."""
    if y.size < n_fft:
        return np.zeros(0, np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop]
    mag = np.abs(np.fft.rfft(frames * np.hanning(n_fft).astype(np.float32), axis=1))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    lo, hi = band_hz
    band = (freqs >= lo) & (freqs <= min(hi, sr / 2))
    logm = np.log1p(100.0 * mag[:, band])
    flux = np.maximum(np.diff(logm, axis=0), 0.0).sum(axis=1)
    return np.concatenate([[0.0], flux]).astype(np.float32)


def _running_median(x: np.ndarray, win: int) -> np.ndarray:
    win = max(3, win | 1)
    pad = np.pad(x, win // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, win), axis=1)


def _refine(y: np.ndarray, sr: int, center: int, half: int) -> int:
    """Sample where the high-passed amplitude first reaches half its local peak (attack of the click)."""
    a, b = max(1, center - half), min(len(y), center + half)
    if b - a < 8:
        return center
    env = np.abs(np.diff(y[a - 1:b]))
    k = max(1, sr // 2000)                          # 0.5 ms smoothing
    env = np.convolve(env, np.ones(k) / k, mode="same")
    peak = int(np.argmax(env))
    above = np.nonzero(env[:peak + 1] >= 0.5 * env[peak])[0]
    return a + int(above[0] if above.size else peak)


def detect_onsets(y: np.ndarray, sr: int, min_gap_s: float = 0.15, band_hz=(1500.0, 10000.0),
                  k: float = 6.0, n_fft: int = 1024, hop: int = 256) -> list[dict]:
    """Hit-like onsets: [{"t" (s, sample precise), "strength" (robust z-score), "confidence"}], time-ordered."""
    flux = onset_envelope(y, sr, n_fft, hop, tuple(band_hz))
    if flux.size < 5:
        return []
    base = _running_median(flux, int(1.0 * sr / hop))          # ~1 s window
    resid = flux - base
    mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826
    scale = max(mad, 1e-3 * float(flux.max()) + 1e-9)
    z = resid / scale
    gap = max(1, int(round(min_gap_s * sr / hop)))
    out: list[dict] = []
    edge = int(0.05 * sr / hop) + 1                           # stream start/end (codec fade-in) is not a hit
    z[:edge] = 0
    z[-edge:] = 0
    cand = np.nonzero(z > k)[0]
    for i in cand[np.argsort(-z[cand])]:                      # strongest first, suppress neighbours
        if any(abs(i - o["_i"]) < gap for o in out):
            continue
        out.append({"_i": int(i), "z": float(z[i])})
    res = []
    for o in sorted(out, key=lambda o: o["_i"]):
        center = o["_i"] * hop + n_fft // 2                     # flux frame i rises inside frame i's window
        s = _refine(y, sr, center, n_fft // 2 + hop)
        conf = float(np.clip(1.0 - np.exp(-(o["z"] - k / 2) / k), 0.3, 0.95))
        res.append({"t": round(s / sr, 4), "strength": round(o["z"], 1), "confidence": round(conf, 2)})
    return res
