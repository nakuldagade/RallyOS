"""StreamAnalyzer (live mode, phase B): chunk ordering, overlap, state carried across chunks, equivalence with the whole-file run.

The clips are computer-generated and written as MJPG (every frame compressed on its own, so a frame is bit-identical
whether it sits in the whole file or in a chunk). That makes the chunked and whole-file runs exactly comparable; the
effect of lossy video compression on real clips is measured separately (docs/live-mode-plan.md, AGENTS.md).
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from rallyos.audio.onsets import ffmpeg_exe  # noqa: E402
from rallyos.live.segments import ChunkMeta, StableIds, cut_clip, dedupe_times, same_event, stitch  # noqa: E402
from rallyos.live.stream import StreamAnalyzer  # noqa: E402

FPS, W, H = 25.0, 640, 360
TAPS = [[100, 340], [540, 340], [440, 70], [200, 70]]
SEG = 25                                          # frames between strikes
RALLIES = [(20, 3), (250, 3)]                     # (first frame the shuttle is seen, number of strikes): a 7 s pause between rallies
HITS = [start + SEG * j for start, k in RALLIES for j in range(1, k + 1)]          # frames where the shuttle is struck
N = 360


def ball_at(i: int):
    """The shuttle: falls, is struck back up, falls again ... absent in the pause between rallies."""
    for start, k in RALLIES:
        if start <= i < start + SEG * (k + 1):
            seg, d = divmod(i - start, SEG)
            y = 30 + 10 * d if seg % 2 == 0 else 280 - 10 * d
            return 100 + 5 * (i - start), y
    return None


def frame_at(i: int) -> np.ndarray:
    img = np.full((H, W, 3), (60, 140, 60), np.uint8)
    b = ball_at(i)
    if b:
        cv2.circle(img, (int(b[0]), int(b[1])), 2, (255, 255, 255), -1)      # small: the detector's size limit scales with width
    return img


def write_avi(path: Path, f0: int, f1: int) -> Path:
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    for i in range(f0, f1):
        w.write(frame_at(i))
    w.release()
    return path


def make_chunks(folder: Path, chunk_s: float = 2.0, overlap_s: float = 0.4, n: int = N) -> list[ChunkMeta]:
    folder.mkdir(parents=True, exist_ok=True)
    metas, seq = [], 0
    while seq * chunk_s * FPS < n - 5:
        f0 = int(seq * chunk_s * FPS)
        f1 = min(n, int((seq * chunk_s + chunk_s + overlap_s) * FPS))
        p = write_avi(folder / f"chunk_{seq:04d}.avi", f0, f1)
        metas.append(ChunkMeta(seq=seq, path=str(p), t0=f0 / FPS, duration=(f1 - f0) / FPS))
        seq += 1
    return metas


@pytest.fixture(autouse=True)
def no_pose(monkeypatch):
    import rallyos.detect.players as players

    monkeypatch.setattr(players, "load_pose_detector", lambda **kw: (None, "disabled in test"))


def stream(tmp_path, metas, trace=None, **kw):
    an = StreamAnalyzer(sport="badminton", taps=kw.pop("taps", TAPS), out_dir=tmp_path / "session", chunk_seconds=2.0, **kw)
    an.start()
    results = []
    for m in metas:
        results.append(an.feed_chunk(m.path, m.seq, m.t0, m.duration))
        if trace is not None:
            trace.append((m.t1, results[-1]["stats"]["rallies"], sum(1 for e in an.events if e["type"] == "landing")))
    return an, results


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One generated clip, cut into chunks and streamed once; the tests that only read the result share it."""
    import rallyos.detect.players as players

    mp = pytest.MonkeyPatch()
    mp.setattr(players, "load_pose_detector", lambda **kw: (None, "disabled in test"))
    base = tmp_path_factory.mktemp("live")
    metas = make_chunks(base / "chunks")
    trace: list = []
    an, results = stream(base, metas, trace)
    yield {"base": base, "metas": metas, "an": an, "results": results, "trace": trace}
    mp.undo()


def hit_times(events):
    return sorted(e["t"] for e in events if e["type"] == "hit")


# -- bookkeeping helpers -----------------------------------------------------------------------------------------

def test_same_event_is_judged_by_time_type_and_player():
    a = {"type": "hit", "t": 1.00, "track_id": 1}
    assert same_event(a, {"type": "hit", "t": 1.10, "track_id": 1}) and same_event(a, {"type": "hit", "t": 1.05, "track_id": None})
    assert not same_event(a, {"type": "hit", "t": 1.30, "track_id": 1}) and not same_event(a, {"type": "landing", "t": 1.0})
    assert not same_event(a, {"type": "hit", "t": 1.0, "track_id": 2})


def test_stable_ids_survive_recomputation_and_small_time_shifts():
    ids = StableIds("l")
    first = ids.assign([{"type": "hit", "t": 1.0, "track_id": None}, {"type": "hit", "t": 2.0, "track_id": 1}])
    again = ids.assign([{"type": "hit", "t": 1.06, "track_id": 2}, {"type": "hit", "t": 2.0, "track_id": 1}, {"type": "hit", "t": 3.0, "track_id": 1}])
    assert [e["id"] for e in first] == ["l_00001", "l_00002"]
    assert [e["id"] for e in again] == ["l_00001", "l_00002", "l_00003"]        # the shifted hit keeps its id


def test_onsets_in_the_overlap_are_not_counted_twice():
    known = [1.0, 4.9, 5.2]
    fresh = [{"t": 5.21}, {"t": 7.0}, {"t": 5.4}]                              # 5.21 is the same click as 5.2
    assert [o["t"] for o in dedupe_times(known, fresh, 0.15)] == [5.4, 7.0]


# -- the analyzer ------------------------------------------------------------------------------------------------

def test_every_frame_is_analysed_exactly_once_across_overlapping_chunks(shared):
    metas, an, results = shared["metas"], shared["an"], shared["results"]
    assert len(metas) >= 6
    assert an.scanner.f == N                                                  # all frames, none twice, none missing
    assert results[0]["overlap_frames_skipped"] == 0
    assert all(r["overlap_frames_skipped"] == 10 for r in results[1:-1])      # the 0.4 s overlap is recognised by time
    assert sum(r["frames"] for r in results) == N and an.dropped_frames == 0
    assert len(an.scanner.cands) == N - 1 and len(an.tracker.frames) == N


def test_chunked_and_whole_file_runs_find_the_same_hits_rallies_and_court(shared):
    from rallyos.pipeline import Analyzer

    tmp_path, an = shared["base"], shared["an"]
    whole = write_avi(tmp_path / "whole.avi", 0, N)
    Analyzer(sport="badminton", taps=TAPS, match_id="m_whole").run(str(whole), out_dir=str(tmp_path / "whole_out"))
    batch = json.loads((tmp_path / "whole_out" / "match.json").read_text(encoding="utf-8"))
    live_hits = hit_times(an.events)                                          # the provisional answer, before finalising
    final = an.finalize(match_id="m_live", out_dir=tmp_path / "final_eq", render_clips=False, split_step=False)
    bh, lh = hit_times(batch["events"]), hit_times(final["events"])
    assert len(bh) >= 4
    assert len(bh) == len(lh) and all(abs(a - b) <= 0.12 for a, b in zip(bh, lh)), (bh, lh)     # same hits, same moments
    assert [(r["hits"], r["end_reason"]) for r in final["rallies"]] == [(r["hits"], r["end_reason"]) for r in batch["rallies"]]
    assert final["calibration"]["homography"] == batch["calibration"]["homography"]            # the court is the same
    assert abs(final["stats"]["ball"]["detected_pct"] - batch["stats"]["ball"]["detected_pct"]) < 0.02
    # the incremental (provisional) answer already had every hit by the time the last chunk was in
    assert live_hits == lh


def test_a_rally_is_closed_only_after_its_pause_and_only_then_gets_an_ending(shared):
    state = shared["trace"]
    first_end = (HITS[2] + 1) / FPS            # the last strike of the first rally
    for t1, closed, landings in state:
        if t1 < first_end + 4.0:
            assert closed == 0 and landings == 0, (t1, closed, landings)      # the pause has not passed: no landing, no call
    assert state[-1][1] == 1 or state[-1][1] == 2                              # by the end the first rally is closed
    assert any(c >= 1 for _, c, _ in state)
    assert all(e["provisional"] for e in shared["an"].events) and all(r["provisional"] for r in shared["an"].rallies)


def test_events_keep_their_ids_and_are_announced_once(shared):
    an, results = shared["an"], shared["results"]
    announced = [e["id"] for r in results for e in r["new_events"]]
    assert len(announced) == len(set(announced))                              # never announced twice
    assert set(announced) == {e["id"] for e in an.events}                      # and nothing is missing
    assert {e["id"] for e in an.events if e["type"] == "hit"} <= set(announced)


def test_missing_frames_are_counted_and_later_events_stay_on_time(tmp_path):
    metas = make_chunks(tmp_path / "chunks")
    gap = [m for i, m in enumerate(metas) if i != 2]                          # chunk 2 never arrives
    an, _ = stream(tmp_path, gap)
    # chunk 2 covers frames 100-150, but chunk 1's 0.4 s overlap already supplied frames 100-110: 40 are really missing
    assert an.scanner.f == N and an.dropped_frames == pytest.approx(40, abs=2)
    assert any(abs(t - HITS[3] / FPS) <= 0.12 for t in hit_times(an.events))     # a later hit is still at its true time


def test_audio_onsets_from_each_chunk_are_merged_without_duplicates(tmp_path, monkeypatch):
    import rallyos.live.stream as live_stream
    from test_audio import click_track, SR

    chunk_clicks = {0: [1.0, 1.9, 2.2], 1: [0.2, 1.4]}                         # chunk 1 starts at 2.0 s: 0.2 is the 2.2 s click again
    monkeypatch.setattr("rallyos.audio.onsets.load_audio",
                        lambda p: (click_track(chunk_clicks[1 if "0001" in str(p) else 0], dur=2.4), "ok"))
    metas = make_chunks(tmp_path / "chunks", n=100)[:2]
    an, _ = stream(tmp_path, metas)
    assert [round(o["t"], 1) for o in an.onsets] == [1.0, 1.9, 2.2, 3.4]
    assert an.audio_status == "ok"


def test_new_corners_rerun_the_stored_chunks_without_a_new_session(tmp_path):
    metas = make_chunks(tmp_path / "chunks")[:3]
    an, _ = stream(tmp_path, metas)
    shifted = [[x + (6 if i in (1, 2) else 0), y] for i, (x, y) in enumerate(TAPS)]
    redone = an.set_corners(shifted)
    assert len(redone) == 3 and [r["seq"] for r in redone] == [0, 1, 2]
    assert an.scene.calib["taps_px"] == [[float(x), float(y)] for x, y in shifted]
    assert an.scanner.f == pytest.approx(3 * 50 + 10 - 10, abs=12) and len(an.chunk_files) == 3


def test_finalize_writes_the_match_contract_with_a_live_block_and_one_source_video(shared):
    an, base = shared["an"], shared["base"]
    out = base / "final_contract"
    m = an.finalize(match_id="m_live_test", out_dir=out, render_clips=False, split_step=False)
    assert m["schema_version"] == "1.1" and m["match_id"] == "m_live_test"
    for key in ("sport", "calibration", "players", "rallies", "events", "score", "stats", "disputes", "insights", "video", "live"):
        assert key in m
    live = m["live"]
    assert live["chunks"] == len(an.chunk_files) and live["dropped_frames"] == 0 and live["chunk_seconds"] == 2.0
    assert [e["id"] for e in m["events"]] == [f"e_{i + 1:04d}" for i in range(len(m["events"]))]   # renumbered, no provisional ids
    assert (out / "source.mp4").is_file() and (out / "tracks.json").is_file() and len(m["video"]["sha256"]) == 64
    cap = cv2.VideoCapture(str(out / "source.mp4"))
    assert abs(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - N) <= 2                  # the overlap was cut: one continuous video
    assert not any(e.get("provisional") for e in m["events"])


def test_a_crashed_session_is_rebuilt_from_its_folder(shared):
    an, base = shared["an"], shared["base"]
    again = StreamAnalyzer.resume(base / "session")
    assert hit_times(again.events) == hit_times(an.events) and again.scanner.f == an.scanner.f
    assert (base / "session" / "chunk_0000" / "summary.json").is_file()


@pytest.mark.skipif(ffmpeg_exe() is None, reason="ffmpeg not available")
def test_cut_and_stitch_give_back_one_continuous_clip(tmp_path):
    whole = write_avi(tmp_path / "whole.avi", 0, 200)
    mp4 = tmp_path / "whole.mp4"
    import subprocess

    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", str(whole), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    chunks = cut_clip(mp4, tmp_path / "cut", chunk_seconds=2.0, overlap_seconds=0.4)
    assert [c.seq for c in chunks] == [0, 1, 2, 3] and chunks[0].duration == pytest.approx(2.4, abs=0.05)
    for c in chunks:                                                           # each chunk is a file that opens on its own
        cap = cv2.VideoCapture(c.path)
        assert cap.isOpened() and cap.read()[0]
    out = stitch(chunks, tmp_path / "joined.mp4", 2.0)
    cap = cv2.VideoCapture(str(out))
    assert abs(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 200) <= 3
