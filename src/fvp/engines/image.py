"""Image Analysis Engine: informazioni sul raster, ELA, residuo di rumore, coerenza della miniatura."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from ..core.findings import Category, Finding, Level
from ..core.tools import ToolError, get_tool, run

MODULE = "image"


def set_pixel_limit(n: int) -> None:
    Image.MAX_IMAGE_PIXELS = n     # protezione da decompression bomb


def image_info(path: str | Path) -> dict:
    with Image.open(path) as im:
        info = {"format": im.format, "mode": im.mode, "width": im.width, "height": im.height,
                "channels": len(im.getbands()), "bands": "".join(im.getbands()),
                "frames": getattr(im, "n_frames", 1), "icc_profile": bool(im.info.get("icc_profile")),
                "dpi": [float(x) for x in im.info["dpi"]] if "dpi" in im.info else None,
                "progressive": bool(im.info.get("progressive") or im.info.get("progression")),
                "orientation": im.getexif().get(0x0112)}
        if im.format == "JPEG":
            try:
                from PIL import JpegImagePlugin
                info["subsampling"] = {0: "4:4:4", 1: "4:2:2", 2: "4:2:0"}.get(
                    JpegImagePlugin.get_sampling(im), "altro")
            except Exception:  # noqa: BLE001
                pass
        if info["icc_profile"]:
            try:
                from PIL import ImageCms
                prof = ImageCms.ImageCmsProfile(io.BytesIO(im.info["icc_profile"]))
                info["icc_description"] = ImageCms.getProfileDescription(prof).strip()
            except Exception:  # noqa: BLE001
                info["icc_description"] = "non leggibile"
    return info


def _load_rgb(path: str | Path) -> Image.Image:
    with Image.open(path) as im:
        im.load()
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        return im.convert("RGB")


def ela(path: str | Path, quality: int = 90, out_png: str | Path | None = None) -> tuple[np.ndarray, Finding]:
    """Error Level Analysis: differenza tra l'immagine e una sua ricompressione JPEG a qualità nota."""
    src = _load_rgb(path)
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    re = Image.open(buf).convert("RGB")
    diff = np.abs(np.asarray(src, dtype=np.int16) - np.asarray(re, dtype=np.int16)).max(axis=2).astype(np.float32)
    p99 = float(np.percentile(diff, 99.5)) or 1.0
    vis = np.clip(diff * (255.0 / p99), 0, 255).astype(np.uint8)
    if out_png:
        Image.fromarray(vis).save(out_png)
    # statistiche per blocchi 32x32: quanto si discostano le regioni dalla mediana
    h, w = diff.shape
    bs = 32
    hb, wb = h // bs, w // bs
    stats = {"quality": quality, "mean": round(float(diff.mean()), 3), "p99_5": round(p99, 3)}
    if hb and wb:
        blocks = diff[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).mean(axis=(1, 3))
        med = float(np.median(blocks)) or 1e-6
        stats["block_max_over_median"] = round(float(blocks.max()) / med, 2)
    fmt = Image.open(path).format
    lim = ("L'ELA evidenzia differenze di errore di compressione: bordi netti, texture fini e colori saturi "
           "producono valori alti anche in immagini integre. Va interpretata visivamente confrontando regioni "
           "con contenuto simile. Non è una prova di manipolazione.")
    if fmt != "JPEG":
        lim = f"Il file è {fmt}, non JPEG: l'ELA ha valore limitato. " + lim
    return vis, Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "Mappa ELA generata",
                        f"Ricompressione a qualità {quality}. Errore medio {stats['mean']}; rapporto massimo tra "
                        f"blocchi e mediana {stats.get('block_max_over_median', 'n/d')}.",
                        "Error Level Analysis", MODULE, confidence="richiede interpretazione dell'operatore",
                        limitations=lim, data=stats)


def noise_residual(path: str | Path, out_png: str | Path | None = None) -> tuple[np.ndarray, Finding]:
    """Residuo di rumore (immagine - filtro mediano 3x3) e mappa della deviazione standard locale."""
    import cv2
    g = np.asarray(_load_rgb(path).convert("L"), dtype=np.float32)
    res = g - cv2.medianBlur(g.astype(np.uint8), 3).astype(np.float32)
    bs = 16
    h, w = res.shape
    hb, wb = h // bs, w // bs
    if not hb or not wb:
        return np.zeros((1, 1), np.uint8), Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED,
                                                   "Residuo di rumore non calcolabile", "Immagine troppo piccola.",
                                                   "Noise residual", MODULE)
    std = res[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).std(axis=(1, 3))
    vis = np.clip(std / (np.percentile(std, 99) or 1) * 255, 0, 255).astype(np.uint8)
    vis = cv2.resize(vis, (w, h), interpolation=cv2.INTER_NEAREST)
    if out_png:
        Image.fromarray(cv2.applyColorMap(vis, cv2.COLORMAP_INFERNO)[:, :, ::-1]).save(out_png)
    flat = std.ravel()
    med = float(np.median(flat))
    mad = float(np.median(np.abs(flat - med))) or 1e-6
    outlier_ratio = float(np.mean(np.abs(flat - med) / mad > 6))
    return vis, Finding(Category.IMAGE_MANIPULATION, Level.PROBABILISTIC, "Mappa del residuo di rumore",
                        f"Deviazione standard locale del residuo su blocchi {bs}x{bs}. Blocchi fortemente fuori "
                        f"distribuzione: {outlier_ratio:.1%}.", "Noise residual (mediano 3x3)", MODULE,
                        confidence="richiede interpretazione dell'operatore",
                        limitations="Regioni piatte (cielo, pareti) e sature hanno rumore naturalmente diverso "
                                    "dalle regioni texturizzate. Rilevante solo se l'incoerenza riguarda aree con "
                                    "contenuto simile.", data={"outlier_ratio": round(outlier_ratio, 4)})


def thumbnail_check(path: str | Path, exiftool_path: str = "") -> Finding | None:
    """Confronta la miniatura EXIF con l'immagine principale. Una miniatura diversa è un indicatore
    classico di modifica con software che non aggiorna la miniatura."""
    tool = get_tool("exiftool", exiftool_path)
    if not tool:
        return None
    try:
        data = run([tool.path, "-b", "-ThumbnailImage", str(Path(path).resolve())], timeout=60)
    except ToolError:
        return None
    if not data or not data.startswith(b"\xff\xd8"):
        return None
    meth = "Confronto miniatura EXIF / immagine principale"
    try:
        th = Image.open(io.BytesIO(data)).convert("L")
    except Exception as e:  # noqa: BLE001
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Miniatura non decodificabile", str(e),
                       meth, MODULE)
    return compare_thumbnail(th, path, meth)


def compare_thumbnail(th: Image.Image, path: str | Path, meth: str) -> Finding:
    """Confronto tra una miniatura già decodificata (scala di grigi) e l'immagine principale."""
    try:
        main = ImageOps.exif_transpose(_load_rgb(path)).convert("L")
        main_raw = _load_rgb(path).convert("L")
    except Exception as e:  # noqa: BLE001
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Miniatura non decodificabile", str(e),
                       meth, MODULE)
    best = None
    for cand in (main_raw, main):
        ar_t, ar_m = th.width / th.height, cand.width / cand.height
        small = cand.resize(th.size, Image.Resampling.LANCZOS)
        d = np.abs(np.asarray(small, np.float32) - np.asarray(th, np.float32))
        score = (abs(ar_t - ar_m) / ar_m, float(d.mean()))
        if best is None or score < best[0]:
            best = (score, ar_t, ar_m, d)
    (ar_err, diff), ar_t, ar_m, dmap = best
    bs = 8
    hb, wb = dmap.shape[0] // bs, dmap.shape[1] // bs
    blocks = dmap[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).mean(axis=(1, 3)) if hb and wb else dmap
    bmax, bmed = float(blocks.max()), float(np.median(blocks))
    n_out = int(np.sum(blocks > max(15.0, 4 * bmed + 8)))
    data_ = {"thumb_size": th.size, "aspect_thumb": round(ar_t, 4), "aspect_main": round(ar_m, 4),
             "mean_abs_diff": round(diff, 2), "block_max": round(bmax, 2), "block_median": round(bmed, 2),
             "blocks_outlier": n_out, "blocks_total": int(blocks.size)}
    lim = ("Alcune fotocamere generano miniature con bande nere o ritagli (rapporto 4:3 o 16:9 fisso). "
           "Confrontare visivamente la miniatura estratta con l'immagine.")
    if ar_err > 0.03 and not (abs(ar_t - 4 / 3) < 0.02 or abs(ar_t - 16 / 9) < 0.02 or abs(ar_t - 1.5) < 0.02):
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Proporzioni della miniatura diverse",
                       f"Miniatura {ar_t:.3f}, immagine {ar_m:.3f}: compatibile con ritaglio non riflesso nella "
                       "miniatura.", meth, MODULE, confidence="media", limitations=lim, data=data_, significant=True)
    if diff > 18 or n_out >= 2:
        where = ""
        if n_out:
            ys, xs = np.where(blocks > max(15.0, 4 * bmed + 8))
            sx, sy = (main_raw.width / th.width), (main_raw.height / th.height)
            where = (f" Regione differente approssimativa nell'immagine: x {int(xs.min() * bs * sx)}–"
                     f"{int((xs.max() + 1) * bs * sx)}, y {int(ys.min() * bs * sy)}–{int((ys.max() + 1) * bs * sy)}.")
            data_["region"] = [int(xs.min() * bs * sx), int(ys.min() * bs * sy), int((xs.max() + 1) * bs * sx),
                               int((ys.max() + 1) * bs * sy)]
        return Finding(Category.IMAGE_MANIPULATION, Level.SUSPICIOUS, "Contenuto della miniatura diverso",
                       f"Differenza media {diff:.1f} livelli; {n_out} blocchi su {blocks.size} differiscono in modo "
                       f"localizzato (max {bmax:.1f}, mediana {bmed:.1f}).{where} Compatibile con una modifica "
                       "dell'immagine principale senza aggiornamento della miniatura.", meth, MODULE,
                       confidence="media", limitations=lim, data=data_, significant=True)
    return Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Miniatura coerente con l'immagine",
                   f"Differenza media {diff:.1f} livelli di grigio.", meth, MODULE, limitations=lim, data=data_)
