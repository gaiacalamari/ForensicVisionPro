"""Metadata Engine: estrazione con ExifTool (fallback Pillow) e controlli sui metadati.

Ogni tag è classificato per attendibilità:
  - "calcolato"  : derivato dall'analisi del file (gruppi File, Composite, ExifTool)
  - "dichiarato" : scritto nel file da dispositivo o software; modificabile, non verificabile da solo
  - "filesystem_copia": tempi del filesystem della copia di lavoro, NON dell'originale
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.findings import Category, Finding, Level
from ..core.tools import ToolError, get_tool, run

MODULE = "metadata"

EDITORS = ["photoshop", "lightroom", "gimp", "paint.net", "affinity", "pixelmator", "snapseed", "picsart",
           "facetune", "canva", "luminar", "capture one", "darktable", "rawtherapee", "acdsee", "corel",
           "paintshop", "inkscape", "fotor", "vsco", "airbrush", "meitu", "photoscape", "premiere", "final cut",
           "davinci", "imovie", "capcut", "after effects", "handbrake", "lavf", "lavc", "ffmpeg", "imagemagick",
           "graphicsmagick", "xnview", "irfanview", "windows photo editor", "microsoft photos"]
AI_MARKERS = {
    "trainedalgorithmicmedia": "IPTC DigitalSourceType: generato da modello addestrato",
    "compositewithtrainedalgorithmicmedia": "IPTC DigitalSourceType: composito con contenuto generato",
    "algorithmicmedia": "IPTC DigitalSourceType: contenuto algoritmico",
    "midjourney": "Midjourney", "dall-e": "DALL-E", "dall·e": "DALL-E", "openai": "OpenAI",
    "stable diffusion": "Stable Diffusion", "stablediffusion": "Stable Diffusion", "sdxl": "Stable Diffusion XL",
    "comfyui": "ComfyUI", "automatic1111": "AUTOMATIC1111", "novelai": "NovelAI", "firefly": "Adobe Firefly",
    "imagen": "Google Imagen", "gemini": "Google Gemini", "flux": "FLUX", "leonardo.ai": "Leonardo.ai",
    "ideogram": "Ideogram", "c2pa": "Manifest C2PA (provenienza)",
}
AI_PNG_KEYS = {"parameters", "prompt", "workflow", "negative_prompt", "sd-metadata", "dream", "invokeai_metadata"}


def reliability(group: str) -> str:
    if group in ("System",):
        return "filesystem_copia"
    if group in ("File", "Composite", "ExifTool"):
        return "calcolato"
    return "dichiarato"


def extract(path: str | Path, exiftool_path: str = "", timeout: int = 120) -> dict:
    """Restituisce {'tool': ..., 'tags': [{group, tag, value, reliability}], 'gps': {...}}."""
    tool = get_tool("exiftool", exiftool_path)
    p = str(Path(path).resolve())
    if tool:
        try:
            raw = run([tool.path, "-j", "-a", "-u", "-G1", "-s", "-charset", "filename=utf8",
                       "-api", "LargeFileSupport=1", p], timeout=timeout)
            data = json.loads(raw.decode("utf-8", errors="replace"))[0]
            tags = []
            for k, v in data.items():
                if k == "SourceFile":
                    continue
                g, _, t = k.partition(":") if ":" in k else ("", "", k)
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                tags.append({"group": g, "tag": t, "value": str(v), "reliability": reliability(g)})
            gps = {}
            try:
                rawn = run([tool.path, "-j", "-n", "-Composite:GPSLatitude", "-Composite:GPSLongitude",
                            "-Composite:GPSAltitude", "-GPS:GPSLatitude", "-GPS:GPSLongitude",
                            "-GPS:GPSLatitudeRef", "-GPS:GPSLongitudeRef", p], timeout=timeout)
                g0 = json.loads(rawn)[0]
                lat, lon = g0.get("GPSLatitude"), g0.get("GPSLongitude")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    gps = {"lat": lat, "lon": lon, "alt": g0.get("GPSAltitude")}
            except (ToolError, ValueError, IndexError):
                pass
            return {"tool": f"ExifTool {tool.version}", "tags": tags, "gps": gps}
        except (ToolError, ValueError, IndexError) as e:
            err = str(e)
    else:
        err = "ExifTool non trovato"
    return _pillow_fallback(p, err)


# Pillow usa i nomi della specifica EXIF; li si allinea a quelli di ExifTool usati dagli altri moduli
_PIL_NAMES = {"DateTime": "ModifyDate", "DateTimeDigitized": "CreateDate", "ExifImageWidth": "ExifImageWidth",
              "ISOSpeedRatings": "ISO"}


def _rat(v) -> float:
    return float(v.numerator) / float(v.denominator) if hasattr(v, "denominator") and v.denominator else float(v)


def _pillow_fallback(p: str, reason: str) -> dict:
    tags: list[dict] = []
    gps: dict = {}
    try:
        from PIL import ExifTags, Image
        with Image.open(p) as im:
            tags += [{"group": "File", "tag": "FileType", "value": str(im.format), "reliability": "calcolato"},
                     {"group": "File", "tag": "ImageWidth", "value": str(im.width), "reliability": "calcolato"},
                     {"group": "File", "tag": "ImageHeight", "value": str(im.height), "reliability": "calcolato"}]
            ex = im.getexif()
            for k, v in ex.items():
                if k in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
                    continue
                name = ExifTags.TAGS.get(k, f"0x{k:04X}")
                tags.append({"group": "IFD0", "tag": _PIL_NAMES.get(name, name), "value": str(v),
                             "reliability": "dichiarato"})
            for k, v in ex.get_ifd(ExifTags.IFD.Exif).items():
                name = ExifTags.TAGS.get(k, f"0x{k:04X}")
                if isinstance(v, bytes):
                    v = v[:64].hex(" ") + (" …" if len(v) > 64 else "")
                tags.append({"group": "ExifIFD", "tag": _PIL_NAMES.get(name, name), "value": str(v),
                             "reliability": "dichiarato"})
            g = ex.get_ifd(ExifTags.IFD.GPSInfo)
            for k, v in g.items():
                name = ExifTags.GPSTAGS.get(k, f"0x{k:04X}")
                if name == "GPSTimeStamp" and isinstance(v, tuple) and len(v) == 3:
                    h, m, sec = (_rat(x) for x in v)
                    v = f"{int(h):02d}:{int(m):02d}:{sec:06.3f}".rstrip("0").rstrip(".")
                elif isinstance(v, tuple):
                    v = " ".join(str(_rat(x)) for x in v)
                tags.append({"group": "GPS", "tag": name, "value": str(v), "reliability": "dichiarato"})
            try:
                lat = sum(_rat(x) / 60 ** i for i, x in enumerate(g[2])) * (-1 if g.get(1) == "S" else 1)
                lon = sum(_rat(x) / 60 ** i for i, x in enumerate(g[4])) * (-1 if g.get(3) == "W" else 1)
                gps = {"lat": lat, "lon": lon, "alt": _rat(g[6]) if 6 in g else None}
            except (KeyError, TypeError, ZeroDivisionError):
                pass
    except Exception as e:  # noqa: BLE001 - file non attendibile, qualsiasi errore va gestito
        reason += f"; Pillow: {e}"
    return {"tool": f"Pillow (fallback: {reason})", "tags": tags, "gps": gps, "limited": True}


def tag_map(meta: dict) -> dict[str, str]:
    return {f"{t['group']}:{t['tag']}": t["value"] for t in meta.get("tags", [])}


def find(meta: dict, name: str) -> list[tuple[str, str]]:
    return [(t["group"], t["value"]) for t in meta.get("tags", []) if t["tag"] == name]


def analyze(meta: dict, png_text: list[dict] | None = None) -> list[Finding]:
    f: list[Finding] = []
    tags = meta.get("tags", [])
    if meta.get("limited"):
        f.append(Finding(Category.METADATA, Level.UNDETERMINED, "Estrazione metadati limitata",
                         f"Estrazione eseguita con {meta.get('tool')}. XMP, IPTC, MakerNotes e metadati video non "
                         "sono disponibili.", "Estrazione metadati", MODULE,
                         limitations="Installare ExifTool o indicarne il percorso nelle impostazioni."))
    declared = [t for t in tags if t["reliability"] == "dichiarato"]
    # Software di modifica (un solo risultato con tutti i tag pertinenti)
    sw_hits = []
    for t in declared:
        if t["tag"] in ("Software", "CreatorTool", "ProcessingSoftware", "HistorySoftwareAgent", "Encoder",
                        "HandlerVendorID", "WriterName", "ReaderName", "CompressorName", "EncoderSettings"):
            low = t["value"].lower()
            if any(e in low for e in EDITORS):
                sw_hits.append(f"{t['group']}:{t['tag']} = {t['value'][:150]}")
    if sw_hits:
        first = sw_hits[0].split(" = ", 1)[1]
        f.append(Finding(Category.METADATA, Level.SUSPICIOUS, f"Software di elaborazione dichiarato: {first[:60]}",
                         "I metadati indicano un software di modifica, conversione o ricodifica.",
                         "Confronto con elenco di software noti", MODULE, evidence="\n".join(sw_hits[:15]),
                         confidence="media",
                         limitations="Il tag è modificabile e può riferirsi a operazioni lecite (ritaglio, "
                                     "conversione, esportazione, invio tramite app). Non indica quale modifica "
                                     "sia avvenuta."))
    hist = [t for t in declared if t["tag"] in ("HistoryAction", "HistoryWhen", "DocumentAncestors",
                                                "DerivedFromDocumentID", "HistoryChanged")]
    if hist:
        f.append(Finding(Category.METADATA, Level.SUSPICIOUS, "Cronologia di modifica XMP presente",
                         "Il file contiene una cronologia XMP (xmpMM:History / DocumentAncestors), scritta dai "
                         "software Adobe e simili quando un documento viene salvato o derivato da altri.",
                         "Analisi XMP Media Management", MODULE,
                         evidence="; ".join(f"{t['tag']}={t['value'][:120]}" for t in hist[:6]), confidence="alta",
                         limitations="Prova che il file è passato da un software che scrive XMP, non che il "
                                     "contenuto visivo sia stato alterato."))
    groups = {t["group"] for t in tags}
    has_exif = any(g in groups for g in ("IFD0", "ExifIFD"))
    if has_exif and not find(meta, "Make") and not find(meta, "Model"):
        f.append(Finding(Category.METADATA, Level.ANOMALY, "EXIF senza Make/Model",
                         "Sono presenti dati EXIF ma non identificano il dispositivo di acquisizione.",
                         "Controllo campi attesi", MODULE, confidence="media",
                         limitations="Alcuni software rimuovono questi campi in esportazione; alcune app li omettono."))
    if not has_exif and any(t["group"] == "File" and t["tag"] == "FileType" and t["value"] in ("JPEG",)
                            for t in tags):
        f.append(Finding(Category.METADATA, Level.INFO, "Nessun EXIF",
                         "Il JPEG non contiene metadati EXIF.", "Controllo campi attesi", MODULE,
                         limitations="Tipico di immagini scaricate da social network o messaggistica, che "
                                     "rimuovono i metadati."))
    if any(g.startswith("Photoshop") for g in groups):
        f.append(Finding(Category.METADATA, Level.SUSPICIOUS, "Blocco Photoshop IRB presente",
                         "Il file contiene risorse Photoshop (APP13), scritte da software Adobe o compatibili.",
                         "Analisi gruppi di metadati", MODULE, confidence="alta",
                         limitations="Anche alcuni strumenti di catalogazione IPTC scrivono questo blocco."))
    # Indicatori di generazione AI nei metadati
    ai_hits: list[str] = []
    for t in declared:
        low = f"{t['tag']} {t['value']}".lower()
        for k, label in AI_MARKERS.items():
            if k == "flux" and not re.search(r"\bflux\b", low):
                continue
            if k == "gemini" and "gemini" not in t["value"].lower():
                continue
            if k in low:
                ai_hits.append(f"{t['group']}:{t['tag']} → {label}")
                break
    for pt in png_text or []:
        if pt["key"].lower() in AI_PNG_KEYS or ("steps:" in pt["value"].lower() and "sampler" in pt["value"].lower()):
            ai_hits.append(f"PNG {pt['chunk']} '{pt['key']}' (offset {pt['offset']}) → parametri di generazione")
    if ai_hits:
        f.append(Finding(Category.AI_GENERATION, Level.SUSPICIOUS, "Metadati riferiti a generazione AI",
                         "I metadati dichiarano o contengono tracce di strumenti di generazione o di provenienza.",
                         "Ricerca di marcatori di generatori noti", MODULE, evidence="\n".join(sorted(set(ai_hits))[:20]),
                         confidence="media", significant=True,
                         limitations="I metadati possono essere aggiunti o rimossi: l'assenza non esclude la "
                                     "generazione AI, la presenza va confermata (es. validando il manifest C2PA)."))
    if meta.get("gps"):
        g = meta["gps"]
        f.append(Finding(Category.METADATA, Level.INFO, "Coordinate GPS presenti",
                         f"Lat {g['lat']:.6f}, Lon {g['lon']:.6f}" + (f", Alt {g['alt']}" if g.get("alt") is not None else ""),
                         "Estrazione GPS", MODULE, limitations="Le coordinate sono dichiarate nel file e "
                                                               "modificabili; la precisione dipende dal fix."))
    return f
