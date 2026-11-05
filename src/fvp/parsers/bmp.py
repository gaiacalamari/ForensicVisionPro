"""Parser BMP: intestazioni, coerenza delle dimensioni e spazi che possono contenere dati nascosti.

Controlla i byte riservati dell'intestazione, lo spazio tra intestazione e pixel, i byte di riempimento
di fine riga (devono essere zero) e i dati dopo la matrice dei pixel.
"""
from __future__ import annotations

import struct
from pathlib import Path

from ..core.findings import Category, Finding, Level
from .base import Node, ParseResult

MODULE = "parser.bmp"
LIM = ("Alcuni programmi scrivono valori non standard in questi campi senza intenzione di nascondere dati; il "
       "contenuto va esaminato con l'Hex Viewer all'offset indicato.")


def parse(path: str | Path) -> ParseResult:
    p = Path(path)
    data = p.read_bytes() if p.stat().st_size < 512 * 1024 * 1024 else None
    if data is None:
        raise ValueError("BMP oltre 512 MB: analisi strutturale non supportata")
    size = len(data)
    root = Node("BMP", 0, size)
    fnd: list[Finding] = []
    extra: dict = {}
    if size < 26 or data[:2] != b"BM":
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Intestazione BMP non valida",
                           "Il file non inizia con un'intestazione BMP completa.", "Parsing BMP", MODULE, offset=0,
                           confidence="alta", significant=True))
        return ParseResult("bmp", root, fnd, extra)
    bf_size, r1, r2, off_bits = struct.unpack("<IHHI", data[2:14])
    dib = struct.unpack("<I", data[14:18])[0]
    root.children.append(Node("BITMAPFILEHEADER", 0, 14, {"bfSize": bf_size, "reserved1": r1, "reserved2": r2,
                                                          "bfOffBits": off_bits}))
    if dib >= 40 and size >= 54:
        w, h, planes, bpp, comp, img_size, _xr, _yr, clr_used = struct.unpack("<iiHHIIiiI", data[18:50])
    elif dib == 12:
        w, h, planes, bpp = struct.unpack("<HHHH", data[18:26])
        comp, clr_used = 0, 0
    else:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.UNDETERMINED, "Intestazione DIB non riconosciuta",
                           f"Dimensione dell'intestazione {dib} byte.", "Parsing BMP", MODULE, offset=14))
        return ParseResult("bmp", root, fnd, extra)
    root.children.append(Node(f"DIB header ({dib} byte)", 14, dib, {"width": w, "height": h, "bpp": bpp,
                                                                     "compression": comp}))
    extra.update({"width": w, "height": abs(h), "bpp": bpp, "compression": comp})
    meth = "Parsing della struttura BMP"
    if bf_size != size:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dimensione dichiarata diversa da quella reale",
                           f"L'intestazione dichiara {bf_size:,} byte, il file ne contiene {size:,}.", meth, MODULE,
                           offset=2, confidence="alta", limitations=LIM))
    if r1 or r2:
        fnd.append(Finding(Category.STEGANOGRAPHY, Level.ANOMALY, "Campi riservati dell'intestazione non nulli",
                           f"I byte riservati (offset 6–9) valgono {data[6:10].hex(' ')}: dovrebbero essere zero.",
                           meth, MODULE, evidence=data[6:10].hex(" "), offset=6, confidence="alta", limitations=LIM))
    palette = (clr_used or (1 << bpp if bpp <= 8 else 0)) * (4 if dib >= 40 else 3)
    expected_start = 14 + dib + palette + (12 if dib == 40 and comp == 3 else 0)
    if off_bits > expected_start and off_bits <= size:
        gap = data[expected_start:off_bits]
        if gap.strip(b"\x00"):
            fnd.append(Finding(Category.STEGANOGRAPHY, Level.ANOMALY, "Dati tra intestazione e pixel",
                               f"{len(gap)} byte tra la fine dell'intestazione e l'inizio dei pixel, non nulli.",
                               meth, MODULE, evidence=gap[:64].hex(" "), offset=expected_start, confidence="alta",
                               significant=True, limitations=LIM))
            root.children.append(Node("Spazio non standard", expected_start, len(gap)))
    root.children.append(Node("Pixel", off_bits, max(0, size - off_bits)))
    if comp in (0, 3) and bpp in (1, 4, 8, 16, 24, 32) and w > 0:
        stride = ((w * bpp + 31) // 32) * 4
        used = (w * bpp + 7) // 8
        end = off_bits + stride * abs(h)
        extra["pixel_end"] = end
        if stride > used and end <= size:
            pad = bytearray()
            for row in range(abs(h)):
                a = off_bits + row * stride + used
                pad += data[a:off_bits + (row + 1) * stride]
            nz = sum(1 for b in pad if b)
            if nz:
                fnd.append(Finding(Category.STEGANOGRAPHY, Level.EVIDENCE, "Byte di riempimento delle righe non nulli",
                                   f"{nz} byte su {len(pad)} nel riempimento di fine riga sono diversi da zero: lo "
                                   "standard prevede zeri; è uno spazio usato per nascondere dati.", meth, MODULE,
                                   evidence=bytes(pad[:64]).hex(" "), offset=off_bits + used, confidence="alta",
                                   significant=True, limitations=LIM, data={"padding_bytes": len(pad), "nonzero": nz}))
        if end < size:
            tail = data[end:]
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY if tail.strip(b"\x00") else Level.INFO,
                               "Dati dopo la matrice dei pixel",
                               f"{len(tail):,} byte oltre la fine dei pixel" +
                               (" (solo zeri)." if not tail.strip(b"\x00") else "."), meth, MODULE,
                               evidence=tail[:32].hex(" "), offset=end, confidence="alta",
                               significant=bool(tail.strip(b"\x00")), limitations=LIM))
            root.children.append(Node("Dati oltre i pixel", end, len(tail)))
        elif end > size:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Matrice dei pixel troncata",
                               f"Mancano {end - size:,} byte di pixel.", meth, MODULE, offset=size, confidence="alta",
                               significant=True))
    return ParseResult("bmp", root, fnd, extra)
