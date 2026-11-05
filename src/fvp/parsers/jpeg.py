"""Parser della struttura JPEG (marker per marker) con stima della qualità di quantizzazione."""
from __future__ import annotations

from pathlib import Path

from ..core.findings import Category, Finding, Level
from .base import MAX_NODES, Node, ParseResult

MODULE = "parser.jpeg"

MARKERS = {
    0xD8: "SOI", 0xD9: "EOI", 0xDA: "SOS", 0xDB: "DQT", 0xC4: "DHT", 0xDD: "DRI", 0xFE: "COM",
    0xC0: "SOF0 (baseline)", 0xC1: "SOF1 (extended)", 0xC2: "SOF2 (progressive)", 0xC3: "SOF3 (lossless)",
    0xC5: "SOF5", 0xC6: "SOF6", 0xC7: "SOF7", 0xC9: "SOF9", 0xCA: "SOF10", 0xCB: "SOF11", 0xCD: "SOF13",
    0xCE: "SOF14", 0xCF: "SOF15", 0xCC: "DAC",
}
for _i in range(16):
    MARKERS[0xE0 + _i] = f"APP{_i}"

# Tabelle standard IJG (Annex K) in ordine naturale riga per riga
STD_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
            14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
            49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
STD_CHROMA = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99,
              47, 66, 99, 99, 99, 99, 99, 99] + [99] * 32
ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6,
          7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31,
          39, 46, 53, 60, 61, 54, 47, 55, 62, 63]


def ijg_table(std: list[int], q: int) -> list[int]:
    scale = 5000 // q if q < 50 else 200 - 2 * q
    return [min(max((v * scale + 50) // 100, 1), 255) for v in std]


def estimate_quality(table_natural: list[int], chroma: bool = False) -> tuple[int, float]:
    """Qualità IJG più vicina e scarto medio. Scarto 0 = tabella IJG esatta (tipica di libjpeg)."""
    std = STD_CHROMA if chroma else STD_LUMA
    best = (0, float("inf"))
    for q in range(1, 101):
        t = ijg_table(std, q)
        err = sum(abs(a - b) for a, b in zip(t, table_natural)) / 64
        if err < best[1]:
            best = (q, err)
    return best


def _app_kind(payload: bytes, n: int) -> str:
    if n == 0 and payload.startswith(b"JFIF\x00"):
        return "JFIF"
    if n == 0 and payload.startswith(b"JFXX\x00"):
        return "JFXX (thumbnail)"
    if n == 1 and payload.startswith(b"Exif\x00"):
        return "EXIF"
    if n == 1 and payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00"):
        return "XMP"
    if n == 1 and payload.startswith(b"http://ns.adobe.com/xmp/extension/\x00"):
        return "Extended XMP"
    if n == 2 and payload.startswith(b"ICC_PROFILE\x00"):
        return "ICC Profile"
    if n == 2 and payload.startswith(b"MPF\x00"):
        return "MPF (Multi-Picture)"
    if n == 11 and (b"jumb" in payload[:32] or b"c2pa" in payload[:64]):
        return "JUMBF (C2PA)"
    if n == 13 and payload.startswith(b"Photoshop 3.0\x00"):
        return "Photoshop IRB / IPTC"
    if n == 14 and payload.startswith(b"Adobe"):
        return "Adobe"
    return ""


def parse(path: str | Path) -> ParseResult:
    data = Path(path).read_bytes() if Path(path).stat().st_size < 512 * 1024 * 1024 else None
    if data is None:
        raise ValueError("File JPEG oltre 512 MB: analisi strutturale non supportata in questa versione")
    size = len(data)
    root = Node("JPEG", 0, size)
    fnd: list[Finding] = []
    extra: dict = {"qtables": {}, "app_segments": [], "sof": None, "scans": 0, "eoi_offset": None}
    if data[:2] != b"\xff\xd8":
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "SOI mancante",
                           "Il file non inizia con il marker SOI (FFD8).", "Parsing marker JPEG", MODULE,
                           offset=0, confidence="alta", significant=True))
        return ParseResult("jpeg", root, fnd, extra)
    root.children.append(Node("SOI", 0, 2))
    pos = 2
    seen_dqt: dict[int, int] = {}
    while pos < size:
        if len(root.children) > MAX_NODES:
            break
        if data[pos] != 0xFF:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Byte inatteso fra i segmenti",
                               f"Atteso un marker (FF) all'offset {pos}, trovato {data[pos]:02X}.",
                               "Parsing marker JPEG", MODULE, offset=pos, confidence="alta", significant=True))
            break
        while pos < size and data[pos] == 0xFF:
            pos += 1          # byte di riempimento
        if pos >= size:
            break
        m = data[pos]
        mstart = pos - 1
        pos += 1
        name = MARKERS.get(m, f"0xFF{m:02X}")
        if m == 0xD9:
            root.children.append(Node("EOI", mstart, 2))
            extra["eoi_offset"] = mstart
            pos = mstart + 2
            break
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            root.children.append(Node(name, mstart, 2))
            continue
        if pos + 2 > size:
            break
        seglen = int.from_bytes(data[pos:pos + 2], "big")
        if seglen < 2 or pos + seglen > size:
            fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "Segmento troncato o lunghezza non valida",
                               f"Il segmento {name} all'offset {mstart} dichiara {seglen} byte oltre la fine del file.",
                               "Parsing marker JPEG", MODULE, offset=mstart, confidence="alta", significant=True))
            break
        payload = data[pos + 2:pos + seglen]
        node = Node(name, mstart, seglen + 2)
        if 0xE0 <= m <= 0xEF:
            kind = _app_kind(payload, m - 0xE0)
            node.fields["tipo"] = kind or "non riconosciuto"
            extra["app_segments"].append({"marker": name, "offset": mstart, "length": seglen + 2, "kind": kind})
        elif m == 0xDB:
            p = 0
            while p < len(payload):
                pq, tq = payload[p] >> 4, payload[p] & 0x0F
                n = 128 if pq else 64
                vals_zz = list(payload[p + 1:p + 1 + n:2 if pq else 1]) if not pq else \
                    [int.from_bytes(payload[p + 1 + 2 * i:p + 3 + 2 * i], "big") for i in range(64)]
                natural = [0] * 64
                for i, v in enumerate(vals_zz[:64]):
                    natural[ZIGZAG[i]] = v
                q, err = estimate_quality(natural, chroma=tq > 0)
                if tq in seen_dqt:
                    node.fields.setdefault("ridefinizioni", []).append(tq)
                seen_dqt[tq] = mstart
                extra["qtables"][str(tq)] = {"values": natural, "ijg_quality": q, "ijg_error": round(err, 2),
                                             "offset": mstart}
                node.fields[f"tabella_{tq}"] = f"qualità IJG ~{q} (scarto {err:.2f})"
                p += 1 + n
        elif 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            if len(payload) >= 6:
                sof = {"type": name, "precision": payload[0], "height": int.from_bytes(payload[1:3], "big"),
                       "width": int.from_bytes(payload[3:5], "big"), "components": payload[5],
                       "sampling": [f"{payload[6 + 3 * i + 1] >> 4}x{payload[6 + 3 * i + 1] & 15}"
                                    for i in range(payload[5]) if 6 + 3 * i + 2 < len(payload)]}
                if extra["sof"]:
                    fnd.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Più marker SOF",
                                       "Il flusso principale contiene più di un frame header.", "Parsing marker JPEG",
                                       MODULE, offset=mstart, confidence="alta"))
                extra["sof"] = sof
                node.fields.update(sof)
        elif m == 0xFE:
            node.fields["testo"] = payload[:200].decode("latin-1", errors="replace")
        root.children.append(node)
        pos += seglen
        if m == 0xDA:
            extra["scans"] += 1
            # dati entropici: avanza fino a un marker diverso da 00 (stuffing) e RSTn
            p = pos
            while p < size - 1:
                if data[p] == 0xFF and data[p + 1] != 0x00 and not (0xD0 <= data[p + 1] <= 0xD7) and data[p + 1] != 0xFF:
                    break
                p += 1
            node.fields["dati_entropici"] = p - pos
            node.length += p - pos
            pos = p
            if p >= size - 1:
                break
    eoi = extra["eoi_offset"]
    if eoi is None:
        fnd.append(Finding(Category.FILE_STRUCTURE, Level.EVIDENCE, "EOI mancante: file troncato o incompleto",
                           "Il marker di fine immagine (FFD9) non è stato trovato dopo i dati compressi.",
                           "Parsing marker JPEG", MODULE, offset=size, confidence="alta",
                           limitations="Un file troncato può derivare da trasferimento interrotto o recupero "
                                       "parziale, non necessariamente da manipolazione.", significant=True))
    else:
        tail = size - (eoi + 2)
        if tail > 0:
            has_mpf = any(a["kind"].startswith("MPF") for a in extra["app_segments"])
            tail_bytes = data[eoi + 2:eoi + 2 + 16]
            embedded_jpeg = data.find(b"\xff\xd8\xff", eoi + 2) != -1
            only_zero = data[eoi + 2:].strip(b"\x00") == b""
            lvl = Level.INFO if (has_mpf and embedded_jpeg) or only_zero else Level.ANOMALY
            desc = (f"{tail} byte dopo il marker EOI all'offset {eoi}. "
                    + ("Il file dichiara un indice MPF: i dati sono compatibili con immagini secondarie "
                       "(es. anteprime o mappe di profondità)." if has_mpf and embedded_jpeg else
                       "Solo byte nulli (padding)." if only_zero else
                       "Dati non previsti dallo standard dopo la fine dell'immagine."))
            fnd.append(Finding(Category.FILE_STRUCTURE, lvl, "Dati dopo la fine dell'immagine (EOI)", desc,
                               "Parsing marker JPEG", MODULE, evidence=f"Primi byte: {tail_bytes.hex(' ')}",
                               offset=eoi + 2, confidence="alta",
                               limitations="Molti dispositivi accodano dati legittimi (MPF, Motion Photo, "
                                           "dati del produttore). Ispezionare con l'Hex Viewer.",
                               significant=lvl == Level.ANOMALY, data={"trailing_bytes": tail}))
            root.children.append(Node("Dati oltre EOI", eoi + 2, tail))
    luma = extra["qtables"].get("0")
    if luma:
        exact = luma["ijg_error"] == 0
        fnd.append(Finding(Category.IMAGE_MANIPULATION, Level.INFO, "Tabelle di quantizzazione",
                           f"Tabella luminanza più vicina a qualità IJG {luma['ijg_quality']} "
                           f"(scarto medio {luma['ijg_error']}). "
                           + ("Corrispondenza esatta con le tabelle IJG, tipica di librerie software (libjpeg) "
                              "e di alcuni dispositivi." if exact else
                              "Tabelle non IJG: tipiche di firmware di fotocamere o encoder proprietari."),
                           "Confronto con tabelle IJG Annex K", MODULE, offset=luma["offset"], confidence="media",
                           limitations="La tabella da sola non identifica il software; va confrontata con un "
                                       "database di firme di quantizzazione per marca e modello."))
    c2pa = [a for a in extra["app_segments"] if a["kind"] == "JUMBF (C2PA)"]
    if c2pa:
        fnd.append(Finding(Category.AI_GENERATION, Level.INFO, "Segmento JUMBF / C2PA presente",
                           "Il file contiene un contenitore JUMBF in APP11, usato dai Content Credentials (C2PA).",
                           "Parsing marker JPEG", MODULE, offset=c2pa[0]["offset"], confidence="alta",
                           limitations="Presenza rilevata, validazione crittografica del manifest non ancora "
                                       "implementata in questa versione."))
    return ParseResult("jpeg", root, fnd, extra)
