"""Indicatori di steganografia nel dominio dei pixel (LSB).

- Piani LSB per canale (ispezione visiva).
- Attacco chi-quadro (Westfeld & Pfitzmann, 1999), anche sequenziale lungo l'immagine.
- RS steganalysis (Fridrich, Goljan & Du, 2001): stima della frazione di pixel con LSB modificato.
Applicabili solo a formati senza perdita. Nessun test dimostra la presenza o l'assenza di dati nascosti.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level

MODULE = "stego"
LOSSLESS = {"png", "bmp", "tiff", "gif", "webp"}


def _gammainc_upper(a: float, x: float) -> float:
    """Q(a, x) regolarizzata, per il valore p del chi-quadro (Numerical Recipes)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        s, term, n = 1 / a, 1 / a, a
        for _ in range(500):
            n += 1
            term *= x / n
            s += term
            if abs(term) < abs(s) * 1e-12:
                break
        return max(0.0, 1 - s * math.exp(-x + a * math.log(x) - math.lgamma(a)))
    b, c, d = x + 1 - a, 1e300, 1 / (x + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - math.lgamma(a)) * h)


def chi_square_p(values: np.ndarray) -> float:
    h = np.bincount(values.ravel(), minlength=256).astype(np.float64)
    even, odd = h[0::2], h[1::2]
    exp = (even + odd) / 2
    m = exp > 4
    if m.sum() < 2:
        return float("nan")
    chi = float((((even[m] - exp[m]) ** 2) / exp[m]).sum())
    return _gammainc_upper((m.sum() - 1) / 2, chi / 2)


def _rs_counts(x: np.ndarray) -> tuple[float, float, float, float]:
    """Frazioni R_M, S_M, R_-M, S_-M su gruppi orizzontali di 4 pixel, maschera [0,1,1,0]."""
    w = (x.shape[1] // 4) * 4
    g = x[:, :w].reshape(-1, 4).astype(np.int16)

    def f(a):
        return np.abs(np.diff(a, axis=1)).sum(axis=1)

    f0 = f(g)
    pos, neg = g.copy(), g.copy()
    pos[:, 1:3] ^= 1                                   # F1: 0<->1, 2<->3
    neg[:, 1:3] = ((neg[:, 1:3] + 1) ^ 1) - 1          # F-1: -1<->0, 1<->2
    fp, fn = f(pos), f(neg)
    n = len(f0)
    return (fp > f0).sum() / n, (fp < f0).sum() / n, (fn > f0).sum() / n, (fn < f0).sum() / n


def rs_estimate(ch: np.ndarray) -> float:
    r, s, rm, sm = _rs_counts(ch)
    r1, s1, rm1, sm1 = _rs_counts(ch ^ 1)
    d0, d1, dm0, dm1 = r - s, r1 - s1, rm - sm, rm1 - sm1
    a, b, c = 2 * (d1 + d0), (dm0 - dm1 - d1 - 3 * d0), (d0 - dm0)
    if abs(a) < 1e-12:
        return 0.0
    disc = b * b - 4 * a * c
    if disc < 0:
        return float("nan")
    roots = [(-b + s_ * math.sqrt(disc)) / (2 * a) for s_ in (1, -1)]
    z = min(roots, key=abs)
    p = z / (z - 0.5) if abs(z - 0.5) > 1e-9 else float("nan")
    return float(max(0.0, min(1.0, p)))


def analyze(path, fmt: str | None, out_png=None) -> tuple[dict, list[Finding]]:
    meth_rs, meth_chi = "RS steganalysis (Fridrich et al., 2001)", "Attacco chi-quadro (Westfeld & Pfitzmann)"
    if fmt not in LOSSLESS:
        return {}, [Finding(Category.STEGANOGRAPHY, Level.INFO, "Test sui pixel non applicabili a questo formato",
                            f"Il formato {fmt or 'sconosciuto'} usa una compressione con perdita: i bit meno significativi "
                            "dei pixel non conservano dati nascosti, quindi i test RS e chi-quadro sui pixel non si "
                            "applicano. Per i JPEG viene eseguito il test sui coefficienti DCT.", "—", MODULE,
                            limitations="Steghide, F5 e OutGuess non sono rilevabili con i test statistici disponibili. "
                                        "I dati accodati al file sono segnalati dal modulo struttura.")]
    with Image.open(path) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"))
    if out_png:
        Image.fromarray(((rgb & 1) * 255).astype(np.uint8)).save(out_png)
    res: dict = {"channels": {}}
    out: list[Finding] = []
    for i, name in enumerate("RGB"):
        ch = np.ascontiguousarray(rgb[:, :, i])
        flat = ch.ravel()
        seq = []
        for pct in (1, 2, 5, 10, 25, 50, 100):
            n = max(1, int(len(flat) * pct / 100))
            seq.append({"percent": pct, "p": round(chi_square_p(flat[:n]), 4)})
        rs = rs_estimate(ch)
        res["channels"][name] = {"rs": rs if math.isnan(rs) else round(rs, 4), "chi_sequence": seq,
                                 "lsb_ones": round(float((ch & 1).mean()), 4)}
    lim = ("Immagini sintetiche, molto rumorose, ridimensionate o con molte aree sature alterano le statistiche. "
           "Un valore alto è un indicatore da verificare, non la prova di un messaggio nascosto; un valore basso "
           "non esclude metodi adattivi o cifrati.")
    # gruppi di 4 pixel identici (aree saturate, nere o piatte): l'RS li conta ma non sono informativi
    w4 = (rgb.shape[1] // 4) * 4
    grp = rgb[:, :w4].reshape(rgb.shape[0], -1, 4, 3)
    flat_frac = float((grp.max(axis=2) == grp.min(axis=2)).all(axis=2).mean())
    res["flat_fraction"] = round(flat_frac, 3)
    unreliable = flat_frac > 0.25
    rs_vals = [c["rs"] for c in res["channels"].values() if not math.isnan(c["rs"])]
    if len(rs_vals) < 3:      # l'equazione RS non ha soluzione reale: tipico di LSB completamente casuali
        out.append(Finding(Category.STEGANOGRAPHY, Level.ANOMALY, "Statistiche LSB non compatibili con un'immagine naturale",
                           "La stima RS non ha soluzione in almeno un canale: accade quando i bit meno significativi "
                           "sono quasi interamente casuali (es. inserimento al 100% della capacità).", meth_rs, MODULE,
                           confidence="media", limitations=lim,
                           data={"rs": {k: v["rs"] for k, v in res["channels"].items()}}))
    rs_max = max(rs_vals) if rs_vals else float("nan")
    lim = ("Immagini sintetiche, molto rumorose, ridimensionate o con molte aree sature alterano le statistiche. "
           "Un valore alto è un indicatore da verificare, non la prova di un messaggio nascosto; un valore basso "
           "non esclude metodi adattivi o cifrati.")
    rs_txt = ", ".join(f"{k} {v['rs']:.1%}" for k, v in res["channels"].items() if v["rs"] == v["rs"])
    if rs_vals and rs_max > 0.1 and unreliable:
        out.append(Finding(Category.STEGANOGRAPHY, Level.PROBABILISTIC, "Stima RS elevata ma poco affidabile",
                           f"La stima RS è alta ({rs_txt}), "
                           f"ma il {flat_frac:.0%} dell'immagine è composto da zone perfettamente uniformi (nero, bianco "
                           "o colori pieni), che rendono il test inaffidabile.", meth_rs, MODULE, confidence="bassa",
                           limitations=lim + " In queste immagini fanno fede l'estrazione dei contenuti (StegoIntelligence) "
                                             "e il confronto con un originale, se disponibile.", data=res["channels"]))
    elif rs_vals and rs_max > 0.1:
        out.append(Finding(Category.STEGANOGRAPHY, Level.SUSPICIOUS, "Stima RS elevata",
                           "Frazione stimata di pixel con LSB modificato: " + ", ".join(
                               f"{k} {v['rs']:.1%}" for k, v in res["channels"].items()) + ".", meth_rs, MODULE,
                           confidence="media" if rs_max > 0.2 else "bassa", significant=rs_max > 0.3,
                           limitations=lim, data={"rs": {k: v["rs"] for k, v in res["channels"].items()}}))
    else:
        out.append(Finding(Category.STEGANOGRAPHY, Level.INFO, "Stima RS nella norma",
                           "Frazione stimata di pixel modificati: " + ", ".join(
                               f"{k} {v['rs']:.1%}" for k, v in res["channels"].items()) + ".", meth_rs, MODULE,
                           limitations=lim))
    # le zone uniformi producono p alti su un singolo canale: si richiede la coerenza su tutti i canali
    seq_hits = [k for k, v in res["channels"].items()
                if np.mean([x["p"] for x in v["chi_sequence"][:3]]) > 0.85]
    if len(seq_hits) == 3:
        out.append(Finding(Category.STEGANOGRAPHY, Level.SUSPICIOUS, "Chi-quadro compatibile con inserimento sequenziale",
                           "In tutti i canali le coppie di valori 2k/2k+1 risultano equalizzate all'inizio "
                           "dell'immagine (p medio > 0,85 sul primo 1–5% dei pixel), come avviene con un inserimento "
                           "sequenziale nei bit meno significativi.", meth_chi, MODULE,
                           confidence="media", limitations=lim,
                           data={k: res["channels"][k]["chi_sequence"] for k in seq_hits}))
    return res, out
