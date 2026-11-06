"""Coerenza con il dispositivo dichiarato.

Quando i metadati identificano il dispositivo (Make/Model), verifica che il resto del file sia
compatibile con quel dispositivo:
  - nome del file secondo le convenzioni del produttore (es. IMG_0000.HEIC su iPhone) e cartella DCIM;
  - ora contenuta nel nome (Samsung, Pixel, molti Android) confrontata con DateTimeOriginal;
  - coerenza interna tra Model, HostComputer, LensModel e LensMake;
  - versione di iOS dichiarata (Software) rispetto al modello e alla data di scatto/modifica;
  - data di scatto rispetto all'uscita del modello;
  - risoluzione reale rispetto a quelle prodotte dalle fotocamere del modello;
  - dimensioni EXIF rispetto ai pixel reali; presenza delle MakerNotes; struttura HEIF tipica.

Ogni controllo produce un Finding con i propri limiti: i profili (device_db) sono riferimenti da
validare con campioni dello stesso modello, e una discordanza è un'anomalia da spiegare, non una prova.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from ..core.findings import Category, Finding, Level
from . import device_db
from .timestamps import parse_dt, parse_offset

MODULE = "device"
TOL_PX = 2
VIDEO_FORMATS = {"mp4", "mov", "3gp"}
# Risoluzioni video della Fotocamera iOS nelle modalità standard (720p, 1080p, 4K)
IPHONE_VIDEO = [(1280, 720), (1920, 1080), (3840, 2160)]


def _track_size(meta: dict) -> tuple[int, int] | None:
    w = h = None
    for t in meta.get("tags", []):
        if re.match(r"^Track\d+$", t["group"]) and t["tag"] in ("ImageWidth", "ImageHeight") and t["value"].isdigit():
            if t["tag"] == "ImageWidth" and w is None and int(t["value"]) > 0:
                w = int(t["value"])
            elif t["tag"] == "ImageHeight" and h is None and int(t["value"]) > 0:
                h = int(t["value"])
        if w and h:
            return (w, h)
    return None


def _video_resolution(f, res, raster, prof, model, live_id, src) -> None:
    res["camera"] = "video"
    if live_id:
        f.append(Finding(Category.SENSOR, Level.INFO, "Componente video di una Live Photo",
                         f"ContentIdentifier {live_id}: il filmato accompagna una foto. Risoluzione "
                         f"{raster[0]}x{raster[1]} non confrontata (dipende dal formato della foto).", src, MODULE))
        return
    bases = prof.get("video") or IPHONE_VIDEO
    a, b = max(raster), min(raster)
    if any(abs(a - w) <= TOL_PX and abs(b - h) <= TOL_PX for w, h in bases):
        f.append(Finding(Category.SENSOR, Level.INFO, f"Risoluzione video coerente con {model}",
                         f"{raster[0]}x{raster[1]}.", src, MODULE))
    else:
        f.append(Finding(Category.SENSOR, Level.ANOMALY, f"Risoluzione video non standard per {model}",
                         f"{raster[0]}x{raster[1]}; attese: {', '.join(f'{w}x{h}' for w, h in bases)}.", src, MODULE,
                         confidence="bassa",
                         limitations="Modalità Azione, Cinema, ProRes, slow motion, app di terze parti ed "
                                     "esportazioni (Foto, iMovie, messaggistica) producono altre dimensioni."))


def load_profiles(home: Path | None = None) -> dict:
    models = dict(device_db.MODELS)
    try:
        from ..core.config import default_home
        f = (home or default_home()) / "device_profiles.json"
        if f.is_file():
            models.update(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return models


def _tags(meta: dict) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for t in meta.get("tags", []):
        out.setdefault(t["tag"], []).append((t["group"], t["value"]))
    return out


def _get(tg: dict, name: str, groups: tuple[str, ...] = ()) -> str | None:
    vals = tg.get(name, [])
    for g in groups:
        for gg, v in vals:
            if gg == g:
                return v.strip()
    return vals[0][1].strip() if vals else None


def _vendor(make: str | None) -> str | None:
    if not make:
        return None
    low = make.lower()
    for k, v in device_db.VENDORS.items():
        if any(m in low for m in v["makes"]):
            return k
    return None


def _crops(base: list[int]) -> list[tuple[int, int, str]]:
    w, h = max(base), min(base)
    return [(w, h, "4:3"), (w, round(w * 9 / 16), "16:9"), (h, h, "1:1")]


def _match_res(size: tuple[int, int], bases: list[list[int]]) -> str | None:
    a, b = max(size), min(size)
    for base in bases:
        for w, h, lab in _crops(base):
            if abs(a - w) <= TOL_PX and abs(b - h) <= TOL_PX:
                return f"{w}x{h} ({lab}, base {max(base)}x{min(base)})"
    return None


def _ver_major(sw: str | None) -> int | None:
    m = re.match(r"^\s*(\d{1,2})(\.\d+){0,2}\s*$", sw or "")
    return int(m.group(1)) if m else None


def _name_dt(m: re.Match) -> datetime | None:
    gd = m.groupdict()
    d, t = gd.get("d"), gd.get("t")
    if not d:
        return None
    d = d.replace("-", "")
    t = (t or "000000").replace("-", "")
    try:
        return datetime.strptime(d + t, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def analyze(meta: dict, original_name: str, source_path: str = "", raster: tuple[int, int] | None = None,
            fmt: str | None = None, heif: dict | None = None, profiles: dict | None = None
            ) -> tuple[dict, list[Finding]]:
    f: list[Finding] = []
    tg = _tags(meta)
    is_video = fmt in VIDEO_FORMATS
    # Foto: EXIF (IFD0/ExifIFD). Video iPhone: QuickTime Keys (com.apple.quicktime.*) o UserData.
    make = _get(tg, "Make", ("IFD0", "Keys", "UserData"))
    model = _get(tg, "Model", ("IFD0", "Keys", "UserData"))
    software = _get(tg, "Software", ("IFD0", "Keys", "UserData"))
    host = _get(tg, "HostComputer", ("IFD0",))
    lens_model = _get(tg, "LensModel", ("ExifIFD", "Keys"))
    lens_make = _get(tg, "LensMake", ("ExifIFD", "Keys"))
    dto_raw = _get(tg, "DateTimeOriginal", ("ExifIFD",))
    off_raw = _get(tg, "OffsetTimeOriginal", ("ExifIFD",))
    if not dto_raw:
        dto_raw = _get(tg, "CreationDate", ("Keys", "UserData"))     # ora locale con fuso (iPhone)
    mod_raw = _get(tg, "ModifyDate", ("IFD0",))
    exif_w = _get(tg, "ExifImageWidth", ("ExifIFD",))
    exif_h = _get(tg, "ExifImageHeight", ("ExifIFD",))
    live_id = _get(tg, "ContentIdentifier", ("Keys", "Apple"))
    if is_video and not raster:
        raster = _track_size(meta)
    dto = parse_dt(dto_raw)[0] if dto_raw else None
    mod = parse_dt(mod_raw)[0] if mod_raw else None
    if dto and dto.tzinfo and not off_raw:
        o = int(dto.utcoffset().total_seconds() // 60)
        off_raw = f"{'+' if o >= 0 else '-'}{abs(o) // 60:02d}:{abs(o) % 60:02d}"
    vendor = _vendor(make)
    name = PureWindowsPath(original_name).name if "\\" in original_name else Path(original_name).name
    res: dict = {"make": make, "model": model, "vendor": vendor, "software": software, "host_computer": host,
                 "lens_model": lens_model, "file_name": name, "raster": list(raster) if raster else None,
                 "content_identifier": live_id}

    _filename_checks(f, res, name, source_path, vendor, make, model, dto, off_raw, mod)
    if raster and not is_video and exif_w and exif_h and exif_w.isdigit() and exif_h.isdigit():
        e = (int(exif_w), int(exif_h))
        if sorted(e) != sorted(raster):
            f.append(Finding(Category.SENSOR, Level.ANOMALY, "Dimensioni EXIF diverse dai pixel reali",
                             f"EXIF dichiara {e[0]}x{e[1]}, l'immagine decodificata è {raster[0]}x{raster[1]}.",
                             "Confronto ExifImageWidth/Height con il raster", MODULE, confidence="alta",
                             significant=True,
                             limitations="Tipico di ritaglio o ridimensionamento con un software che copia l'EXIF "
                                         "originale senza aggiornarlo. Alcuni editor aggiornano correttamente il "
                                         "campo: la coerenza non esclude modifiche."))
    if not make or not model:
        res["profile"] = None
        return res, f

    # Coerenza interna dei campi che nominano il dispositivo
    incoherent = []
    if host and vendor == "apple" and host.lower() != model.lower():
        incoherent.append(f"HostComputer = '{host}'")
    if lens_model and vendor == "apple" and "iphone" in lens_model.lower() and \
            not lens_model.lower().startswith(model.lower() + " "):
        incoherent.append(f"LensModel = '{lens_model}'")
    if lens_make and vendor == "apple" and lens_make.lower() != "apple":
        incoherent.append(f"LensMake = '{lens_make}'")
    if incoherent:
        f.append(Finding(Category.SENSOR, Level.ANOMALY, "Campi del dispositivo in contraddizione",
                         f"Model = '{model}' ma " + "; ".join(incoherent) + ".", "Confronto Model/HostComputer/"
                         "LensModel/LensMake", MODULE, evidence="\n".join(incoherent), confidence="alta",
                         significant=True,
                         limitations="La Fotocamera iOS scrive lo stesso nome di modello in tutti questi campi. "
                                     "Una contraddizione indica metadati copiati da un altro file o modificati."))

    if vendor == "apple" and not is_video and meta.get("tags") and not meta.get("limited") and lens_model and \
            "camera" in lens_model.lower() and not any(t["group"] == "Apple" for t in meta["tags"]):
        f.append(Finding(Category.SENSOR, Level.ANOMALY, "MakerNotes Apple assenti",
                         "Il file dichiara una fotocamera iPhone ma non contiene le MakerNotes Apple, scritte dalla "
                         "Fotocamera iOS in ogni scatto.", "Analisi gruppi di metadati (ExifTool)", MODULE,
                         confidence="media",
                         limitations="Molti software di modifica o conversione rimuovono le MakerNotes mantenendo "
                                     "Make/Model: indica un passaggio successivo allo scatto, non la sua natura."))

    profiles = profiles if profiles is not None else load_profiles()
    key = f"{make}|{model}"
    prof = profiles.get(key)
    res["profile_key"] = key
    res["profile"] = prof
    if not prof:
        f.append(Finding(Category.SENSOR, Level.UNDETERMINED, f"Profilo non disponibile per {model}",
                         f"Il modello '{make} {model}' non è nell'archivio dei profili: risoluzione, firmware e data "
                         "di uscita non sono stati verificati.", "Profili dei dispositivi", MODULE,
                         limitations="Aggiungere il modello in device_profiles.json nella cartella dati, partendo "
                                     "da file campione acquisiti in laboratorio."))
        return res, f
    conf = "media" if prof.get("verificato") else "bassa (profilo non validato con campioni)"
    src = f"Profilo {key} ({prof.get('fonte', 'n/d')})"

    # Data di scatto rispetto all'uscita del modello
    rel = date.fromisoformat(prof["released"]) if prof.get("released") else None
    if rel and dto and dto.date() < rel:
        f.append(Finding(Category.TEMPORAL, Level.ANOMALY, f"Scatto anteriore all'uscita di {model}",
                         f"DateTimeOriginal {dto_raw} precede la data di uscita del modello ({rel.isoformat()}).",
                         src, MODULE, evidence=dto_raw, confidence=conf, significant=True,
                         limitations="Possibile con orologio del dispositivo impostato male, dispositivi di "
                                     "pre-produzione o metadati modificati."))

    # Formato HEIC su un modello che non lo produce
    if fmt == "heif" and prof.get("heic") is False:
        f.append(Finding(Category.SENSOR, Level.ANOMALY, f"HEIC non prodotto da {model}",
                         f"La Fotocamera di {model} non salva in HEIC (hardware non supportato).", src, MODULE,
                         confidence=conf, significant=True,
                         limitations="Il file può essere stato convertito in HEIC da un altro dispositivo o "
                                     "software, mantenendo l'EXIF originale."))

    # Versione di iOS dichiarata
    major = _ver_major(software) if vendor == "apple" else None
    if major is not None:
        res["os_major"] = major
        launch = _ver_major(prof.get("launch_os"))
        mx = _ver_major(prof.get("max_os"))
        if launch and major < launch:
            f.append(Finding(Category.SENSOR, Level.ANOMALY, "Versione di iOS anteriore al modello",
                             f"Software = {software}, ma {model} è uscito con iOS {prof['launch_os']}.", src, MODULE,
                             evidence=f"IFD0:Software = {software}", confidence=conf, significant=True))
        if mx and major > mx:
            f.append(Finding(Category.SENSOR, Level.ANOMALY, "Versione di iOS non supportata dal modello",
                             f"Software = {software}, ma {model} si ferma a iOS {prof['max_os']}.", src, MODULE,
                             evidence=f"IFD0:Software = {software}", confidence=conf, significant=True))
        rel_os = device_db.IOS_RELEASES.get(major)
        last = mod or dto
        if rel_os and last:
            d = (date.fromisoformat(rel_os) - last.date()).days
            if d > 100:
                f.append(Finding(Category.TEMPORAL, Level.ANOMALY, f"iOS {major} non ancora disponibile alla data del file",
                                 f"Software = {software} (iOS {major}.0 pubblicato il {rel_os}), ma la data più recente "
                                 f"del file è {last.isoformat(sep=' ')}: {d} giorni prima.",
                                 "Confronto versione di sistema / date EXIF", MODULE,
                                 evidence=f"Software {software}; ModifyDate {mod_raw}; DateTimeOriginal {dto_raw}",
                                 confidence="media", significant=True,
                                 limitations="Possibile con orologio errato. Le beta per sviluppatori escono circa tre "
                                             "mesi prima: sono già escluse dalla tolleranza di 100 giorni."))
            elif d > 0:
                f.append(Finding(Category.TEMPORAL, Level.INFO, f"iOS {major} in fase beta alla data del file",
                                 f"iOS {major}.0 è stato pubblicato il {rel_os}, {d} giorni dopo la data del file: "
                                 "compatibile solo con una versione beta.", "Confronto versione di sistema / date EXIF",
                                 MODULE, evidence=f"Software {software}"))

    # Risoluzione rispetto alle fotocamere del modello
    if raster and is_video:
        _video_resolution(f, res, raster, prof, model, live_id, src)
    elif raster:
        lm = (lens_model or "").lower()
        cam = "front" if "front" in lm else "rear" if ("back" in lm or "rear" in lm) else None
        bases = (prof.get(cam) if cam else (prof.get("rear") or []) + (prof.get("front") or []))
        res["camera"] = cam or "non dichiarata"
        a, b = max(raster), min(raster)
        if bases is None:
            f.append(Finding(Category.SENSOR, Level.UNDETERMINED, "Risoluzione non verificabile",
                             f"Il profilo di {model} non contiene le risoluzioni della fotocamera {cam}.", src, MODULE))
        elif a / max(b, 1) > 2.2:
            f.append(Finding(Category.SENSOR, Level.INFO, "Risoluzione da panoramica",
                             f"{raster[0]}x{raster[1]}: proporzioni tipiche di una panoramica, che ha dimensioni "
                             "variabili e non è confrontabile con il profilo.", src, MODULE))
        else:
            hit = _match_res(raster, bases)
            if hit:
                f.append(Finding(Category.SENSOR, Level.INFO, f"Risoluzione coerente con {model}",
                                 f"{raster[0]}x{raster[1]} corrisponde a {hit}.", src, MODULE, confidence=conf,
                                 limitations="La coerenza non esclude modifiche che preservano le dimensioni."))
            else:
                exp = ", ".join(f"{w}x{h}" for base in bases for w, h, _ in _crops(base))
                f.append(Finding(Category.SENSOR, Level.ANOMALY, f"Risoluzione non prodotta da {model}",
                                 f"{raster[0]}x{raster[1]} non corrisponde a nessuna risoluzione della fotocamera "
                                 f"{'frontale' if cam == 'front' else 'posteriore' if cam == 'rear' else ''} "
                                 f"del modello. Attese: {exp}.", src, MODULE, confidence=conf,
                                 limitations="Ritagli in Foto, zoom digitale in alcune app, app di terze parti, "
                                             "screenshot e ricompressioni producono altre dimensioni. Verificare "
                                             "con campioni dello stesso modello e versione di iOS."))

    # Struttura HEIF tipica della Fotocamera iOS
    if vendor == "apple" and fmt == "heif" and heif:
        res["heif_brands"] = heif.get("brands")
        if heif.get("primary_type") and heif["primary_type"] != "grid":
            f.append(Finding(Category.SENSOR, Level.ANOMALY, "Struttura HEIF diversa dalla Fotocamera iOS",
                             f"L'immagine principale è un item '{heif['primary_type']}' singolo; la Fotocamera "
                             "iOS scrive una griglia ('grid') di tile HEVC.", "Confronto con la struttura di "
                             "riferimento", MODULE, confidence="bassa",
                             limitations="Indica una riscrittura del file (conversione, esportazione, software "
                                         "terzo). Confermare con file campione dello stesso modello."))
        elif heif.get("grid", {}).get("tile_size") and heif["grid"]["tile_size"] != [512, 512]:
            f.append(Finding(Category.SENSOR, Level.ANOMALY, "Tile HEIF non standard per iPhone",
                             f"Tile {heif['grid']['tile_size']}, la Fotocamera iOS usa tile 512x512.",
                             "Confronto con la struttura di riferimento", MODULE, confidence="bassa"))
    return res, f


def _filename_checks(f, res, name, source_path, vendor, make, model, dto, off_raw, mod) -> None:
    meth = "Convenzioni di nome dei file"
    for rx, label, expl in device_db.TRANSFER_PATTERNS:
        m = re.match(rx, name, re.IGNORECASE)
        if not m:
            continue
        res["name_origin"] = label
        f.append(Finding(Category.METADATA, Level.INFO, f"Nome del file assegnato da: {label}", expl, meth, MODULE,
                         evidence=name))
        ndt = _name_dt(m)
        if label.startswith("WhatsApp") and make and model:
            f.append(Finding(Category.METADATA, Level.SUSPICIOUS, "EXIF del dispositivo in un file con nome WhatsApp",
                             f"Il nome indica un media salvato da WhatsApp, ma il file contiene Make/Model "
                             f"({make} {model}), che WhatsApp rimuove dalle foto inviate come media.", meth, MODULE,
                             evidence=name, confidence="media",
                             limitations="Possibile se il file è stato rinominato a mano, inviato come documento o "
                                         "se l'EXIF è stato reinserito."))
        if ndt and dto and ndt.date() < dto.date():
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Data nel nome precedente allo scatto",
                             f"Il nome indica il {ndt.date().isoformat()}, DateTimeOriginal il "
                             f"{dto.date().isoformat()}: il file risulta ricevuto/salvato prima dello scatto.",
                             meth, MODULE, evidence=name, confidence="media", significant=True,
                             limitations="Verificare il fuso orario e l'impostazione dell'orologio dei dispositivi."))
        return
    if not vendor:
        return
    v = device_db.VENDORS[vendor]
    flags = 0 if v.get("uppercase_ext") else re.IGNORECASE
    native = next((m for rx in v["native"] if (m := re.match(rx, name, flags))), None)
    edited = next((m for rx in v["edited"] if (m := re.match(rx, name, flags))), None)
    loose = None if native or edited else next(
        (m for rx in v["native"] + v["edited"] if (m := re.match(rx, name, re.IGNORECASE))), None)
    who = f"{make} {model}".strip()
    if native:
        res["name_pattern"] = "nativo"
        f.append(Finding(Category.METADATA, Level.INFO, "Nome del file coerente con il dispositivo",
                         f"'{name}' segue la convenzione della fotocamera {who}.", meth, MODULE, evidence=name,
                         limitations="Il nome si cambia facilmente: la coerenza non prova l'origine."))
        n = native.groupdict().get("n")
        if n == "0000":
            f.append(Finding(Category.METADATA, Level.ANOMALY, "Numerazione IMG_0000",
                             "La Fotocamera iOS numera i file da IMG_0001.", meth, MODULE, evidence=name,
                             confidence="bassa"))
    elif edited:
        res["name_pattern"] = "modificato"
        f.append(Finding(Category.METADATA, Level.SUSPICIOUS, "Nome di una versione modificata (IMG_E)",
                         f"'{name}': il prefisso IMG_E identifica la versione modificata in Foto di iOS/macOS, "
                         "esportata accanto all'originale IMG_xxxx.", meth, MODULE, evidence=name, confidence="alta",
                         significant=True,
                         limitations="La modifica può essere lecita (ritaglio, filtro, raddrizzamento). Cercare "
                                     "l'originale con lo stesso numero."))
    elif loose:
        res["name_pattern"] = "maiuscole/minuscole diverse"
        f.append(Finding(Category.METADATA, Level.ANOMALY, "Nome del file rinominato rispetto al dispositivo",
                         f"'{name}' ha la struttura della convenzione di {who}, ma con maiuscole/minuscole diverse "
                         "(la Fotocamera iOS usa nome ed estensione in maiuscolo).", meth, MODULE, evidence=name,
                         confidence="bassa",
                         limitations="Alcuni strumenti di trasferimento o di backup convertono i nomi in minuscolo."))
    else:
        res["name_pattern"] = "non tipico"
        f.append(Finding(Category.METADATA, Level.ANOMALY, "Nome del file non tipico del dispositivo",
                         f"'{name}' non segue la convenzione della fotocamera {who}.", meth, MODULE, evidence=name,
                         confidence="bassa",
                         limitations="Esportazioni, app di terze parti, servizi cloud e strumenti di estrazione "
                                     "possono rinominare i file. Ha valore solo se il nome è quello originale al "
                                     "momento dell'acquisizione."))
    m = native or edited or loose
    if source_path and v.get("folder") and re.search(r"[\\/]DCIM[\\/]", source_path, re.IGNORECASE):
        if not re.search(v["folder"], source_path):
            f.append(Finding(Category.METADATA, Level.ANOMALY, "Cartella DCIM non tipica del dispositivo",
                             f"Il percorso di origine '{source_path}' non corrisponde alle cartelle usate da {who}.",
                             meth, MODULE, evidence=source_path, confidence="bassa"))
    ndt = _name_dt(m) if m else None
    if not ndt or not dto:
        return
    if v["time"] == "utc":
        tz = parse_offset(off_raw)
        if tz is None:
            d = (dto - ndt).total_seconds()
            q = round(d / 900) * 900
            if abs(d - q) <= 2 and abs(q) <= 14 * 3600:
                f.append(Finding(Category.TEMPORAL, Level.INFO, "Ora nel nome coerente (UTC)",
                                 f"Il nome riporta l'ora UTC; lo scarto con DateTimeOriginal ({q / 3600:+.2f} h) è "
                                 "compatibile con un fuso orario.", meth, MODULE, evidence=name))
                return
            dto_cmp = None
        else:
            dto_cmp = dto.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    else:
        dto_cmp = dto
    diff = (dto_cmp - ndt).total_seconds() if dto_cmp else None
    if diff is not None and abs(diff) <= 2:
        f.append(Finding(Category.TEMPORAL, Level.INFO, "Ora nel nome coerente con lo scatto",
                         f"Scarto di {diff:+.0f} s tra nome del file e DateTimeOriginal.", meth, MODULE, evidence=name))
        return
    f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Ora nel nome diversa dallo scatto",
                     f"Il nome '{name}' indica {ndt.isoformat(sep=' ')}" +
                     (f", DateTimeOriginal differisce di {timedelta(seconds=int(abs(diff)))} "
                      f"({'dopo' if diff > 0 else 'prima'})." if diff is not None else
                      ", non riconducibile a DateTimeOriginal con un fuso orario."),
                     meth, MODULE, evidence=name, confidence="media",
                     significant=diff is None or abs(diff) > 60,
                     limitations="Il nome è assegnato al salvataggio: scarti di pochi secondi sono possibili con "
                                 "scatti a raffica o elaborazioni lunghe (Notte, HDR). Scarti grandi indicano che "
                                 "DateTimeOriginal o il nome sono stati modificati."))
