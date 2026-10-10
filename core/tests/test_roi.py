"""Court regions of interest from the 4 taps: players and the shuttle are only searched on/around the court."""

import numpy as np

from rallyos.calibration import roi
from rallyos.calibration.camera import camera_from_homography
from rallyos.events.landings import in_polygon
from rallyos.sports import load_sport

from test_outcome import HH, W, camera_matrices, to_px

CFG = load_sport("badminton")
P = camera_matrices(f=2400.0, pos=(3.05, -12.0, 6.0))      # raised camera behind the court (typical tripod / stand)
H = np.linalg.inv(P[:, [0, 1, 3]] / P[2, 3])
CAMERA = camera_from_homography(H, W, HH)


def test_player_region_keeps_court_people_and_drops_spectators():
    for camera in (CAMERA, None):
        poly = roi.player_region(H, CFG, W, HH, camera)
        assert in_polygon(to_px(P, (3.0, 3.0, 1.7)), poly)          # near player's head
        assert in_polygon(to_px(P, (3.0, 14.5, 0.0)), poly)         # far player's feet, behind the baseline
        assert not in_polygon(to_px(P, (-5.0, 6.7, 0.0)), poly)     # spectator / coach 5 m off the sideline
        assert not in_polygon(to_px(P, (10.5, 3.0, 0.0)), poly)


def test_ball_region_covers_the_air_above_the_court_only():
    poly = roi.ball_region(H, CFG, W, HH, CAMERA)
    m = roi.mask(poly, W, HH)
    def inside(X):
        x, y = to_px(P, X)
        return 0 <= x < W and 0 <= y < HH and bool(m[int(y), int(x)])
    assert inside((3.0, 10.0, 2.0)) and inside((1.0, 2.0, 0.0)) and inside((5.0, 4.0, 3.5))
    assert not inside((-6.0, 6.7, 1.0))                              # crowd beside the court


def test_cropped_detector_shifts_boxes_and_keypoints_back():
    frame = np.zeros((HH, W, 3), np.uint8)
    def det(crop):
        assert crop.shape[:2] == (500, 800)
        return [{"bbox": [10, 20, 110, 220], "conf": 0.9, "kp": [[50, 60, 0.9], [0, 0, 0.0]]}]
    out = roi.cropped(det, frame, (100, 200, 900, 700))
    assert out[0]["bbox"] == [110, 220, 210, 420]
    assert out[0]["kp"] == [[150, 260, 0.9], [0, 0, 0.0]]                # missing keypoints stay missing
    box = roi.bbox(roi.player_region(H, CFG, W, HH, CAMERA), W, HH)
    assert 0 <= box[0] < box[2] <= W and 0 <= box[1] < box[3] <= HH
