"""POST /v1/calibrate: one video frame -> the court found automatically (sport, 4 corners, quality), or the
homography from 4 given corner taps. Thin wrapper: the logic lives in rallyos.calibration."""
import json

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

router = APIRouter(tags=["calibrate"])


def _decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "the frame is not a readable image (send a JPEG or PNG)")
    return img


@router.post("/calibrate")
async def calibrate(frame: UploadFile = File(...), sport: str | None = Form(None), taps: str | None = Form(None)):
    """Without `taps`: automatic Court Fingerprint on this frame (`sport` = one sport, or empty/"auto" to try all).
    With `taps` ([[x,y]*4]: near-left, near-right, far-right, far-left, in frame pixels): the 4-tap calibration.

    Returns {"found": bool, "sport", "sport_confidence", "quality": "high" | "check", "corners_px", ...}.
    quality "check" means the court was found but part of it was hidden (net, graphics, players): show the corners
    to the user and let them adjust. A single frame still has the players on it, so the full pipeline, which
    looks at several frames, can do slightly better than this preview.
    """
    from rallyos.calibration.camera import camera_from_homography
    from rallyos.calibration.court_fit import detect_court
    from rallyos.calibration.template_fit import homography_from_taps
    from rallyos.sports import list_sports, load_sport

    img = _decode(await frame.read())
    h, w = img.shape[:2]
    chosen = None if sport in (None, "", "auto") else sport
    if chosen and chosen not in list_sports():
        raise HTTPException(404, f"unknown sport {chosen!r}; available: {list_sports()}")
    if taps:
        try:
            pts = json.loads(taps)
            calib = homography_from_taps(pts, load_sport(chosen or "badminton"))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from None
        cam = camera_from_homography(np.array(calib["homography"]), w, h)
        return {"found": True, "method": "4-tap", "sport": chosen or "badminton", "used_taps": True,
                "homography": calib["homography"], "corners_px": calib["taps_px"],
                "focal_px": cam and cam["focal_px"], "camera_position_m": cam and cam["position_m"]}
    det = await run_in_threadpool(detect_court, [img], [chosen] if chosen else None)
    if det is None:
        return {"found": False, "used_taps": False, "width": w, "height": h,
                "message": "No court found in this frame. Tap the 4 outer corners instead."}
    cam = camera_from_homography(
        np.array(homography_from_taps(det["corners_px"], load_sport(det["sport"]))["homography"]), w, h)
    return {"found": True, "method": "auto", "used_taps": False, "width": w, "height": h, **det,
            "focal_px": cam and cam["focal_px"], "camera_position_m": cam and cam["position_m"]}
