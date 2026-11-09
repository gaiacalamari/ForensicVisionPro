"""Human Pose & Kinematics Engine: analisi di persone e movimento in immagini e video (metodologia Sports2D).

Cosa calcola, come Sports2D (D. Pagnon, BSD-3-Clause):
- posa 2D di ogni persona con 26 keypoint HALPE (YOLOX + RTMPose, vedi pose_model.py);
- tracciamento delle persone tra i frame;
- angoli articolari e segmentali con le definizioni, gli offset e il lato visibile di Sports2D/Pose2Sim;
- interpolazione dei buchi brevi e filtro Butterworth passa-basso a fase zero;
- esportazione in CSV e nei formati TRC/MOT di Sports2D (apribili in OpenSim, Blender, Excel).

Cosa aggiunge per l'uso forense (non presente in Sports2D):
- discontinuità cinematiche: spostamenti o cambi di scala di una persona tra due frame consecutivi incompatibili
  con un movimento umano reale, classificati come "di scena" (tutte le persone, con conferma da timestamp o
  differenza dell'immagine) oppure "isolati" (tipici di errori di stima o di tracciamento);
- sostituzione simultanea di tutte le persone in scena;
- cadenza del passo (stima spettrale) come dato descrittivo per il confronto dell'andatura;
- posture insolite (iperestensioni marcate) come indicatore probabilistico, utile anche su immagini sintetiche.

Le discontinuità sono calcolate sui keypoint grezzi: il filtro Butterworth (usato solo per gli angoli) attenuerebbe
proprio i salti da cercare. Nessun risultato di questo modulo è una misura antropometrica: le coordinate sono in
pixel, senza calibrazione della camera.
"""
from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..core.findings import Category, Finding, Level
from ..core.tasks import CancelToken
from .pose_model import PoseUnavailable  # noqa: F401  (rilanciato dalla pipeline)

__all__ = ["analyze", "PoseUnavailable", "Params", "compute_angles", "transitions", "cadence"]
MODULE = "pose"
METHOD = "Stima della posa 2D (YOLOX + RTMPose HALPE-26) e cinematica in stile Sports2D"

HALPE26 = ["Nose", "LEye", "REye", "LEar", "REar", "LShoulder", "RShoulder", "LElbow", "RElbow", "LWrist", "RWrist",
           "LHip", "RHip", "LKnee", "RKnee", "LAnkle", "RAnkle", "Head", "Neck", "Hip", "LBigToe", "RBigToe",
           "LSmallToe", "RSmallToe", "LHeel", "RHeel"]
KP = {n: i for i, n in enumerate(HALPE26)}
EDGES = [("Nose", "LEye"), ("Nose", "REye"), ("LEye", "LEar"), ("REye", "REar"), ("Head", "Neck"),
         ("Neck", "LShoulder"), ("Neck", "RShoulder"), ("LShoulder", "LElbow"), ("LElbow", "LWrist"),
         ("RShoulder", "RElbow"), ("RElbow", "RWrist"), ("Neck", "Hip"), ("Hip", "LHip"), ("Hip", "RHip"),
         ("LHip", "LKnee"), ("LKnee", "LAnkle"), ("RHip", "RKnee"), ("RKnee", "RAnkle"), ("LAnkle", "LBigToe"),
         ("LAnkle", "LSmallToe"), ("LAnkle", "LHeel"), ("RAnkle", "RBigToe"), ("RAnkle", "RSmallToe"),
         ("RAnkle", "RHeel")]

# Definizioni degli angoli di Sports2D/Pose2Sim (Pose2Sim/common.py): keypoint, tipo, offset, fattore di scala.
# 'right wrist', 'left wrist', 'right hand', 'left hand' richiedono il keypoint Index, assente in HALPE-26: sono
# esclusi (in Sports2D, con lo stesso modello, risultano sempre NaN).
ANGLE_DICT: dict[str, tuple[list[str], str, float, float]] = {
    "right ankle": (["RKnee", "RAnkle", "RBigToe", "RHeel"], "dorsiflexion", 90, 1),
    "left ankle": (["LKnee", "LAnkle", "LBigToe", "LHeel"], "dorsiflexion", 90, 1),
    "right knee": (["RAnkle", "RKnee", "RHip"], "flexion", -180, 1),
    "left knee": (["LAnkle", "LKnee", "LHip"], "flexion", -180, 1),
    "right hip": (["RKnee", "RHip", "Hip", "Neck"], "flexion", 0, -1),
    "left hip": (["LKnee", "LHip", "Hip", "Neck"], "flexion", 0, -1),
    "right shoulder": (["RElbow", "RShoulder", "Hip", "Neck"], "flexion", 0, -1),
    "left shoulder": (["LElbow", "LShoulder", "Hip", "Neck"], "flexion", 0, -1),
    "right elbow": (["RWrist", "RElbow", "RShoulder"], "flexion", 180, -1),
    "left elbow": (["LWrist", "LElbow", "LShoulder"], "flexion", 180, -1),
    "right foot": (["RBigToe", "RHeel"], "horizontal", 0, -1),
    "left foot": (["LBigToe", "LHeel"], "horizontal", 0, -1),
    "right shank": (["RAnkle", "RKnee"], "horizontal", 0, -1),
    "left shank": (["LAnkle", "LKnee"], "horizontal", 0, -1),
    "right thigh": (["RKnee", "RHip"], "horizontal", 0, -1),
    "left thigh": (["LKnee", "LHip"], "horizontal", 0, -1),
    "pelvis": (["LHip", "RHip"], "horizontal", 0, -1),
    "trunk": (["Neck", "Hip"], "horizontal", 0, -1),
    "shoulders": (["LShoulder", "RShoulder"], "horizontal", 0, -1),
    "head": (["Head", "Neck"], "horizontal", 0, -1),
    "right arm": (["RElbow", "RShoulder"], "horizontal", 0, -1),
    "left arm": (["LElbow", "LShoulder"], "horizontal", 0, -1),
    "right forearm": (["RWrist", "RElbow"], "horizontal", 0, -1),
    "left forearm": (["LWrist", "LElbow"], "horizontal", 0, -1),
}
ANGLE_NAMES = list(ANGLE_DICT)
ANGLE_LABELS_IT = {
    "right ankle": "caviglia destra", "left ankle": "caviglia sinistra", "right knee": "ginocchio destro",
    "left knee": "ginocchio sinistro", "right hip": "anca destra", "left hip": "anca sinistra",
    "right shoulder": "spalla destra", "left shoulder": "spalla sinistra", "right elbow": "gomito destro",
    "left elbow": "gomito sinistro", "right foot": "piede destro", "left foot": "piede sinistro",
    "right shank": "gamba destra", "left shank": "gamba sinistra", "right thigh": "coscia destra",
    "left thigh": "coscia sinistra", "pelvis": "bacino", "trunk": "tronco", "shoulders": "linea delle spalle",
    "head": "testa", "right arm": "braccio destro", "left arm": "braccio sinistro",
    "right forearm": "avambraccio destro", "left forearm": "avambraccio sinistro",
}


@dataclass
class Params:
    kpt_thr: float = 0.3            # Sports2D: keypoint_likelihood_threshold
    reliable_thr: float = 0.5       # keypoint usati per le misure forensi
    det_every: int = 4              # Sports2D: det_frequency
    redetect_below: float = 0.4     # nuovo rilevamento se la confidenza media cala
    max_frames: int = 3600
    frame_step: int = 1
    track_gate: float = 1.0         # distanza massima di associazione, in altezze della persona
    max_missing: int = 10           # frame di assenza oltre i quali una traccia è chiusa
    interp_gap: int = 10            # Sports2D: interp_gap_smaller_than
    butter_order: int = 4           # Sports2D: butterworth order (doppio passaggio)
    butter_cutoff: float = 6.0      # Sports2D: cut_off_frequency (Hz)
    v_max: float = 8.0              # altezze/s: oltre lo sprint umano (≈13 m/s per 1,70 m)
    jump_min: float = 0.15          # spostamento minimo (altezze) per considerare un salto
    jump_strong: float = 0.5        # salto netto anche per una persona sola
    scale_jump: float = 1.33        # rapporto di altezza tra frame consecutivi
    hyperext_deg: float = -25.0     # iperestensione di gomito/ginocchio
    save_video: bool = False

    @classmethod
    def from_settings(cls, s) -> "Params":
        p = cls()
        p.max_frames = int(getattr(s, "pose_max_frames", p.max_frames))
        p.frame_step = max(1, int(getattr(s, "pose_frame_step", p.frame_step)))
        p.det_every = max(1, int(getattr(s, "pose_det_every", p.det_every)))
        p.save_video = bool(getattr(s, "pose_save_video", p.save_video))
        return p


# ------------------------------------------------------------------ angoli (Pose2Sim/common.py)

def points_to_angles(pts: list[np.ndarray]) -> float:
    a = np.asarray(pts, dtype=float)
    if len(a) == 2:
        u = a[0] - a[1]
        return float(np.degrees(np.arctan2(u[1], u[0])))
    if len(a) == 3:
        u, v = a[0] - a[1], a[2] - a[1]
    elif len(a) == 4:
        u, v = a[1] - a[0], a[3] - a[2]
    else:
        return float("nan")
    cross = u[0] * v[1] - u[1] * v[0]
    dot = u[0] * v[0] + u[1] * v[1]
    return float(np.degrees(-np.arctan2(cross, dot)))


def fixed_angle(pts: list[np.ndarray], name: str) -> float:
    _k, _t, off, sc = ANGLE_DICT[name]
    ang = (points_to_angles(pts) + off) * sc
    if name in ("pelvis", "shoulders"):
        return (ang + 90) % 180 - 90
    return (ang + 180) % 360 - 180


def visible_side(x: np.ndarray) -> str:
    """Lato visibile come Sports2D ('auto'): punte dei piedi davanti o dietro ai talloni."""
    vals = [x[KP["RBigToe"]] - x[KP["RHeel"]], x[KP["LBigToe"]] - x[KP["LHeel"]]]
    vals = [v for v in vals if np.isfinite(v)]
    if not vals:
        return "right"
    return "right" if sum(vals) >= 0 else "left"


def compute_angles(xy: np.ndarray, side: str = "auto") -> tuple[dict[str, float], str]:
    """xy: (26, 2) in pixel, NaN dove il keypoint non è affidabile."""
    side = visible_side(xy[:, 0]) if side == "auto" else side
    xf = xy[:, 0].copy()
    if side == "left":
        xf = -xf
    out = {}
    for name, (kpts, _t, _o, _s) in ANGLE_DICT.items():
        if any(k not in KP for k in kpts):
            out[name] = float("nan")
            continue
        pts = [np.array([xf[KP[k]], xy[KP[k], 1]]) for k in kpts]
        out[name] = fixed_angle(pts, name) if all(np.isfinite(p).all() for p in pts) else float("nan")
    return out, side


# ------------------------------------------------------------------ filtri

def butter_lowpass(order: int, cutoff: float, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Coefficienti (b, a) di un Butterworth passa-basso di ordine pari, trasformazione bilineare con prewarping."""
    if order % 2 or order < 2:
        raise ValueError("ordine pari richiesto")
    wc = 2 * fs * math.tan(math.pi * cutoff / fs)
    k = 2 * fs
    b, a = np.array([1.0]), np.array([1.0])
    for i in range(order // 2):
        th = math.pi * (2 * i + 1) / (2 * order)
        al = 2 * wc * math.sin(th)
        d = k * k + al * k + wc * wc
        bb = np.array([wc * wc, 2 * wc * wc, wc * wc]) / d
        aa = np.array([1.0, 2 * (wc * wc - k * k) / d, (k * k - al * k + wc * wc) / d])
        b, a = np.convolve(b, bb), np.convolve(a, aa)
    return b, a


def _lfilter(b, a, x, zi):
    y = np.empty_like(x)
    z = zi.astype(float).copy()
    n = len(z)
    for i, xi in enumerate(x):
        yi = b[0] * xi + (z[0] if n else 0.0)
        for j in range(n - 1):
            z[j] = b[j + 1] * xi + z[j + 1] - a[j + 1] * yi
        if n:
            z[n - 1] = b[n] * xi - a[n] * yi
        y[i] = yi
    return y


def _lfilter_zi(b, a):
    n = max(len(a), len(b)) - 1
    m = np.zeros((n, n))                       # matrice compagna, come scipy.signal.lfilter_zi
    m[0, :] = -a[1:]
    m[1:, :-1] = np.eye(n - 1)
    return np.linalg.solve(np.eye(n) - m.T, b[1:] - a[1:] * b[0])


def filtfilt(b: np.ndarray, a: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Filtro a fase zero (come scipy.signal.filtfilt con padtype='odd')."""
    pad = 3 * max(len(a), len(b))
    if len(x) <= pad:
        return x.copy()
    ext = np.concatenate([2 * x[0] - x[pad:0:-1], x, 2 * x[-1] - x[-2:-pad - 2:-1]])
    zi = _lfilter_zi(b, a)
    y = _lfilter(b, a, ext, zi * ext[0])
    y = _lfilter(b, a, y[::-1], zi * y[-1])[::-1]
    return y[pad:-pad]


def interpolate_gaps(x: np.ndarray, max_gap: int) -> np.ndarray:
    """Interpolazione lineare dei buchi (NaN) lunghi al massimo max_gap campioni; i buchi più lunghi restano."""
    y = x.astype(float).copy()
    ok = np.isfinite(y)
    if ok.sum() < 2:
        return y
    idx = np.arange(len(y))
    i = 0
    while i < len(y):
        if ok[i]:
            i += 1
            continue
        j = i
        while j < len(y) and not ok[j]:
            j += 1
        if i > 0 and j < len(y) and (j - i) <= max_gap:
            y[i:j] = np.interp(idx[i:j], [i - 1, j], [y[i - 1], y[j]])
        i = j
    return y


def smooth_series(x: np.ndarray, fs: float, p: Params) -> np.ndarray:
    """Interpolazione + Butterworth per tratti continui (i buchi lunghi non vengono attraversati dal filtro)."""
    y = interpolate_gaps(x, p.interp_gap)
    if not fs or fs <= 2 * p.butter_cutoff:
        return y
    # come Pose2Sim: butter(order/2) applicato in avanti e all'indietro, ordine effettivo = order
    b, a = butter_lowpass(max(2, p.butter_order // 4 * 2), p.butter_cutoff, fs)
    ok = np.isfinite(y)
    out = y.copy()
    i = 0
    while i < len(y):
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < len(y) and ok[j]:
            j += 1
        out[i:j] = filtfilt(b, a, y[i:j])
        i = j
    return out


# ------------------------------------------------------------------ tracciamento

@dataclass
class Track:
    tid: int
    frames: list[int] = field(default_factory=list)
    kpts: list[np.ndarray] = field(default_factory=list)       # (26, 2)
    scores: list[np.ndarray] = field(default_factory=list)     # (26,)
    missing: int = 0

    @property
    def last(self) -> tuple[np.ndarray, np.ndarray]:
        return self.kpts[-1], self.scores[-1]


def body_height(k: np.ndarray, s: np.ndarray, thr: float) -> float:
    m = s >= thr
    if m.sum() < 3:
        return 0.0
    return float(k[m, 1].max() - k[m, 1].min())


def full_body(s: np.ndarray, thr: float) -> bool:
    head = max(s[KP["Head"]], s[KP["Nose"]]) >= thr
    feet = max(s[KP["LAnkle"]], s[KP["RAnkle"]]) >= thr
    return bool(head and feet)


class Tracker:
    """Associazione greedy per distanza mediana dei keypoint, normalizzata sull'altezza della persona."""

    def __init__(self, p: Params):
        self.p = p
        self.active: list[Track] = []
        self.done: list[Track] = []
        self.next_id = 1

    def update(self, frame: int, kpts: np.ndarray, scores: np.ndarray) -> list[tuple[int, int]]:
        p = self.p
        pairs = []
        for i, t in enumerate(self.active):
            tk, ts = t.last
            h = max(body_height(tk, ts, p.kpt_thr), 1.0)
            for j in range(len(kpts)):
                m = (ts >= p.kpt_thr) & (scores[j] >= p.kpt_thr)
                if m.sum() < 4:
                    continue
                c = float(np.median(np.linalg.norm(tk[m] - kpts[j][m], axis=1))) / h
                if c <= p.track_gate:
                    pairs.append((c, i, j))
        pairs.sort()
        used_t, used_d, matched = set(), set(), []
        for _c, i, j in pairs:
            if i in used_t or j in used_d:
                continue
            used_t.add(i)
            used_d.add(j)
            t = self.active[i]
            t.frames.append(frame)
            t.kpts.append(kpts[j].astype(np.float32))
            t.scores.append(scores[j].astype(np.float32))
            t.missing = 0
            matched.append((t.tid, j))
        for i, t in enumerate(self.active):
            if i not in used_t:
                t.missing += 1
        for j in range(len(kpts)):
            if j not in used_d and (scores[j] >= p.kpt_thr).sum() >= 4:
                t = Track(self.next_id, [frame], [kpts[j].astype(np.float32)], [scores[j].astype(np.float32)])
                self.next_id += 1
                self.active.append(t)
                matched.append((t.tid, j))
        keep = []
        for t in self.active:
            (self.done if t.missing > p.max_missing else keep).append(t)
        self.active = keep
        return matched

    def all_tracks(self) -> list[Track]:
        return sorted(self.done + self.active, key=lambda t: t.tid)


# ------------------------------------------------------------------ analisi forensi

def transitions(tracks: list[Track], times: np.ndarray, vis_diff: np.ndarray, p: Params) -> list[dict]:
    """Discontinuità tra frame analizzati consecutivi. times e vis_diff sono indicizzati per frame analizzato."""
    n = len(times)
    if n < 3:
        return []
    dts = np.diff(times)
    med_dt = float(np.median(dts[dts > 0])) if (dts > 0).any() else 0.0
    vd = vis_diff[1:][np.isfinite(vis_diff[1:])]
    med_vd = float(np.median(vd)) if len(vd) else 0.0
    present: dict[int, set[int]] = {}
    for t in tracks:
        for f in t.frames:
            present.setdefault(f, set()).add(t.tid)
    events: dict[int, dict] = {}

    def ev(f: int) -> dict:
        if f not in events:
            dt = float(times[f] - times[f - 1])
            events[f] = {"frame": f, "time_s": round(float(times[f]), 3), "dt_s": round(dt, 4),
                         "dt_ratio": round(dt / med_dt, 2) if med_dt else None,
                         "visual_ratio": round(float(vis_diff[f]) / med_vd, 2) if med_vd and np.isfinite(vis_diff[f])
                         else None, "jumps": [], "scale": [], "replaced": False}
        return events[f]

    for t in tracks:
        if len(t.frames) < 2:
            continue
        hs = [body_height(k, s, p.reliable_thr) for k, s in zip(t.kpts, t.scores)]
        hs_ok = [h for h in hs if h > 0]
        if not hs_ok:
            continue
        H = float(np.median(hs_ok))
        for a in range(1, len(t.frames)):
            f0, f1 = t.frames[a - 1], t.frames[a]
            if f1 - f0 != 1:
                continue                            # la persona mancava: nessun confronto tra frame adiacenti
            k0, s0, k1, s1 = t.kpts[a - 1], t.scores[a - 1], t.kpts[a], t.scores[a]
            m = (s0 >= p.reliable_thr) & (s1 >= p.reliable_thr)
            if m.sum() < 6 or H <= 0:
                continue
            d = float(np.median(np.linalg.norm(k1[m] - k0[m], axis=1))) / H
            dt = float(times[f1] - times[f0]) or (med_dt or 1.0)
            v = d / dt
            conf = float(min(s0[m].mean(), s1[m].mean()))
            if d >= p.jump_min and v > p.v_max:
                ev(f1)["jumps"].append({"track": t.tid, "jump_h": round(d, 3), "speed_h_s": round(v, 1),
                                        "confidence": round(conf, 2)})
            if full_body(s0, p.reliable_thr) and full_body(s1, p.reliable_thr) and hs[a - 1] > 0 and hs[a] > 0:
                r = hs[a] / hs[a - 1]
                if r > p.scale_jump or r < 1 / p.scale_jump:
                    ev(f1)["scale"].append({"track": t.tid, "ratio": round(r, 2)})
    for f in range(1, n):
        before, after = present.get(f - 1, set()), present.get(f, set())
        if before and after and not (before & after):
            long_before = [t for t in tracks if t.tid in before and len(t.frames) >= 5]
            if long_before:
                ev(f)["replaced"] = True
    out = []
    for f, e in sorted(events.items()):
        tracks_here = present.get(f, set()) & present.get(f - 1, set())
        flagged = {j["track"] for j in e["jumps"]} | {s["track"] for s in e["scale"]}
        corroborated = bool((e["dt_ratio"] and e["dt_ratio"] > 1.8) or (e["visual_ratio"] and e["visual_ratio"] > 4))
        strong = any(j["jump_h"] >= p.jump_strong and j["confidence"] >= 0.6 for j in e["jumps"])
        all_moved = bool(tracks_here) and tracks_here <= flagged
        scene = e["replaced"] or (all_moved and (len(tracks_here) >= 2 or corroborated or strong))
        e["tracks_flagged"] = sorted(flagged)
        e["tracks_present"] = len(tracks_here)
        e["corroborated"] = corroborated
        e["class"] = "scena" if scene else "isolata"
        out.append(e)
    return out


def cadence(t: Track, times: np.ndarray, p: Params) -> dict | None:
    """Cadenza dal segnale di separazione delle caviglie: un ciclo per falcata (due passi)."""
    if len(t.frames) < 2:
        return None
    ts = times[t.frames]
    dur = float(ts[-1] - ts[0])
    if dur < 3.0:
        return None
    la, ra = KP["LAnkle"], KP["RAnkle"]
    ok = np.array([s[la] >= p.reliable_thr and s[ra] >= p.reliable_thr for s in t.scores])
    if ok.mean() < 0.7:
        return None
    k = np.stack(t.kpts)
    dx = np.where(ok, k[:, la, 0] - k[:, ra, 0], np.nan)
    dy = np.where(ok, k[:, la, 1] - k[:, ra, 1], np.nan)
    sig = dx if np.nanstd(dx) >= np.nanstd(dy) else dy
    fs = (len(ts) - 1) / dur
    grid = np.linspace(ts[0], ts[-1], len(ts))
    good = np.isfinite(sig)
    sig = np.interp(grid, ts[good], sig[good])
    sig = sig - np.polyval(np.polyfit(grid - grid[0], sig, 1), grid - grid[0])
    spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig)))) ** 2
    freqs = np.fft.rfftfreq(len(sig), 1 / fs)
    band = (freqs >= 0.4) & (freqs <= 1.6)
    if band.sum() < 3:
        return None
    i = int(np.argmax(np.where(band, spec, -1)))
    prom = float(spec[i] / (np.mean(spec[band]) + 1e-12))
    hs = [body_height(kk, ss, p.reliable_thr) for kk, ss in zip(t.kpts, t.scores)]
    H = float(np.median([h for h in hs if h > 0] or [1.0]))
    cen = np.nanmean(np.where(ok[:, None], k[:, [la, ra], 0], np.nan), axis=1)
    travel = float(np.nanmax(cen) - np.nanmin(cen)) / H if np.isfinite(cen).any() else 0.0
    if prom < 4:
        return {"stride_hz": None, "steps_per_min": None, "prominence": round(prom, 1), "duration_s": round(dur, 1),
                "travel_h": round(travel, 2), "note": "nessuna periodicità netta"}
    return {"stride_hz": round(float(freqs[i]), 3), "steps_per_min": round(float(freqs[i]) * 120, 1),
            "prominence": round(prom, 1), "duration_s": round(dur, 1), "travel_h": round(travel, 2),
            "resolution_steps_min": round(120 / dur, 1)}


def unusual_posture(t: Track, p: Params) -> list[dict]:
    """Frame con iperestensione marcata di ginocchio o gomito, con persona di profilo e keypoint affidabili."""
    out = []
    for f, k, s in zip(t.frames, t.kpts, t.scores):
        xy = np.where((s >= 0.6)[:, None], k, np.nan)
        sw = abs(xy[KP["LShoulder"], 0] - xy[KP["RShoulder"], 0])
        h = body_height(k, s, 0.6)
        if not (np.isfinite(sw) and h > 0 and sw < 0.15 * h):
            continue
        ang, side = compute_angles(xy)
        for name in ("right knee", "left knee", "right elbow", "left elbow"):
            a = ang.get(name)
            if a is not None and np.isfinite(a) and a < p.hyperext_deg:
                out.append({"frame": f, "track": t.tid, "angle": name, "deg": round(a, 1), "side": side})
    return out


# ------------------------------------------------------------------ disegno e esportazioni

L_COL, R_COL, C_COL = (255, 140, 30), (40, 80, 230), (60, 200, 60)


def draw_pose(img: np.ndarray, k: np.ndarray, s: np.ndarray, label: str = "", thr: float = 0.3) -> None:
    sc = max(1, int(round(max(img.shape[:2]) / 900)))
    for a, b in EDGES:
        ia, ib = KP[a], KP[b]
        if s[ia] >= thr and s[ib] >= thr:
            col = L_COL if a.startswith("L") or b.startswith("L") else R_COL if a.startswith("R") or \
                b.startswith("R") else C_COL
            cv2.line(img, tuple(int(v) for v in k[ia]), tuple(int(v) for v in k[ib]), col, 2 * sc, cv2.LINE_AA)
    for i in range(len(k)):
        if s[i] >= thr:
            cv2.circle(img, tuple(int(v) for v in k[i]), 2 * sc + 1, (255, 255, 255), -1, cv2.LINE_AA)
    if label:
        m = s >= thr
        if m.any():
            x, y = int(k[m, 0].min()), int(max(12, k[m, 1].min() - 8))
            cv2.putText(img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * sc, (0, 0, 0), 4 * sc, cv2.LINE_AA)
            cv2.putText(img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * sc, (255, 255, 255), 1 * sc, cv2.LINE_AA)


def _caption(img: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((34, img.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, text, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def motion_plot(path: Path, times: np.ndarray, speed: np.ndarray, p: Params, flagged: list[dict]) -> None:
    w, h, ml, mb = 1200, 360, 60, 40
    img = np.full((h, w, 3), 255, np.uint8)
    if len(times) < 2:
        cv2.imwrite(str(path), img)
        return
    t0, t1 = float(times[0]), float(times[-1]) or 1.0
    vmax = max(p.v_max * 1.5, float(np.nanmax(speed)) if np.isfinite(speed).any() else 1.0)
    X = lambda t: int(ml + (t - t0) / max(t1 - t0, 1e-6) * (w - ml - 10))  # noqa: E731
    Y = lambda v: int(h - mb - min(v, vmax) / vmax * (h - mb - 20))        # noqa: E731
    cv2.line(img, (ml, h - mb), (w - 10, h - mb), (0, 0, 0), 1)
    cv2.line(img, (ml, 10), (ml, h - mb), (0, 0, 0), 1)
    cv2.line(img, (ml, Y(p.v_max)), (w - 10, Y(p.v_max)), (60, 60, 220), 1, cv2.LINE_AA)
    cv2.putText(img, f"soglia {p.v_max:g} altezze/s", (ml + 6, Y(p.v_max) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (60, 60, 220), 1, cv2.LINE_AA)
    prev = None
    for t, v in zip(times, speed):
        if not np.isfinite(v):
            prev = None
            continue
        pt = (X(t), Y(v))
        if prev:
            cv2.line(img, prev, pt, (120, 80, 20), 1, cv2.LINE_AA)
        prev = pt
    for e in flagged:
        col = (40, 40, 210) if e["class"] == "scena" else (0, 170, 230)
        cv2.line(img, (X(e["time_s"]), 10), (X(e["time_s"]), h - mb), col, 1, cv2.LINE_AA)
    for i in range(5):
        v = vmax * i / 4
        cv2.line(img, (ml - 4, Y(v)), (ml, Y(v)), (0, 0, 0), 1)
        cv2.putText(img, f"{v:.0f}", (ml - 40, Y(v) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    for i in range(6):
        t = t0 + (t1 - t0) * i / 5
        cv2.putText(img, f"{t:.1f}s", (X(t) - 14, h - mb + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    cv2.putText(img, "velocita' massima tra frame (altezze del corpo al secondo) - rosso: discontinuita' di scena, "
                     "arancio: isolate", (ml, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def write_trc(path: Path, times: np.ndarray, xy: np.ndarray, fps: float) -> None:
    """TRC come Sports2D senza calibrazione: unità pixel, Y verso l'alto (-y immagine), Z=0."""
    n = len(times)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"PathFileType\t4\t(X/Y/Z)\t{path.name}\n")
        fh.write("DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\tOrigDataStartFrame\tOrigNumFrames\n")
        fh.write(f"{fps:.3f}\t{fps:.3f}\t{n}\t{len(HALPE26)}\tpx\t{fps:.3f}\t1\t{n}\n")
        fh.write("Frame#\tTime\t" + "\t\t\t".join(HALPE26) + "\n")
        fh.write("\t\t" + "\t".join(f"X{i + 1}\tY{i + 1}\tZ{i + 1}" for i in range(len(HALPE26))) + "\n")
        for i in range(n):
            vals = []
            for j in range(len(HALPE26)):
                x, y = xy[i, j]
                vals += ["" if not np.isfinite(x) else f"{x:.3f}", "" if not np.isfinite(y) else f"{-y:.3f}", "0"]
            fh.write(f"{i + 1}\t{times[i]:.4f}\t" + "\t".join(vals) + "\n")


def write_mot(path: Path, times: np.ndarray, angles: dict[str, np.ndarray]) -> None:
    names = list(angles)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(f"{path.stem}\nversion=1\nnRows={len(times)}\nnColumns={len(names) + 1}\ninDegrees=yes\nendheader\n")
        fh.write("time\t" + "\t".join(n.replace(" ", "_") for n in names) + "\n")
        for i, t in enumerate(times):
            fh.write(f"{t:.4f}\t" + "\t".join("nan" if not np.isfinite(angles[n][i]) else f"{angles[n][i]:.3f}"
                                               for n in names) + "\n")


def _file_entry(p: Path) -> dict:
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"path": str(p), "sha256": h, "size": p.stat().st_size}


def _py(o):
    if isinstance(o, dict):
        return {str(k): _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


# ------------------------------------------------------------------ lettura dei frame

def _read_image(path: Path) -> tuple[np.ndarray, bool]:
    from PIL import Image, ImageOps
    from . import heif_support
    heif_support.ensure_registered()
    with Image.open(path) as im:
        im.load()
        orientation = im.getexif().get(0x0112, 1)
        rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), orientation not in (None, 1)


def _small_gray(img: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)


# ------------------------------------------------------------------ analisi

ProgressFn = Callable[[float, str], None]


def analyze(path: str | Path, kind: str, out_dir: Path, settings=None, estimator=None,
            progress: ProgressFn | None = None, cancel: CancelToken | None = None) -> tuple[dict, list[Finding]]:
    """kind: 'image' oppure 'video'. estimator: oggetto con detect(img) e keypoints(img, boxes) (per i test)."""
    p = Params.from_settings(settings) if settings is not None else Params()
    progress = progress or (lambda _f, _m: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if estimator is None:
        from . import pose_model
        estimator = pose_model.load(getattr(settings, "pose_det_model", ""), getattr(settings, "pose_model", ""))
    engine = estimator.describe() if hasattr(estimator, "describe") else {"runtime": "stimatore esterno"}
    params = {k: v for k, v in p.__dict__.items()}
    if kind == "image":
        return _analyze_image(Path(path), out_dir, estimator, engine, params, p)
    return _analyze_video(Path(path), out_dir, estimator, engine, params, p, progress, cancel)


def _person_summary(t: Track, times: np.ndarray, fps: float, p: Params, n_frames: int) -> tuple[dict, dict]:
    k = np.stack(t.kpts)
    s = np.stack(t.scores)
    xy = np.where((s >= p.kpt_thr)[..., None], k, np.nan)
    ts = times[t.frames]
    # serie complete sulla finestra della traccia (NaN dove la persona manca) per interpolazione e filtro
    span = np.arange(t.frames[0], t.frames[-1] + 1)
    full = np.full((len(span), len(HALPE26), 2), np.nan)
    full[np.array(t.frames) - t.frames[0]] = xy
    sm = np.empty_like(full)
    for j in range(len(HALPE26)):
        for c in range(2):
            sm[:, j, c] = smooth_series(full[:, j, c], fps, p)
    angles = {n: np.full(len(span), np.nan) for n in ANGLE_NAMES}
    sides = []
    for i in range(len(span)):
        if np.isfinite(sm[i]).any():
            a, sd = compute_angles(sm[i])
            sides.append(sd)
            for n in ANGLE_NAMES:
                angles[n][i] = a[n]
    stats = {}
    for n, v in angles.items():
        f = v[np.isfinite(v)]
        if len(f):
            stats[n] = {"min": round(float(f.min()), 1), "max": round(float(f.max()), 1),
                        "mean": round(float(f.mean()), 1), "n": int(len(f))}
    hs = [body_height(kk, ss, p.reliable_thr) for kk, ss in zip(t.kpts, t.scores)]
    hs = [h for h in hs if h > 0]
    summ = {"track": t.tid, "frames": len(t.frames), "first_s": round(float(ts[0]), 3), "last_s": round(float(ts[-1]), 3),
            "coverage": round(len(t.frames) / max(n_frames, 1), 3), "height_px": round(float(np.median(hs)), 1) if hs else None,
            "mean_score": round(float(s.mean()), 3),
            "side": max(set(sides), key=sides.count) if sides else None, "angles": stats}
    return summ, {"span_times": times[span], "smoothed": sm, "angles": angles}


def _analyze_image(path: Path, out_dir: Path, est, engine: dict, params: dict, p: Params):
    img, rotated = _read_image(path)
    boxes = est.detect(img)
    kpts, scores = est.keypoints(img, boxes[:, :4] if len(boxes) else boxes)
    tr = Tracker(p)
    tr.update(0, kpts, scores)
    tracks = tr.all_tracks()
    times = np.array([0.0])
    persons, exports, unusual = [], {}, []
    over = img.copy()
    rows = []
    for t in tracks:
        k, s = t.last
        xy = np.where((s >= p.kpt_thr)[:, None], k, np.nan)
        ang, side = compute_angles(xy)
        hs = body_height(k, s, p.reliable_thr)
        persons.append({"track": t.tid, "frames": 1, "height_px": round(hs, 1) or None,
                        "mean_score": round(float(s.mean()), 3), "side": side,
                        "angles": {n: {"min": round(a, 1), "max": round(a, 1), "mean": round(a, 1), "n": 1}
                                   for n, a in ang.items() if np.isfinite(a)}})
        draw_pose(over, k, s, f"P{t.tid}", p.kpt_thr)
        unusual += unusual_posture(t, p)
        for j, nm in enumerate(HALPE26):
            rows.append([0, 0.0, t.tid, nm, f"{k[j, 0]:.2f}", f"{k[j, 1]:.2f}", f"{s[j]:.3f}"])
    ov = out_dir / "pose_overlay.png"
    cv2.imwrite(str(ov), over)
    csvp = out_dir / "keypoints.csv"
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "time_s", "person", "keypoint", "x_px", "y_px", "score"])
        w.writerows(rows)
    exports = {"pose_overlay.png": _file_entry(ov), "keypoints.csv": _file_entry(csvp)}
    res = {"kind": "image", "engine": engine, "params": params, "exif_orientation_applied": rotated,
           "frames": {"analyzed": 1}, "persons": persons, "transitions": [], "unusual_posture": unusual,
           "exports": exports, "artifacts": {"pose": str(ov)}}
    fs = _findings(res, times, p)
    return _py(res), fs


def _analyze_video(path: Path, out_dir: Path, est, engine: dict, params: dict, p: Params,
                   progress: ProgressFn, cancel: CancelToken | None):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("OpenCV non riesce ad aprire il video (codec non supportato dal backend FFmpeg di OpenCV)")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    orient = cap.get(getattr(cv2, "CAP_PROP_ORIENTATION_META", 48))
    tr = Tracker(p)
    times, vis, raw_rows = [], [], []
    boxes = np.zeros((0, 5), np.float32)
    prev_small, best = None, (-1.0, None, None, -1)
    writer = None
    src_idx, n, last_det = -1, 0, -10 ** 9
    src_of: list[int] = []                   # frame analizzato -> indice del frame nel video
    try:
        while n < p.max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            src_idx += 1
            if src_idx % p.frame_step:
                continue
            if cancel:
                cancel.check()
            ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            t = ms / 1000.0 if ms and ms > 0 or src_idx == 0 else (src_idx / fps if fps else float(n))
            if times and t <= times[-1]:
                t = src_idx / fps if fps else times[-1] + 1e-3
            small = _small_gray(frame)
            vis.append(float(np.mean(np.abs(small - prev_small))) if prev_small is not None else float("nan"))
            prev_small = small
            need_det = (n - last_det) >= p.det_every or len(boxes) == 0
            if not need_det:
                kpts, scores = est.keypoints(frame, boxes[:, :4])
                if len(scores) == 0 or float(scores.mean()) < p.redetect_below:
                    need_det = True
            if need_det:
                boxes = est.detect(frame)
                last_det = n
                kpts, scores = est.keypoints(frame, boxes[:, :4] if len(boxes) else boxes)
            matched = tr.update(n, kpts, scores)
            # riquadri del frame successivo dai keypoint attuali (come Sports2D tra un rilevamento e l'altro)
            nb = []
            for _tid, j in matched:
                m = scores[j] >= p.kpt_thr
                if m.sum() >= 4:
                    x1, y1 = kpts[j][m].min(0)
                    x2, y2 = kpts[j][m].max(0)
                    nb.append([x1, y1, x2, y2, float(scores[j][m].mean())])
            if nb:
                boxes = np.array(nb, np.float32)
            times.append(t)
            for tid, j in matched:
                for q, nm in enumerate(HALPE26):
                    raw_rows.append([src_idx, f"{t:.4f}", tid, nm, f"{kpts[j][q, 0]:.2f}", f"{kpts[j][q, 1]:.2f}",
                                     f"{scores[j][q]:.3f}"])
            sc = float(scores.mean()) * len(scores) if len(scores) else 0.0
            if sc > best[0]:
                best = (sc, frame.copy(), [(tid, kpts[j].copy(), scores[j].copy()) for tid, j in matched], n)
            src_of.append(src_idx)
            if p.save_video:
                if writer is None:
                    writer = cv2.VideoWriter(str(out_dir / "pose_overlay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                             fps / p.frame_step if fps else 25, (frame.shape[1], frame.shape[0]))
                vf = frame.copy()
                for tid, j in matched:
                    draw_pose(vf, kpts[j], scores[j], f"P{tid}", p.kpt_thr)
                writer.write(vf)
            n += 1
            if total:
                progress(min(0.95, src_idx / max(1, min(total, p.max_frames * p.frame_step))),
                         f"Stima della posa: frame {src_idx + 1} di {total}")
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    if n == 0:
        raise RuntimeError("nessun frame decodificabile")
    times_a = np.array(times, float)
    vis_a = np.array(vis, float)
    eff_fps = (n - 1) / (times_a[-1] - times_a[0]) if n > 1 and times_a[-1] > times_a[0] else (fps / p.frame_step or 0)
    tracks = [t for t in tr.all_tracks() if len(t.frames) >= 1]
    progress(0.96, "Cinematica: angoli, filtri, discontinuità")
    trans = transitions(tracks, times_a, vis_a, p)
    for e in trans:
        e["source_frame"] = src_of[e["frame"]]
    persons, unusual, exports = [], [], {}
    speed = np.full(n, np.nan)
    for t in tracks:
        hs = [body_height(k, s, p.reliable_thr) for k, s in zip(t.kpts, t.scores)]
        H = float(np.median([h for h in hs if h > 0] or [0]))
        for a in range(1, len(t.frames)):
            f0, f1 = t.frames[a - 1], t.frames[a]
            m = (t.scores[a - 1] >= p.reliable_thr) & (t.scores[a] >= p.reliable_thr)
            if f1 - f0 == 1 and m.sum() >= 6 and H > 0 and times_a[f1] > times_a[f0]:
                v = float(np.median(np.linalg.norm(t.kpts[a][m] - t.kpts[a - 1][m], axis=1))) / H / \
                    (times_a[f1] - times_a[f0])
                speed[f1] = v if not np.isfinite(speed[f1]) else max(speed[f1], v)
        summ, series = _person_summary(t, times_a, eff_fps, p, n)
        summ["cadence"] = cadence(t, times_a, p)
        persons.append(summ)
        bad = unusual_posture(t, p)
        runs = _runs([b["frame"] for b in bad])
        unusual += [b for b in bad if any(r[0] <= b["frame"] <= r[1] and r[1] - r[0] + 1 >= 5 for r in runs)]
        if len(t.frames) >= 2:
            trc = out_dir / f"person_{t.tid:02d}_px.trc"
            mot = out_dir / f"person_{t.tid:02d}_angles.mot"
            write_trc(trc, series["span_times"], series["smoothed"], eff_fps)
            write_mot(mot, series["span_times"], series["angles"])
            exports[trc.name] = _file_entry(trc)
            exports[mot.name] = _file_entry(mot)
    csvp = out_dir / "keypoints_raw.csv"
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source_frame", "time_s", "person", "keypoint", "x_px", "y_px", "score"])
        w.writerows(raw_rows)
    exports[csvp.name] = _file_entry(csvp)
    arts = {}
    if best[1] is not None:
        img = best[1]
        for tid, k, s in best[2]:
            draw_pose(img, k, s, f"P{tid}", p.kpt_thr)
        ov = out_dir / "pose_overlay.png"
        cv2.imwrite(str(ov), _caption(img, f"frame analizzato {best[3]} - t = {times_a[best[3]]:.3f} s"))
        arts["pose"] = str(ov)
        exports[ov.name] = _file_entry(ov)
    mp = out_dir / "pose_motion.png"
    motion_plot(mp, times_a, speed, p, trans)
    arts["pose_motion"] = str(mp)
    exports[mp.name] = _file_entry(mp)
    progress(0.98, "Fotogrammi dei punti di discontinuità")
    jumps = _jump_montage(path, out_dir, trans, src_of, tracks, p)
    if jumps:
        arts["pose_jumps"] = str(jumps)
        exports[jumps.name] = _file_entry(jumps)
    if (out_dir / "pose_overlay.mp4").is_file():
        exports["pose_overlay.mp4"] = _file_entry(out_dir / "pose_overlay.mp4")
    res = {"kind": "video", "engine": engine, "params": params,
           "frames": {"total_declared": total, "analyzed": n, "step": p.frame_step, "fps_declared": round(fps, 3),
                      "fps_effective": round(eff_fps, 3), "duration_analyzed_s": round(float(times_a[-1] - times_a[0]), 3),
                      "limited": bool(total and n * p.frame_step < total and n >= p.max_frames),
                      "orientation_meta": orient},
           "persons": persons, "transitions": trans, "unusual_posture": unusual, "exports": exports,
           "artifacts": arts}
    fs = _findings(res, times_a, p)
    return _py(res), fs


def _jump_montage(path: Path, out_dir: Path, trans: list[dict], src_of: list[int], tracks: list[Track],
                 p: Params, limit: int = 4) -> Path | None:
    """Coppie di fotogrammi (prima / dopo) dei punti più rilevanti, con lo scheletro delle persone coinvolte.
    Il video viene riletto solo in decodifica, dopo l'analisi, quindi non serve tenere frame in memoria."""
    sel = sorted(trans, key=lambda e: (e["class"] != "scena",
                                       -max([j["jump_h"] for j in e["jumps"]] or [0])))[:limit]
    if not sel:
        return None
    want = {}
    for e in sel:
        for n in (e["frame"] - 1, e["frame"]):
            want[src_of[n]] = n
    by_frame: dict[int, list[tuple[int, np.ndarray, np.ndarray]]] = {}
    for t in tracks:
        for f, k, sc in zip(t.frames, t.kpts, t.scores):
            if f in want.values():
                by_frame.setdefault(f, []).append((t.tid, k, sc))
    got: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(path))
    try:
        i, last = -1, max(want)
        while i < last:
            ok = cap.grab()
            if not ok:
                break
            i += 1
            if i in want:
                ok, fr = cap.retrieve()
                if ok:
                    n = want[i]
                    for tid, k, sc in by_frame.get(n, []):
                        draw_pose(fr, k, sc, f"P{tid}", p.kpt_thr)
                    sc_ = min(1.0, 640 / fr.shape[1])
                    got[n] = cv2.resize(fr, (int(fr.shape[1] * sc_), int(fr.shape[0] * sc_)))
    finally:
        cap.release()
    tiles = []
    for e in sel:
        a, b = got.get(e["frame"] - 1), got.get(e["frame"])
        if a is None or b is None:
            continue
        h = max(a.shape[0], b.shape[0])
        pad = lambda im: np.vstack([im, np.zeros((h - im.shape[0], im.shape[1], 3), np.uint8)])  # noqa: E731
        pair = np.hstack([pad(a), np.full((h, 6, 3), 255, np.uint8), pad(b)])
        tiles.append(_caption(pair, f"frame {src_of[e['frame'] - 1]} -> {src_of[e['frame']]}  t={e['time_s']:.3f}s  "
                                    f"discontinuita' {e['class']}"))
    if not tiles:
        return None
    w = max(t.shape[1] for t in tiles)
    tiles = [np.hstack([t, np.zeros((t.shape[0], w - t.shape[1], 3), np.uint8)]) if t.shape[1] < w else t
             for t in tiles]
    out = out_dir / "pose_jumps.png"
    cv2.imwrite(str(out), np.vstack(tiles))
    return out


def _runs(frames: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for f in sorted(set(frames)):
        if out and f == out[-1][1] + 1:
            out[-1] = (out[-1][0], f)
        else:
            out.append((f, f))
    return out


# ------------------------------------------------------------------ risultati

LIMITS = ("Coordinate in pixel senza calibrazione della camera: nessuna misura in metri né di statura. Le stime "
          "dei keypoint possono essere errate con occlusioni, abiti larghi, risoluzione bassa, motion blur o "
          "persone vicine tra loro.")


def _findings(res: dict, times: np.ndarray, p: Params) -> list[Finding]:
    f: list[Finding] = []
    persons = res["persons"]
    eng = res["engine"]
    model_ev = "; ".join(f"{m['role']}: {m['file']} SHA-256 {m['sha256']}" for m in
                         (eng.get("detector"), eng.get("pose")) if m)
    if res["kind"] == "image":
        f.append(Finding(Category.HUMAN_POSE, Level.INFO,
                         f"Persone rilevate: {len(persons)}" if persons else "Nessuna persona rilevata",
                         ("Posa stimata per ciascuna persona (26 punti) con angoli articolari secondo le definizioni di "
                          "Sports2D." if persons else "Il rilevatore non ha trovato figure umane nell'immagine.")
                         + (" Orientamento EXIF applicato prima dell'analisi." if res.get("exif_orientation_applied")
                            else ""), METHOD, MODULE, evidence=model_ev, confidence="n/a", limitations=LIMITS,
                         data={"persons": [{k: v for k, v in x.items() if k != "angles"} for x in persons]}))
    else:
        fr = res["frames"]
        f.append(Finding(Category.HUMAN_POSE, Level.INFO,
                         f"Persone tracciate: {len(persons)} in {fr['analyzed']} frame",
                         f"Analizzati {fr['analyzed']} frame (passo {fr['step']}, {fr['fps_effective']} fps effettivi, "
                         f"{fr['duration_analyzed_s']} s). Esportati keypoint grezzi (CSV), traiettorie filtrate "
                         "(TRC) e angoli (MOT) compatibili con Sports2D/OpenSim.", METHOD, MODULE,
                         evidence=model_ev, confidence="n/a", limitations=LIMITS,
                         data={"persons": [{k: v for k, v in x.items() if k != "angles"} for x in persons]}))
        if fr["limited"]:
            f.append(Finding(Category.HUMAN_POSE, Level.UNDETERMINED,
                             f"Analisi della posa limitata ai primi {fr['analyzed']} frame",
                             f"Il video dichiara {fr['total_declared']} frame; il limite impostato è "
                             f"{p.max_frames} frame analizzati. La parte restante non è stata esaminata.", METHOD,
                             MODULE, limitations="Aumentare il limite nelle impostazioni o analizzare il video a "
                                                 "segmenti per coprirlo tutto."))
        scene = [e for e in res["transitions"] if e["class"] == "scena"]
        single = [e for e in res["transitions"] if e["class"] == "isolata"]
        if scene:
            ev = "\n".join(_ev_line(e) for e in scene[:20])
            corro = sum(1 for e in scene if e["corroborated"])
            f.append(Finding(Category.HUMAN_POSE, Level.SUSPICIOUS,
                             f"Discontinuità del movimento in {len(scene)} "
                             f"{'punto' if len(scene) == 1 else 'punti'} del video",
                             "In questi punti le persone in scena cambiano posizione, scala o identità da un frame al "
                             "successivo in modo incompatibile con un movimento reale e continuo"
                             + (f"; in {corro} casi anche l'intervallo di tempo tra i frame o l'immagine nel suo "
                                "insieme cambiano bruscamente" if corro else "") + ".",
                             "Salti cinematici sui keypoint grezzi (velocità > "
                             f"{p.v_max:g} altezze/s), salti di scala, sostituzione delle persone; confronto con "
                             "timestamp e differenza globale del frame", MODULE, evidence=ev,
                             confidence="media" if corro else "bassa", significant=bool(corro),
                             limitations="Compatibile con tagli, frame mancanti o inseriti, giunzioni di riprese "
                                         "diverse, ma anche con cambi di inquadratura, zoom rapidi o persone che "
                                         "escono e rientrano. Verificare i frame indicati (vedi 'Salti tra frame').",
                             data={"transitions": scene[:200]}))
        if single:
            f.append(Finding(Category.HUMAN_POSE, Level.PROBABILISTIC,
                             f"Salti isolati di singole persone: {len(single)}",
                             "Una sola persona cambia posizione in modo brusco mentre il resto della scena è continuo: "
                             "di solito è un errore di stima o di tracciamento (occlusione, scambio di identità).",
                             "Salti cinematici sui keypoint grezzi", MODULE,
                             evidence="\n".join(_ev_line(e) for e in single[:20]), confidence="bassa",
                             limitations="Da solo non indica manipolazione.", data={"transitions": single[:200]}))
        for x in persons:
            c = x.get("cadence")
            if c and c.get("steps_per_min"):
                f.append(Finding(Category.HUMAN_POSE, Level.INFO,
                                 f"Persona P{x['track']}: cadenza stimata {c['steps_per_min']:.0f} passi/min",
                                 f"Periodicità della separazione delle caviglie: {c['stride_hz']} Hz per falcata su "
                                 f"{c['duration_s']} s (risoluzione ±{c['resolution_steps_min']} passi/min, "
                                 f"spostamento {c['travel_h']} altezze).", "Analisi spettrale (FFT con finestra di Hann)",
                                 MODULE, confidence="media" if c["prominence"] >= 8 else "bassa",
                                 limitations="Dato descrittivo per il confronto dell'andatura, non identificativo. "
                                             "Dipende dall'angolo di ripresa, dal frame rate effettivo e dalla "
                                             "regolarità del passo; il confronto tra soggetti richiede un esperto di "
                                             "analisi forense dell'andatura.", data={"cadence": c, "track": x["track"]}))
    if res["unusual_posture"]:
        u = res["unusual_posture"]
        f.append(Finding(Category.HUMAN_POSE, Level.PROBABILISTIC, "Postura anatomicamente insolita",
                         f"{len(u)} misure con iperestensione oltre {abs(p.hyperext_deg):g}° di ginocchio o gomito, "
                         "con persona di profilo e keypoint affidabili.", "Angoli articolari Sports2D", MODULE,
                         evidence="\n".join(f"frame {x['frame']} P{x['track']} {ANGLE_LABELS_IT[x['angle']]} "
                                            f"{x['deg']}°" for x in u[:20]), confidence="bassa",
                         limitations="Può derivare da un errore del modello o da una vista non di profilo. Nelle "
                                     "immagini generate o composte le pose impossibili sono più frequenti, ma questo "
                                     "risultato non lo dimostra.", data={"items": u[:200]}))
    return f


def _ev_line(e: dict) -> str:
    parts = [f"frame {e.get('source_frame', e['frame'])} (t={e['time_s']:.3f} s)"]
    if e["jumps"]:
        parts.append("salti " + ", ".join(f"P{j['track']} {j['jump_h']:.2f} alt." for j in e["jumps"][:4]))
    if e["scale"]:
        parts.append("scala " + ", ".join(f"P{s['track']} ×{s['ratio']}" for s in e["scale"][:4]))
    if e["replaced"]:
        parts.append("persone sostituite")
    if e.get("dt_ratio") and e["dt_ratio"] > 1.8:
        parts.append(f"intervallo ×{e['dt_ratio']}")
    if e.get("visual_ratio") and e["visual_ratio"] > 4:
        parts.append(f"cambio immagine ×{e['visual_ratio']}")
    return " · ".join(parts)
