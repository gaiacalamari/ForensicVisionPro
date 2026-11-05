"""Analisi della storia di compressione JPEG.

Implementazione indipendente basata sulla letteratura citata per ciascun metodo.

- ELA multi-qualità: ELA a 8 livelli, mappa composita e coerenza delle regioni tra i livelli.
- JPEG ghost (Farid, 2009): regioni ricompresse in precedenza a qualità diversa mostrano un
  minimo locale della differenza quando si risalva a quella qualità.
- Doppia quantizzazione (Popescu & Farid, 2004; Lin et al., 2009): gli istogrammi dei coefficienti
  DCT di un'immagine compressa due volte con tabelle diverse presentano periodicità.
- Allineamento della griglia 8x8: una griglia di blocchi non allineata all'origine indica un ritaglio
  dopo una compressione precedente; artefatti a blocchi in un file non JPEG indicano una storia JPEG.
"""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level

MODULE = "jpeg_forensics"
ELA_QUALITIES = (60, 65, 70, 75, 80, 85, 90, 95)


def _rgb(path) -> np.ndarray:
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"))


def _resave(arr: np.ndarray, q: int) -> np.ndarray:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=q)
    buf.seek(0)
    return np.asarray(Image.open(buf).convert("RGB"))


def _blocks(a: np.ndarray, bs: int) -> np.ndarray:
    h, w = a.shape[:2]
    hb, wb = h // bs, w // bs
    return a[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).mean(axis=(1, 3))


def _heat(a: np.ndarray, shape, out) -> None:
    v = np.clip(a / (np.percentile(a, 99.5) or 1) * 255, 0, 255).astype(np.uint8)
    v = cv2.resize(v, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    Image.fromarray(cv2.applyColorMap(v, cv2.COLORMAP_INFERNO)[:, :, ::-1]).save(out)


# ---------------------------------------------------------------- ELA multi-qualità
def multi_ela(path, out_png=None, qualities=ELA_QUALITIES) -> Finding:
    rgb = _rgb(path)
    src = rgb.astype(np.int16)
    maps, zs = [], []
    for q in qualities:
        d = np.abs(src - _resave(rgb, q).astype(np.int16)).max(axis=2).astype(np.float32)
        d /= (np.percentile(d, 99.5) or 1.0)
        maps.append(d)
        b = _blocks(d, 32)
        mad = np.median(np.abs(b - np.median(b))) or 1e-6
        zs.append((b - np.median(b)) / (1.4826 * mad))
    comp = np.mean(maps, axis=0)
    if out_png:
        _heat(comp, rgb.shape, out_png)
    z = np.stack(zs)
    persistent = (z > 3).sum(axis=0) >= len(qualities) - 2
    frac = float(persistent.mean()) if persistent.size else 0.0
    data = {"qualities": list(qualities), "persistent_blocks": int(persistent.sum()),
            "persistent_fraction": round(frac, 4)}
    if persistent.any():
        ys, xs = np.where(persistent)
        data["bbox"] = [int(xs.min() * 32), int(ys.min() * 32), int((xs.max() + 1) * 32), int((ys.max() + 1) * 32)]
    return Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "ELA multi-qualità",
                   f"ELA a {len(qualities)} livelli ({qualities[0]}–{qualities[-1]}). Blocchi 32x32 anomali a quasi "
                   f"tutti i livelli: {int(persistent.sum())} ({frac:.1%}).", "Error Level Analysis multi-qualità",
                   MODULE, confidence="richiede interpretazione dell'operatore",
                   limitations="Bordi netti e texture fini risultano anomali a tutti i livelli anche in immagini "
                               "integre. La persistenza riduce le anomalie casuali ma non distingue il contenuto "
                               "dall'alterazione.", data=data)


# ---------------------------------------------------------------- JPEG ghost
def jpeg_ghost(path, out_png=None, last_quality: int | None = None, qualities=range(40, 100, 5),
               bs: int = 16) -> Finding:
    rgb = _rgb(path)
    src = rgb.astype(np.float32)
    qs = [q for q in qualities if last_quality is None or q <= last_quality - 10]
    meth = "JPEG ghost (Farid, 2009)"
    if len(qs) < 3:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "JPEG ghost non applicabile",
                       f"Qualità corrente stimata {last_quality}: troppo bassa per cercare compressioni precedenti "
                       "a qualità inferiore.", meth, MODULE)
    D = np.stack([_blocks(((src - _resave(rgb, q)) ** 2).mean(axis=2), bs) for q in qs])
    mn, mx = D.min(axis=0), D.max(axis=0)
    N = (D - mn) / np.maximum(mx - mn, 1e-6)
    textured = (mx - mn) > 2.0                       # nei blocchi piatti la differenza non è informativa
    best = None
    for i, q in enumerate(qs):
        low = (N[i] < 0.2) & textured
        frac = low.sum() / max(textured.sum(), 1)
        med_rest = np.median(N[i][textured & ~low]) if (textured & ~low).any() else 0
        if frac > 0.4 or med_rest <= 0.45 or low.sum() < 4:
            continue
        n, lab, st, _ = cv2.connectedComponentsWithStats(low.astype(np.uint8), connectivity=8)
        if n <= 1:
            continue
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        area = int(st[k, cv2.CC_STAT_AREA])
        compact = area / low.sum()          # la regione deve essere compatta, non un insieme di blocchi sparsi
        if area >= max(40, 0.005 * textured.sum()) and compact >= 0.6:
            score = area * med_rest
            if best is None or score > best[0]:
                best = (score, q, i, area, st[k], float(frac))
    if out_png:
        idx = best[2] if best else len(qs) // 2
        _heat(1 - N[idx], rgb.shape, out_png)
    if not best:
        return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "JPEG ghost: nessuna regione distinta",
                       f"Nessuna regione compatta con un minimo di differenza a qualità {qs[0]}–{qs[-1]}.", meth, MODULE,
                       limitations="Non rileva regioni ricompresse a qualità uguale o superiore a quella finale, "
                                   "né regioni troppo piccole o piatte.", data={"qualities": qs})
    _, q, _, area, st, frac = best
    x, y, w, h = (int(v) * bs for v in st[:4])
    return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, f"JPEG ghost a qualità {q}",
                   f"Una regione di {area} blocchi {bs}x{bs} (x {x}–{x + w}, y {y}–{y + h}) mostra un minimo di "
                   f"differenza alla qualità {q}, diversa dal resto dell'immagine: compatibile con un inserto "
                   "compresso in precedenza a quella qualità.", meth, MODULE, confidence="media", significant=True,
                   limitations="Regioni sature, molto scure o con texture uniforme possono produrre falsi ghost. "
                               "Verificare visivamente la mappa alla qualità indicata.",
                   data={"quality": q, "bbox": [x, y, x + w, y + h], "fraction": round(frac, 4), "qualities": qs})


# ---------------------------------------------------------------- doppia quantizzazione
ZIGZAG_IDX = [(0, 1), (1, 0), (2, 0), (1, 1), (0, 2), (0, 3), (1, 2), (2, 1), (3, 0)]


def _block_dct(y: np.ndarray, oy: int = 0, ox: int = 0) -> np.ndarray:
    y = y[oy:, ox:]
    h, w = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    b = y[:h, :w].reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 8, 8).astype(np.float32) - 128
    return np.stack([cv2.dct(blk) for blk in b])


def _periodicity(hist: np.ndarray) -> float:
    """Rapporto tra il picco spettrale non continuo e la media: alto se l'istogramma è periodico."""
    h = hist.astype(np.float64)
    smooth = np.convolve(h, np.ones(5) / 5, mode="same")
    r = h / np.maximum(smooth, 1) - 1
    spec = np.abs(np.fft.rfft(r))[2:]
    return float(spec.max() / (np.mean(spec) or 1e-9)) if spec.size else 0.0


def double_jpeg(path, qtable_luma: list[int] | None) -> Finding:
    meth = "Periodicità degli istogrammi DCT (doppia quantizzazione)"
    if not qtable_luma:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Doppia compressione non valutabile",
                       "Tabella di quantizzazione non disponibile (file non JPEG).", meth, MODULE)
    y = np.asarray(Image.open(path).convert("YCbCr"))[:, :, 0].astype(np.float32)
    coef = _block_dct(y)
    q = np.array(qtable_luma, dtype=np.float32).reshape(8, 8)
    modes = []
    for (i, j) in ZIGZAG_IDX:
        if q[i, j] < 2:
            continue
        v = np.rint(coef[:, i, j] / q[i, j]).astype(np.int64)
        v = v[(v != 0) & (np.abs(v) <= 40)]
        if v.size < 400:
            continue
        hist = np.bincount(np.abs(v), minlength=41)[1:41]
        modes.append({"mode": f"({i},{j})", "q2": int(q[i, j]), "n": int(v.size), "score": round(_periodicity(hist), 2)})
    if len(modes) < 3:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Doppia compressione non valutabile",
                       "Coefficienti insufficienti: qualità troppo alta (passi di quantizzazione 1) o immagine "
                       "troppo uniforme.", meth, MODULE, data={"modes": modes})
    hits = [m for m in modes if m["score"] > 3.5]
    data = {"modes": modes, "threshold": 3.5}
    if len(hits) >= max(2, len(modes) // 3):
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Indizi di doppia compressione JPEG",
                       f"{len(hits)} modi DCT su {len(modes)} mostrano istogrammi periodici, tipici di una "
                       "ricompressione con tabelle diverse.", meth, MODULE, confidence="media", data=data,
                       limitations="La doppia compressione è normale per foto modificate e anche per immagini "
                                   "solo ricondivise o ruotate: dimostra una ricompressione, non un'alterazione del "
                                   "contenuto. Non rileva ricompressioni con la stessa tabella.")
    return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Nessuna periodicità DCT rilevata",
                   f"Nessun indizio di doppia quantizzazione su {len(modes)} modi analizzati.", meth, MODULE, data=data,
                   limitations="Non esclude ricompressioni a qualità uguale o non allineate alla griglia.")


# ---------------------------------------------------------------- griglia 8x8
def grid_alignment(path, is_jpeg: bool) -> Finding:
    meth = "Analisi della blocchettatura 8x8"
    y = np.asarray(Image.open(path).convert("L")).astype(np.float32)
    if min(y.shape) < 64:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Griglia JPEG non valutabile",
                       "Immagine troppo piccola.", meth, MODULE)
    # differenza seconda attraverso il confine: picco dove i blocchi si incontrano
    dh = np.abs(2 * y[:, 1:-1] - y[:, :-2] - y[:, 2:])
    dv = np.abs(2 * y[1:-1, :] - y[:-2, :] - y[2:, :])
    ph = np.array([dh[:, (np.arange(dh.shape[1]) % 8) == k].mean() for k in range(8)])
    pv = np.array([dv[(np.arange(dv.shape[0]) % 8) == k, :].mean() for k in range(8)])
    # l'indice k della differenza seconda centrata in x=k+1; confine tra 7 e 8 => colonna 7 o 8 => k=6 o 7
    ox, oy = (int(np.argmax(ph)) + 1) % 8, (int(np.argmax(pv)) + 1) % 8
    if float(np.median(ph)) < 0.3 or float(np.median(pv)) < 0.3:
        return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Griglia di compressione non valutabile",
                       "L'immagine è quasi del tutto uniforme: non ci sono abbastanza dettagli per misurare la griglia "
                       "di compressione.", meth, MODULE)
    sh = float(ph.max() / np.median(ph)) if np.median(ph) else 0.0
    sv = float(pv.max() / np.median(pv)) if np.median(pv) else 0.0
    strength = min(sh, sv)
    data = {"offset_x": ox, "offset_y": oy, "strength": round(strength, 3)}
    if strength < 1.08:
        return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Griglia di compressione non evidente",
                       f"Blocchettatura debole (forza {strength:.2f}).", meth, MODULE, data=data,
                       limitations="Compressioni ad alta qualità non lasciano una griglia misurabile.")
    aligned = ox in (0, 7) and oy in (0, 7)
    if not is_jpeg:
        return Finding(Category.IMAGE_MANIPULATION, Level.ANOMALY, "Storia di compressione JPEG in un file non JPEG",
                       f"Il file presenta una griglia di blocchi 8x8 (forza {strength:.2f}, origine x={ox}, y={oy}): "
                       "è stato compresso in JPEG prima di essere salvato in questo formato.", meth, MODULE,
                       confidence="media", data=data,
                       limitations="Una conversione di formato è spesso lecita; rilevante se il file è presentato "
                                   "come originale senza perdita.")
    if not aligned:
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Griglia JPEG non allineata",
                       f"La griglia dominante ha origine x={ox}, y={oy} invece di 0,0: compatibile con un ritaglio "
                       "dopo una compressione precedente.", meth, MODULE, confidence="media", data=data,
                       significant=strength > 1.3,
                       limitations="Ritagli e ricompressioni sono comuni nella condivisione delle immagini.")
    return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Griglia JPEG allineata",
                   f"Origine 0,0 (forza {strength:.2f}).", meth, MODULE, data=data)


# ---------------------------------------------------------------- steganalisi DCT (tipo JSteg)
def dct_chi_square(path, qtable_luma: list[int] | None) -> Finding:
    """JSteg sostituisce il bit meno significativo dei coefficienti DCT diversi da 0 e 1: le coppie di valori
    (2k, 2k+1) tendono ad avere la stessa frequenza. Coefficienti ricostruiti dai pixel e dalla tabella di
    quantizzazione (approssimazione)."""
    from ..core.findings import Category as Cat
    from .stego import _gammainc_upper
    meth = "Chi-quadro sulle coppie di coefficienti DCT (Westfeld & Pfitzmann; attacco a JSteg)"
    lim = ("Rileva inserimenti sequenziali nei coefficienti DCT del tipo JSteg. Non rileva F5, OutGuess e Steghide, "
           "che preservano queste statistiche. I coefficienti sono ricostruiti dai pixel decodificati: la stima è "
           "approssimata.")
    if not qtable_luma:
        return Finding(Cat.STEGANOGRAPHY, Level.UNDETERMINED, "Steganalisi DCT non eseguibile",
                       "Tabella di quantizzazione non disponibile.", meth, MODULE, limitations=lim)
    y = np.asarray(Image.open(path).convert("YCbCr"))[:, :, 0].astype(np.float32)
    coef = _block_dct(y)
    q = np.array(qtable_luma, dtype=np.float32).reshape(8, 8)
    v = np.rint(coef / q).astype(np.int64).reshape(len(coef), 64)[:, 1:]
    seq = []
    for pct in (5, 10, 25, 100):
        n = max(1, int(len(v) * pct / 100))
        vals = v[:n].ravel()
        vals = vals[(vals != 0) & (vals != 1) & (np.abs(vals) <= 64)]
        h = np.bincount(vals + 64, minlength=129).astype(np.float64)
        pairs = [(h[64 + 2 * k], h[64 + 2 * k + 1]) for k in range(-32, 32) if 2 * k not in (0,) and 2 * k + 1 != 1]
        chi, dof = 0.0, 0
        for a, b in pairs:
            e = (a + b) / 2
            if e > 4:
                chi += (a - e) ** 2 / e
                dof += 1
        p = _gammainc_upper((dof - 1) / 2, chi / 2) if dof > 1 else float("nan")
        seq.append({"percent": pct, "p": round(float(p), 4) if p == p else None, "coefficients": int(vals.size)})
    data = {"sequence": seq}
    if seq[0]["p"] is not None and seq[0]["p"] > 0.9 and seq[1]["p"] is not None and seq[1]["p"] > 0.9:
        return Finding(Cat.STEGANOGRAPHY, Level.SUSPICIOUS, "Coefficienti DCT compatibili con inserimento JSteg",
                       f"Le coppie di coefficienti risultano equalizzate all'inizio dell'immagine (p = {seq[0]['p']} sul "
                       f"primo 5% dei blocchi, {seq[1]['p']} sul 10%).", meth, MODULE, confidence="media",
                       significant=True, limitations=lim, data=data)
    return Finding(Cat.STEGANOGRAPHY, Level.INFO, "Nessun indizio di inserimento nei coefficienti DCT",
                   f"Distribuzione dei coefficienti naturale (p = {seq[0]['p']} sul primo 5%, {seq[-1]['p']} "
                   "sull'intera immagine).", meth, MODULE, limitations=lim, data=data)
