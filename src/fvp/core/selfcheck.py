"""Controllo automatico di dipendenze e strumenti.

Eseguito all'avvio dell'interfaccia, dalla pagina Settings e dalla build (`ForensicVisionPro.exe --selfcheck`).
Ogni strumento esterno è verificato con una prova reale (non solo la presenza del file), e gli eseguibili
installati da tools/fetch_tools.py sono confrontati con gli hash registrati in bin/tools.lock.json.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .tools import _bundled_dir, get_tool

CRITICAL, OPTIONAL = "essenziale", "facoltativo"


@dataclass
class Check:
    name: str
    level: str
    ok: bool
    detail: str
    version: str = ""


def _pkg(name: str, module: str, attr: str = "__version__") -> Check:
    try:
        m = importlib.import_module(module)
        return Check(name, CRITICAL, True, "importato", str(getattr(m, attr, "")))
    except Exception as e:  # noqa: BLE001
        return Check(name, CRITICAL, False, f"non importabile: {e}")


def _exiftool(settings: Settings, tmp: Path) -> Check:
    t = get_tool("exiftool", settings.exiftool_path)
    if not t:
        return Check("ExifTool", CRITICAL, False, "non trovato: metadati XMP, IPTC, MakerNotes, video e miniature non "
                                                  "disponibili")
    from PIL import Image
    p = tmp / "probe.jpg"
    ex = Image.Exif()
    ex[0x010F] = "SelfCheck"
    Image.new("RGB", (16, 16), (120, 130, 140)).save(p, "JPEG", exif=ex.tobytes())
    from ..engines import metadata
    m = metadata.extract(p, settings.exiftool_path, 60)
    ok = not m.get("limited") and any(x["tag"] == "Make" and x["value"] == "SelfCheck" for x in m["tags"])
    return Check("ExifTool", CRITICAL, ok, f"{t.path}" if ok else f"esecuzione non riuscita: {m.get('tool')}", t.version)


def _ffprobe(settings: Settings, tmp: Path) -> Check:
    t = get_tool("ffprobe", settings.ffprobe_path)
    if not t:
        return Check("FFprobe", CRITICAL, False, "non trovato: analisi video non disponibile")
    p = tmp / "probe.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)
    from ..engines import video
    try:
        s = video.summarize(video.probe(p, settings.ffprobe_path, 60))
        ok = any(x["type"] == "audio" for x in s["streams"])
        return Check("FFprobe", CRITICAL, ok, t.path if ok else "risposta inattesa", t.version[:60])
    except Exception as e:  # noqa: BLE001
        return Check("FFprobe", CRITICAL, False, f"esecuzione non riuscita: {e}", t.version[:60])


def _ffmpeg(settings: Settings) -> Check:
    t = get_tool("ffmpeg", settings.ffmpeg_path)
    return Check("FFmpeg", OPTIONAL, bool(t), t.path if t else "non trovato: usato solo per generare il dataset di prova",
                 t.version[:60] if t else "")


def _bundle_integrity() -> list[Check]:
    lock = _bundled_dir() / "tools.lock.json"
    if not lock.exists():
        return []
    out = []
    for name, info in json.loads(lock.read_text(encoding="utf-8")).items():
        bad = [f for f, h in info.get("file_hashes", {}).items()
               if not (_bundled_dir() / f).is_file() or
               hashlib.sha256((_bundled_dir() / f).read_bytes()).hexdigest() != h]
        out.append(Check(f"Integrità binari {name}", CRITICAL, not bad,
                         "corrispondono a tools.lock.json" if not bad else f"modificati o mancanti: {', '.join(bad)}",
                         info.get("version", "")))
    return out


def _writable(name: str, path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".fvp_write_test"
        probe.write_text("ok")
        probe.unlink()
        free = shutil.disk_usage(path).free / 1e9
        return Check(name, CRITICAL, True, f"{path} ({free:.1f} GB liberi)" + (" — spazio scarso" if free < 2 else ""))
    except OSError as e:
        return Check(name, CRITICAL, False, f"{path}: non scrivibile ({e})")


def _heif(tmp: Path) -> Check:
    """Decodifica reale di un HEIC generato al momento (verifica libheif + libde265 inclusi nella build)."""
    try:
        import pillow_heif
        from PIL import Image

        from ..engines import heif_support
        if not heif_support.ensure_registered():
            return Check("Decoder HEIF/HEIC (pillow-heif)", CRITICAL, False, "registrazione non riuscita")
        f = tmp / "selfcheck.heic"
        Image.new("RGB", (64, 48), (200, 30, 30)).save(f, quality=90)
        with Image.open(f) as im:
            im.load()
            ok = im.size == (64, 48) and im.getpixel((10, 10))[0] > 150
        return Check("Decoder HEIF/HEIC (pillow-heif)", CRITICAL, ok, "decodifica verificata" if ok else
                     "decodifica errata", f"{pillow_heif.__version__} / libheif {pillow_heif.libheif_version()}")
    except Exception as e:  # noqa: BLE001
        return Check("Decoder HEIF/HEIC (pillow-heif)", CRITICAL, False, f"{type(e).__name__}: {e}")


def run(settings: Settings | None = None) -> list[Check]:
    settings = settings or Settings.load()
    checks = [_pkg("Qt (PySide6)", "PySide6"), _pkg("Pillow", "PIL"), _pkg("NumPy", "numpy"),
              _pkg("OpenCV", "cv2")]
    try:
        import cv2
        cv2.SIFT_create()
        checks.append(Check("OpenCV SIFT (copy-move)", CRITICAL, True, "disponibile"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("OpenCV SIFT (copy-move)", CRITICAL, False, str(e)))
    try:
        import cv2
        casc = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        checks.append(Check("Rilevatore volti (Haar)", OPTIONAL, casc.is_file(),
                            "disponibile" if casc.is_file() else f"file mancante: {casc}"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("Rilevatore volti (Haar)", OPTIONAL, False, str(e)))
    with tempfile.TemporaryDirectory() as td:
        checks += [_exiftool(settings, Path(td)), _ffprobe(settings, Path(td)), _heif(Path(td))]
    checks.append(_ffmpeg(settings))
    checks += _bundle_integrity()
    checks += [_writable("Cartella dei casi", settings.cases_path), _writable("Archivio impronte PRNU", settings.prnu_path)]
    return checks


def summary(checks: list[Check]) -> tuple[bool, list[Check]]:
    failed = [c for c in checks if not c.ok and c.level == CRITICAL]
    return not failed, failed


def write_report(checks: list[Check], out: str | os.PathLike) -> None:
    ok, _ = summary(checks)
    Path(out).write_text(json.dumps({"ok": ok, "checks": [asdict(c) for c in checks]}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
