"""Parser della struttura PNG: chunk, CRC, ordine, testo e dati accodati."""
from __future__ import annotations

import zlib
from pathlib import Path

from ..core.findings import Category, Finding, Level
from .base import MAX_NODES, Node, ParseResult

MODULE = "parser.png"
SIG = b"\x89PNG\r\n\x1a\n"
KNOWN = {"IHDR", "PLTE", "IDAT", "IEND", "tRNS", "cHRM", "gAMA", "iCCP", "sBIT", "sRGB", "cICP", "mDCv", "cLLi",
         "tEXt", "zTXt", "iTXt", "bKGD", "hIST", "pHYs", "sPLT", "eXIf", "tIME", "acTL", "fcTL", "fdAT", "caBX"}


def parse(path: str | Path) -> ParseResult:
    p = Path(path)
    size = p.stat().st_size
    root = Node("PNG", 0, size)
    fnd: list[Finding] = []
    extra: dict = {"text": [], "chunks": {}, "ihdr": None}
    with open(p, "rb") as fh:
        if fh.read(8) != SIG:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Firma PNG non valida",
                               "I primi 8 byte non corrispondono alla firma PNG.", "Parsing chunk PNG", MODULE,
                               offset=0, confidence="alta", significant=True))
            return ParseResult("png", root, fnd, extra)
        root.children.append(Node("Signature", 0, 8))
        pos = 8
        order: list[str] = []
        iend_end = None
        idat_runs = 0
        last = ""
        while pos + 12 <= size and len(root.children) < MAX_NODES:
            fh.seek(pos)
            hdr = fh.read(8)
            length = int.from_bytes(hdr[:4], "big")
            ctype = hdr[4:8].decode("latin-1")
            if length > 0x7FFFFFFF or pos + 12 + length > size:
                fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Chunk troncato",
                                   f"Il chunk '{ctype}' all'offset {pos} dichiara {length} byte oltre la fine del file.",
                                   "Parsing chunk PNG", MODULE, offset=pos, confidence="alta", significant=True))
                break
            body = fh.read(length) if length <= 64 * 1024 * 1024 else None
            crc_stored = int.from_bytes(fh.read(4), "big")
            node = Node(ctype, pos, length + 12, {"lunghezza_dati": length})
            if body is not None:
                crc = zlib.crc32(hdr[4:8] + body) & 0xFFFFFFFF
                if crc != crc_stored:
                    node.fields["crc"] = "ERRATO"
                    fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, f"CRC errato nel chunk {ctype}",
                                       f"CRC memorizzato {crc_stored:08X}, calcolato {crc:08X}.",
                                       "Verifica CRC-32 dei chunk", MODULE, offset=pos, confidence="alta",
                                       limitations="Indica dati alterati o corrotti dopo la scrittura del chunk.",
                                       significant=True))
                else:
                    node.fields["crc"] = "ok"
                if ctype == "IHDR" and length >= 13:
                    ih = {"width": int.from_bytes(body[0:4], "big"), "height": int.from_bytes(body[4:8], "big"),
                          "bit_depth": body[8], "color_type": body[9], "interlace": body[12]}
                    extra["ihdr"] = ih
                    node.fields.update(ih)
                elif ctype in ("tEXt", "zTXt", "iTXt"):
                    try:
                        key, _, rest = body.partition(b"\x00")
                        if ctype == "zTXt":
                            text = zlib.decompressobj().decompress(rest[1:], 1_000_000).decode("latin-1")
                        elif ctype == "iTXt":
                            comp_flag = rest[0]
                            parts = rest[2:].split(b"\x00", 2)
                            raw = parts[2] if len(parts) == 3 else b""
                            text = (zlib.decompressobj().decompress(raw, 1_000_000) if comp_flag else raw).decode(
                                "utf-8", errors="replace")
                        else:
                            text = rest.decode("latin-1")
                        k = key.decode("latin-1")
                        extra["text"].append({"chunk": ctype, "key": k, "value": text[:20000], "offset": pos})
                        node.fields["chiave"] = k
                    except (zlib.error, IndexError, UnicodeDecodeError):
                        node.fields["testo"] = "non decodificabile"
                elif ctype == "tIME" and length == 7:
                    node.fields["tIME"] = (f"{int.from_bytes(body[0:2], 'big'):04d}-{body[2]:02d}-{body[3]:02d} "
                                           f"{body[4]:02d}:{body[5]:02d}:{body[6]:02d} UTC")
                    extra["tIME"] = node.fields["tIME"]
            if ctype not in KNOWN:
                node.fields["nota"] = "chunk non standard"
            extra["chunks"][ctype] = extra["chunks"].get(ctype, 0) + 1
            if ctype == "IDAT" and last != "IDAT":
                idat_runs += 1
            last = ctype
            order.append(ctype)
            root.children.append(node)
            pos += length + 12
            if ctype == "IEND":
                iend_end = pos
                break
    if order and order[0] != "IHDR":
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "IHDR non è il primo chunk",
                           f"Primo chunk: {order[0]}.", "Ordine dei chunk", MODULE, offset=8, confidence="alta",
                           significant=True))
    if extra["chunks"].get("IHDR", 0) > 1:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "IHDR duplicato",
                           "Il file contiene più intestazioni IHDR.", "Ordine dei chunk", MODULE, confidence="alta",
                           significant=True))
    if idat_runs > 1:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Chunk IDAT non consecutivi",
                           "Lo standard richiede che i chunk IDAT siano contigui.", "Ordine dei chunk", MODULE,
                           confidence="alta"))
    unknown = sorted(k for k in extra["chunks"] if k not in KNOWN)
    if unknown:
        fnd.append(Finding(Category.METADATA, Level.INFO, "Chunk non standard",
                           f"Chunk presenti non definiti dalla specifica: {', '.join(unknown)}.", "Parsing chunk PNG",
                           MODULE, limitations="Spesso sono dati privati di un software (es. editor grafici)."))
    if iend_end is None:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "IEND mancante: file troncato",
                           "Il chunk finale IEND non è stato trovato.", "Parsing chunk PNG", MODULE, offset=size,
                           confidence="alta", significant=True))
    elif iend_end < size:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dati dopo IEND",
                           f"{size - iend_end} byte oltre la fine dell'immagine.", "Parsing chunk PNG", MODULE,
                           offset=iend_end, confidence="alta", significant=True,
                           limitations="Dati accodati sono un metodo comune per nascondere contenuti, ma possono "
                                       "anche essere residui di un software."))
        root.children.append(Node("Dati oltre IEND", iend_end, size - iend_end))
    return ParseResult("png", root, fnd, extra)
