"""Orchestrazione di un'analisi completa su un reperto acquisito.

Sequenza: hash iniziale della copia di lavoro → moduli → hash finale.
Tutti i moduli lavorano sulla copia di lavoro in sola lettura, mai sull'originale.
Un errore in un modulo non interrompe gli altri: viene registrato come risultato
"non determinabile" con il motivo.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from .. import __version__
from ..cases.store import Case
from ..engines import (compare, hashing, hidden_text, image, image_extra, jpeg_forensics, metadata, prnu, signature, stego,
                       stegointel, timestamps, video)
from ..parsers.registry import parser_for
from .audit import utc_now
from .config import Settings
from .findings import Category, Finding, Level
from .tasks import Cancelled, CancelToken, ProgressFn, noop_progress
from .tools import get_tool

IMAGE_FORMATS = {"jpeg", "png", "gif", "tiff", "bmp", "webp"}
VIDEO_FORMATS = {"mp4", "mov", "3gp", "avi", "mkv", "webm", "mpeg_ps", "mpeg_ts", "m2ts"}
AUDIO_FORMATS = {"wav", "mp3", "flac", "ogg", "aac"}
ALL_MODULES = ["integrity", "signature", "structure", "metadata", "timestamps", "image", "jpeg_advanced", "median",
               "copymove", "stego", "stegointel", "hidden_text", "quality", "prnu", "video", "carving_scan"]
ARTIFACT_LABELS = {
    "ela": "Error Level Analysis (q90)", "ela_multi": "ELA multi-qualità (composita)", "ghost": "JPEG ghost",
    "noise": "Residuo di rumore", "median": "Stabilità sotto filtro mediano", "copymove": "Copy-move (overlay)",
    "lsb": "Piani LSB (R, G, B)", "faces": "Volti rilevati", "prnu_local": "Correlazione locale PRNU",
    "faint": "Contrasto esaltato (testo quasi invisibile)",
}


def _fail(module: str, cat: Category, e: BaseException) -> Finding:
    return Finding(cat, Level.UNDETERMINED, f"Modulo {module} non completato", f"{type(e).__name__}: {e}",
                   "—", module, limitations="Il modulo non ha prodotto risultati: il file potrebbe essere "
                                            "malformato o lo strumento esterno non disponibile.",
                   data={"traceback": traceback.format_exc(limit=3)})


def analyze_exhibit(case: Case, ex_id: str, operator: str, settings: Settings | None = None,
                    modules: list[str] | None = None, progress: ProgressFn = noop_progress,
                    cancel: CancelToken | None = None) -> int:
    settings = settings or Settings()
    modules = modules or ALL_MODULES
    image.set_pixel_limit(settings.max_image_pixels)
    ex = case.exhibit(ex_id)
    wp = ex.working_path
    started = utc_now()
    findings: list[Finding] = []
    results: dict = {"executed": [], "artifacts": {}}
    executed: set[Category] = set()
    algs = list(ex.working_hashes)
    case.audit.append(operator, "analisi_avviata", {"exhibit": ex_id, "modules": modules})

    def step(p: float, msg: str) -> None:
        if cancel:
            cancel.check()
        progress(p, msg)

    step(0.02, "Hash iniziale della copia di lavoro")
    pre = hashing.hash_file(wp, algs, cancel=cancel)
    executed.add(Category.INTEGRITY)
    if pre != ex.working_hashes:
        findings.append(Finding(Category.INTEGRITY, Level.EVIDENCE, "Copia di lavoro diversa dall'acquisizione",
                                "Gli hash della copia di lavoro non corrispondono a quelli registrati "
                                "all'acquisizione. L'analisi è stata interrotta.", "Confronto hash", "integrity",
                                evidence=f"atteso {ex.working_hashes.get('sha256')}, ottenuto {pre.get('sha256')}",
                                confidence="alta", significant=True))
        return case.save_analysis(ex_id, operator, started, modules, findings, results, pre, pre, {})

    try:
        step(0.08, "Identificazione del formato")
        sig = signature.identify(wp)
        sig["original_extension"] = Path(ex.original_name).suffix.lower()
        sig["extension_matches"] = sig["format"] is not None and sig["original_extension"] in \
            signature.FORMATS[sig["format"]].extensions
        sig["extension"] = sig["original_extension"]
        results["signature"] = sig
        findings += signature.findings_for(sig)
        executed.add(Category.FILE_STRUCTURE)
        results["executed"].append("signature")
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001
        findings.append(_fail("signature", Category.FILE_STRUCTURE, e))
        sig = {"format": None}
    fmt = sig.get("format")

    png_text, png_time, container_times = None, None, None
    qtable, jpeg_q = None, None
    if "structure" in modules and parser_for(fmt):
        try:
            step(0.15, "Analisi della struttura")
            pr = parser_for(fmt)(wp)
            results["structure"] = pr.to_dict()
            findings += pr.findings
            png_text = pr.extra.get("text")
            png_time = pr.extra.get("tIME")
            container_times = pr.extra.get("times")
            if pr.extra.get("qtables", {}).get("0"):
                qtable = pr.extra["qtables"]["0"]["values"]
                jpeg_q = pr.extra["qtables"]["0"]["ijg_quality"]
            results["executed"].append("structure")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("structure", Category.FILE_STRUCTURE, e))

    meta = {"tags": []}
    if "metadata" in modules:
        try:
            step(0.3, "Estrazione dei metadati")
            meta = metadata.extract(wp, settings.exiftool_path, settings.tool_timeout_s)
            results["metadata"] = meta
            findings += metadata.analyze(meta, png_text)
            executed.add(Category.METADATA)
            # Nessun detector AI è attivo: la categoria resta grigia (inconcludente) salvo indicatori nei metadati
            if any(f.category == Category.AI_GENERATION and f.level != Level.INFO for f in findings):
                executed.add(Category.AI_GENERATION)
            results["executed"].append("metadata")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("metadata", Category.METADATA, e))

    if "timestamps" in modules:
        try:
            step(0.4, "Analisi temporale")
            ev = timestamps.collect(meta.get("tags", []), ex.source_stat, container_times, png_time)
            results["timeline"] = timestamps.timeline(ev)
            findings += timestamps.analyze(ev)
            executed.add(Category.TEMPORAL)
            results["executed"].append("timestamps")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("timestamps", Category.TEMPORAL, e))

    art = case.artifacts_dir(ex_id)
    if fmt in IMAGE_FORMATS:
        try:
            from PIL import Image as _Image
            with _Image.open(wp) as _im:
                _im.load()
        except Exception as e:  # noqa: BLE001 - il file non è attendibile
            findings.append(Finding(
                Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Immagine non decodificabile: analisi dei pixel saltate",
                f"Il raster non può essere decodificato ({type(e).__name__}: {e}). ELA, rumore, storia JPEG, copy-move, "
                "steganalisi, PRNU e caratteristiche non sono stati eseguiti.", "Decodifica Pillow", "image",
                limitations="Le cause tipiche (troncamento, CRC errato) sono riportate dal modulo struttura."))
            executed.add(Category.IMAGE_MANIPULATION)
            fmt_pixels = False
        else:
            fmt_pixels = True
    else:
        fmt_pixels = False
    if "image" in modules and fmt_pixels:
        executed.add(Category.IMAGE_MANIPULATION)
        for name, fn in (("image_info", lambda: image.image_info(wp)),):
            try:
                results[name] = fn()
            except Exception as e:  # noqa: BLE001
                findings.append(_fail("image_info", Category.IMAGE_MANIPULATION, e))
        try:
            step(0.55, "Error Level Analysis")
            _, fe = image.ela(wp, 90, art / "ela_q90.png")
            findings.append(fe)
            results["artifacts"]["ela"] = str(art / "ela_q90.png")
            step(0.65, "Residuo di rumore")
            _, fn_ = image.noise_residual(wp, art / "noise_residual.png")
            findings.append(fn_)
            results["artifacts"]["noise"] = str(art / "noise_residual.png")
            step(0.72, "Controllo della miniatura")
            ft = image.thumbnail_check(wp, settings.exiftool_path)
            if ft:
                findings.append(ft)
            results["executed"].append("image")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("image", Category.IMAGE_MANIPULATION, e))

    def run_image_module(name: str, p: float, msg: str, fn) -> None:
        if name not in modules or not fmt_pixels:
            return
        try:
            step(p, msg)
            fn()
            results["executed"].append(name)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail(name, Category.IMAGE_MANIPULATION, e))

    def m_jpeg():
        executed.add(Category.IMAGE_MANIPULATION)
        findings.append(jpeg_forensics.multi_ela(wp, art / "ela_multi.png"))
        results["artifacts"]["ela_multi"] = str(art / "ela_multi.png")
        g = jpeg_forensics.jpeg_ghost(wp, art / "ghost.png", jpeg_q if fmt == "jpeg" else None)
        findings.append(g)
        if (art / "ghost.png").exists():
            results["artifacts"]["ghost"] = str(art / "ghost.png")
        if fmt == "jpeg":
            findings.append(jpeg_forensics.double_jpeg(wp, qtable))
        findings.append(jpeg_forensics.grid_alignment(wp, fmt == "jpeg"))

    def m_median():
        executed.add(Category.IMAGE_MANIPULATION)
        findings.append(image_extra.median_filter(wp, fmt == "jpeg", art / "median.png", jpeg_q))
        if (art / "median.png").exists():
            results["artifacts"]["median"] = str(art / "median.png")

    def m_copymove():
        executed.add(Category.IMAGE_MANIPULATION)
        findings.append(image_extra.copy_move(wp, art / "copymove.png"))
        results["artifacts"]["copymove"] = str(art / "copymove.png")

    def m_stego():
        executed.add(Category.STEGANOGRAPHY)
        res, fs = stego.analyze(wp, fmt, art / "lsb.png")
        results["stego"] = res
        findings.extend(fs)
        if fmt == "jpeg":
            findings.append(jpeg_forensics.dct_chi_square(wp, qtable))
        if (art / "lsb.png").exists():
            results["artifacts"]["lsb"] = str(art / "lsb.png")

    def m_quality():
        info, f = image_extra.characteristics(wp, art / "faces.png")
        results["characteristics"] = info
        results["perceptual_hashes"] = compare.perceptual_hashes(wp)
        findings.append(f)
        if (art / "faces.png").exists():
            results["artifacts"]["faces"] = str(art / "faces.png")

    def m_prnu():
        store = prnu.PrnuStore(settings.prnu_path)
        if not store.list():
            return
        executed.add(Category.SENSOR)
        res, fs = prnu.match(wp, store, art / "prnu_local.png")
        results["prnu"] = res
        findings.extend(fs)
        if (art / "prnu_local.png").exists():
            results["artifacts"]["prnu_local"] = str(art / "prnu_local.png")

    run_image_module("jpeg_advanced", 0.62, "Storia di compressione JPEG", m_jpeg)
    run_image_module("median", 0.66, "Filtro mediano", m_median)
    run_image_module("copymove", 0.70, "Ricerca di regioni duplicate", m_copymove)
    run_image_module("stego", 0.74, "Steganalisi LSB", m_stego)
    if "stegointel" in modules and (fmt_pixels or fmt in AUDIO_FORMATS):
        try:
            step(0.75, "StegoIntelligence: estrazione LSB")
            executed.add(Category.STEGANOGRAPHY)
            res, fs = stegointel.analyze(wp, fmt, art / "stegointel")
            results["stegointel"] = res
            findings.extend(fs)
            results["executed"].append("stegointel")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("stegointel", Category.STEGANOGRAPHY, e))
    if "hidden_text" in modules:
        try:
            step(0.755, "Ricerca di testo nascosto")
            executed.add(Category.STEGANOGRAPHY)
            items, fs = hidden_text.metadata_text(meta.get("tags", []), png_text)
            findings.extend(fs)
            hits, fs2 = hidden_text.file_strings(wp, results.get("structure"))
            findings.extend(fs2)
            ht_res = {"metadata_fields": items, "file_strings": hits[:100]}
            if fmt_pixels:
                fdata, ff = hidden_text.faint_content(wp, art / "faint.png")
                findings.append(ff)
                ht_res["faint"] = fdata
                if (art / "faint.png").exists():
                    results["artifacts"]["faint"] = str(art / "faint.png")
            results["hidden_text"] = ht_res
            results["executed"].append("hidden_text")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("hidden_text", Category.STEGANOGRAPHY, e))
    run_image_module("quality", 0.76, "Caratteristiche e hash percettivi", m_quality)
    run_image_module("prnu", 0.78, "Confronto PRNU", m_prnu)

    if "video" in modules and fmt in VIDEO_FORMATS | AUDIO_FORMATS:
        try:
            step(0.6, "Analisi FFprobe")
            summ = video.summarize(video.probe(wp, settings.ffprobe_path, settings.tool_timeout_s))
            results["video"] = summ
            findings += video.analyze(summ)
            executed.add(Category.VIDEO_INTEGRITY)
            if any(s["type"] == "audio" for s in summ["streams"]):
                executed.add(Category.AUDIO_INTEGRITY)
            results["executed"].append("video")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("video", Category.VIDEO_INTEGRITY, e))

    if "carving_scan" in modules:
        try:
            step(0.8, "Scansione delle firme incorporate")
            hits = signature.scan_signatures(wp, cancel=cancel)
            results["embedded_signatures"] = hits
            inner = [h for h in hits if h["offset"] > 0 and h.get("valid", True)]
            results["embedded_signatures_unverified"] = sum(1 for h in hits if h["offset"] > 0 and not h.get("valid", True))
            if fmt == "jpeg":
                inner = [h for h in inner if not h["signature"].startswith("JPEG")]
            if fmt in VIDEO_FORMATS | {"heif"}:
                inner = [h for h in inner if h["signature"] not in ("MP4", "QuickTime", "HEIC", "RIFF")]
            if inner:
                findings.append(Finding(Category.FILE_STRUCTURE, Level.ANOMALY, "Firme di altri formati nel file",
                                        f"{len(inner)} firme di formati diversi dal contenitore, con una struttura "
                                        "valida dopo la firma.",
                                        "File Signature Scanner (read-only)", "signature",
                                        evidence="\n".join(f"0x{h['offset']:X}  {h['signature']}" for h in inner[:30]),
                                        offset=inner[0]["offset"], confidence="bassa",
                                        limitations="Sequenze brevi come 'RIFF' o 'MZ' possono comparire per caso "
                                                    "nei dati compressi. Verificare ogni offset con l'Hex Viewer."))
            results["executed"].append("carving_scan")
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            findings.append(_fail("carving_scan", Category.FILE_STRUCTURE, e))

    step(0.95, "Hash finale")
    post = hashing.hash_file(wp, algs, cancel=cancel)
    same = pre == post
    findings.insert(0, Finding(
        Category.INTEGRITY, Level.INFO if same else Level.EVIDENCE,
        "Integrità della copia di lavoro verificata" if same else "La copia di lavoro è cambiata durante l'analisi",
        "Gli hash calcolati prima e dopo l'analisi coincidono con quelli dell'acquisizione." if same else
        "Gli hash prima e dopo l'analisi sono diversi.", "Hash pre/post analisi", "integrity",
        evidence=f"SHA-256 {post.get('sha256', '')}", confidence="alta", significant=not same))
    results["executed_categories"] = sorted(c.value for c in executed)
    tools = {"app": __version__}
    for t in ("exiftool", "ffprobe"):
        tl = get_tool(t, getattr(settings, f"{t}_path", ""))
        tools[t] = tl.version if tl else "non disponibile"
    try:
        import cv2, numpy, PIL
        tools.update({"pillow": PIL.__version__, "numpy": numpy.__version__, "opencv": cv2.__version__})
    except ImportError:
        pass
    progress(1.0, "Completato")
    return case.save_analysis(ex_id, operator, started, modules, findings, results, pre, post, tools)
