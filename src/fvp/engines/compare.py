"""Hash percettivi e confronto tra immagini.

aHash, dHash, pHash (DCT 32x32) e wHash (approssimazione Haar) sono implementati qui; servono a trovare
immagini uguali o quasi uguali anche dopo ricompressione o ridimensionamento. SSIM (Wang et al., 2004),
PSNR, mappa delle differenze e relazione geometrica tramite ORB + omografia.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _gray(path) -> np.ndarray:
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("L"))


def _bits(b: np.ndarray) -> str:
    v = 0
    for x in b.ravel():
        v = (v << 1) | int(x)
    return f"{v:0{b.size // 4}x}"


def perceptual_hashes(path) -> dict:
    g = _gray(path).astype(np.float32)
    a = cv2.resize(g, (8, 8), interpolation=cv2.INTER_AREA)
    d = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    p = cv2.dct(cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA))[:8, :8]
    # wHash: approssimazione LL di Haar a 8x8 (media su blocchi di potenza di 2), soglia sulla mediana
    w = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    for _ in range(3):
        w = (w[0::2, 0::2] + w[1::2, 0::2] + w[0::2, 1::2] + w[1::2, 1::2]) / 4
    return {"ahash": _bits(a > a.mean()), "dhash": _bits(d[:, 1:] > d[:, :-1]),
            "phash": _bits(p > np.median(p.ravel()[1:])), "whash": _bits(w > np.median(w))}


def hamming(h1: str, h2: str) -> int:
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def ssim(a: np.ndarray, b: np.ndarray) -> tuple[float, np.ndarray]:
    a, b = a.astype(np.float64), b.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    blur = lambda x: cv2.GaussianBlur(x, (11, 11), 1.5)  # noqa: E731
    ma, mb = blur(a), blur(b)
    va, vb, cov = blur(a * a) - ma * ma, blur(b * b) - mb * mb, blur(a * b) - ma * mb
    m = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(m.mean()), m


def compare(path_a, path_b, out_diff=None, out_ssim=None, out_overlay=None) -> dict:
    ga, gb = _gray(path_a), _gray(path_b)
    res: dict = {"size_a": [ga.shape[1], ga.shape[0]], "size_b": [gb.shape[1], gb.shape[0]], "resized": False}
    ha, hb = perceptual_hashes(path_a), perceptual_hashes(path_b)
    res["hashes"] = {"a": ha, "b": hb, "distance": {k: hamming(ha[k], hb[k]) for k in ha}}
    # relazione geometrica (ritaglio, scala, rotazione)
    orb = cv2.ORB_create(4000)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    geo = {"matches": 0, "inliers": 0}
    if da is not None and db is not None and len(ka) >= 8 and len(kb) >= 8:
        ms = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
        geo["matches"] = len(ms)
        if len(ms) >= 8:
            src = np.float32([ka[m.queryIdx].pt for m in ms])
            dst = np.float32([kb[m.trainIdx].pt for m in ms])
            H, inl = cv2.findHomography(dst, src, cv2.RANSAC, 4.0)
            if H is not None:
                geo["inliers"] = int(inl.sum())
                geo["homography"] = [[round(float(v), 5) for v in row] for row in H]
    res["geometry"] = geo
    # allineamento: omografia affidabile se molti inlier, altrimenti semplice ridimensionamento
    if geo.get("homography") and geo["inliers"] >= 30 and ga.shape != gb.shape:
        Hm = np.array(geo["homography"])
        gb2 = cv2.warpPerspective(gb, Hm, (ga.shape[1], ga.shape[0]))
        valid = cv2.warpPerspective(np.ones_like(gb), Hm, (ga.shape[1], ga.shape[0]),
                                    flags=cv2.INTER_NEAREST) > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
        res["aligned"] = "omografia"
        res["overlap_fraction"] = round(float(valid.mean()), 3)
    elif ga.shape != gb.shape:
        gb2 = cv2.resize(gb, (ga.shape[1], ga.shape[0]), interpolation=cv2.INTER_AREA)
        res["aligned"] = "ridimensionamento"
        res["resized"] = True
    else:
        gb2 = gb
        res["aligned"] = "nessuno (stesse dimensioni)"
    if "overlap_fraction" not in res:
        valid = np.ones(ga.shape, bool)
    diff = np.abs(ga.astype(np.int16) - gb2.astype(np.int16)).astype(np.float32)
    diff[~valid] = 0
    mse = float((diff[valid] ** 2).mean()) if valid.any() else float("nan")
    res["psnr_db"] = round(10 * np.log10(255 ** 2 / mse), 2) if mse else float("inf")
    res["identical_pixels"] = mse == 0
    _s, smap = ssim(ga, gb2)
    smap[~valid] = 1.0
    res["ssim"] = round(float(smap[valid].mean()), 4) if valid.any() else float("nan")
    res["diff_pixels_over_10"] = round(float((diff[valid] > 10).mean()), 4) if valid.any() else float("nan")
    if out_diff:
        v = np.clip(diff / max(np.percentile(diff, 99.5), 1) * 255, 0, 255).astype(np.uint8)
        Image.fromarray(cv2.applyColorMap(v, cv2.COLORMAP_INFERNO)[:, :, ::-1]).save(out_diff)
    if out_ssim:
        v = (np.clip(1 - smap, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(cv2.applyColorMap(v, cv2.COLORMAP_INFERNO)[:, :, ::-1]).save(out_ssim)
    if out_overlay:
        ov = np.dstack([ga, gb2, ga]).astype(np.uint8)    # magenta = solo A, verde = solo B
        Image.fromarray(ov).save(out_overlay)
    return res


def interpret(res: dict) -> str:
    d = res["hashes"]["distance"]
    if res["identical_pixels"]:
        return "Pixel identici."
    if d["phash"] <= 6 and res["ssim"] > 0.9:
        return ("Stesso contenuto visivo con differenze minori (ricompressione, ridimensionamento o piccole modifiche "
                "locali: controllare la mappa delle differenze).")
    if res["geometry"]["inliers"] >= 30:
        return "Contenuto in comune con trasformazione geometrica (ritaglio, scala o rotazione)."
    if d["phash"] <= 12:
        return "Immagini simili: possibile derivazione con modifiche più ampie."
    return "Immagini diverse."
