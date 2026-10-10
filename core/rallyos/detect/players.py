"""Players + pose from the pretrained YOLO11n-pose model (person class only, never fine-tuned).

Backends, tried in order by load_pose_detector():
  0. OpenVINO on CPU (the same weights, converted in memory; RALLYOS_POSE_BACKEND=torch turns it off)
  1. ultralytics + PyTorch (models/yolo11n-pose.pt)
  2. OpenCV DNN on an ONNX export of the same pretrained weights (models/yolo11n-pose.onnx), for machines
     where PyTorch can't load (e.g. Windows Application Control blocking its DLLs). Export it once on a
     machine with torch:  yolo export model=yolo11n-pose.pt format=onnx imgsz=640
  3. None: the pipeline skips players and says so in match.json.

Who counts as a player (singles: track 1 = near, track 2 = far). The detector finds every person, so
officials and spectators are filtered out with geometry and time, never with a trained classifier:
  * static people: umpires, service judges and line judges stay in one spot for most of the clip; any
    person whose head stays within a few pixels in >= 40% of sampled frames is ignored
    (find_static_people, a pass over the whole clip before roles are assigned)
  * court boundary (needs the 4-tap calibration): feet at most 1 m outside a sideline and 2.5 m behind a
    baseline. Feet come from the ankle keypoints when visible, else the box bottom
  * height sanity (needs calibration): a person's height measured in court metres at their feet must be
    plausible for a standing player and close to the players seen so far (a raised umpire's chair
    projects to the wrong floor spot and fails this)
A role with no valid candidate in a frame stays empty rather than falling back to someone else.
"""

from __future__ import annotations

import os
import statistics
import threading
from pathlib import Path

import numpy as np

from rallyos.calibration.template_fit import apply_h
from rallyos.device import get_device

DEFAULT_WEIGHTS = "models/yolo11n-pose.pt"
DEFAULT_ONNX = "models/yolo11n-pose.onnx"
SIDE_MARGIN_M = 1.0          # outside the sidelines
END_MARGIN_M = 2.5           # behind the baselines (players retreat further here)
ANKLES = (15, 16)
NEAR, FAR = 1, 2


def weights_path() -> Path:
    """Pretrained weights path (RALLYOS_POSE_WEIGHTS); downloaded once by ultralytics if missing."""
    p = Path(os.environ.get("RALLYOS_POSE_WEIGHTS", DEFAULT_WEIGHTS))
    if not p.is_file():
        from ultralytics.utils.downloads import attempt_download_asset

        p.parent.mkdir(parents=True, exist_ok=True)
        attempt_download_asset(p)
    return p


_MODELS: dict[tuple, object] = {}      # loaded once per process: a second upload does not pay the load time again


class PoseDetector:
    def __init__(self, device: str | None = None, imgsz: int = 1280, conf: float = 0.25):
        from ultralytics import YOLO

        path = str(weights_path())
        if path not in _MODELS:
            _MODELS[path] = YOLO(path)
        self.model = _MODELS[path]
        self.device = get_device(device)
        if os.environ.get("RALLYOS_TORCH_THREADS"):
            import torch

            torch.set_num_threads(int(os.environ["RALLYOS_TORCH_THREADS"]))
        self.imgsz = imgsz
        self.conf = conf

    def __call__(self, frame_bgr: np.ndarray) -> list[dict]:
        r = self.model.predict(frame_bgr, imgsz=self.imgsz, conf=self.conf, classes=[0],
                               device=self.device, verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        kps = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None
        out = []
        for i, b in enumerate(boxes):
            kp = kps[i].round(1).tolist() if kps is not None else None
            out.append({"bbox": [round(float(v), 1) for v in b], "conf": round(float(confs[i]), 3), "kp": kp})
        return out


class OnnxPoseDetector:
    """Same pretrained YOLO11n-pose weights, exported to ONNX, run with OpenCV DNN (no PyTorch)."""

    def __init__(self, onnx_path: str | Path, imgsz: int = 640, conf: float = 0.25, iou: float = 0.45):
        import cv2

        self.net = cv2.dnn.readNetFromONNX(str(onnx_path))
        self.imgsz, self.conf, self.iou = imgsz, conf, iou
        self.device = "cpu"

    def _letterbox(self, img: np.ndarray) -> tuple[np.ndarray, float, float, float]:
        import cv2

        h, w = img.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nw, nh = round(w * r), round(h * r)
        px, py = (self.imgsz - nw) / 2, (self.imgsz - nh) / 2
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        top, left = int(round(py - 0.1)), int(round(px - 0.1))
        canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return canvas, r, px, py

    def __call__(self, frame_bgr: np.ndarray) -> list[dict]:
        import cv2

        img, r, px, py = self._letterbox(frame_bgr)
        self.net.setInput(cv2.dnn.blobFromImage(img, 1 / 255.0, swapRB=True))
        return decode_pose_output(self.net.forward(), r, px, py, self.conf, self.iou)


def decode_pose_output(raw: np.ndarray, r: float, px: float, py: float, conf: float = 0.25,
                       iou: float = 0.45) -> list[dict]:
    """YOLO pose ONNX output (1, 56, N): cx, cy, w, h, person score, 17 x (x, y, visibility) in letterbox px."""
    import cv2

    pred = np.squeeze(raw, 0).T                      # (N, 56)
    pred = pred[pred[:, 4] > conf]
    if not len(pred):
        return []
    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack([(cx - w / 2 - px) / r, (cy - h / 2 - py) / r, w / r, h / r], axis=1)
    keep = cv2.dnn.NMSBoxes(boxes.tolist(), pred[:, 4].tolist(), conf, iou)
    out = []
    for i in np.array(keep).reshape(-1):
        x, y, bw, bh = boxes[i]
        kp = pred[i, 5:].reshape(17, 3).copy()
        kp[:, 0] = (kp[:, 0] - px) / r
        kp[:, 1] = (kp[:, 1] - py) / r
        out.append({"bbox": [round(float(v), 1) for v in (x, y, x + bw, y + bh)], "conf": round(float(pred[i, 4]), 3),
                    "kp": kp.round(1).tolist()})
    return out


_OV_COMPILED: dict[tuple, object] = {}   # (weights, height, width) -> compiled OpenVINO model: a crop size is compiled once per process


class OpenVinoPoseDetector:
    """The same pretrained YOLO11n-pose weights, converted in memory to OpenVINO (no new weights, nothing trained) and run on
    the CPU: about 1.3-1.5x faster than PyTorch for this model. A static input shape is compiled per crop size (the court
    crop is the same size for a whole session), then every frame of that size reuses it. Output decoding is shared with the
    ONNX backend."""

    def __init__(self, imgsz: int = 1280, conf: float = 0.25, iou: float = 0.7):
        import openvino as ov  # noqa: F401 - fail early (ImportError) when the runtime is not installed

        self.weights = str(weights_path())
        self.imgsz, self.conf, self.iou = imgsz, conf, iou
        self.device = "cpu"
        self._tls = threading.local()

    def _compiled(self, h: int, w: int):
        key = (self.weights, h, w)
        if key not in _OV_COMPILED:
            import openvino as ov
            import torch
            from ultralytics import YOLO

            net = YOLO(self.weights).model.eval().fuse()
            net.model[-1].export = True                       # raw (1, 56, N) tensor, as the ONNX export gives
            example = torch.zeros(1, 3, h, w)
            with torch.no_grad():
                traced = torch.jit.trace(net, example, check_trace=False)
            _OV_COMPILED[key] = ov.Core().compile_model(ov.convert_model(traced, example_input=example), "CPU",
                                                       {"PERFORMANCE_HINT": "LATENCY"})
        return _OV_COMPILED[key]

    def _letterbox(self, img: np.ndarray) -> tuple[np.ndarray, float, float, float]:
        import cv2

        h, w = img.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nw, nh = round(w * r), round(h * r)
        W, H = -(-nw // 32) * 32, -(-nh // 32) * 32          # padded to the model's stride of 32
        px, py = (W - nw) / 2, (H - nh) / 2
        canvas = np.full((H, W, 3), 114, np.uint8)
        top, left = int(round(py - 0.1)), int(round(px - 0.1))
        canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        return canvas, r, px, py

    def __call__(self, frame_bgr: np.ndarray) -> list[dict]:
        import cv2

        img, r, px, py = self._letterbox(frame_bgr)
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, swapRB=True)
        key = (img.shape[0], img.shape[1])
        reqs = getattr(self._tls, "reqs", None)
        if reqs is None:
            reqs = self._tls.reqs = {}
        if key not in reqs:                                   # one infer request per thread: a request cannot be entered twice
            reqs[key] = self._compiled(*key).create_infer_request()
        req = reqs[key]
        req.infer({0: blob})
        raw = np.array(req.get_output_tensor(0).data)
        return decode_pose_output(raw, r, px, py, self.conf, self.iou)


def load_pose_detector(device: str | None = None, imgsz: int = 1280) -> tuple[object | None, str]:
    """(detector, backend description). Detector is None when no backend can run on this machine."""
    reasons = []
    # RALLYOS_POSE_BACKEND = auto | torch | openvino. auto: OpenVINO on a CPU run when it is installed (faster), else PyTorch.
    want = os.environ.get("RALLYOS_POSE_BACKEND", "auto").strip().lower()
    if want in ("auto", "openvino") and get_device(device) == "cpu":
        try:
            return OpenVinoPoseDetector(imgsz=imgsz), "yolo11n-pose (OpenVINO, CPU)"
        except Exception as e:  # noqa: BLE001 - not installed or blocked: PyTorch is the fallback, and it is reported
            reasons.append(f"OpenVINO unavailable ({str(e).splitlines()[0][:100]})")
    try:
        return PoseDetector(device=device, imgsz=imgsz), "yolo11n-pose (ultralytics/PyTorch)"
    except (ImportError, OSError) as e:                # OSError: e.g. torch DLL blocked by policy
        reasons.append(f"PyTorch unavailable ({str(e).splitlines()[0][:120]})")
    onnx = Path(os.environ.get("RALLYOS_POSE_ONNX", DEFAULT_ONNX))
    if onnx.is_file():
        try:
            return OnnxPoseDetector(onnx, imgsz=imgsz), "yolo11n-pose (ONNX via OpenCV DNN)"
        except Exception as e:  # noqa: BLE001 - report any OpenCV load failure
            reasons.append(f"ONNX model failed to load ({e})")
    else:
        reasons.append(f"no ONNX export at {onnx}")
    return None, "; ".join(reasons)


# -- who is a player -----------------------------------------------------------------------------------

def foot_px(det_or_bbox) -> tuple[float, float]:
    """Ground contact point in pixels: ankle keypoints when visible, else the bottom centre of the box."""
    det = det_or_bbox if isinstance(det_or_bbox, dict) else {"bbox": det_or_bbox}
    x1, y1, x2, y2 = det["bbox"]
    kp = det.get("kp")
    if kp:
        ankles = [kp[i] for i in ANKLES if kp[i][2] > 0.5]
        if ankles:
            return sum(a[0] for a in ankles) / len(ankles), max(max(a[1] for a in ankles), y2 - 0.04 * (y2 - y1))
    return (x1 + x2) / 2, y2


def head_px(det: dict) -> tuple[float, float]:
    """Head point: nose keypoint when visible, else the top centre of the box. Seated officials' feet
    flicker (legs on chair rungs drop in and out of the box) but their heads barely move."""
    x1, y1, x2, y2 = det["bbox"]
    kp = det.get("kp")
    if kp and kp[0][2] > 0.5:
        return kp[0][0], kp[0][1]
    return (x1 + x2) / 2, y1 + 0.06 * (y2 - y1)


def box_h(det: dict) -> float:
    return det["bbox"][3] - det["bbox"][1]


def find_static_people(frames_dets: list[list[dict]], frame_h: int, min_coverage: float = 0.4,
                       radius_frac: float = 0.05, max_spread_frac: float = 0.02, min_frames: int = 8) -> list[dict]:
    """People who barely move across the clip (umpires, line judges, seated spectators).

    frames_dets = person detections per sampled frame. Head points are clustered greedily (radius
    radius_frac * frame height); a cluster seen in >= min_coverage of the frames whose median distance from
    its median point is at most max_spread_frac * frame height is static. Players move far more than that
    over a rally, and one walking past an official's spot doesn't hide the official.
    """
    n = len(frames_dets)
    if n < min_frames:
        return []
    radius = radius_frac * frame_h
    clusters: list[dict] = []
    for fi, dets in enumerate(frames_dets):
        for d in dets:
            fx, fy = head_px(d)
            best = min(clusters, key=lambda c: (c["cx"] - fx) ** 2 + (c["cy"] - fy) ** 2, default=None)
            if best is not None and np.hypot(best["cx"] - fx, best["cy"] - fy) < radius:
                best["pts"].append((fx, fy))
                best["hs"].append(box_h(d))
                best["frames"].add(fi)
                k = len(best["pts"])
                best["cx"] += (fx - best["cx"]) / k
                best["cy"] += (fy - best["cy"]) / k
            else:
                clusters.append({"cx": fx, "cy": fy, "pts": [(fx, fy)], "hs": [box_h(d)], "frames": {fi}})
    static = []
    for c in clusters:
        coverage = len(c["frames"]) / n
        if coverage < min_coverage:
            continue
        # median centre + median distance: a player walking past the spot adds a few outliers, not spread
        mx = statistics.median(p[0] for p in c["pts"])
        my = statistics.median(p[1] for p in c["pts"])
        spread = statistics.median(float(np.hypot(p[0] - mx, p[1] - my)) for p in c["pts"])
        if spread > max_spread_frac * frame_h:
            continue
        static.append({"head_px": [round(mx, 1), round(my, 1)], "spread_px": round(spread, 1),
                       "height_px": round(statistics.median(c["hs"]), 1), "frames_pct": round(coverage, 3)})
    return static


def _near_static(det: dict, statics: list[dict], frame_h: int) -> bool:
    hx, hy = head_px(det)
    for s in statics:
        r = max(0.035 * frame_h, 4 * s["spread_px"])
        if np.hypot(hx - s["head_px"][0], hy - s["head_px"][1]) < r and 0.65 < box_h(det) / max(1.0, s["height_px"]) < 1.5:
            return True
    return False


class PlayerSelector:
    """Picks the near (1) and far (2) player per frame; everyone else is returned as ignored with a reason."""

    MIN_HEIGHT_M, MAX_HEIGHT_M = 0.7, 3.2      # height in court metres at the feet, before learning
    LEARN_AFTER = 15

    def __init__(self, h: np.ndarray | None, court: dict, frame_h: int, statics: list[dict] | None = None):
        self.h = h
        self.h_inv = np.linalg.inv(h) if h is not None else None
        self.court = court
        self.frame_h = frame_h
        self.statics = statics or []
        self.prev: dict[int, dict] = {}
        self.heights: list[float] = []

    def _apparent_height_m(self, cx: float, cy: float, det: dict) -> float:
        """Box height divided by the local pixels-per-metre across the court at the feet."""
        a, b = apply_h(self.h_inv, [(cx - 0.5, cy), (cx + 0.5, cy)])
        px_per_m = float(np.hypot(*(b - a))) or 1.0
        return box_h(det) / px_per_m

    def _height_ok(self, hm: float) -> bool:
        if len(self.heights) >= self.LEARN_AFTER:
            ref = statistics.median(self.heights[-200:])
            return 0.55 * ref <= hm <= 1.6 * ref
        return self.MIN_HEIGHT_M <= hm <= self.MAX_HEIGHT_M

    def select(self, dets: list[dict]) -> tuple[dict[int, dict], list[dict]]:
        ignored, cands = [], []
        W, L = self.court["width"], self.court["length"]
        for d in dets:
            if _near_static(d, self.statics, self.frame_h):
                ignored.append({"bbox": d["bbox"], "reason": "static (official / spectator)"})
                continue
            fx, fy = foot_px(d)
            pos = hm = None
            if self.h is not None:
                cx, cy = (float(v) for v in apply_h(self.h, [(fx, fy)])[0])
                if not (-SIDE_MARGIN_M <= cx <= W + SIDE_MARGIN_M and -END_MARGIN_M <= cy <= L + END_MARGIN_M):
                    ignored.append({"bbox": d["bbox"], "reason": "off court"})
                    continue
                hm = self._apparent_height_m(cx, cy, d)
                if not self._height_ok(hm):
                    ignored.append({"bbox": d["bbox"], "reason": "implausible size for a player here"})
                    continue
                pos = (cx, cy)
            elif box_h(d) < 0.08 * self.frame_h:
                ignored.append({"bbox": d["bbox"], "reason": "too small (far spectator)"})
                continue
            cands.append({**d, "court_pos": pos, "foot": (fx, fy), "area": box_h(d) * (d["bbox"][2] - d["bbox"][0]), "hm": hm})

        if self.h is not None:
            net = L / 2
            groups = {NEAR: [c for c in cands if c["court_pos"][1] < net], FAR: [c for c in cands if c["court_pos"][1] >= net]}
        else:
            top2 = sorted(cands, key=lambda c: -c["area"])[:2]
            top2.sort(key=lambda c: -c["foot"][1])             # larger foot y = closer to the camera
            groups = {NEAR: top2[:1], FAR: top2[1:]}

        roles: dict[int, dict] = {}
        chosen = set()
        for role, group in groups.items():
            if not group:
                continue
            p = self.prev.get(role)
            best = max(group, key=lambda c: c["area"])
            if p is not None:                                  # stay with the same person when plausible
                pf = foot_px(p)
                near = min(group, key=lambda c: (c["foot"][0] - pf[0]) ** 2 + (c["foot"][1] - pf[1]) ** 2)
                if np.hypot(near["foot"][0] - pf[0], near["foot"][1] - pf[1]) <= 0.25 * self.frame_h:
                    best = near
            chosen.add(id(best))
            if best["hm"] is not None:
                self.heights.append(best["hm"])
            pos = best["court_pos"]
            roles[role] = {"track_id": role, "bbox": best["bbox"], "kp": best["kp"],
                           "court": [round(pos[0], 2), round(pos[1], 2)] if pos else None}
        for c in cands:
            if id(c) not in chosen:
                ignored.append({"bbox": c["bbox"], "reason": "extra person in this half"})
        self.prev = {**self.prev, **roles}
        return roles, ignored


def assign_roles(dets: list[dict], h: np.ndarray | None, court: dict, frame_h: int,
                 prev: dict[int, dict] | None = None) -> dict[int, dict]:
    """Single-frame convenience wrapper (no static filter, no learned heights)."""
    sel = PlayerSelector(h, court, frame_h)
    sel.prev = dict(prev or {})
    return sel.select(dets)[0]
