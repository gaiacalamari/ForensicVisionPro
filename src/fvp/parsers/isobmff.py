"""Parser ISO Base Media File Format (MP4, MOV, 3GP, HEIF): albero degli atom e timestamp."""
from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.findings import Category, Finding, Level
from .base import MAX_NODES, Node, ParseLimit, ParseResult

MODULE = "parser.isobmff"
EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)
CONTAINERS = {"moov", "trak", "mdia", "minf", "stbl", "udta", "edts", "dinf", "mvex", "moof", "traf", "mfra",
              "tref", "ilst", "iprp", "ipco", "sinf", "schi", "gmhd", "tapt"}
FULLBOX_CONTAINERS = {"meta"}
TOP_LEVEL_KNOWN = {"ftyp", "moov", "mdat", "free", "skip", "wide", "uuid", "meta", "moof", "mfra", "styp", "sidx",
                   "pdin", "prft", "emsg", "pnot", "PICT"}
MAX_DEPTH = 32


def mac_time(v: int) -> str | None:
    if v == 0:
        return None
    try:
        return (EPOCH_1904 + timedelta(seconds=v)).isoformat()
    except OverflowError:
        return f"non valido ({v})"


def _fourcc(b: bytes) -> str:
    return b.decode("latin-1")


class _Ctx:
    def __init__(self, fh, size):
        self.fh, self.size, self.count = fh, size, 0
        self.findings: list[Finding] = []
        self.times: list[dict] = []
        self.tracks: list[dict] = []
        self.handler: str | None = None
        self.udta: list[dict] = []


def _parse_boxes(ctx: _Ctx, start: int, end: int, parent: Node, depth: int, path: str) -> None:
    pos = start
    while pos + 8 <= end:
        ctx.count += 1
        if ctx.count > MAX_NODES:
            raise ParseLimit("troppi atom")
        ctx.fh.seek(pos)
        hdr = ctx.fh.read(16)
        size = struct.unpack(">I", hdr[:4])[0]
        typ = _fourcc(hdr[4:8])
        hlen = 8
        if size == 1:
            size = struct.unpack(">Q", hdr[8:16])[0]
            hlen = 16
        elif size == 0:
            size = end - pos
        if size < hlen or pos + size > end:
            ctx.findings.append(Finding(
                Category.FILE_STRUCTURE, Level.EVIDENCE, f"Atom '{typ}' oltre i limiti del contenitore",
                f"L'atom all'offset {pos} dichiara {size} byte; il contenitore '{path or 'file'}' termina a {end}.",
                "Parsing ISO BMFF", MODULE, offset=pos, confidence="alta", significant=True,
                limitations="Indica troncamento o modifica non coerente della struttura."))
            parent.children.append(Node(f"{typ} (non valido)", pos, end - pos))
            return
        node = Node(typ, pos, size)
        parent.children.append(node)
        body_start = pos + hlen
        fullpath = f"{path}/{typ}" if path else typ
        if typ in CONTAINERS and depth < MAX_DEPTH:
            _parse_boxes(ctx, body_start, pos + size, node, depth + 1, fullpath)
        elif typ in FULLBOX_CONTAINERS and depth < MAX_DEPTH:
            ctx.fh.seek(body_start)
            peek = ctx.fh.read(8)
            # in QuickTime 'meta' non è un FullBox: se dopo 4 byte c'è già un fourcc 'hdlr' si salta diversamente
            off = 0 if peek[4:8] == b"hdlr" else 4
            _parse_boxes(ctx, body_start + off, pos + size, node, depth + 1, fullpath)
        else:
            _leaf(ctx, typ, body_start, pos + size, node, fullpath)
        pos += size
    if pos < end and end - pos < 8 and parent.name != "file":
        pass


def _leaf(ctx: _Ctx, typ: str, start: int, end: int, node: Node, path: str) -> None:
    ln = end - start
    if typ == "ftyp" and ln >= 8:
        ctx.fh.seek(start)
        b = ctx.fh.read(min(ln, 256))
        node.fields["major_brand"] = _fourcc(b[:4])
        node.fields["minor_version"] = struct.unpack(">I", b[4:8])[0]
        node.fields["compatible"] = [_fourcc(b[i:i + 4]) for i in range(8, len(b) - 3, 4)]
    elif typ in ("mvhd", "tkhd", "mdhd") and ln >= 20:
        ctx.fh.seek(start)
        b = ctx.fh.read(min(ln, 40))
        ver = b[0]
        if ver == 1 and len(b) >= 28:
            ct, mt = struct.unpack(">QQ", b[4:20])
            rest = b[20:]
        else:
            ct, mt = struct.unpack(">II", b[4:12])
            rest = b[12:]
        node.fields.update({"version": ver, "creation_time": mac_time(ct), "modification_time": mac_time(mt),
                            "creation_raw": ct, "modification_raw": mt})
        if typ in ("mvhd", "mdhd") and len(rest) >= 12:
            if ver == 1:
                ts, dur = struct.unpack(">IQ", rest[:12])
            else:
                ts, dur = struct.unpack(">II", rest[:8])
            node.fields["timescale"] = ts
            node.fields["duration_s"] = round(dur / ts, 3) if ts else None
        ctx.times.append({"source": f"{path}", "atom": typ, "offset": node.offset, "creation": mac_time(ct),
                          "modification": mac_time(mt), "creation_raw": ct, "modification_raw": mt})
    elif typ == "hdlr" and ln >= 12:
        ctx.fh.seek(start)
        b = ctx.fh.read(min(ln, 64))
        node.fields["handler_type"] = _fourcc(b[8:12])
        name = b[24:].split(b"\x00")[0].decode("utf-8", errors="replace").strip()
        if name:
            node.fields["name"] = name
    elif path.startswith("moov/udta/") or path.startswith("moov/meta/ilst/"):
        ctx.fh.seek(start)
        b = ctx.fh.read(min(ln, 512))
        txt = b.decode("utf-8", errors="replace").strip("\x00 ")
        printable = "".join(c for c in txt if c.isprintable())
        if printable:
            node.fields["testo"] = printable[:200]
            ctx.udta.append({"atom": path, "offset": node.offset, "text": printable[:200]})


def parse(path: str | Path) -> ParseResult:
    p = Path(path)
    size = p.stat().st_size
    root = Node("file", 0, size)
    with open(p, "rb") as fh:
        ctx = _Ctx(fh, size)
        try:
            _parse_boxes(ctx, 0, size, root, 0, "")
        except ParseLimit as e:
            ctx.findings.append(Finding(Category.FILE_STRUCTURE, Level.UNDETERMINED, "Analisi interrotta",
                                        f"Limite di sicurezza raggiunto: {e}.", "Parsing ISO BMFF", MODULE))
    top = [c.name for c in root.children]
    fnd = ctx.findings
    if "moov" not in top and not any(n.startswith("moof") for n in top):
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Atom 'moov' assente",
                           "Senza 'moov' il file non è riproducibile: tipico di registrazioni interrotte o file "
                           "troncati.", "Parsing ISO BMFF", MODULE, confidence="alta", significant=True))
    if top.count("moov") > 1:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Più atom 'moov'",
                           "Il file contiene più indici 'moov' al livello principale.", "Parsing ISO BMFF", MODULE,
                           confidence="alta", significant=True))
    if top and top[0] not in ("ftyp", "wide", "free", "skip", "mdat", "moov", "styp"):
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Primo atom inatteso",
                           f"Il primo atom è '{top[0]}'.", "Parsing ISO BMFF", MODULE, offset=0, confidence="media"))
    unknown_top = sorted({t for t in top if t not in TOP_LEVEL_KNOWN and "(non valido)" not in t})
    if unknown_top:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Atom non standard al livello principale",
                           f"Atom presenti: {', '.join(unknown_top)}.", "Parsing ISO BMFF", MODULE,
                           limitations="Alcuni produttori usano atom proprietari: confrontare con file di "
                                       "riferimento dello stesso modello."))
    if "moov" in top and "mdat" in top:
        order = "moov prima di mdat (faststart / remux)" if top.index("moov") < top.index("mdat") else \
            "mdat prima di moov (tipico di registrazione diretta)"
        fnd.append(Finding(Category.VIDEO_INTEGRITY, Level.INFO, "Ordine moov/mdat", order + ".",
                           "Parsing ISO BMFF", MODULE,
                           limitations="Molte fotocamere scrivono moov alla fine; alcuni smartphone e i software "
                                       "di editing lo spostano all'inizio. È un indizio, non una prova."))
    majors = [n.fields.get("major_brand") for n in root.children if n.name == "ftyp"]
    extra = {"top_level": top, "times": ctx.times, "udta": ctx.udta, "major_brand": majors[0] if majors else None}
    return ParseResult("isobmff", root, fnd, extra)
