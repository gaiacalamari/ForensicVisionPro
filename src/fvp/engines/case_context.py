"""Coerenza tra i reperti dello stesso caso.

Confronta il reperto in analisi con gli altri reperti del caso:
  - Live Photo: la foto (HEIC/JPG) e il filmato (MOV) condividono lo stesso ContentIdentifier
    (MakerNotes Apple nella foto, chiave com.apple.quicktime.content.identifier nel MOV). Si verifica che
    abbiano lo stesso numero IMG_xxxx, lo stesso modello e orari vicini.
  - Stesso scatto in più file: stesso ContentIdentifier su più foto con hash diversi (es. originale e IMG_E).
  - Numerazione: sullo stesso modello iPhone il numero IMG_xxxx cresce con il tempo di scatto. Un numero
    più alto con una data precedente indica date modificate, file di dispositivi diversi o orologio cambiato.

I dati degli altri reperti si leggono dalle copie di lavoro (sola lettura) con una sola chiamata ExifTool,
e si conservano in una cache del caso indicizzata per SHA-256: l'esito non dipende dall'ordine di analisi.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..core.findings import Category, Finding, Level
from ..core.tools import ToolError, get_tool, run
from .timestamps import parse_dt, parse_offset

MODULE = "case_context"
CACHE = "_case_context.json"
FIELDS = ["Make", "Model", "DateTimeOriginal", "OffsetTimeOriginal", "CreationDate", "ContentIdentifier",
          "FileType"]
VIDEO_TYPES = {"MOV", "MP4", "M4V", "3GP"}
RX_NUM = re.compile(r"^IMG_(?P<e>E?)(?P<n>\d{4})(?: \d+|\(\d+\))?\.\w+$", re.IGNORECASE)
LIVE_TOL_S = 3          # il filmato di una Live Photo inizia ~1,5 s prima della foto
SEQ_TOL_S = 2


def _record(ex, tags: dict[str, str]) -> dict:
    """Riduce i tag di un reperto ai campi usati qui. tags: {nome_tag: valore} (primo trovato)."""
    raw = tags.get("DateTimeOriginal") or tags.get("CreationDate")
    dt, tz_known, _ = parse_dt(raw) if raw else (None, False, "")
    utc = local = None
    if dt:
        tz = dt.tzinfo or parse_offset(tags.get("OffsetTimeOriginal"))
        local = dt.replace(tzinfo=None).isoformat()
        if tz:
            utc = dt.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    m = RX_NUM.match(Path(ex.original_name).name)
    return {"id": ex.id, "name": Path(ex.original_name).name, "sha256": ex.working_hashes.get("sha256", ""),
            "make": tags.get("Make"), "model": tags.get("Model"), "time_raw": raw, "local": local, "utc": utc,
            "cid": tags.get("ContentIdentifier"),
            "kind": "video" if (tags.get("FileType") or "").upper() in VIDEO_TYPES else "still",
            "img_num": int(m.group("n")) if m else None, "edited": bool(m and m.group("e"))}


def collect(case, exiftool_path: str = "", timeout: int = 300) -> list[dict]:
    cache_f = case.root / "artifacts" / CACHE
    try:
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    exs = case.exhibits()
    todo = [e for e in exs if e.working_hashes.get("sha256") not in cache and Path(e.working_path).is_file()]
    tool = get_tool("exiftool", exiftool_path)
    if todo and tool:
        args = [tool.path, "-j", "-G1", "-s", "-charset", "filename=utf8", "-api", "LargeFileSupport=1"]
        args += [f"-{f}" for f in FIELDS] + [str(Path(e.working_path).resolve()) for e in todo]
        try:
            data = json.loads(run(args, timeout=timeout).decode("utf-8", errors="replace"))
        except (ToolError, ValueError):
            data = []
        by_path = {str(Path(d.get("SourceFile", "")).resolve()): d for d in data}
        for e in todo:
            d = by_path.get(str(Path(e.working_path).resolve()), {})
            tags: dict[str, str] = {}
            # Preferenze: EXIF per le foto, Keys per i video iPhone
            for key in sorted(d, key=lambda k: (not k.startswith(("ExifIFD:", "IFD0:", "Keys:", "Apple:")), k)):
                if ":" in key:
                    tags.setdefault(key.split(":", 1)[1], str(d[key]))
            cache[e.working_hashes["sha256"]] = tags
        try:
            cache_f.parent.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return [_record(e, cache.get(e.working_hashes.get("sha256"), {})) for e in exs]


def _dt(r: dict, utc: bool) -> datetime | None:
    v = r["utc"] if utc else r["local"]
    return datetime.fromisoformat(v) if v else None


def _delta(a: dict, b: dict) -> tuple[float | None, bool]:
    """Secondi a-b, preferendo UTC; False nel secondo valore se il confronto è tra ore locali."""
    if a["utc"] and b["utc"]:
        return (_dt(a, True) - _dt(b, True)).total_seconds(), True
    if a["local"] and b["local"]:
        return (_dt(a, False) - _dt(b, False)).total_seconds(), False
    return None, False


def analyze(cur_id: str, records: list[dict]) -> tuple[dict, list[Finding]]:
    f: list[Finding] = []
    cur = next((r for r in records if r["id"] == cur_id), None)
    if not cur:
        return {}, f
    others = [r for r in records if r["id"] != cur_id]
    res = {"exhibits_compared": len(others), "live_photo": None, "sequence": None}
    _live(cur, others, res, f)
    _sequence(cur, others, res, f)
    return res, f


def _live(cur, others, res, f) -> None:
    if not cur["cid"]:
        return
    meth = "Confronto ContentIdentifier tra reperti"
    same = [r for r in others if r["cid"] == cur["cid"]]
    partners = [r for r in same if r["kind"] != cur["kind"]]
    twins = [r for r in same if r["kind"] == cur["kind"] and r["sha256"] != cur["sha256"]]
    copies = [r for r in same if r["sha256"] == cur["sha256"]]
    res["live_photo"] = {"content_identifier": cur["cid"], "partners": [r["id"] for r in partners],
                         "same_kind": [r["id"] for r in twins], "copies": [r["id"] for r in copies]}
    if copies:
        f.append(Finding(Category.METADATA, Level.INFO, "Copia identica nel caso",
                         f"Stesso SHA-256 di {', '.join(r['id'] + ' (' + r['name'] + ')' for r in copies)}.",
                         meth, MODULE))
    if twins:
        f.append(Finding(Category.METADATA, Level.SUSPICIOUS, "Più versioni dello stesso scatto",
                         f"{len(twins)} altri file con lo stesso identificativo di scatto ({cur['cid']}) ma contenuto "
                         f"diverso: {', '.join(r['id'] + ' (' + r['name'] + ')' for r in twins)}.", meth, MODULE,
                         confidence="media",
                         limitations="Tipico di originale e versione modificata (IMG_E) o di esportazioni diverse "
                                     "dello stesso scatto. Confrontarli con il modulo Confronto."))
    if not partners:
        other = "il filmato (MOV)" if cur["kind"] == "still" else "la foto"
        f.append(Finding(Category.METADATA, Level.INFO, "Live Photo: componente non acquisito",
                         f"Il file ha un identificativo Live Photo ({cur['cid']}) ma {other} con lo stesso "
                         "identificativo non è tra i reperti del caso.", meth, MODULE,
                         limitations="L'altro componente può essere sul dispositivo o in iCloud: acquisirlo permette "
                                     "di verificare orari e modello in modo incrociato."))
        return
    for p in partners:
        issues, significant = [], False
        if cur["img_num"] is not None and p["img_num"] is not None and cur["img_num"] != p["img_num"]:
            issues.append(f"numeri diversi nei nomi ({cur['name']} / {p['name']})")
        if cur["model"] and p["model"] and cur["model"] != p["model"]:
            issues.append(f"modelli diversi ({cur['model']} / {p['model']})")
            significant = True
        d, is_utc = _delta(cur, p)
        if d is not None and abs(d) > LIVE_TOL_S:
            issues.append(f"orari distanti {timedelta(seconds=int(abs(d)))} "
                          f"({'UTC' if is_utc else 'ora locale'})")
            significant = significant or abs(d) > 60
        if issues:
            f.append(Finding(Category.METADATA, Level.ANOMALY, "Live Photo: componenti incoerenti",
                             f"{cur['id']} e {p['id']} condividono l'identificativo {cur['cid']}, ma: "
                             + "; ".join(issues) + ".", meth, MODULE, confidence="media", significant=significant,
                             evidence=f"{cur['name']}: {cur['time_raw']} {cur['model']}\n"
                                      f"{p['name']}: {p['time_raw']} {p['model']}",
                             limitations="L'identificativo è scritto dalla Fotocamera iOS in entrambi i file nello "
                                         "stesso istante. Nomi diversi possono derivare da rinomina in "
                                         "esportazione; orari o modelli diversi indicano metadati modificati."))
        else:
            f.append(Finding(Category.METADATA, Level.INFO, "Live Photo: componenti coerenti",
                             f"Abbinato a {p['id']} ({p['name']}): stesso identificativo, stesso modello"
                             + (f", scarto di {d:+.1f} s" if d is not None else "") + ".", meth, MODULE))


def _sequence(cur, others, res, f) -> None:
    if cur["img_num"] is None or cur["edited"] or not cur["model"] or not (cur["make"] or "").lower() == "apple":
        return
    group = [r for r in others if r["img_num"] is not None and not r["edited"] and r["model"] == cur["model"]
             and (r["make"] or "").lower() == "apple" and (r["local"] or r["utc"])]
    # foto e video condividono la stessa numerazione; una Live Photo ha lo stesso numero nei due file
    if not group or not (cur["local"] or cur["utc"]):
        return
    nums = [r["img_num"] for r in group] + [cur["img_num"]]
    rollover = max(nums) - min(nums) > 5000        # IMG_9999 -> IMG_0001 con nuova cartella DCIM

    def key(r):
        return r["img_num"] + (10000 if rollover and r["img_num"] < 5000 else 0)
    meth = "Numerazione IMG_xxxx rispetto alle date di scatto (stesso modello)"
    dup = [r for r in group if r["img_num"] == cur["img_num"] and r["sha256"] != cur["sha256"]
           and r["kind"] == cur["kind"]]
    if dup:
        f.append(Finding(Category.TEMPORAL, Level.INFO, "Numero IMG ripetuto sullo stesso modello",
                         f"{cur['name']} ha lo stesso numero di {', '.join(r['id'] + ' (' + r['name'] + ')' for r in dup)}"
                         " con contenuto diverso.", meth, MODULE,
                         limitations="Possibile con più dispositivi dello stesso modello, con il riavvio della "
                                     "numerazione dopo IMG_9999 o con un ripristino del dispositivo."))
    k = key(cur)
    before = max((r for r in group if key(r) < k), key=key, default=None)
    after = min((r for r in group if key(r) > k), key=key, default=None)
    res["sequence"] = {"model": cur["model"], "group_size": len(group) + 1, "rollover": rollover,
                       "previous": before["id"] if before else None, "next": after["id"] if after else None}
    for nb, rel in ((before, "precedente"), (after, "successivo")):
        if not nb:
            continue
        d, is_utc = _delta(cur, nb)
        if d is None:
            continue
        inverted = (rel == "precedente" and d < -SEQ_TOL_S) or (rel == "successivo" and d > SEQ_TOL_S)
        if not inverted:
            continue
        tz_like = not is_utc and abs(abs(d) - round(abs(d) / 900) * 900) <= 120 and abs(d) <= 14 * 3600
        f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Numerazione incoerente con la data di scatto",
                         f"{cur['name']} ({cur['time_raw']}) e il numero {rel} {nb['name']} ({nb['time_raw']}): "
                         f"il file con numero {'più alto' if rel == 'precedente' else 'più basso'} risulta scattato "
                         f"{timedelta(seconds=int(abs(d)))} {'prima' if rel == 'precedente' else 'dopo'}.",
                         meth, MODULE, evidence=f"{cur['id']} {cur['name']} / {nb['id']} {nb['name']}",
                         confidence="bassa" if tz_like else "media", significant=not tz_like,
                         limitations=("Lo scarto è un multiplo di 15 minuti tra ore locali: compatibile con un "
                                      "cambio di fuso orario tra i due scatti. " if tz_like else "") +
                                     "La Fotocamera iOS assegna i numeri in ordine di scatto. Un'inversione è "
                                     "compatibile con date modificate, file di dispositivi diversi dello stesso "
                                     "modello, cambio manuale dell'orologio o importazioni che rinumerano i file."))
