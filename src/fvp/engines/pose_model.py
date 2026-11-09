"""Stima della posa 2D (rilevamento persone YOLOX + keypoint RTMPose, formato HALPE-26) con ONNX Runtime.

È la stessa catena di modelli usata da Sports2D (modalità "balanced" di rtmlib), reimplementata qui per tre motivi:
- rtmlib dipende da opencv-python e opencv-contrib-python, che entrano in conflitto con opencv-python-headless e
  con i plugin Qt di PySide6 nella build;
- rtmlib scarica i modelli da Internet al primo uso: qui i modelli sono file locali, installati e verificati con
  SHA-256 da tools/fetch_tools.py, e l'impronta di ciascuno è registrata in ogni analisi;
- l'inferenza è vincolata a CPUExecutionProvider, per risultati ripetibili sulla stessa macchina.

Pre e post-elaborazione seguono rtmlib (Apache-2.0, T. Jiang): letterbox YOLOX con riempimento 114, ritaglio
affine top-down con margine 1.25, normalizzazione mean/std sul frame BGR, decodifica SimCC con fattore 2.

Avviso ai sensi della licenza Apache-2.0, sezione 4(b): questo file contiene codice derivato da rtmlib
(https://github.com/Tau-J/rtmlib, Copyright 2018-2020 Open-MMLab; T. Jiang), modificato per Forensic Vision Pro:
rimossi download dei modelli e backend diversi da ONNX Runtime su CPU, decodifica YOLOX limitata alla classe persona
per i modelli senza NMS, aggiunta la verifica delle impronte dei modelli. Testo della licenza:
licenses/Apache-2.0.txt.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from ..core.tools import _bundled_dir

DET_FILE = "pose_det_yolox_m_humanart.onnx"
POSE_FILE = "pose_rtmpose_m_halpe26.onnx"
DEFAULT_DET_INPUT = (640, 640)       # (altezza, larghezza)
DEFAULT_POSE_INPUT = (192, 256)      # (larghezza, altezza)
MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)


class PoseUnavailable(RuntimeError):
    """La stima della posa non può essere eseguita (runtime o modelli assenti o non verificati)."""


@dataclass(frozen=True)
class ModelFile:
    role: str
    path: str
    sha256: str
    size: int
    verified_against_lock: bool

    def to_dict(self) -> dict:
        return {"role": self.role, "file": Path(self.path).name, "sha256": self.sha256, "size": self.size,
                "verified_against_lock": self.verified_against_lock}


def _models_home() -> Path:
    from ..core.config import default_home
    return default_home() / "models"


def _candidates(name: str, configured: str) -> list[Path]:
    out = []
    if configured:
        out.append(Path(configured))
    out += [_bundled_dir() / name, _models_home() / name]
    return out


@lru_cache(maxsize=8)
def _sha256_cached(path: str, size: int, mtime_ns: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _lock_hashes() -> dict[str, str]:
    lock = _bundled_dir() / "tools.lock.json"
    if not lock.is_file():
        return {}
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for info in data.values():
        out.update(info.get("file_hashes", {}))
    return out


def locate_models(det_path: str = "", pose_path: str = "") -> tuple[ModelFile, ModelFile]:
    """Trova i due modelli e ne calcola l'impronta. Se il file è registrato in tools.lock.json, l'impronta deve
    coincidere: un modello modificato non viene caricato."""
    lock = _lock_hashes()
    found = []
    for role, name, conf in (("detector", DET_FILE, det_path), ("pose", POSE_FILE, pose_path)):
        p = next((c for c in _candidates(name, conf) if c.is_file()), None)
        if p is None:
            raise PoseUnavailable(
                f"Modello '{name}' non trovato (cercato in: impostazioni, {_bundled_dir()}, {_models_home()}). "
                "Installarlo con: python tools/fetch_tools.py --only pose-models")
        st = p.stat()
        digest = _sha256_cached(str(p), st.st_size, st.st_mtime_ns)
        expected = lock.get(p.name) if p.parent == _bundled_dir() else None
        if expected and expected != digest:
            raise PoseUnavailable(f"Il modello {p.name} non corrisponde a tools.lock.json (atteso {expected}, "
                                  f"ottenuto {digest}): non viene usato.")
        found.append(ModelFile(role, str(p), digest, st.st_size, bool(expected)))
    return found[0], found[1]


def runtime_version() -> str:
    try:
        import onnxruntime as ort
        return ort.__version__
    except ImportError:
        return "non disponibile"


# ------------------------------------------------------------------ pre/post-elaborazione (da rtmlib)

def letterbox(img: np.ndarray, size_hw: tuple[int, int]) -> tuple[np.ndarray, float]:
    h, w = size_hw
    ratio = min(h / img.shape[0], w / img.shape[1])
    out = np.full((h, w, 3), 114, dtype=np.uint8)
    nh, nw = int(img.shape[0] * ratio), int(img.shape[1] * ratio)
    out[:nh, :nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return out, ratio


def nms(boxes: np.ndarray, scores: np.ndarray, thr: float) -> list[int]:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= thr)[0] + 1]
    return keep


def yolox_decode(out: np.ndarray, ratio: float, size_hw: tuple[int, int], score_thr: float,
                 nms_thr: float = 0.45) -> np.ndarray:
    """Restituisce (N, 5): x1, y1, x2, y2, punteggio, nelle coordinate del frame."""
    if out.shape[-1] == 5:                       # modello end2end con NMS incorporata
        dets = out[0].astype(np.float32)
        dets = dets[dets[:, 4] > score_thr]
        dets[:, :4] /= ratio
        return dets
    strides = (8, 16, 32)                        # uscita grezza: decodifica della griglia e NMS
    grids, exp = [], []
    for s in strides:
        hs, ws = size_hw[0] // s, size_hw[1] // s
        xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
        g = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(g)
        exp.append(np.full((*g.shape[:2], 1), s))
    o = out.astype(np.float32).copy()
    o[..., :2] = (o[..., :2] + np.concatenate(grids, 1)) * np.concatenate(exp, 1)
    o[..., 2:4] = np.exp(o[..., 2:4]) * np.concatenate(exp, 1)
    p = o[0]
    sc = p[:, 4] * p[:, 5]                       # classe 0 (persona)
    m = sc > score_thr
    if not m.any():
        return np.zeros((0, 5), np.float32)
    b = p[m, :4]
    xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1)
    xyxy /= ratio
    keep = nms(xyxy, sc[m], nms_thr)
    return np.concatenate([xyxy[keep], sc[m][keep, None]], 1).astype(np.float32)


def bbox_cs(bbox: np.ndarray, padding: float = 1.25) -> tuple[np.ndarray, np.ndarray]:
    x1, y1, x2, y2 = bbox[:4]
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2], np.float32), np.array([(x2 - x1), (y2 - y1)], np.float32) * padding


def _third(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = a - b
    return b + np.r_[-d[1], d[0]]


def warp_matrix(center: np.ndarray, scale: np.ndarray, out_wh: tuple[int, int], inv: bool = False) -> np.ndarray:
    w, h = out_wh
    src = np.zeros((3, 2), np.float32)
    dst = np.zeros((3, 2), np.float32)
    src[0] = center
    src[1] = center + np.array([0.0, scale[0] * -0.5])
    src[2] = _third(src[0], src[1])
    dst[0] = [w * 0.5, h * 0.5]
    dst[1] = dst[0] + np.array([0.0, w * -0.5])
    dst[2] = _third(dst[0], dst[1])
    return cv2.getAffineTransform(dst, src) if inv else cv2.getAffineTransform(src, dst)


def top_down_crop(img: np.ndarray, center: np.ndarray, scale: np.ndarray,
                  in_wh: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    w, h = in_wh
    ar = w / h
    bw, bh = scale
    scale = np.array([bw, bw / ar] if bw > bh * ar else [bh * ar, bh], np.float32)
    m = warp_matrix(center, scale, (w, h))
    return cv2.warpAffine(img, m, (int(w), int(h)), flags=cv2.INTER_LINEAR), scale


def simcc_decode(sx: np.ndarray, sy: np.ndarray, in_wh: tuple[int, int], center: np.ndarray, scale: np.ndarray,
                 split: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    n, k, _ = sx.shape
    fx, fy = sx.reshape(n * k, -1), sy.reshape(n * k, -1)
    locs = np.stack([fx.argmax(1), fy.argmax(1)], -1).astype(np.float32)
    vals = (fx.max(1) + fy.max(1)) / 2.0
    locs[vals <= 0] = -1
    kp = locs.reshape(n, k, 2) / split
    kp = kp / np.array(in_wh, np.float32) * scale + center - scale / 2
    return kp, vals.reshape(n, k).astype(np.float32)


# ------------------------------------------------------------------ stimatore

class PoseEstimator:
    """Rilevatore di persone + stimatore top-down di 26 keypoint (HALPE-26)."""

    def __init__(self, det: ModelFile, pose: ModelFile, det_score_thr: float = 0.3, threads: int = 0):
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise PoseUnavailable("ONNX Runtime non installato (pip install onnxruntime)") from e
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        so.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        try:
            self.det_sess = ort.InferenceSession(det.path, sess_options=so, providers=prov)
            self.pose_sess = ort.InferenceSession(pose.path, sess_options=so, providers=prov)
        except Exception as e:  # noqa: BLE001 - file non valido o incompatibile
            raise PoseUnavailable(f"Modelli ONNX non caricabili: {type(e).__name__}: {e}") from e
        self.det_model, self.pose_model = det, pose
        self.det_score_thr = det_score_thr
        ds = self.det_sess.get_inputs()[0].shape
        self.det_hw = (ds[2], ds[3]) if all(isinstance(x, int) for x in ds[2:4]) else DEFAULT_DET_INPUT
        ps = self.pose_sess.get_inputs()[0].shape
        self.pose_wh = (ps[3], ps[2]) if all(isinstance(x, int) for x in ps[2:4]) else DEFAULT_POSE_INPUT
        self.det_in = self.det_sess.get_inputs()[0].name
        self.pose_in = self.pose_sess.get_inputs()[0].name

    def describe(self) -> dict:
        return {"runtime": f"onnxruntime {runtime_version()}", "provider": "CPUExecutionProvider",
                "detector": {**self.det_model.to_dict(), "input_hw": list(self.det_hw),
                             "score_thr": self.det_score_thr},
                "pose": {**self.pose_model.to_dict(), "input_wh": list(self.pose_wh), "keypoints": "HALPE-26",
                         "bbox_padding": 1.25, "simcc_split": 2.0}}

    def detect(self, img: np.ndarray) -> np.ndarray:
        x, ratio = letterbox(img, self.det_hw)
        inp = np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)
        out = self.det_sess.run(None, {self.det_in: inp})[0]
        return yolox_decode(out, ratio, self.det_hw, self.det_score_thr)

    def keypoints(self, img: np.ndarray, boxes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if len(boxes) == 0:
            return np.zeros((0, 26, 2), np.float32), np.zeros((0, 26), np.float32)
        kps, scs = [], []
        for b in boxes:
            c, s = bbox_cs(np.asarray(b, np.float32))
            crop, s2 = top_down_crop(img, c, s, self.pose_wh)
            x = (crop.astype(np.float32) - MEAN) / STD
            inp = np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)
            sx, sy = self.pose_sess.run(None, {self.pose_in: inp})[:2]
            k, v = simcc_decode(sx, sy, self.pose_wh, c, s2)
            kps.append(k)
            scs.append(v)
        return np.concatenate(kps), np.concatenate(scs)

    def __call__(self, img: np.ndarray, boxes: np.ndarray | None = None):
        if boxes is None:
            boxes = self.detect(img)
        return self.keypoints(img, boxes[:, :4] if len(boxes) else boxes)


def load(det_path: str = "", pose_path: str = "", threads: int = 0) -> PoseEstimator:
    det, pose = locate_models(det_path, pose_path)
    return PoseEstimator(det, pose, threads=threads or max(1, (os.cpu_count() or 2) - 1))
