"""StegoIntelligence: rilevamento ed estrazione di informazioni nascoste.

Implementa in modo nativo le tecniche catalogate dal progetto StegoIntelligence (CScorza), che documenta la
steganografia su immagini, audio e file e gli strumenti per analizzarla (Stegsolve, StegoVeritas, zsteg, OpenStego):

- piani di bit per canale (come Stegsolve), calcolati al volo dall'interfaccia;
- estrazione del flusso LSB in 56 combinazioni di canali, bit, ordine dei pixel e ordine dei bit (come zsteg e
  StegoVeritas), con ricerca di firme di file, testo leggibile, messaggi con prefisso di lunghezza e firme di
  strumenti noti (OpenStego);
- lo stesso per i campioni PCM dei file audio WAV;
- i dati accodati e i file incorporati sono già rilevati dai moduli struttura e firme.

L'estrazione legge solo la copia di lavoro; i contenuti estratti sono salvati tra gli artefatti del caso con il
loro SHA-256. Messaggi cifrati o inseriti con password (Steghide, OutGuess, OpenStego con cifratura) non sono
riconoscibili in questo modo.
"""
from __future__ import annotations

import hashlib
import itertools
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from ..core.findings import Category, Finding, Level

MODULE = "stegointel"
SCAN_BYTES = 64 * 1024
MAGICS = [
    (b"PK\x03\x04", "zip", "Archivio ZIP"), (b"\x89PNG\r\n\x1a\n", "png", "Immagine PNG"),
    (b"\xff\xd8\xff", "jpg", "Immagine JPEG"), (b"GIF8", "gif", "Immagine GIF"), (b"%PDF-", "pdf", "Documento PDF"),
    (b"7z\xbc\xaf\x27\x1c", "7z", "Archivio 7-Zip"), (b"Rar!\x1a\x07", "rar", "Archivio RAR"),
    (b"\x1f\x8b\x08", "gz", "Archivio gzip"), (b"\x7fELF", "elf", "Eseguibile ELF"),
    (b"RIFF", "riff", "Contenitore RIFF (WAV/AVI/WebP)"), (b"OggS", "ogg", "Contenitore Ogg"),
    (b"ID3", "mp3", "Audio MP3 (ID3)"), (b"-----BEGIN PGP", "asc", "Blocco PGP"), (b"Salted__", "enc", "Dati cifrati OpenSSL"),
]
TOOL_STAMPS = [(b"OPENSTEGO", "OpenStego")]
PRINTABLE = set(range(32, 127)) | {9, 10, 13}


def to_array(path) -> np.ndarray:
    with Image.open(path) as im:
        im.load()
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            return np.asarray(im.convert("RGBA"))
        return np.asarray(im.convert("RGB"))


def bit_plane(arr: np.ndarray, channel: str, bit: int) -> np.ndarray:
    """Piano di bit come immagine in bianco e nero. channel: R, G, B, A o L (luminanza)."""
    if channel == "L":
        ch = np.asarray(Image.fromarray(arr[:, :, :3]).convert("L"))
    else:
        idx = "RGBA".index(channel)
        if idx >= arr.shape[2]:
            return np.zeros(arr.shape[:2], np.uint8)
        ch = arr[:, :, idx]
    return (((ch >> bit) & 1) * 255).astype(np.uint8)


def extract(arr: np.ndarray, channels: str, nbits: int, order: str, msb_first: bool, limit: int = SCAN_BYTES) -> bytes:
    """Flusso dei bit meno significativi. order 'xy' = per righe, 'yx' = per colonne."""
    idx = ["RGBA".index(c) for c in channels]
    a = arr if order == "xy" else arr.transpose(1, 0, 2)
    need_bits = limit * 8
    per_pixel = len(idx) * nbits
    npx = min(a.shape[0] * a.shape[1], need_bits // per_pixel + 1)
    px = a.reshape(-1, a.shape[2])[:npx][:, idx]                       # pixel x canali
    bits = np.stack([(px >> b) & 1 for b in range(nbits - 1, -1, -1)], axis=-1)   # bit alti prima
    stream = bits.reshape(-1)[:need_bits]
    stream = stream[: (len(stream) // 8) * 8]
    return np.packbits(stream, bitorder="big" if msb_first else "little").tobytes()


WORD = __import__("re").compile(rb"[A-Za-z\xc0-\xff]{3,}")
B64 = __import__("re").compile(rb"[A-Za-z0-9+/]{24,}={0,2}")


def _is_text(s: bytes, min_len: int = 16) -> bool:
    """Testo in linguaggio naturale: abbastanza lungo, vario, fatto soprattutto di lettere e spazi, con parole."""
    if len(s) < min_len or len(set(s)) < 8:
        return False
    from collections import Counter
    if Counter(s).most_common(1)[0][1] / len(s) > 0.25:          # zone uniformi: "UUUUUUUU…"
        return False
    if __import__("re").search(rb"(.)\1{4,}", s):                 # nessun carattere ripetuto più di 4 volte di fila
        return False
    letters = [c for c in s if chr(c).isalpha()]
    if (sum(chr(c).isalpha() or c == 32 for c in s) / len(s) < 0.75 or len(WORD.findall(s)) < 2 or not letters):
        return False
    vowels = sum(chr(c).lower() in "aeiouàèéìòù" for c in letters) / len(letters)
    return 0.2 <= vowels <= 0.7 and (32 in s or len(s) >= 24)


def _printable_runs(data: bytes, min_len: int = 16):
    start = None
    for i, b in enumerate(data):
        if b in PRINTABLE:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_len:
                yield start, data[start:i]
            start = None
    if start is not None and len(data) - start >= min_len:
        yield start, data[start:]


def _length_prefixed(data: bytes) -> tuple[int, str] | None:
    """Messaggio preceduto dalla sua lunghezza su 1, 2, 4 o 8 byte (big o little endian), eventualmente dopo zeri."""
    lead = len(data) - len(data.lstrip(b"\x00"))
    for width in (8, 4, 2):
        for endian in ("big", "little"):
            for start in {0, max(0, lead - (lead % width))}:
                if start + width >= len(data):
                    continue
                n = int.from_bytes(data[start:start + width], endian)
                body = data[start + width:start + width + n]
                if 8 <= n <= 1_000_000 and len(body) == n and _is_text(body.rstrip(b"\x00\n\r"), 8):
                    return start, body.decode("utf-8", errors="replace")
    return None


def _find_text(data: bytes) -> tuple[int, str, str] | None:
    """Testo leggibile in qualunque punto del flusso, o un blocco Base64 che si decodifica in testo o in un file."""
    best = None
    for off, run in _printable_runs(data[:SCAN_BYTES]):
        if _is_text(run):
            if best is None or len(run) > len(best[1]):
                best = (off, run.decode("ascii", errors="replace"), "Testo nascosto")
        else:
            for m in B64.finditer(run):
                import base64
                import binascii
                blob = m.group(0)
                for shift in range(4):          # il blocco può essere preceduto da caratteri estranei
                    core = blob[shift:].rstrip(b"=")
                    if len(core) % 4 == 1:
                        continue
                    part = core + b"=" * (-len(core) % 4)
                    try:
                        dec = base64.b64decode(part, validate=True)
                    except (binascii.Error, ValueError):
                        continue
                    if _is_text(dec, 8) or any(dec.startswith(mg) for mg, _, _ in MAGICS):
                        best = best or (off + m.start() + shift, part.decode() + "\n\n[decodificato]\n" +
                                        dec[:4000].decode("utf-8", errors="replace"), "Testo nascosto codificato in Base64")
                        break
    return best


def analyze_stream(data: bytes) -> dict | None:
    for stamp, tool in TOOL_STAMPS:
        i = data.find(stamp)
        if 0 <= i < 64:
            return {"type": "firma_strumento", "detail": f"Intestazione {tool}", "offset": i, "ext": "bin"}
    lead = len(data) - len(data.lstrip(b"\x00"))
    for magic, ext, name in MAGICS:
        if data.startswith(magic) or (0 < lead <= 16 and data[lead:].startswith(magic) and len(magic) >= 4):
            return {"type": "file", "detail": name, "offset": 0 if data.startswith(magic) else lead, "ext": ext}
    if data[:2] == b"MZ" and len(data) > 0x40:
        e = int.from_bytes(data[0x3C:0x40], "little")
        if 0 < e < len(data) - 4 and data[e:e + 4] == b"PE\x00\x00":
            return {"type": "file", "detail": "Eseguibile Windows (PE)", "offset": 0, "ext": "exe.bin"}
    lp = _length_prefixed(data)
    t = _find_text(data)
    if lp and not (t and t[0] <= lp[0] and len(t[1]) >= len(lp[1])):
        return {"type": "testo", "detail": "Testo nascosto (preceduto dalla sua lunghezza)", "offset": lp[0], "ext": "txt",
                "text": lp[1]}
    if t:
        return {"type": "testo", "detail": t[2], "offset": t[0], "ext": "txt", "text": t[1]}
    return None


def combos(has_alpha: bool):
    chans = ["R", "G", "B", "RGB", "BGR"] + (["A", "RGBA"] if has_alpha else [])
    return itertools.product(chans, (1, 2), ("xy", "yx"), (True, False))


def scan_image(path) -> list[dict]:
    arr = to_array(path)
    hits = []
    for ch, nb, order, msb in combos(arr.shape[2] == 4):
        data = extract(arr, ch, nb, order, msb)
        h = analyze_stream(data)
        if h:
            h.update({"channels": ch, "bits": nb, "order": order, "msb_first": msb})
            hits.append(h)
    return hits


def wav_samples(path) -> np.ndarray | None:
    with wave.open(str(path), "rb") as w:
        sw, n = w.getsampwidth(), w.getnframes() * w.getnchannels()
        raw = w.readframes(w.getnframes())
    if sw == 1:
        return np.frombuffer(raw, np.uint8)[:n]
    if sw == 2:
        return np.frombuffer(raw, "<i2")[:n].astype(np.int32) & 0xFFFF
    return None


def scan_wav(path) -> list[dict]:
    s = wav_samples(path)
    if s is None:
        return []
    hits = []
    for nb, msb in itertools.product((1, 2), (True, False)):
        bits = np.stack([(s >> b) & 1 for b in range(nb - 1, -1, -1)], axis=-1).reshape(-1)[:SCAN_BYTES * 8]
        bits = bits[: (len(bits) // 8) * 8].astype(np.uint8)
        data = np.packbits(bits, bitorder="big" if msb else "little").tobytes()
        h = analyze_stream(data)
        if h:
            h.update({"channels": "campioni PCM", "bits": nb, "order": "temporale", "msb_first": msb})
            hits.append(h)
    return hits


def carve(data: bytes, ext: str) -> bytes:
    """Taglia il flusso estratto alla fine strutturale del file, quando il formato la rende determinabile."""
    end = None
    if ext == "zip":
        i = data.rfind(b"PK\x05\x06")
        while i != -1:
            clen = int.from_bytes(data[i + 20:i + 22], "little")
            cd_size = int.from_bytes(data[i + 12:i + 16], "little")
            cd_off = int.from_bytes(data[i + 16:i + 20], "little")
            if cd_off + cd_size == i:           # record di fine coerente con la directory centrale
                end = i + 22 + clen
                break
            i = data.rfind(b"PK\x05\x06", 0, i)
    elif ext == "png":
        i = data.find(b"IEND")
        end = i + 8 if i != -1 else None
    elif ext == "jpg":
        i = data.find(b"\xff\xd9")
        end = i + 2 if i != -1 else None
    elif ext == "pdf":
        i = data.find(b"%%EOF")
        end = i + 5 if i != -1 else None
    elif ext == "gif":
        i = data.find(b"\x00;")
        end = i + 2 if i != -1 else None
    return data[:end] if end else data


def _save(hit: dict, data: bytes, out_dir, i: int) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    is_text = "text" in hit
    payload = hit.pop("text").encode() if is_text else carve(data[hit["offset"]:], hit["ext"])
    hit["carved"] = not is_text and hit["ext"] in ("zip", "png", "jpg", "pdf", "gif")
    name = f"lsb_{i:02d}_{hit['channels']}_{hit['bits']}b_{hit['order']}_{'msb' if hit['msb_first'] else 'lsb'}.{hit['ext']}"
    p = out_dir / name.replace(" ", "_")
    p.write_bytes(payload)
    hit.update({"file": str(p), "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "preview": payload[:120].decode("latin-1").translate({c: "·" for c in range(32) if c not in (9, 10)})})


def analyze(path, fmt: str | None, out_dir: Path | None = None) -> tuple[dict, list[Finding]]:
    meth = "StegoIntelligence: estrazione LSB multi-combinazione e ricerca di firme e testo"
    lim = ("Rileva contenuti in chiaro (testo, file, intestazioni di strumenti) inseriti nei bit meno significativi. "
           "Contenuti cifrati, compressi senza intestazione o inseriti con password (Steghide, OutGuess, OpenStego "
           "con cifratura) appaiono come dati casuali e non sono riconoscibili. Non analizza il dominio DCT dei JPEG.")
    if fmt == "wav":
        try:
            hits, scope = scan_wav(path), "campioni audio PCM (4 combinazioni)"
        except (wave.Error, EOFError) as e:
            return {}, [Finding(Category.STEGANOGRAPHY, Level.UNDETERMINED, "StegoIntelligence: WAV non leggibile",
                                f"Formato audio non supportato ({e}): sono gestiti PCM a 8 e 16 bit.", meth, MODULE)]
        arr = None
    elif fmt in ("png", "bmp", "tiff", "gif", "webp"):
        arr = to_array(path)
        hits, scope = scan_image(path), f"piani LSB ({len(list(combos(arr.shape[2] == 4)))} combinazioni)"
    else:
        return {}, [Finding(Category.STEGANOGRAPHY, Level.UNDETERMINED, "StegoIntelligence: formato non analizzabile",
                            f"L'estrazione LSB si applica a immagini senza perdita e audio WAV; il formato è "
                            f"{fmt or 'sconosciuto'}.", meth, MODULE, limitations=lim)]
    if out_dir and hits:
        for i, h in enumerate(hits):
            if arr is not None:
                data = extract(arr, h["channels"], h["bits"], h["order"], h["msb_first"], limit=4 * 1024 * 1024)
            else:
                s = wav_samples(path)
                bits = np.stack([(s >> b) & 1 for b in range(h["bits"] - 1, -1, -1)], axis=-1).reshape(-1)
                bits = bits[: (len(bits) // 8) * 8].astype(np.uint8)
                data = np.packbits(bits, bitorder="big" if h["msb_first"] else "little").tobytes()
            _save(h, data, out_dir, i)
    res = {"scope": scope, "hits": hits}
    if not hits:
        return res, [Finding(Category.STEGANOGRAPHY, Level.INFO, "StegoIntelligence: nessun contenuto in chiaro",
                             f"Nessuna firma di file, testo leggibile o intestazione di strumenti nei {scope}.", meth,
                             MODULE, limitations=lim)]
    out = []
    for h in hits:
        combo = (f"canali {h['channels']}, {h['bits']} bit, ordine {h['order']}, "
                 f"{'MSB' if h['msb_first'] else 'LSB'} prima")
        out.append(Finding(Category.STEGANOGRAPHY, Level.EVIDENCE if h["type"] != "testo" else Level.ANOMALY,
                           f"Contenuto nascosto estratto: {h['detail']}",
                           f"Il flusso dei bit meno significativi ({combo}) contiene {h['detail'].lower()}"
                           + (f" a partire dal byte {h['offset']} del flusso" if h.get("offset") else "")
                           + (f"; estratto e salvato ({h['size']:,} byte, SHA-256 {h['sha256'][:16]}…)." if "file" in h else "."),
                           meth, MODULE, evidence=h.get("preview", ""), confidence="alta" if h["type"] != "testo" else "media",
                           significant=True, limitations=lim, data=h))
    return res, out
