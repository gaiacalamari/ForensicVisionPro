"""Crediti e licenze dei componenti di terze parti: un solo registro usato da riga di comando (--credits),
interfaccia (Impostazioni), report HTML, raccolta delle licenze per la build (tools/collect_licenses.py) e test.

Per aggiungere un componente: aggiungere una voce qui e in THIRD_PARTY_NOTICES.md. I test verificano che ogni
pacchetto di requirements.txt e ogni strumento di bin/tools.json abbia una voce, e che ogni voce compaia nelle note.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

RUNTIME, TOOL, MODEL, METHOD, BUILD = ("Incluso nel programma", "Strumento esterno incluso", "Modello",
                                        "Metodologia o fonte", "Solo sviluppo e build")


@dataclass(frozen=True)
class Credit:
    name: str
    authors: str
    kind: str
    use: str
    license: str
    url: str
    packages: tuple[str, ...] = ()      # nomi pip (requirements.txt)
    tools: tuple[str, ...] = ()         # nomi in bin/tools.json
    license_files: tuple[str, ...] = field(default=())   # testi in licenses/ da distribuire
    source: str = ""                    # dove ottenere il sorgente (licenze copyleft)


CREDITS: list[Credit] = [
    Credit("Python", "Python Software Foundation", RUNTIME, "Interprete incluso nell'eseguibile", "PSF-2.0",
           "https://www.python.org/"),
    Credit("Qt for Python (PySide6, Shiboken6) e Qt", "The Qt Company", RUNTIME, "Interfaccia grafica",
           "LGPL-3.0-only", "https://www.qt.io/qt-for-python", ("PySide6",), (), ("LGPL-3.0.txt", "GPL-3.0.txt"),
           "https://download.qt.io/official_releases/QtForPython/"),
    Credit("Pillow", "Jeffrey A. Clark e collaboratori; PIL di Fredrik Lundh", RUNTIME,
           "Decodifica delle immagini, ELA, miniature", "MIT-CMU (HPND)", "https://python-pillow.github.io/",
           ("Pillow",)),
    Credit("NumPy", "NumPy Developers", RUNTIME, "Calcolo numerico in tutti i moduli d'immagine",
           "BSD-3-Clause (con componenti 0BSD, MIT, Zlib, CC0)", "https://numpy.org/", ("numpy",)),
    Credit("OpenCV (opencv-python-headless)", "OpenCV team e collaboratori; classificatori Haar © Intel Corporation",
           RUNTIME, "SIFT (copy-move), rilevamento dei volti, lettura dei frame video, elaborazioni d'immagine",
           "Apache-2.0; librerie incluse nella wheel (FFmpeg LGPL-2.1 e altre) elencate in LICENSE-3RD-PARTY.txt; "
           "classificatori Haar: Intel License Agreement", "https://opencv.org/", ("opencv-python-headless",), (),
           ("Apache-2.0.txt", "LGPL-2.1.txt"),
           "https://github.com/opencv/opencv-python (script di build e versioni delle librerie incluse) e "
           "https://ffmpeg.org/download.html"),
    Credit("pillow-heif", "Alexander Piskun e collaboratori", RUNTIME, "Decodifica HEIC/HEIF",
           "BSD-3-Clause (sorgente); wheel binarie GPL-2.0 perché includono x265", "https://github.com/bigcat88/pillow_heif",
           ("pillow-heif",), (), ("GPL-2.0.txt", "LGPL-3.0.txt"), "https://github.com/bigcat88/pillow_heif"),
    Credit("libheif", "struktur AG e collaboratori", RUNTIME, "Decodifica HEIF (dentro pillow-heif)", "LGPL-3.0",
           "https://github.com/strukturag/libheif", (), (), ("LGPL-3.0.txt",), "https://github.com/strukturag/libheif"),
    Credit("libde265", "struktur AG e collaboratori", RUNTIME, "Decodifica HEVC (dentro pillow-heif)", "LGPL-3.0",
           "https://github.com/strukturag/libde265", (), (), ("LGPL-3.0.txt",), "https://github.com/strukturag/libde265"),
    Credit("x265", "MulticoreWare Inc. e collaboratori", RUNTIME,
           "Codifica HEVC (dentro pillow-heif; usata solo dal self-check per generare un HEIC di prova)", "GPL-2.0",
           "https://www.x265.org/", (), (), ("GPL-2.0.txt",), "https://github.com/Multicorewareinc/x265"),
    Credit("ONNX Runtime", "Microsoft Corporation e collaboratori", RUNTIME, "Esecuzione dei modelli di stima della posa",
           "MIT", "https://onnxruntime.ai/", ("onnxruntime",)),
    Credit("ExifTool", "Phil Harvey", TOOL, "Estrazione dei metadati, miniature, tag QuickTime",
           "Stessi termini di Perl (Artistic License o GPL-1.0-or-later); il pacchetto Windows include l'interprete Perl",
           "https://exiftool.org/", (), ("exiftool",), ("Artistic-Perl.txt", "GPL-1.0.txt"), "https://exiftool.org/"),
    Credit("FFmpeg / FFprobe", "FFmpeg developers; build Windows di Gyan Doshi (gyan.dev)", TOOL,
           "Lettura di stream, contenitori e tempi dei video (FFprobe)", "GPL-3.0 (build gyan.dev statica con "
           "--enable-gpl --enable-version3)", "https://ffmpeg.org/", (), ("ffmpeg",), ("GPL-3.0.txt",),
           "https://www.gyan.dev/ffmpeg/builds/ (sorgente di ogni build) e https://github.com/GyanD/codexffmpeg"),
    Credit("YOLOX-m HumanArt e RTMPose-m Body7 HALPE-26", "OpenMMLab (MMPose); YOLOX di Megvii", MODEL,
           "Rilevamento delle persone e stima dei 26 punti del corpo", "Apache-2.0",
           "https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose", (), ("pose-detector", "pose-estimator"),
           ("Apache-2.0.txt",)),
    Credit("Sports2D", "David Pagnon (perfanalytics)", METHOD,
           "Metodologia di Persone e movimento: angoli, lato visibile, filtri, formati TRC/MOT", "BSD-3-Clause",
           "https://github.com/davidpagnon/Sports2D", (), (), ("BSD-3-Clause-perfanalytics.txt",)),
    Credit("Pose2Sim", "David Pagnon (perfanalytics)", METHOD,
           "Definizioni degli angoli e funzioni di calcolo, riprese in engines/pose.py", "BSD-3-Clause",
           "https://github.com/perfanalytics/pose2sim", (), (), ("BSD-3-Clause-perfanalytics.txt",)),
    Credit("rtmlib", "Tao Jiang; Open-MMLab", METHOD,
           "Pre e post-elaborazione di YOLOX e RTMPose, reimplementate e modificate in engines/pose_model.py",
           "Apache-2.0", "https://github.com/Tau-J/rtmlib", (), (), ("Apache-2.0.txt",)),
    Credit("StegoIntelligence", "CScorza", METHOD,
           "Catalogo di tecniche e strumenti di steganografia, implementate in modo nativo (nessun codice copiato)",
           "nessuna licenza dichiarata (usato solo come fonte di consultazione)", "https://github.com/CScorza/StegoIntelligence"),
    Credit("PixIntelligence", "jacobobb", METHOD,
           "Spunto per l'elenco delle funzioni della milestone 2 (nessun codice copiato)",
           "CC BY-NC-SA 4.0 / licenza commerciale", "https://github.com/jacobobb/pixintelligence"),
    Credit("PyInstaller", "PyInstaller Development Team", BUILD,
           "Creazione dell'eseguibile (il bootloader è incluso nell'eseguibile)",
           "GPL-2.0-or-later con eccezione per il bootloader", "https://pyinstaller.org/", ("pyinstaller",)),
    Credit("Inno Setup", "Jordan Russell e Martijn Laan", BUILD, "Creazione dell'installer Windows",
           "Inno Setup License", "https://jrsoftware.org/isinfo.php"),
    Credit("pytest", "Holger Krekel e collaboratori", BUILD, "Test automatici", "MIT", "https://pytest.org/",
           ("pytest",)),
]


def by_kind() -> dict[str, list[Credit]]:
    out: dict[str, list[Credit]] = {}
    for c in CREDITS:
        out.setdefault(c.kind, []).append(c)
    return out


def _base() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))


def notices_path() -> Path:
    return _base() / "THIRD_PARTY_NOTICES.md"


def licenses_dir() -> Path:
    return _base() / "licenses"


def notices_text() -> str:
    p = notices_path()
    return p.read_text(encoding="utf-8") if p.is_file() else text_summary()


def text_summary() -> str:
    lines = ["Forensic Vision Pro - crediti e licenze di terze parti", ""]
    for kind, items in by_kind().items():
        lines.append(kind.upper())
        for c in items:
            lines.append(f"  {c.name} - {c.authors}")
            lines.append(f"    uso: {c.use}")
            lines.append(f"    licenza: {c.license} - {c.url}")
            if c.source:
                lines.append(f"    sorgente: {c.source}")
        lines.append("")
    lines.append(f"Testi completi delle licenze: {licenses_dir()}")
    return "\n".join(lines)


def credits_cli(argv: list[str]) -> int:
    """--credits [file]: stampa (o scrive nel file indicato) crediti e licenze."""
    i = argv.index("--credits")
    out = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") else None
    txt = text_summary() + "\n\n" + "=" * 78 + "\n\n" + notices_text()
    if out:
        Path(out).write_text(txt, encoding="utf-8")
    elif sys.stdout is not None:                  # l'eseguibile senza console non ha stdout: usare un file
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
        sys.stdout.write(txt + "\n")
    return 0
