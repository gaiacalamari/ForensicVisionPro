"""Identificazione del formato effettivo (magic bytes) e File Signature Scanner."""
from __future__ import annotations

import mmap
import os
from dataclasses import dataclass
from pathlib import Path

from ..core.findings import Category, Finding, Level
from ..core.tasks import CancelToken, ProgressFn, noop_progress

MODULE = "signature"


@dataclass(frozen=True)
class FormatInfo:
    key: str
    name: str
    mime: str
    extensions: tuple[str, ...]


FORMATS = {
    "jpeg": FormatInfo("jpeg", "JPEG/JFIF", "image/jpeg", (".jpg", ".jpeg", ".jpe", ".jfif")),
    "png": FormatInfo("png", "PNG", "image/png", (".png",)),
    "gif": FormatInfo("gif", "GIF", "image/gif", (".gif",)),
    "tiff": FormatInfo("tiff", "TIFF", "image/tiff", (".tif", ".tiff", ".dng", ".nef", ".cr2", ".arw")),
    "bmp": FormatInfo("bmp", "BMP", "image/bmp", (".bmp",)),
    "webp": FormatInfo("webp", "WebP", "image/webp", (".webp",)),
    "heif": FormatInfo("heif", "HEIF/HEIC", "image/heic", (".heic", ".heif", ".hif")),
    "avif": FormatInfo("avif", "AVIF", "image/avif", (".avif",)),
    "mp4": FormatInfo("mp4", "MP4 (ISO BMFF)", "video/mp4", (".mp4", ".m4v", ".m4a")),
    "mov": FormatInfo("mov", "QuickTime MOV", "video/quicktime", (".mov", ".qt")),
    "3gp": FormatInfo("3gp", "3GPP", "video/3gpp", (".3gp", ".3g2")),
    "avi": FormatInfo("avi", "AVI (RIFF)", "video/x-msvideo", (".avi",)),
    "wav": FormatInfo("wav", "WAV (RIFF)", "audio/wav", (".wav",)),
    "mkv": FormatInfo("mkv", "Matroska", "video/x-matroska", (".mkv", ".mka")),
    "webm": FormatInfo("webm", "WebM", "video/webm", (".webm",)),
    "mpeg_ps": FormatInfo("mpeg_ps", "MPEG Program Stream", "video/mpeg", (".mpg", ".mpeg", ".vob")),
    "mpeg_ts": FormatInfo("mpeg_ts", "MPEG Transport Stream", "video/mp2t", (".ts", ".mts", ".m2ts")),
    "m2ts": FormatInfo("m2ts", "BDAV MPEG-2 TS (192 byte)", "video/mp2t", (".m2ts", ".mts")),
    "mp3": FormatInfo("mp3", "Audio MP3", "audio/mpeg", (".mp3",)),
    "flac": FormatInfo("flac", "Audio FLAC", "audio/flac", (".flac",)),
    "ogg": FormatInfo("ogg", "Contenitore Ogg", "audio/ogg", (".ogg", ".oga", ".opus")),
    "aac": FormatInfo("aac", "Audio AAC (ADTS)", "audio/aac", (".aac",)),
    "pdf": FormatInfo("pdf", "PDF", "application/pdf", (".pdf",)),
    "zip": FormatInfo("zip", "ZIP", "application/zip", (".zip", ".docx", ".xlsx", ".pptx", ".apk", ".jar")),
    "rar": FormatInfo("rar", "RAR", "application/vnd.rar", (".rar",)),
    "7z": FormatInfo("7z", "7-Zip", "application/x-7z-compressed", (".7z",)),
    "pe": FormatInfo("pe", "Eseguibile Windows (MZ)", "application/x-msdownload", (".exe", ".dll")),
    "elf": FormatInfo("elf", "ELF", "application/x-elf", ("",)),
}

_FTYP_BRANDS = {
    "qt  ": "mov", "heic": "heif", "heix": "heif", "hevc": "heif", "mif1": "heif", "msf1": "heif",
    "avif": "avif", "3gp4": "3gp", "3gp5": "3gp", "3gp6": "3gp", "3g2a": "3gp",
}


def identify_bytes(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:2] == b"BM" and len(head) >= 14:
        return "bmp"
    if head[:4] == b"RIFF" and len(head) >= 12:
        return {b"WEBP": "webp", b"AVI ": "avi", b"WAVE": "wav"}.get(head[8:12])
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12].decode("latin-1")
        return _FTYP_BRANDS.get(brand, "mp4")
    if len(head) >= 8 and head[4:8] in (b"moov", b"mdat", b"wide", b"free", b"skip"):
        return "mov"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm" if b"webm" in head[:64] else "mkv"
    if head.startswith(b"\x00\x00\x01\xba"):
        return "mpeg_ps"
    if len(head) >= 377 and head[0] == 0x47 and head[188] == 0x47 and head[376] == 0x47:
        return "mpeg_ts"
    if len(head) >= 389 and head[4] == 0x47 and head[196] == 0x47 and head[388] == 0x47:
        return "m2ts"
    if head.startswith(b"ID3") and len(head) > 5 and head[3] in (2, 3, 4):
        return "mp3"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"OggS"):
        return "ogg"
    if len(head) >= 4 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:
        return "aac"
    if len(head) >= 4 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] >> 1) & 3 != 0 \
            and (head[2] >> 4) not in (0, 15) and ((head[2] >> 2) & 3) != 3:
        return "mp3"            # frame MPEG audio senza tag ID3
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"MZ"):
        return "pe"
    if head.startswith(b"\x7fELF"):
        return "elf"
    return None


def identify(path: str | Path) -> dict:
    p = Path(path)
    with open(p, "rb") as fh:
        head = fh.read(512)
    key = identify_bytes(head)
    fi = FORMATS.get(key) if key else None
    ext = p.suffix.lower()
    return {
        "name": p.name, "extension": ext, "size": p.stat().st_size,
        "magic_hex": head[:16].hex(" "), "format": key, "format_name": fi.name if fi else "sconosciuto",
        "mime": fi.mime if fi else "application/octet-stream",
        "extension_matches": bool(fi and (ext in fi.extensions)),
    }


def findings_for(info: dict) -> list[Finding]:
    out: list[Finding] = []
    if info["format"] is None:
        out.append(Finding(Category.FILE_STRUCTURE, Level.UNDETERMINED, "Formato non riconosciuto",
                           "I primi byte non corrispondono ad alcuna firma nota al modulo.", "Confronto magic bytes",
                           MODULE, evidence=f"Header: {info['magic_hex']}", offset=0,
                           limitations="La tabella delle firme copre i formati multimediali principali e alcuni "
                                       "contenitori comuni."))
    elif not info["extension_matches"]:
        out.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Estensione non coerente con il contenuto",
                           f"L'estensione '{info['extension']}' non corrisponde al formato effettivo "
                           f"{info['format_name']}.", "Confronto magic bytes / estensione", MODULE,
                           evidence=f"Header: {info['magic_hex']}", offset=0, confidence="alta",
                           limitations="Una ridenominazione può essere innocua (es. salvataggio da browser): "
                                       "va valutata nel contesto.", significant=True))
    return out


# ---------- File Signature Scanner (ricerca di firme incorporate, read-only) ----------
SCAN_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff\xe0", "JPEG (JFIF)"), (b"\xff\xd8\xff\xe1", "JPEG (EXIF)"), (b"\xff\xd8\xff\xdb", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"), (b"GIF89a", "GIF"), (b"GIF87a", "GIF"), (b"%PDF-", "PDF"),
    (b"PK\x03\x04", "ZIP"), (b"Rar!\x1a\x07", "RAR"), (b"7z\xbc\xaf\x27\x1c", "7-Zip"),
    (b"ftypisom", "MP4"), (b"ftypmp42", "MP4"), (b"ftypqt  ", "QuickTime"), (b"ftypheic", "HEIC"),
    (b"\x1a\x45\xdf\xa3", "Matroska/WebM"), (b"RIFF", "RIFF"), (b"MZ\x90\x00", "PE (MZ)"),
    (b"\x7fELF", "ELF"), (b"OggS", "Ogg"), (b"ID3", "MP3 (ID3)"),
]


def validate(b: bytes, name: str, remaining: int) -> bool:
    """Verifica che dopo la firma ci sia una struttura plausibile: le firme brevi compaiono per caso nei dati."""
    try:
        if name == "ZIP":
            ver, method = int.from_bytes(b[4:6], "little"), int.from_bytes(b[8:10], "little")
            nlen = int.from_bytes(b[26:28], "little")
            return ver <= 63 and method in (0, 1, 6, 8, 9, 12, 14, 93, 95, 98, 99) and 0 < nlen <= 512
        if name == "RIFF":
            size = int.from_bytes(b[4:8], "little")
            return 12 <= size + 8 <= remaining + 8 and b[8:12] in (b"WAVE", b"AVI ", b"WEBP", b"RMID", b"ACON")
        if name == "MP3 (ID3)":
            return b[3] in (2, 3, 4) and b[4] == 0 and all(x < 0x80 for x in b[6:10])
        if name == "Ogg":
            return b[4] == 0 and b[5] in (0, 1, 2, 4, 5, 6, 7)
        if name == "Matroska/WebM":
            return b"webm" in b[:64] or b"matroska" in b[:64] or b[4] & 0x80 != 0
        if name == "PDF":
            return b[5:7] in (b"1.", b"2.")
        if name.startswith("JPEG"):
            return len(b) > 4 and b[3] in (0xE0, 0xE1, 0xDB, 0xEE, 0xE2, 0xC0, 0xC4)
        if name == "GIF":
            return len(b) >= 10
    except IndexError:
        return False
    return True       # firme lunghe (PNG, 7z, RAR, ftyp, ELF, PE già verificato) sono affidabili


def scan_signatures(path: str | Path, progress: ProgressFn = noop_progress, cancel: CancelToken | None = None,
                    limit: int = 5000) -> list[dict]:
    """Cerca firme note in tutto il file tramite mmap read-only (anche file molto grandi)."""
    size = os.path.getsize(path)
    hits: list[dict] = []
    if size == 0:
        return hits
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        step = 64 * 1024 * 1024
        for sig, name in SCAN_SIGNATURES:
            pos = 0
            while len(hits) < limit:
                if cancel:
                    cancel.check()
                i = mm.find(sig, pos, min(size, pos + step + len(sig)))
                if i == -1:
                    if pos + step >= size:
                        break
                    pos += step
                    continue
                if name == "PE (MZ)" and i + 0x40 <= size:
                    e = int.from_bytes(mm[i + 0x3C:i + 0x40], "little")
                    if not (0 < e < 4096 and i + e + 4 <= size and mm[i + e:i + e + 4] == b"PE\x00\x00"):
                        pos = i + 1
                        continue
                off = i - 4 if sig.startswith(b"ftyp") else i
                hits.append({"offset": off, "signature": name, "hex": bytes(mm[off:off + 16]).hex(" "),
                             "valid": validate(bytes(mm[off:off + 64]), name, size - off)})
                pos = i + 1
            progress(1.0, "Scansione firme")
    hits.sort(key=lambda h: h["offset"])
    return hits
