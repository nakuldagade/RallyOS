"""Chunk bookkeeping for live mode: cutting a clip into overlapping chunks (for the replay script and tests), and the
time-based de-duplication used at chunk boundaries.

A chunk k covers [k * chunk_seconds, (k + 1) * chunk_seconds + overlap_seconds): its last `overlap_seconds` are also
the first seconds of chunk k + 1. The analyzer processes every chunk completely as soon as it arrives (lowest latency) and
simply skips, in the next chunk, the frames it has already seen (by time, not by counting), so nothing is analysed twice.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

DEDUP_S = 0.12            # two events of the same kind this close in time are the same event


@dataclass
class ChunkMeta:
    seq: int
    path: str
    t0: float                       # session-relative start of the chunk, seconds
    duration: float                 # length of the file, seconds (including the overlap)
    t_ready: float | None = None    # wall-clock time the chunk was complete (for latency), if known

    @property
    def t1(self) -> float:
        return self.t0 + self.duration

    def to_json(self) -> dict:
        return asdict(self)


def cut_clip(clip: str | Path, out_dir: str | Path, chunk_seconds: float = 5.0, overlap_seconds: float = 0.5,
             fmt: str = "mp4", duration: float | None = None) -> list[ChunkMeta]:
    """Cut a finished clip into live-style chunks: each an independent file with its own header (and audio, if any)."""
    from rallyos.audio.onsets import ffmpeg_exe
    from rallyos.videoio import video_info

    exe = ffmpeg_exe()
    if exe is None:
        raise RuntimeError("ffmpeg not found (pip install imageio-ffmpeg)")
    total = duration if duration is not None else video_info(clip)["duration_s"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chunks, seq = [], 0
    while seq * chunk_seconds < total - 0.2:
        t0 = seq * chunk_seconds
        length = min(chunk_seconds + overlap_seconds, total - t0)
        path = out / f"chunk_{seq:04d}.{fmt}"
        codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac"] if fmt == "mp4" \
            else ["-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "4M", "-c:a", "libopus"]
        cmd = [exe, "-v", "error", "-y", "-ss", f"{t0:.3f}", "-i", str(clip), "-t", f"{length:.3f}", *codec, str(path)]
        subprocess.run(cmd, check=True, capture_output=True)
        chunks.append(ChunkMeta(seq=seq, path=str(path), t0=t0, duration=length))
        seq += 1
    return chunks


def stitch(chunks: list[ChunkMeta], out_path: str | Path, chunk_seconds: float) -> Path:
    """One continuous file from the chunks: every chunk but the last is cut at its nominal length (dropping the overlap
    that the next chunk repeats), then the pieces are joined without re-encoding (stream copy)."""
    from rallyos.audio.onsets import ffmpeg_exe

    exe = ffmpeg_exe()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    chunks = sorted(chunks, key=lambda c: c.seq)
    parts = []
    for i, c in enumerate(chunks):
        if i == len(chunks) - 1:
            parts.append(Path(c.path))
            continue
        part = out.parent / f"_part_{c.seq:04d}{Path(c.path).suffix}"
        keep = min(c.duration, chunks[i + 1].t0 - c.t0)
        subprocess.run([exe, "-v", "error", "-y", "-i", c.path, "-t", f"{keep:.3f}", "-c", "copy", str(part)], check=True, capture_output=True)
        parts.append(part)
    listing = out.parent / "_concat.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run([exe, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
                   check=True, capture_output=True)
    for p in parts[:-1]:
        p.unlink(missing_ok=True)
    listing.unlink(missing_ok=True)
    return out


def same_event(a: dict, b: dict, tol: float = DEDUP_S) -> bool:
    """The same event seen twice: same type, same player when both are known, and the same moment."""
    if a["type"] != b["type"] or abs(a["t"] - b["t"]) > tol:
        return False
    ta, tb = a.get("track_id"), b.get("track_id")
    return ta is None or tb is None or ta == tb


def dedupe_times(existing: list[float], new: list[dict], min_gap: float, key: str = "t") -> list[dict]:
    """New items (e.g. audio onsets) that are not within min_gap seconds of anything already known, in time order."""
    out = []
    known = sorted(existing)
    for item in sorted(new, key=lambda x: x[key]):
        t = item[key]
        if any(abs(t - k) < min_gap for k in known):
            continue
        out.append(item)
        known.append(t)
    return out


class StableIds:
    """Gives an event the same id every time it is recomputed (a hit found again in the next chunk's window is the same hit)."""

    def __init__(self, prefix: str = "e"):
        self.prefix, self.items, self.n = prefix, [], 0

    def assign(self, events: list[dict]) -> list[dict]:
        for e in events:
            hit = next((x for x in self.items if same_event(x, e)), None)
            if hit is None:
                self.n += 1
                hit = {"type": e["type"], "t": e["t"], "track_id": e.get("track_id"), "id": f"{self.prefix}_{self.n:05d}"}
                self.items.append(hit)
            else:
                hit["t"] = e["t"]
                if hit.get("track_id") is None:
                    hit["track_id"] = e.get("track_id")
            e["id"] = hit["id"]
        return events


def to_mp4(src: str | Path, dst: str | Path) -> Path:
    """Re-encode a browser recording (WebM) to H.264 MP4 so every player and the dispute-clip renderer can read it."""
    from rallyos.audio.onsets import ffmpeg_exe

    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)], check=True, capture_output=True)
    return Path(dst)
