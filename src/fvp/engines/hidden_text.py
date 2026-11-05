"""Testo nascosto o non immediatamente visibile.

Tre controlli complementari all'estrazione LSB (stegointel):
1. testo nei metadati: commenti, descrizioni, parole chiave e altri campi liberi, con riconoscimento di blocchi
   codificati (Base64, esadecimale), indirizzi web, e-mail e contenuti ad alta entropia;
2. stringhe leggibili nei byte del file fuori dalle aree di metadati note (es. dati accodati, segmenti di commento,
   chunk sconosciuti), in ASCII e UTF-16;
3. testo a bassissimo contrasto: segni quasi invisibili su zone uniformi (colore del testo quasi uguale allo
   sfondo), con una mappa a contrasto esaltato per la verifica visiva.
"""
from __future__ import annotations

import base64
import binascii
import math
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level
from .stegointel import MAGICS, _is_text, _printable_runs

MODULE = "hidden_text"
FREE_TEXT = {"Comment", "UserComment", "ImageDescription", "XPComment", "XPTitle", "XPSubject", "XPKeywords",
             "XPAuthor", "Artist", "Copyright", "Description", "Title", "Caption-Abstract", "Keywords", "Instructions",
             "Headline", "Subject", "Label", "Notes", "Rights", "Creator", "Credit", "Source", "SpecialInstructions",
             "ObjectName", "Writer-Editor", "Parameters", "Prompt", "Software", "HostComputer", "OwnerName",
             "CameraOwnerName", "ImageUniqueID", "DocumentName", "PageName", "Make", "Model", "LensModel",
             "Comment-xxx", "Warning"}
URL = re.compile(r"(https?://|www\.)[^\s'\"<>]{4,}", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
HEXBLOB = re.compile(r"\b[0-9a-fA-F]{40,}\b")
B64BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def entropy(s: str) -> float:
    if not s:
        return 0.0
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def _decode_b64(blob: str) -> bytes | None:
    core = blob.rstrip("=")
    if len(core) % 4 == 1:
        return None
    try:
        return base64.b64decode(core + "=" * (-len(core) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None


# ---------------------------------------------------------------- 1. metadati
def metadata_text(tags: list[dict], png_text: list[dict] | None = None) -> tuple[list[dict], list[Finding]]:
    meth = "Analisi dei campi di testo libero nei metadati"
    items = []
    for t in tags:
        if t["reliability"] != "dichiarato":
            continue
        v = t["value"]
        if v.startswith("(Binary data") or v.startswith("(binary"):
            continue
        name = t["tag"]
        if name in FREE_TEXT or (t["group"].startswith("XMP") and len(v) >= 40) or name.startswith("XP"):
            items.append({"where": f"{t['group']}:{name}", "value": v})
    for pt in png_text or []:
        items.append({"where": f"PNG {pt['chunk']} '{pt['key']}' (offset {pt['offset']})", "value": pt["value"]})
    findings = []
    encoded, links = [], []
    for it in items:
        v = it["value"]
        for m in B64BLOB.finditer(v):
            dec = _decode_b64(m.group(0))
            if dec and (_is_text(dec, 8) or any(dec.startswith(mg) for mg, _, _ in MAGICS)):
                encoded.append(f"{it['where']}: Base64 → {dec[:200].decode('utf-8', errors='replace')}")
        for m in HEXBLOB.finditer(v):
            try:
                dec = bytes.fromhex(m.group(0) if len(m.group(0)) % 2 == 0 else m.group(0)[:-1])
            except ValueError:
                continue
            if _is_text(dec, 8):
                encoded.append(f"{it['where']}: esadecimale → {dec[:200].decode('utf-8', errors='replace')}")
        for rx in (URL, EMAIL):
            links += [f"{it['where']}: {m.group(0)}" for m in rx.finditer(v)]
        if len(v) >= 60 and entropy(v) > 5.2 and not _is_text(v.encode("utf-8", "ignore"), 16):
            encoded.append(f"{it['where']}: contenuto ad alta entropia ({len(v)} caratteri), possibile dato cifrato "
                           f"o compresso")
    lim = ("I campi di testo libero sono modificabili e spesso contengono informazioni lecite (autore, copyright, "
           "didascalie). Sono segnalati perché possono anche essere usati per veicolare messaggi.")
    if encoded:
        findings.append(Finding(Category.STEGANOGRAPHY, Level.SUSPICIOUS, "Contenuti codificati nei metadati",
                                "Alcuni campi di testo contengono dati codificati o non leggibili direttamente.",
                                meth, MODULE, evidence="\n".join(encoded[:20]), confidence="media", significant=True,
                                limitations=lim, data={"encoded": encoded}))
    if links:
        findings.append(Finding(Category.METADATA, Level.INFO, "Indirizzi web o e-mail nei metadati",
                                f"{len(links)} riferimenti trovati.", meth, MODULE, evidence="\n".join(links[:20]),
                                limitations=lim))
    long_text = [it for it in items if len(it["value"]) >= 30 and _is_text(it["value"].encode("utf-8", "ignore"), 16)
                 and it["where"].split(":")[-1] not in ("Software", "Make", "Model", "LensModel")]
    if long_text:
        findings.append(Finding(Category.METADATA, Level.INFO, "Testo descrittivo nei metadati",
                                f"{len(long_text)} campi contengono frasi in chiaro: leggerle può fornire contesto.",
                                meth, MODULE, evidence="\n".join(f"{it['where']}: {it['value'][:300]}" for it in long_text[:10]),
                                limitations=lim))
    return items, findings


# ---------------------------------------------------------------- 2. stringhe nel file
def _excluded_ranges(structure: dict | None) -> list[tuple[int, int, str]]:
    """Aree già interpretate da altri moduli (metadati standard) e quindi escluse dalla ricerca."""
    out = []
    if not structure:
        return out

    def walk(n):
        name, tipo = n["name"], str(n["fields"].get("tipo", ""))
        if (tipo in ("EXIF", "XMP", "Extended XMP", "ICC Profile", "Photoshop IRB / IPTC", "JFIF", "MPF (Multi-Picture)",
                     "Adobe", "JUMBF (C2PA)") or name in ("tEXt", "iTXt", "zTXt", "iCCP", "eXIf")
                or name in ("moov", "udta", "meta")):
            out.append((n["offset"], n["offset"] + n["length"], name))
            return
        for c in n["children"]:
            walk(c)
    walk(structure["root"])
    return out


def _location(structure: dict | None, off: int) -> str:
    if not structure:
        return "file"
    best = "file"

    def walk(n, depth):
        nonlocal best
        if n["offset"] <= off < n["offset"] + n["length"]:
            if depth:
                best = n["name"] + (f" [{n['fields']['tipo']}]" if n["fields"].get("tipo") else "")
            for c in n["children"]:
                walk(c, depth + 1)
    walk(structure["root"], 0)
    return best


def _sentence(s: bytes) -> bool:
    """Frase in linguaggio naturale: almeno tre parole separate da spazi, fatte di lettere."""
    words = [w for w in s.split(b" ") if w]
    good = [w for w in words if sum(chr(c).isalpha() for c in w) / len(w) >= 0.7 and len(w) >= 2]
    return len(good) >= 3 and len(good) / max(len(words), 1) >= 0.6 and _is_text(s, 20)


def file_strings(path, structure: dict | None, max_bytes: int = 256 * 1024 * 1024) -> tuple[list[dict], list[Finding]]:
    meth = "Ricerca di testo leggibile nei byte del file (ASCII e UTF-16)"
    p = Path(path)
    if p.stat().st_size > max_bytes:
        return [], [Finding(Category.STEGANOGRAPHY, Level.UNDETERMINED, "Ricerca di testo nel file non eseguita",
                            "File oltre 256 MB.", meth, MODULE)]
    data = p.read_bytes()
    excl = _excluded_ranges(structure)
    hits = []
    for off, run in _printable_runs(data, 20):
        if any(a <= off < b for a, b, _ in excl) or not _sentence(run):
            continue
        hits.append({"offset": off, "encoding": "ASCII", "text": run[:500].decode("ascii", "replace")})
    # UTF-16LE: caratteri ASCII alternati a zeri
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){20,}", data):
        off = m.start()
        if any(a <= off < b for a, b, _ in excl):
            continue
        txt = m.group(0).decode("utf-16-le", "replace")
        if _sentence(txt.encode("ascii", "ignore")):
            hits.append({"offset": off, "encoding": "UTF-16", "text": txt[:500]})
    for h in hits:
        h["location"] = _location(structure, h["offset"])
    if not hits:
        return [], [Finding(Category.STEGANOGRAPHY, Level.INFO, "Nessun testo leggibile fuori dai metadati",
                            "Nei byte del file non ci sono frasi leggibili al di fuori delle aree di metadati standard.",
                            meth, MODULE, limitations="Testo cifrato, compresso o inserito nei pixel non è leggibile "
                                                      "direttamente: per quest'ultimo vedi l'estrazione LSB.")]
    benign = [h for h in hits if h["location"].startswith("COM")]
    other = [h for h in hits if h not in benign]
    out = []
    if other:
        out.append(Finding(Category.STEGANOGRAPHY, Level.ANOMALY, "Testo leggibile in aree non previste del file",
                           f"{len(other)} frasi leggibili in punti del file che normalmente non contengono testo "
                           f"(es. {other[0]['location']}).", meth, MODULE,
                           evidence="\n".join(f"0x{h['offset']:X} [{h['location']}, {h['encoding']}]: {h['text'][:160]}"
                                              for h in other[:15]), offset=other[0]["offset"], confidence="alta",
                           significant=True, limitations="Alcuni software scrivono note o firme proprie: valutare il "
                                                         "contenuto.", data={"hits": other[:50]}))
    if benign:
        out.append(Finding(Category.METADATA, Level.INFO, "Commento JPEG",
                           f"Il file contiene {len(benign)} commenti testuali (segmento COM).", meth, MODULE,
                           evidence="\n".join(h["text"][:200] for h in benign[:5]), offset=benign[0]["offset"]))
    return hits, out


# ---------------------------------------------------------------- 3. testo a bassissimo contrasto
def faint_content(path, out_png=None) -> tuple[dict, Finding]:
    meth = "Esaltazione del contrasto nelle zone uniformi"
    with Image.open(path) as im:
        im.load()
        rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    dev = np.zeros(rgb.shape[:2], np.float32)
    for c in range(3):
        ch = rgb[:, :, c]
        med = cv2.medianBlur(ch.astype(np.uint8), 21).astype(np.float32)
        dev = np.maximum(dev, np.abs(ch - med))
    g = rgb.mean(axis=2)
    edges = cv2.dilate((cv2.Canny(g.astype(np.uint8), 40, 120) > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    loc_std = np.sqrt(np.maximum(cv2.blur(g * g, (15, 15)) - cv2.blur(g, (15, 15)) ** 2, 0))
    flat = (~edges) & (loc_std < 4.0)
    faint = flat & (dev >= 1.5) & (dev <= 14)
    faint_u8 = cv2.morphologyEx(faint.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(faint_u8, connectivity=8)
    comps = [i for i in range(1, n) if 8 <= st[i, cv2.CC_STAT_AREA] <= 4000]
    if out_png:
        vis = np.clip(dev * 18, 0, 255).astype(np.uint8)
        vis[~flat] = (vis[~flat] * 0.25).astype(np.uint8)
        Image.fromarray(cv2.applyColorMap(vis, cv2.COLORMAP_MAGMA)[:, :, ::-1]).save(out_png)
    data = {"flat_fraction": round(float(flat.mean()), 3), "faint_components": len(comps)}
    lim = ("Il controllo cerca segni deboli su zone uniformi (es. testo scritto con un colore quasi uguale allo "
           "sfondo). Rumore del sensore, compressione e sfumature producono deviazioni simili: la mappa va guardata, "
           "il numero da solo non basta. Non legge il testo (nessun OCR).")
    if flat.mean() < 0.05:
        return data, Finding(Category.STEGANOGRAPHY, Level.UNDETERMINED, "Testo a basso contrasto: poche zone uniformi",
                             "L'immagine ha troppo poche zone uniformi per questo controllo.", meth, MODULE,
                             limitations=lim, data=data)
    if len(comps) >= 8:
        # i segni devono essere raggruppati (come parole e righe), non sparsi su tutta l'immagine
        keep = np.isin(lab, comps).astype(np.uint8)
        groups = cv2.dilate(keep, np.ones((15, 25), np.uint8))
        gn, glab, gst, _ = cv2.connectedComponentsWithStats(groups, connectivity=8)
        img_area = rgb.shape[0] * rgb.shape[1]
        for gi in range(1, gn):
            members = [i for i in comps if glab[st[i, 1] + st[i, 3] // 2, st[i, 0] + st[i, 2] // 2] == gi]
            x, y, w, h = (int(v) for v in gst[gi, :4])
            heights = np.array([st[i, 3] for i in members]) if members else np.array([0])
            # testo: gruppo compatto che concentra la maggior parte dei segni deboli dell'immagine
            # (il rumore di compressione li distribuisce invece ovunque)
            if (len(members) >= 12 and len(members) >= 0.5 * len(comps) and w * h <= 0.25 * img_area
                    and (w / max(h, 1) >= 3 or len(members) >= 30)
                    and np.std(heights) / max(np.mean(heights), 1) < 0.8):
                data["bbox"] = [x, y, x + w, y + h]
                data["group_components"] = len(members)
                return data, Finding(Category.STEGANOGRAPHY, Level.SUSPICIOUS, "Possibili segni quasi invisibili",
                                     f"{len(members)} piccoli segni di contrasto molto basso, raggruppati come parole o "
                                     f"righe, nell'area x {x}–{x + w}, y {y}–{y + h}: compatibili con testo o disegni "
                                     "resi quasi invisibili (colore molto simile allo sfondo).", meth, MODULE,
                                     confidence="bassa", limitations=lim, data=data)
    return data, Finding(Category.STEGANOGRAPHY, Level.INFO, "Nessun segno a basso contrasto evidente",
                         "Nessun gruppo di segni deboli su zone uniformi. La mappa 'Contrasto esaltato' permette "
                         "comunque una verifica visiva.", meth, MODULE, limitations=lim, data=data)
