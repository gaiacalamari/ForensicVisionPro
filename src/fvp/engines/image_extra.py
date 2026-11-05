"""Filtro mediano, copy-move (clonazione) e caratteristiche dell'immagine.

- Filtro mediano: idempotenza (un segnale filtrato con il mediano ne è quasi una radice), misurata
  globalmente e per blocchi per individuare ritocchi localizzati.
- Copy-move: corrispondenze SIFT all'interno della stessa immagine con test g2NN e verifica
  geometrica RANSAC (Amerini et al., 2011).
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level

MODULE = "image_extra"


def _gray(path) -> np.ndarray:
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("L"))


# ---------------------------------------------------------------- filtro mediano
def median_filter(path, is_jpeg: bool, out_png=None, jpeg_quality: int | None = None) -> Finding:
    """Idempotenza del mediano: un'immagine già filtrata con un mediano cambia poco se filtrata di nuovo
    (i segnali filtrati tendono a essere "radici" del filtro). Si misura la frazione di pixel texturizzati
    invariati dopo un mediano 3x3, globalmente e per blocchi."""
    meth = "Idempotenza del filtro mediano 3x3 (radici del mediano)"
    g = _gray(path)
    gf = g.astype(np.float32)
    var = cv2.blur(gf ** 2, (7, 7)) - cv2.blur(gf, (7, 7)) ** 2
    tex = (var > 1) & (g > 3) & (g < 252)          # esclusi solo aree perfettamente piatte e saturate
    if tex.sum() < 5000:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Filtro mediano non valutabile",
                       "Aree texturizzate insufficienti.", meth, MODULE)
    same = (cv2.medianBlur(g, 3) == g)
    frac = float(same[tex].mean())
    bs = 32
    h, w = g.shape
    hb, wb = h // bs, w // bs
    t = tex[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).sum(axis=(1, 3)).astype(np.float32)
    sm = (same & tex)[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).sum(axis=(1, 3)).astype(np.float32)
    local = np.where(t >= 200, sm / np.maximum(t, 1), np.nan)
    med = float(np.nanmedian(local)) if np.isfinite(local).any() else frac
    hot = np.nan_to_num(local) > max(0.45, med + 0.25)
    region = None
    if hot.any():
        n, _lab, st, _ = cv2.connectedComponentsWithStats(hot.astype(np.uint8), connectivity=8)
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        if st[k, cv2.CC_STAT_AREA] >= 4:
            x, y, ww, hh = (int(v) * bs for v in st[k, :4])
            region = [x, y, x + ww, y + hh]
    if out_png and np.isfinite(local).any():
        v = (np.clip(np.nan_to_num(local), 0, 1) * 255).astype(np.uint8)
        v = cv2.resize(v, (w, h), interpolation=cv2.INTER_NEAREST)
        Image.fromarray(cv2.applyColorMap(v, cv2.COLORMAP_VIRIDIS)[:, :, ::-1]).save(out_png)
    reliable = not is_jpeg or (jpeg_quality or 0) >= 90
    data = {"unchanged_fraction": round(frac, 3), "block_median": round(med, 3), "region": region,
            "reliable_format": reliable}
    lim = ("Il valore assoluto dipende dal rumore dell'immagine (immagini poco rumorose, sfocate o compresse "
           "risultano naturalmente stabili): per questo il test segnala come sospette solo le regioni molto più "
           "stabili del resto della stessa immagine. Anche altri filtri di denoising, una sfocatura locale o un inserto "
           "compresso più fortemente aumentano la stabilità: il test individua una regione elaborata diversamente, "
           "non il tipo di elaborazione.")
    if region:
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Regione con elaborazione diversa (compatibile con filtro mediano)",
                       f"Nella regione x {region[0]}–{region[2]}, y {region[1]}–{region[3]} i pixel sono stabili sotto "
                       f"un nuovo mediano molto più che nel resto dell'immagine (mediana dei blocchi {med:.2f}).", meth,
                       MODULE, confidence="media" if reliable else "bassa", significant=reliable, limitations=lim,
                       data=data)
    if frac >= 0.45:
        return Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "Stabilità elevata sotto filtro mediano",
                       f"{frac:.0%} dei pixel texturizzati è invariato dopo un mediano 3x3, in modo uniforme su tutta "
                       "l'immagine: compatibile con un filtraggio globale oppure con un'immagine poco rumorosa.", meth,
                       MODULE, confidence="bassa", limitations=lim, data=data)
    return Finding(Category.IMAGE_MANIPULATION, Level.INFO if reliable else Level.UNDETERMINED,
                   "Nessuna traccia di filtro mediano" if reliable else "Filtro mediano: valutazione poco affidabile",
                   f"{frac:.0%} dei pixel texturizzati è invariato dopo un mediano 3x3."
                   + ("" if reliable else " La compressione JPEG sotto qualità 90 limita il test."), meth, MODULE,
                   limitations=lim, data=data)


# ---------------------------------------------------------------- copy-move
def copy_move(path, out_png=None, max_features: int = 8000) -> Finding:
    meth = "SIFT + g2NN + RANSAC (copy-move)"
    g = _gray(path)
    scale = 1.0
    if max(g.shape) > 2000:
        scale = 2000 / max(g.shape)
        g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sift = cv2.SIFT_create(nfeatures=max_features)
    kps, des = sift.detectAndCompute(g, None)
    if des is None or len(kps) < 20:
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Copy-move non valutabile",
                       f"Solo {0 if des is None else len(kps)} punti caratteristici: immagine troppo uniforme.", meth,
                       MODULE, limitations="Le regioni piatte non producono punti caratteristici.")
    k = min(10, len(kps))
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des, des, k=k)
    pairs = []
    for ms in matches:
        ms = [m for m in ms if m.trainIdx != m.queryIdx]
        # g2NN: accetta i vicini finché il rapporto con il successivo resta sotto 0,5
        for a, b in zip(ms, ms[1:]):
            if a.distance / max(b.distance, 1e-6) >= 0.5:
                break
            p1, p2 = np.array(kps[a.queryIdx].pt), np.array(kps[a.trainIdx].pt)
            if np.linalg.norm(p1 - p2) > 40:
                pairs.append((p1, p2))
    # elimina coppie duplicate (A->B e B->A)
    uniq = {}
    for p1, p2 in pairs:
        key = tuple(np.round(np.concatenate(sorted([p1, p2], key=lambda p: (p[0], p[1])))).astype(int))
        uniq[key] = (p1, p2)
    pairs = list(uniq.values())
    clusters = []
    remaining = pairs
    for _ in range(3):
        if len(remaining) < 6:
            break
        src = np.float32([p[0] for p in remaining])
        dst = np.float32([p[1] for p in remaining])
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is None or inl is None or inl.sum() < 6:
            break
        inl = inl.ravel().astype(bool)
        shift = float(np.hypot(M[0, 2], M[1, 2]))
        clusters.append({"inliers": int(inl.sum()), "src": src[inl] / scale, "dst": dst[inl] / scale, "M": M,
                         "scale": round(float(np.hypot(M[0, 0], M[1, 0])), 3),
                         "rotation_deg": round(float(np.degrees(np.arctan2(M[1, 0], M[0, 0]))), 1),
                         "shift_px": round(shift / scale, 1)})
        remaining = [p for p, keep in zip(remaining, inl) if not keep]
    for c in clusters:
        c.update(_verify_clone(g, c["src"] * scale, c["dst"] * scale, c["M"]))
    if out_png:
        with Image.open(path) as im:
            vis = np.ascontiguousarray(np.asarray(im.convert("RGB"))[:, :, ::-1])
        colors = [(60, 80, 230), (40, 200, 240), (230, 120, 60)]
        for c, cl in zip(colors, clusters):
            for a, b in zip(cl["src"], cl["dst"]):
                cv2.line(vis, tuple(int(v) for v in a), tuple(int(v) for v in b), c, 1, cv2.LINE_AA)
            for pts in (cl["src"], cl["dst"]):
                if len(pts) >= 3:
                    hull = cv2.convexHull(pts.astype(np.int32))
                    cv2.polylines(vis, [hull], True, c, 2, cv2.LINE_AA)
        Image.fromarray(vis[:, :, ::-1]).save(out_png)
    data = {"keypoints": len(kps), "candidate_pairs": len(pairs),
            "clusters": [{k2: (v.tolist() if isinstance(v, np.ndarray) else v) for k2, v in c.items()
                          if k2 not in ("src", "dst", "M")} | {
                "bbox_src": [int(c["src"][:, 0].min()), int(c["src"][:, 1].min()), int(c["src"][:, 0].max()), int(c["src"][:, 1].max())],
                "bbox_dst": [int(c["dst"][:, 0].min()), int(c["dst"][:, 1].min()), int(c["dst"][:, 0].max()), int(c["dst"][:, 1].max())]}
                for c in clusters]}
    lim = ("Pattern ripetitivi legittimi (piastrelle, finestre, tessuti, testo) producono corrispondenze reali tra "
           "regioni diverse: per questo ogni gruppo è verificato riallineando i pixel e valutando se la zona è "
           "testuale. Una copia ridotta, ruotata molto o ritoccata può non essere confermata. Le regioni piatte o "
           "molto piccole non vengono rilevate. Verificare visivamente le regioni collegate nell'overlay.")
    strong = [c for c in data["clusters"] if c["inliers"] >= 10]
    # le zone testuali non sono mai confermate come copia: in schermate e documenti le stesse parole si ripetono
    # identiche pixel per pixel. Sono comunque elencate, con la somiglianza misurata, per una verifica mirata.
    confirmed = [c for c in strong if c["ncc"] >= 0.85 and not c["text_like"]]
    repeated = [c for c in strong if c not in confirmed]

    def where(c):
        return (f"x{c['bbox_src'][0]}–{c['bbox_src'][2]}, y{c['bbox_src'][1]}–{c['bbox_src'][3]} → "
                f"x{c['bbox_dst'][0]}–{c['bbox_dst'][2]}, y{c['bbox_dst'][1]}–{c['bbox_dst'][3]}")
    if confirmed:
        desc = "; ".join(f"{c['inliers']} punti corrispondenti da {where(c)} (somiglianza dei pixel {c['ncc']:.2f}, "
                         f"scala {c['scale']}, rotazione {c['rotation_deg']}°)" for c in confirmed)
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Regioni duplicate (copy-move)", desc + ".",
                       meth, MODULE, confidence="media" if len(confirmed) == 1 else "alta", significant=True,
                       limitations=lim, data=data)
    if repeated:
        sims = ", ".join(f"{c['ncc']:.2f}" for c in repeated)
        identical_text = [c for c in repeated if c["text_like"] and c["ncc"] >= 0.95]
        why = ("le regioni contengono testo o motivi regolari" if any(c["text_like"] for c in repeated) else
               "dopo l'allineamento i pixel delle due regioni non coincidono")
        extra = (" Alcune scritte sono identiche anche pixel per pixel: è normale in schermate e documenti, va "
                 "verificato solo se quel testo non dovrebbe ripetersi (ad esempio importi o date in una ricevuta)."
                 if identical_text else "")
        return Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "Elementi ripetuti, non confermati come copia",
                       f"{len(repeated)} gruppi di punti simili ({'; '.join(where(c) for c in repeated)}), ma {why} "
                       f"(somiglianza dei pixel {sims}): è "
                       "il comportamento tipico di scritte, caratteri o motivi che si ripetono naturalmente." + extra,
                       meth, MODULE, confidence="bassa", limitations=lim, data=data)
    if data["clusters"]:
        return Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "Corrispondenze deboli tra regioni",
                       f"{len(data['clusters'])} gruppi con meno di 10 corrispondenze coerenti.", meth, MODULE,
                       confidence="bassa", limitations=lim, data=data)
    return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Nessuna regione duplicata rilevata",
                   f"{len(kps)} punti caratteristici analizzati.", meth, MODULE, limitations=lim, data=data)


def _verify_clone(g: np.ndarray, src: np.ndarray, dst: np.ndarray, M: np.ndarray) -> dict:
    """Conferma a livello di pixel: una vera copia, riallineata, coincide con l'originale; testo e motivi ripetuti
    coincidono solo nei punti caratteristici. Valuta anche se la zona è testuale (due livelli netti, molti segni)."""
    h, w = g.shape
    mask_d = np.zeros((h, w), np.uint8)
    if len(dst) >= 3:
        cv2.fillConvexPoly(mask_d, cv2.convexHull(dst.astype(np.int32)), 1)
    mask_d = cv2.dilate(mask_d, np.ones((15, 15), np.uint8)) > 0
    warped = cv2.warpAffine(g, M.astype(np.float32), (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    valid = cv2.warpAffine(np.ones_like(g), M.astype(np.float32), (w, h), flags=cv2.INTER_NEAREST) > 0
    sel = mask_d & valid
    ncc = 0.0
    if sel.sum() > 100:
        a, b = g[sel].astype(np.float64), warped[sel].astype(np.float64)
        a, b = a - a.mean(), b - b.mean()
        den = np.sqrt((a * a).sum() * (b * b).sum())
        ncc = float((a * b).sum() / den) if den else 0.0
    region = g[mask_d]
    text_like = False
    if region.size > 500:
        t, _ = cv2.threshold(region.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        lo, hi = region[region <= t].astype(np.float64), region[region > t].astype(np.float64)
        if lo.size and hi.size:
            between = lo.size * hi.size / region.size ** 2 * (hi.mean() - lo.mean()) ** 2
            eta = between / max(region.astype(np.float64).var(), 1e-6)
            ys, xs = np.where(mask_d)
            box = g[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            minority = (box > t) if (hi.size < lo.size) else (box <= t)
            n, _l, st, _c = cv2.connectedComponentsWithStats(minority.astype(np.uint8), connectivity=8)
            sel = (st[1:, cv2.CC_STAT_AREA] >= 15) & (st[1:, cv2.CC_STAT_AREA] <= 3000)
            glyphs = int(sel.sum())
            heights = st[1:, cv2.CC_STAT_HEIGHT][sel].astype(np.float64)
            similar = glyphs >= 3 and heights.std() / max(heights.mean(), 1) < 0.6   # caratteri di altezza simile
            # anche una singola parola (5+ caratteri) su sfondo uniforme conta come testo
            text_like = bool(eta > 0.75 and (glyphs >= 10 or (glyphs >= 5 and similar)))
    return {"ncc": round(ncc, 3), "text_like": text_like}


# ---------------------------------------------------------------- caratteristiche
def characteristics(path, out_png=None) -> tuple[dict, Finding]:
    with Image.open(path) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB"))
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
    # stima del rumore (Immerkær, 1996)
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float64)
    conv = cv2.filter2D(g.astype(np.float64), -1, k)
    sigma = float(np.sqrt(np.pi / 2) * np.abs(conv[1:-1, 1:-1]).sum() / (6 * (g.shape[0] - 2) * (g.shape[1] - 2)))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    clip_hi, clip_lo = float((g >= 254).mean()), float((g <= 1).mean())
    faces = []
    try:
        casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not casc.empty():
            faces = [[int(v) for v in f] for f in casc.detectMultiScale(g, 1.1, 6, minSize=(40, 40))]
    except (AttributeError, cv2.error):
        faces = None
    if out_png and faces:
        vis = rgb.copy()
        for x, y, w, h in faces:
            cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 200, 40), 2)
        Image.fromarray(vis).save(out_png)
    info = {"sharpness_laplacian_var": round(lap, 1), "noise_sigma": round(sigma, 2),
            "saturation_mean": round(float(hsv[:, :, 1].mean()) / 255, 3), "clipped_high": round(clip_hi, 4),
            "clipped_low": round(clip_lo, 4), "faces": faces}
    desc = (f"Nitidezza (varianza del laplaciano) {lap:.0f}; rumore stimato σ≈{sigma:.1f}; saturazione media "
            f"{info['saturation_mean']:.2f}; pixel saturati {clip_hi:.1%} / neri {clip_lo:.1%}; volti frontali "
            f"rilevati: {'n/d' if faces is None else len(faces)}.")
    return info, Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Caratteristiche dell'immagine", desc,
                         "Statistiche del raster, Haar cascade per i volti", MODULE,
                         limitations="Dati descrittivi, utili per interpretare gli altri test (es. il rumore basso "
                                     "riduce l'affidabilità di PRNU e steganalisi). Il rilevatore di volti è "
                                     "classico e manca volti di profilo, piccoli o parzialmente coperti.")
