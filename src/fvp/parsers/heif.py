"""Parser HEIF/HEIC (ISO/IEC 23008-12): item, posizioni dei dati, riferimenti e proprietà.

Un file HEIF non ha 'moov': l'immagine è descritta dal box 'meta' (hdlr 'pict') con
  - iinf/infe : elenco degli item (tile HEVC 'hvc1', 'grid', 'Exif', XMP 'mime', ...)
  - iloc      : dove si trovano i byte di ogni item (in 'mdat' o in 'idat')
  - iref      : relazioni tra item (dimg = tile della griglia, thmb = miniatura, cdsc = metadati,
                auxl = immagini ausiliarie come gain map HDR, matte del ritratto, profondità)
  - iprp      : proprietà (ispe = dimensioni, irot/imir = rotazione/specchio, pixi, colr, auxC, hvcC)
Su iPhone l'immagine principale è di norma un item 'grid' composto da tile HEVC 512x512.

Il parser legge solo, con limiti espliciti, e non decodifica i pixel (lo fa pillow-heif nei moduli d'immagine).
"""
from __future__ import annotations

import struct
from pathlib import Path

from ..core.findings import Category, Finding, Level
from . import isobmff

MODULE = "parser.heif"
MAX_META = 32 * 1024 * 1024     # un 'meta' più grande non è plausibile per una foto
MAX_ITEMS = 20_000
MAX_EXTENTS = 200_000
METHOD = "Parsing HEIF (ISO/IEC 23008-12)"

AUX_LABELS = {
    "urn:mpeg:hevc:2015:auxid:1": "canale alfa",
    "urn:mpeg:mpegB:cicp:systems:auxiliary:alpha": "canale alfa",
    "urn:mpeg:hevc:2015:auxid:2": "mappa di profondità",
    "urn:mpeg:mpegB:cicp:systems:auxiliary:depth": "mappa di profondità",
    "urn:com:apple:photo:2018:aux:portraiteffectsmatte": "matte effetto Ritratto (Apple)",
    "urn:com:apple:photo:2020:aux:hdrgainmap": "gain map HDR (Apple)",
}
IMAGE_TYPES = {"hvc1", "av01", "jpeg", "grid", "iovl", "iden", "unci", "vvc1", "tmap"}


class HeifError(Exception):
    pass


def _u(b: bytes, pos: int, n: int) -> int:
    if n == 0:
        return 0
    if pos + n > len(b):
        raise HeifError(f"lettura oltre la fine del box (pos {pos}, {n} byte)")
    return int.from_bytes(b[pos:pos + n], "big")


def _cstr(b: bytes, pos: int, end: int) -> tuple[str, int]:
    z = b.find(b"\x00", pos, end)
    if z < 0:
        return b[pos:end].decode("utf-8", "replace"), end
    return b[pos:z].decode("utf-8", "replace"), z + 1


def _boxes(b: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack_from(">I4s", b, pos)
        hl = 8
        if size == 1:
            size, hl = _u(b, pos + 8, 8), 16
        elif size == 0:
            size = end - pos
        if size < hl or pos + size > end:
            raise HeifError(f"box '{typ.decode('latin-1')}' a +{pos} dichiara {size} byte oltre il contenitore")
        yield typ.decode("latin-1"), pos + hl, pos + size, pos
        pos += size


# --------------------------------------------------------------------------- lettura dei box di 'meta'

def _pitm(b, s, e):
    return _u(b, s + 4, 2 if b[s] == 0 else 4)


def _iinf(b, s, e):
    ver = b[s]
    p = s + 4 + (2 if ver == 0 else 4)
    items = {}
    for typ, bs, be, _ in _boxes(b, p, e):
        if typ != "infe":
            continue
        if len(items) >= MAX_ITEMS:
            raise HeifError("troppi item")
        v, flags = b[bs], _u(b, bs + 1, 3)
        q = bs + 4
        if v >= 2:
            iid = _u(b, q, 2 if v == 2 else 4)
            q += 2 if v == 2 else 4
            q += 2                                        # item_protection_index
            itype = b[q:q + 4].decode("latin-1")
            q += 4
            name, q = _cstr(b, q, be)
            ctype = ""
            if itype == "mime":
                ctype, q = _cstr(b, q, be)
            elif itype == "uri ":
                ctype, q = _cstr(b, q, be)
        else:                                             # infe v0/v1 (raro)
            iid = _u(b, q, 2)
            q += 4
            name, q = _cstr(b, q, be)
            ctype, q = _cstr(b, q, be)
            itype = "mime" if ctype else "????"
        items[iid] = {"id": iid, "type": itype, "name": name, "content_type": ctype, "hidden": bool(flags & 1)}
    return items


def _iloc(b, s, e):
    ver = b[s]
    q = s + 4
    off_sz, len_sz = b[q] >> 4, b[q] & 15
    base_sz, idx_sz = b[q + 1] >> 4, (b[q + 1] & 15) if ver in (1, 2) else 0
    q += 2
    n = _u(b, q, 2 if ver < 2 else 4)
    q += 2 if ver < 2 else 4
    locs, total = {}, 0
    for _ in range(n):
        iid = _u(b, q, 2 if ver < 2 else 4)
        q += 2 if ver < 2 else 4
        method = 0
        if ver in (1, 2):
            method = _u(b, q, 2) & 15
            q += 2
        dref = _u(b, q, 2)
        q += 2
        base = _u(b, q, base_sz)
        q += base_sz
        ext_n = _u(b, q, 2)
        q += 2
        total += ext_n
        if total > MAX_EXTENTS:
            raise HeifError("troppi extent in iloc")
        exts = []
        for _ in range(ext_n):
            if idx_sz:
                q += idx_sz
            off = _u(b, q, off_sz)
            q += off_sz
            ln = _u(b, q, len_sz)
            q += len_sz
            exts.append((base + off, ln))
        locs[iid] = {"method": method, "data_ref": dref, "extents": exts}
    return locs


def _iref(b, s, e):
    ver = b[s]
    w = 2 if ver == 0 else 4
    refs = []
    for typ, bs, be, _ in _boxes(b, s + 4, e):
        src = _u(b, bs, w)
        cnt = _u(b, bs + w, 2)
        dst = [_u(b, bs + w + 2 + i * w, w) for i in range(cnt)]
        refs.append({"type": typ, "from": src, "to": dst})
    return refs


def _ipco(b, s, e):
    props = []
    for typ, bs, be, _ in _boxes(b, s, e):
        p = {"type": typ}
        if typ == "ispe" and be - bs >= 12:
            p["width"], p["height"] = _u(b, bs + 4, 4), _u(b, bs + 8, 4)
        elif typ == "irot" and be > bs:
            p["angle"] = (b[bs] & 3) * 90                 # antiorario
        elif typ == "imir" and be > bs:
            p["axis"] = "orizzontale" if b[bs] & 1 else "verticale"
        elif typ == "pixi" and be - bs >= 5:
            nch = b[bs + 4]
            p["bits"] = list(b[bs + 5:bs + 5 + nch])
        elif typ == "auxC" and be - bs > 4:
            p["aux_type"], _ = _cstr(b, bs + 4, be)
        elif typ == "colr" and be - bs >= 4:
            p["colour_type"] = b[bs:bs + 4].decode("latin-1")
        elif typ == "hvcC" and be - bs >= 23:
            p["chroma"] = {0: "4:0:0", 1: "4:2:0", 2: "4:2:2", 3: "4:4:4"}.get(b[bs + 16] & 3)
            p["bit_depth_luma"] = (b[bs + 17] & 7) + 8
        props.append(p)
    return props


def _ipma(b, s, e):
    ver, flags = b[s], _u(b, s + 1, 3)
    q = s + 4
    n = _u(b, q, 4)
    q += 4
    assoc = {}
    for _ in range(min(n, MAX_ITEMS)):
        iid = _u(b, q, 2 if ver < 1 else 4)
        q += 2 if ver < 1 else 4
        cnt = b[q]
        q += 1
        lst = []
        for _ in range(cnt):
            if flags & 1:
                v = _u(b, q, 2)
                q += 2
                lst.append(v & 0x7FFF)
            else:
                lst.append(b[q] & 0x7F)
                q += 1
        assoc[iid] = lst
    return assoc


# --------------------------------------------------------------------------- analisi

def _item_bytes(fh, file_size: int, loc: dict, idat: tuple[int, int] | None, limit: int = 64) -> bytes:
    out = b""
    for off, ln in loc["extents"]:
        if loc["method"] == 0:
            ln = ln or (file_size - off)
            fh.seek(off)
            out += fh.read(min(ln, limit - len(out)))
        elif loc["method"] == 1 and idat:
            st = idat[0] + off
            ln = ln or (idat[1] - st)
            fh.seek(st)
            out += fh.read(min(ln, limit - len(out)))
        if len(out) >= limit:
            break
    return out


def _grid(data: bytes) -> dict | None:
    if len(data) < 8:
        return None
    flags = data[1]
    w = 4 if flags & 1 else 2
    if len(data) < 4 + 2 * w:
        return None
    return {"rows": data[2] + 1, "columns": data[3] + 1, "output_width": _u(data, 4, w),
            "output_height": _u(data, 4 + w, w)}


def parse(path: str | Path):
    p = Path(path)
    size = p.stat().st_size
    res = isobmff.parse(p, still_image=True)
    res.format = "heif"
    fnd = res.findings
    metas = [n for n in res.root.children if n.name == "meta"]
    has_track = any(n.name == "moov" for n in res.root.children)
    if not metas and has_track:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.INFO, "Sequenza di immagini HEIF",
                           "Il file contiene solo una traccia di immagini ('moov', brand msf1) e nessun item: viene "
                           "trattato come un filmato.", METHOD, MODULE))
        return res
    if not metas:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Box 'meta' assente",
                           "Un'immagine HEIF descrive i propri item nel box 'meta' di livello principale: senza di "
                           "esso l'immagine non è decodificabile.", METHOD, MODULE, confidence="alta",
                           significant=True))
        return res
    meta = metas[0]
    if meta.length > MAX_META:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.UNDETERMINED, "Box 'meta' troppo grande",
                           f"{meta.length} byte: analisi degli item saltata per sicurezza.", METHOD, MODULE))
        return res
    with open(p, "rb") as fh:
        fh.seek(meta.offset)
        b = fh.read(meta.length)
        hl = 16 if struct.unpack_from(">I", b, 0)[0] == 1 else 8
        info: dict = {"items": {}, "locs": {}, "refs": [], "props": [], "assoc": {}, "primary": None,
                      "handler": None}
        idat = None
        try:
            for typ, bs, be, bo in _boxes(b, hl + 4, len(b)):         # +4: meta è un FullBox
                if typ == "hdlr" and be - bs >= 12:
                    info["handler"] = b[bs + 8:bs + 12].decode("latin-1")
                elif typ == "pitm":
                    info["primary"] = _pitm(b, bs, be)
                elif typ == "iinf":
                    info["items"] = _iinf(b, bs, be)
                elif typ == "iloc":
                    info["locs"] = _iloc(b, bs, be)
                elif typ == "iref":
                    info["refs"] = _iref(b, bs, be)
                elif typ == "idat":
                    idat = (meta.offset + bs, meta.offset + be)
                elif typ == "iprp":
                    for t2, s2, e2, _ in _boxes(b, bs, be):
                        if t2 == "ipco":
                            info["props"] = _ipco(b, s2, e2)
                        elif t2 == "ipma":
                            info["assoc"].update(_ipma(b, s2, e2))
        except (HeifError, IndexError, struct.error) as e:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Box 'meta' HEIF non valido",
                               f"Errore di lettura: {e}.", METHOD, MODULE, offset=meta.offset, confidence="alta",
                               significant=True,
                               limitations="Indica troncamento o una riscrittura non conforme del contenitore."))
            return res
        summary = _analyze(info, fnd, fh, size, idat, res)
    res.extra["heif"] = summary
    return res


def _props_of(info: dict, iid: int) -> list[dict]:
    out = []
    for idx in info["assoc"].get(iid, []):
        if 1 <= idx <= len(info["props"]):
            out.append(info["props"][idx - 1])
    return out


def _prop(info: dict, iid: int, typ: str) -> dict | None:
    return next((p for p in _props_of(info, iid) if p["type"] == typ), None)


def _analyze(info: dict, fnd: list[Finding], fh, size: int, idat, res) -> dict:
    items, locs, refs = info["items"], info["locs"], info["refs"]
    prim = info["primary"]
    by_type: dict[str, int] = {}
    for it in items.values():
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    s: dict = {"handler": info["handler"], "primary_item": prim, "items_by_type": by_type,
               "brands": next((n.fields for n in res.root.children if n.name == "ftyp"), {})}

    if info["handler"] not in ("pict", None):
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Handler HEIF inatteso",
                           f"hdlr = '{info['handler']}' (atteso 'pict' per un'immagine).", METHOD, MODULE,
                           confidence="alta"))
    if prim is None:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Item primario (pitm) assente",
                           "Il file non indica quale item sia l'immagine principale.", METHOD, MODULE,
                           confidence="alta", significant=True))
        return s
    if prim not in items:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Item primario inesistente",
                           f"pitm indica l'item {prim}, che non è descritto in iinf.", METHOD, MODULE,
                           confidence="alta", significant=True))
        return s
    ptype = items[prim]["type"]
    s["primary_type"] = ptype
    ispe = _prop(info, prim, "ispe")
    if ispe:
        s["primary_size"] = [ispe["width"], ispe["height"]]
    rot, mir = _prop(info, prim, "irot"), _prop(info, prim, "imir")
    s["rotation_ccw"] = rot["angle"] if rot else 0
    s["mirror"] = mir["axis"] if mir else None
    pixi = _prop(info, prim, "pixi")
    if pixi:
        s["bits_per_channel"] = pixi["bits"]
    colr = [p["colour_type"] for p in _props_of(info, prim) if p["type"] == "colr"]
    s["colour"] = colr

    def refs_from(rtype: str, src: int) -> list[int]:
        return [d for r in refs if r["type"] == rtype and r["from"] == src for d in r["to"]]

    def refs_to(rtype: str, dst: int) -> list[int]:
        return [r["from"] for r in refs if r["type"] == rtype and dst in r["to"]]

    # Griglia di tile (formato tipico dell'iPhone)
    if ptype == "grid":
        tiles = refs_from("dimg", prim)
        g = _grid(_item_bytes(fh, size, locs[prim], idat)) if prim in locs else None
        if g:
            t0 = _prop(info, tiles[0], "ispe") if tiles else None
            if t0:
                g["tile_size"] = [t0["width"], t0["height"]]
            g["tiles"] = len(tiles)
            s["grid"] = g
            if len(tiles) != g["rows"] * g["columns"]:
                fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Griglia HEIF incompleta",
                                   f"La griglia dichiara {g['rows']}x{g['columns']} tile ma ne referenzia "
                                   f"{len(tiles)}.", METHOD, MODULE, confidence="alta", significant=True))
            if ispe and (ispe["width"], ispe["height"]) != (g["output_width"], g["output_height"]):
                fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dimensioni della griglia incoerenti",
                                   f"ispe {ispe['width']}x{ispe['height']}, griglia {g['output_width']}x"
                                   f"{g['output_height']}.", METHOD, MODULE, confidence="alta", significant=True))
            if t0 and not (g["columns"] * t0["width"] >= g["output_width"] > (g["columns"] - 1) * t0["width"]
                           and g["rows"] * t0["height"] >= g["output_height"] > (g["rows"] - 1) * t0["height"]):
                fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Tile non compatibili con la griglia",
                                   f"{g['columns']}x{g['rows']} tile da {t0['width']}x{t0['height']} non coprono "
                                   f"esattamente {g['output_width']}x{g['output_height']}.", METHOD, MODULE,
                                   confidence="media"))
        else:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Descrittore della griglia non leggibile",
                               "L'item 'grid' primario non ha dati validi.", METHOD, MODULE, confidence="alta",
                               significant=True))

    # Miniature, metadati, immagini ausiliarie
    thumbs = refs_to("thmb", prim)
    s["thumbnails"] = [{"item": t, "type": items.get(t, {}).get("type"),
                        "size": [(_prop(info, t, "ispe") or {}).get("width"),
                                 (_prop(info, t, "ispe") or {}).get("height")]} for t in thumbs]
    descr = refs_to("cdsc", prim)
    s["exif_items"] = [d for d in descr if items.get(d, {}).get("type") == "Exif"]
    s["xmp_items"] = [d for d in descr if items.get(d, {}).get("type") == "mime" and
                      "rdf+xml" in items[d]["content_type"]]
    orphan_exif = [i for i, it in items.items() if it["type"] == "Exif" and i not in descr]
    if orphan_exif:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Item Exif non collegato all'immagine principale",
                           f"Item Exif {orphan_exif} non referenziati con 'cdsc' dall'item primario.", METHOD,
                           MODULE, confidence="media",
                           limitations="Alcuni software collegano l'Exif alle tile o a un'altra immagine; "
                                       "confrontare con file di riferimento dello stesso dispositivo."))
    aux = []
    for a in refs_to("auxl", prim):
        c = _prop(info, a, "auxC")
        urn = c["aux_type"] if c else ""
        label = AUX_LABELS.get(urn) or ("ausiliaria Apple" if "com:apple" in urn else urn or "non specificata")
        e = _prop(info, a, "ispe") or {}
        aux.append({"item": a, "urn": urn, "label": label, "size": [e.get("width"), e.get("height")]})
    s["auxiliary"] = aux
    s["apple_auxiliary"] = any("com:apple" in a["urn"] for a in aux)

    # Posizione dei dati: extent fuori dal file, sovrapposti, item senza dati, byte non referenziati
    out_of_file, intervals = [], []
    for iid, loc in locs.items():
        if iid not in items:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dati per un item inesistente",
                               f"iloc descrive l'item {iid}, assente in iinf.", METHOD, MODULE, confidence="alta"))
            continue
        if loc["method"] != 0 or loc["data_ref"] != 0:
            continue
        for off, ln in loc["extents"]:
            ln = ln or max(size - off, 0)
            if off + ln > size:
                out_of_file.append((iid, off, ln))
            intervals.append((off, off + ln, iid))
    if out_of_file:
        iid, off, ln = out_of_file[0]
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Dati di item oltre la fine del file",
                           f"{len(out_of_file)} extent puntano oltre la fine del file ({size} byte): il file è "
                           "troncato o la tabella iloc non corrisponde al contenuto.", METHOD, MODULE,
                           evidence="\n".join(f"item {i} ({items[i]['type']}): offset {o}, {n} byte"
                                              for i, o, n in out_of_file[:20]),
                           offset=off, confidence="alta", significant=True))
    missing = [i for i, it in items.items() if it["type"] in IMAGE_TYPES - {"iden", "grid"} | {"Exif", "mime"}
               and i not in locs]
    if missing:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Item senza posizione dei dati",
                           f"Item {missing[:20]} dichiarati in iinf ma assenti in iloc.", METHOD, MODULE,
                           confidence="alta"))
    intervals.sort()
    overlaps = [(a, b) for a, b in zip(intervals, intervals[1:]) if b[0] < a[1] and a[2] != b[2]]
    if overlaps:
        a, b2 = overlaps[0]
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dati condivisi tra item diversi",
                           f"{len(overlaps)} sovrapposizioni tra extent di item diversi (prima: item {a[2]} e "
                           f"{b2[2]} a offset {b2[0]}).", METHOD, MODULE, offset=b2[0], confidence="media",
                           limitations="Insolito per un file scritto dalla fotocamera; possibile in file "
                                       "ottimizzati o riscritti da software."))
    mdats = []
    for n in res.root.children:
        if n.name == "mdat":
            fh.seek(n.offset)
            hl = 16 if struct.unpack(">I", fh.read(4))[0] == 1 else 8
            mdats.append((n.offset + hl, n.offset + n.length))
    gaps = []
    for ms, me in mdats:
        cur = ms
        for st, en, _ in intervals:
            if en <= ms or st >= me:
                continue
            if st > cur:
                gaps.append((cur, st - cur))
            cur = max(cur, en)
        if cur < me:
            gaps.append((cur, me - cur))
    if any(n.name == "moov" for n in res.root.children):
        gaps = []                   # in una sequenza i campioni della traccia stanno in mdat senza essere item
    unref = sum(g[1] for g in gaps)
    mdat_total = sum(me - ms for ms, me in mdats) or 1
    s["mdat_unreferenced_bytes"] = unref
    if unref > max(4096, mdat_total // 200):
        big = sorted(gaps, key=lambda g: -g[1])[:10]
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Dati non referenziati nel blocco mdat",
                           f"{unref} byte di 'mdat' non appartengono a nessun item: possono contenere dati residui "
                           "di una versione precedente o contenuti aggiunti.", METHOD, MODULE,
                           evidence="\n".join(f"offset 0x{o:X}: {n} byte" for o, n in big), offset=big[0][0],
                           confidence="bassa", significant=unref > 65536,
                           limitations="Alcuni encoder lasciano spazio di riempimento. Esaminare gli offset con "
                                       "l'Hex Viewer e la scansione delle firme incorporate."))

    dims = s.get("primary_size")
    desc = (f"Immagine principale: item {prim} di tipo '{ptype}'" + (f", {dims[0]}x{dims[1]}" if dims else "") +
            (f", griglia {s['grid']['columns']}x{s['grid']['rows']} tile" if s.get("grid") else "") +
            (f", rotazione {s['rotation_ccw']}°" if s["rotation_ccw"] else "") +
            f". Item per tipo: {', '.join(f'{k}={v}' for k, v in sorted(by_type.items()))}. "
            f"Miniature: {len(thumbs)}. Exif: {len(s['exif_items'])}. XMP: {len(s['xmp_items'])}. "
            f"Immagini ausiliarie: {', '.join(a['label'] for a in aux) or 'nessuna'}.")
    fnd.append(Finding(Category.FILE_STRUCTURE, Level.INFO, "Struttura HEIF", desc, METHOD, MODULE, data=s,
                       limitations="Le immagini ausiliarie Apple (gain map HDR, matte del Ritratto) sono scritte "
                                   "dalla pipeline della Fotocamera iOS: la loro presenza è coerente con uno scatto "
                                   "nativo, ma possono sopravvivere a strumenti che riscrivono solo i metadati; la "
                                   "loro assenza dipende anche da modello, versione di iOS e modalità di scatto."))
    return s
