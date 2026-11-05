"""PRNU (Photo Response Non-Uniformity): impronta del sensore e confronto con un'immagine.

Implementazione indipendente basata su Lukáš, Fridrich & Goljan (2006) e Goljan, Fridrich & Filler (2009):
- residuo di rumore W = I - F(I), con F denoiser di Wiener adattivo (stima della varianza locale minima su
  finestre 3, 5, 7, 9, come in Mihcak et al.) applicato nel dominio spaziale;
- rimozione delle componenti periodiche (media nulla per righe e colonne);
- impronta K = Σ W·I / Σ I² su immagini di riferimento dello stesso dispositivo;
- confronto con PCE (Peak to Correlation Energy) della correlazione incrociata tra W e I·K.
L'esito è un indice statistico di compatibilità, non un'attribuzione certa.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level

MODULE = "prnu"
CROP = 1024          # le impronte usano il ritaglio centrale per limitare memoria e disco
PCE_THRESHOLD = 60.0  # soglia comunemente usata in letteratura


def load_gray(path, crop: int = CROP) -> np.ndarray:
    with Image.open(path) as im:
        im.load()
        g = np.asarray(im.convert("L"), dtype=np.float32)
    h, w = g.shape
    if h > w:      # orientamento normalizzato: lato lungo in orizzontale (senza applicare l'EXIF)
        g = np.ascontiguousarray(np.rot90(g))
        h, w = w, h
    c = min(crop, h, w)
    y0, x0 = (h - c) // 2, (w - c) // 2
    return g[y0:y0 + c, x0:x0 + c]


def residual(g: np.ndarray, sigma0: float = 3.0) -> np.ndarray:
    est = None
    for k in (3, 5, 7, 9):
        mean = cv2.blur(g, (k, k))
        var = np.maximum(cv2.blur(g * g, (k, k)) - mean * mean - sigma0 ** 2, 0)
        est = var if est is None else np.minimum(est, var)
    mean = cv2.blur(g, (3, 3))
    den = mean + est / (est + sigma0 ** 2) * (g - mean)
    w = g - den
    w -= w.mean(axis=1, keepdims=True)
    w -= w.mean(axis=0, keepdims=True)
    w[(g > 250) | (g < 3)] = 0      # pixel saturati: nessuna informazione sul PRNU
    return w


def fingerprint(paths: list) -> np.ndarray:
    num = den = None
    shape = None
    for p in paths:
        g = load_gray(p)
        if shape is None:
            shape = g.shape
        elif g.shape != shape:
            raise ValueError(f"{Path(p).name}: risoluzione diversa dalle altre immagini di riferimento")
        w = residual(g)
        num = w * g if num is None else num + w * g
        den = g * g if den is None else den + g * g
    k = num / np.maximum(den, 1)
    k -= k.mean(axis=1, keepdims=True)
    k -= k.mean(axis=0, keepdims=True)
    return k.astype(np.float32)


def pce(k: np.ndarray, g: np.ndarray, exclude: int = 5) -> tuple[float, tuple[int, int]]:
    x = (g * k).astype(np.float64)
    y = residual(g).astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    xc = np.real(np.fft.ifft2(np.fft.fft2(y) * np.conj(np.fft.fft2(x))))
    peak = xc[0, 0]                      # nessuno spostamento atteso tra impronta e immagine
    mask = np.ones_like(xc, dtype=bool)
    for dy in range(-exclude, exclude + 1):
        for dx in range(-exclude, exclude + 1):
            mask[dy % xc.shape[0], dx % xc.shape[1]] = False
    energy = float(np.mean(xc[mask] ** 2)) or 1e-12
    iy, ix = np.unravel_index(int(np.argmax(xc)), xc.shape)
    return float(np.sign(peak) * peak ** 2 / energy), (int(iy), int(ix))


def local_correlation(k: np.ndarray, g: np.ndarray, bs: int = 64) -> np.ndarray:
    x, y = g * k, residual(g)
    h, w = g.shape
    out = np.full((h // bs, w // bs), np.nan, np.float32)
    for i in range(h // bs):
        for j in range(w // bs):
            a = x[i * bs:(i + 1) * bs, j * bs:(j + 1) * bs].ravel()
            b = y[i * bs:(i + 1) * bs, j * bs:(j + 1) * bs].ravel()
            a, b = a - a.mean(), b - b.mean()
            d = np.sqrt((a * a).sum() * (b * b).sum())
            out[i, j] = (a * b).sum() / d if d else np.nan
    return out


# ---------------------------------------------------------------- archivio delle impronte
class PrnuStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"

    def list(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _save(self, items: list[dict]) -> None:
        self.index_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, label: str, model: str, paths: list, operator: str) -> dict:
        if len(paths) < 5:
            raise ValueError("Servono almeno 5 immagini di riferimento (consigliate 20 o più, piatte e luminose)")
        k = fingerprint(paths)
        fid = uuid.uuid4().hex[:10]
        np.save(self.root / f"{fid}.npy", k)
        item = {"id": fid, "label": label, "model": model, "operator": operator, "shape": list(k.shape),
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "references": [{"name": Path(p).name, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                               for p in paths],
                "fingerprint_sha256": hashlib.sha256((self.root / f"{fid}.npy").read_bytes()).hexdigest()}
        items = self.list()
        items.append(item)
        self._save(items)
        return item

    def remove(self, fid: str) -> None:
        items = [i for i in self.list() if i["id"] != fid]
        (self.root / f"{fid}.npy").unlink(missing_ok=True)
        self._save(items)

    def load(self, fid: str) -> np.ndarray:
        item = next(i for i in self.list() if i["id"] == fid)
        p = self.root / f"{fid}.npy"
        if hashlib.sha256(p.read_bytes()).hexdigest() != item["fingerprint_sha256"]:
            raise ValueError(f"L'impronta {item['label']} è stata modificata dopo la creazione")
        return np.load(p)


def match(path, store: PrnuStore, out_png=None) -> tuple[list[dict], list[Finding]]:
    meth = "PRNU: residuo di Wiener adattivo, PCE (Lukáš, Fridrich & Goljan)"
    items = store.list()
    if not items:
        return [], []
    g = load_gray(path)
    results = []
    for it in items:
        if tuple(it["shape"]) != g.shape:
            results.append({"id": it["id"], "label": it["label"], "pce": None,
                            "note": f"dimensioni incompatibili ({g.shape} contro {tuple(it['shape'])})"})
            continue
        try:
            k = store.load(it["id"])
        except ValueError as e:
            results.append({"id": it["id"], "label": it["label"], "pce": None, "note": str(e)})
            continue
        v, peak = pce(k, g)
        results.append({"id": it["id"], "label": it["label"], "model": it["model"], "pce": round(v, 1),
                        "peak_at": peak, "references": len(it["references"])})
    findings = []
    lim = ("Il PCE indica quanto il rumore dell'immagine è compatibile con l'impronta del sensore. Ridimensionamenti, "
           "ritagli non centrati, stabilizzazione digitale, forte compressione e rotazioni lo riducono fino a "
           "renderlo non significativo. Impronte costruite con poche immagini o con immagini molto texturizzate sono "
           "meno affidabili. Il valore non è una probabilità e non costituisce da solo un'attribuzione.")
    valid = [r for r in results if r["pce"] is not None]
    hits = [r for r in valid if r["pce"] >= PCE_THRESHOLD]
    for r in hits:
        findings.append(Finding(Category.SENSOR, Level.PROBABILISTIC, f"Compatibile con il sensore {r['label']}",
                                f"PCE {r['pce']} (soglia {PCE_THRESHOLD:.0f}) con l'impronta '{r['label']}' "
                                f"({r['model']}, {r['references']} immagini di riferimento).", meth, MODULE,
                                confidence="alta" if r["pce"] > 10 * PCE_THRESHOLD else "media",
                                limitations=lim, data=r))
    if hits and out_png:
        best = max(hits, key=lambda r: r["pce"])
        lc = local_correlation(store.load(best["id"]), g)
        v = np.clip(np.nan_to_num(lc) / max(np.nanpercentile(lc, 95), 1e-6), 0, 1)
        v = cv2.resize((v * 255).astype(np.uint8), (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
        Image.fromarray(cv2.applyColorMap(v, cv2.COLORMAP_VIRIDIS)[:, :, ::-1]).save(out_png)
        weak = int((np.nan_to_num(lc) < 0.25 * np.nanmedian(lc)).sum())
        findings.append(Finding(Category.SENSOR, Level.PROBABILISTIC, "Mappa di correlazione locale PRNU",
                                f"Correlazione per blocchi 64x64 con l'impronta '{best['label']}' (ritaglio centrale "
                                f"{g.shape[1]}x{g.shape[0]}). Blocchi con correlazione molto bassa: {weak}.", meth,
                                MODULE, confidence="richiede interpretazione dell'operatore",
                                limitations="Aree scure, sature o molto texturizzate hanno correlazione bassa anche "
                                            "senza alterazioni: una regione è sospetta solo se ha contenuto simile "
                                            "alle aree circostanti ben correlate.", data={"weak_blocks": weak}))
    if valid and not hits:
        best = max(valid, key=lambda r: r["pce"])
        findings.append(Finding(Category.SENSOR, Level.INFO, "Nessuna impronta compatibile",
                                f"PCE massimo {best['pce']} ('{best['label']}'), sotto la soglia {PCE_THRESHOLD:.0f}, su "
                                f"{len(valid)} impronte confrontabili.", meth, MODULE, limitations=lim,
                                data={"results": results}))
    if not valid:
        findings.append(Finding(Category.SENSOR, Level.UNDETERMINED, "Confronto PRNU non eseguibile",
                                "Nessuna impronta ha dimensioni compatibili con l'immagine.", meth, MODULE,
                                data={"results": results}))
    return results, findings
