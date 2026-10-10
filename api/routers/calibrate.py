"""POST /v1/calibrate: frame (+ optional 4 corner taps) -> sport, H, K, fit_error."""
from fastapi import APIRouter, File, Form, UploadFile

router = APIRouter(tags=["calibrate"])


@router.post("/calibrate")
async def calibrate(frame: UploadFile = File(...), taps: str | None = Form(None)):
    """taps: optional JSON [[x,y],...] with the 4 court corners.
    MOCK until rallyos.calibration is wired in (core owns the real logic)."""
    await frame.read()
    return {"mock": True, "sport": "badminton", "sport_confidence": 0.96,
            "homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "focal_px": 1450.0,
            "fit_error_px": 3.1, "used_taps": taps is not None}
