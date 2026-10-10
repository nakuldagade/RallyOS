"""Phase F speed work: everything that makes the live path faster must give the SAME answers as the slow way, or say that it differs.

* the parallel FrameScanner (pose on worker threads, shuttle search on a pool) equals a plain one-frame-at-a-time loop
* the time-based pose stride and the adaptive degradation (and that degradation is flagged)
* the OpenVINO pose backend decodes boxes and keypoints back to the right pixels (the model itself is compared with PyTorch on
  real frames in docs/live-mode-plan.md: that needs real footage, not generated frames)
"""
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("cv2")

from test_live_stream import N, frame_at  # noqa: E402

from rallyos.detect.ball_candidates import BallCandidateDetector  # noqa: E402
from rallyos.live.stream import ADAPT_DOWN, ADAPT_UP, MAX_ADAPT_STEPS, StreamAnalyzer, pose_stride_for  # noqa: E402
from rallyos.stages import FrameScanner  # noqa: E402


class FakePose:
    """A deterministic 'pose model': a box that depends on the frame content, slow enough to make threads interleave."""

    def __call__(self, frame):
        import time

        time.sleep(0.004)
        m = float(frame.mean())
        return [{"bbox": [10.0 + m, 20.0, 60.0 + m, 150.0], "conf": 0.9, "kp": None}]


def reference_scan(frames, detector, stride):
    """The scanner as it was before the speed work: one frame at a time, pose first, then the shuttle search."""
    from collections import deque

    det, window, boxes, sampled, cands = BallCandidateDetector(), deque(maxlen=3), [], [], []
    for f, frame in enumerate(frames):
        if f % stride == 0:
            dets = detector(frame)
            sampled.append((f, dets))
            boxes = [d["bbox"] for d in dets]
        window.append((det.prepare(frame), boxes))
        if len(window) == 3:
            (g0, _), (g1, b), (g2, _) = window
            cands.append(det.candidates(g0, g1, g2, b, roi=None))
        elif f == 0:
            cands.append([])
    return sampled, cands


@pytest.mark.parametrize("stride", [1, 3, 7])
def test_the_parallel_scanner_gives_exactly_the_sequential_results(stride):
    frames = [frame_at(i) for i in range(0, 130)]
    ref_s, ref_c = reference_scan(frames, FakePose(), stride)
    sc = FrameScanner(SimpleNamespace(pose_box=None, ball_mask=None), FakePose(), stride)
    for fr in frames:
        sc.feed(fr)
    assert sc.sampled == ref_s
    assert sc.candidates()[: len(ref_c)] == ref_c
    assert sc.f == len(frames) and len(sc._cands) == len(ref_c)
    assert any(c for c in ref_c), "the generated shuttle must actually be found, or this test proves nothing"


def test_skipping_dropped_frames_keeps_indices_aligned_in_the_parallel_scanner():
    frames = [frame_at(i) for i in range(60)]
    sc = FrameScanner(SimpleNamespace(pose_box=None, ball_mask=None), FakePose(), 3)
    for fr in frames[:30]:
        sc.feed(fr)
    sc.skip(5)
    for fr in frames[35:]:
        sc.feed(fr)
    assert sc.f == 60 and len(sc.candidates()) == 60
    assert [f for f, _ in sc.sampled][:12] == [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 36, 39]      # pose stays on multiples of the stride across the gap


def test_pose_stride_follows_the_frame_rate_not_the_frame_count():
    assert [pose_stride_for(fps) for fps in (25, 30, 50, 60, 120)] == [3, 4, 6, 7, 14]
    assert pose_stride_for(10) == 3                      # never denser than the configured minimum


def test_slow_chunks_make_pose_rarer_quick_ones_bring_it_back_and_the_first_chunk_is_ignored():
    an = StreamAnalyzer(sport="badminton", stride=3)
    an.base_stride = an.stride = 3
    slow, quick, middle = (ADAPT_UP + 0.1) * 5.5, 0.3 * 5.5, (ADAPT_DOWN + 0.05) * 5.5
    an.chunks_done = [{}]
    an._adapt(slow, 5.5)                                 # chunk 0: court search + model compile, never counts
    an.chunks_done.append({})
    an._adapt(slow, 5.5)                                 # one slow chunk is not enough...
    assert an.stride == 3
    an._adapt(quick, 5.5)                                # ...and a quick one in between resets the count
    an._adapt(slow, 5.5)
    assert an.stride == 3
    for expected in (5, 5, 7, 7, 9, 9, 9, 9):            # two slow chunks in a row: pose gets rarer by 2, up to a limit
        an._adapt(slow, 5.5)
        assert an.stride == expected
    assert an.stride == 3 + 2 * MAX_ADAPT_STEPS
    an._adapt(middle, 5.5)                               # in between: hold
    assert an.stride == 9
    for expected in (7, 5, 3, 3):                        # room again: back to the base rate
        an._adapt(quick, 5.5)
        assert an.stride == expected


def test_openvino_decoding_maps_boxes_and_keypoints_back_to_the_crop():
    from rallyos.detect.players import OpenVinoPoseDetector, decode_pose_output

    det = OpenVinoPoseDetector.__new__(OpenVinoPoseDetector)
    det.imgsz = 640
    img = np.zeros((300, 800, 3), np.uint8)
    canvas, r, px, py = det._letterbox(img)
    assert canvas.shape[0] % 32 == 0 and canvas.shape[1] % 32 == 0 and max(canvas.shape[:2]) <= 640 + 32
    # a person at x 200..300, y 100..250 of the crop, as the model would report it (centre/size in letterbox pixels)
    bx = (200 * r + px, 100 * r + py, 300 * r + px, 250 * r + py)
    raw = np.zeros((1, 56, 1), np.float32)
    raw[0, :4, 0] = [(bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, bx[2] - bx[0], bx[3] - bx[1]]
    raw[0, 4, 0] = 0.9
    raw[0, 5:8, 0] = [250 * r + px, 120 * r + py, 0.9]                       # the nose
    out = decode_pose_output(raw, r, px, py, 0.25, 0.7)
    assert len(out) == 1
    x1, y1, x2, y2 = out[0]["bbox"]
    assert (round(x1), round(y1), round(x2), round(y2)) == (200, 100, 300, 250)
    assert out[0]["kp"][0][:2] == pytest.approx([250.0, 120.0], abs=0.2)
