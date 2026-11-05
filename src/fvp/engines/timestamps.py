"""Timestamp & Temporal Forensics.

Raccoglie tutti i riferimenti temporali (metadati interni, contenitore, filesystem
dell'originale rilevato all'acquisizione), li normalizza in UTC quando il fuso è
noto e segnala le incoerenze. Un orario senza fuso resta "locale non determinato":
non viene mai convertito per ipotesi.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from ..core.findings import Category, Finding, Level

MODULE = "timestamps"
_RX = re.compile(r"^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?")
_OFF = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
# Gruppi ExifTool i cui tempi sono UTC per specifica (QuickTime/ISO BMFF)
UTC_GROUPS = re.compile(r"^(QuickTime|Track\d+|Movie|Media)$")
CAPTURE_TAGS = {"DateTimeOriginal", "CreateDate", "DateCreated", "CreationDate", "TrackCreateDate", "MediaCreateDate"}


@dataclass
class TimeEvent:
    source: str            # es. "ExifIFD:DateTimeOriginal"
    raw: str
    kind: str              # acquisizione | modifica | digitalizzazione | gps | contenitore | filesystem | altro
    utc: str | None        # ISO UTC se determinabile
    local: str | None      # ISO locale senza fuso se il fuso non è noto
    tz_known: bool
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def dt_utc(self) -> datetime | None:
        return datetime.fromisoformat(self.utc) if self.utc else None

    @property
    def dt_local(self) -> datetime | None:
        return datetime.fromisoformat(self.local) if self.local else None


def parse_offset(s: str | None) -> timezone | None:
    if not s:
        return None
    m = _OFF.match(s.strip())
    if not m:
        return timezone.utc if s.strip() == "Z" else None
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def parse_dt(value: str) -> tuple[datetime | None, bool, str]:
    """(datetime, fuso_noto, nota). Restituisce None per date nulle o non valide."""
    v = value.strip()
    if v.startswith("0000:00:00") or v.startswith("0000-00-00"):
        return None, False, "data nulla (campo presente ma non impostato)"
    m = _RX.match(v)
    if not m:
        return None, False, ""
    try:
        frac = m.group(7) or ""
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
                      int(m.group(6)), int(float(frac) * 1_000_000) if frac else 0)
    except ValueError:
        return None, False, f"data non valida: {v}"
    tz = parse_offset(m.group(8))
    if tz:
        return dt.replace(tzinfo=tz), True, ""
    return dt, False, ""


def _kind(tag: str, group: str) -> str:
    t = tag.lower()
    if group == "GPS" or t.startswith("gps"):
        return "gps"
    if "original" in t or t in ("datecreated", "creationdate"):
        return "acquisizione"
    if t in ("createdate", "trackcreatedate", "mediacreatedate"):
        return "contenitore" if UTC_GROUPS.match(group) else "digitalizzazione"
    if "modif" in t or "metadatadate" in t:
        return "modifica"
    return "altro"


def collect(tags: list[dict], source_stat: dict | None = None, container_times: list[dict] | None = None,
            png_time: str | None = None) -> list[TimeEvent]:
    by = {f"{t['group']}:{t['tag']}": t["value"] for t in tags}
    ev: list[TimeEvent] = []
    offsets = {k.split(":")[1]: v for k, v in by.items() if k.split(":")[1].startswith("OffsetTime")}
    have_exiftool_container = any(UTC_GROUPS.match(t["group"]) for t in tags)
    for t in tags:
        g, name, val = t["group"], t["tag"], t["value"]
        if g in ("System", "File", "Composite", "ExifTool"):
            continue
        if not ("Date" in name or "Time" in name) or name.startswith("OffsetTime") or name.startswith("SubSec"):
            continue
        if name in ("GPSTimeStamp", "GPSDateStamp", "ExposureTime", "TimeZone", "TimeScale", "MediaTimeScale",
                    "PreviewTime", "PosterTime", "SelectionTime", "CurrentTime", "Duration", "SelfTimer"):
            continue
        dt, tzk, note = parse_dt(val)
        if dt is None:
            if note:
                ev.append(TimeEvent(f"{g}:{name}", val, _kind(name, g), None, None, False, note))
            continue
        if not tzk:
            off_tag = {"DateTimeOriginal": "OffsetTimeOriginal", "CreateDate": "OffsetTimeDigitized",
                       "ModifyDate": "OffsetTime"}.get(name)
            tz = parse_offset(offsets.get(off_tag)) if off_tag and g in ("ExifIFD", "IFD0") else None
            if tz:
                dt, tzk, note = dt.replace(tzinfo=tz), True, f"fuso da {off_tag}"
            elif UTC_GROUPS.match(g):
                dt, tzk, note = dt.replace(tzinfo=timezone.utc), True, \
                    "UTC per specifica QuickTime/ISO BMFF (alcuni dispositivi scrivono l'ora locale)"
        if tzk:
            ev.append(TimeEvent(f"{g}:{name}", val, _kind(name, g), dt.astimezone(timezone.utc).isoformat(), None,
                                True, note))
        else:
            ev.append(TimeEvent(f"{g}:{name}", val, _kind(name, g), None, dt.isoformat(), False,
                                note or "fuso orario non dichiarato"))
    gd, gt = by.get("GPS:GPSDateStamp"), by.get("GPS:GPSTimeStamp")
    if gd and gt:
        dt, _, _ = parse_dt(f"{gd} {gt.split('.')[0]}")
        if dt:
            ev.append(TimeEvent("GPS:GPSDateStamp+GPSTimeStamp", f"{gd} {gt}", "gps",
                                dt.replace(tzinfo=timezone.utc).isoformat(), None, True, "UTC per specifica GPS"))
    if container_times and not have_exiftool_container:
        for c in container_times:
            for k in ("creation", "modification"):
                if c.get(k):
                    ev.append(TimeEvent(f"{c['source']}.{k}", str(c[f'{k}_raw']),
                                        "contenitore" if k == "creation" else "modifica", c[k], None, True,
                                        "UTC per specifica ISO BMFF"))
    if png_time:
        dt, _, _ = parse_dt(png_time.replace(" UTC", ""))
        if dt:
            ev.append(TimeEvent("PNG:tIME", png_time, "modifica", dt.replace(tzinfo=timezone.utc).isoformat(), None,
                                True, "ultima modifica dichiarata (UTC)"))
    if source_stat:
        for k, label in (("mtime_utc", "modifica"), ("birthtime_utc", "creazione"), ("ctime_utc", "ctime"),
                         ("atime_utc", "accesso")):
            if source_stat.get(k):
                note = "filesystem dell'originale al momento dell'acquisizione"
                if k == "ctime_utc":
                    note += f" ({source_stat.get('ctime_meaning', '')})"
                ev.append(TimeEvent(f"Filesystem:{label}", source_stat[k], "filesystem", source_stat[k], None, True,
                                    note))
    return ev


def _first(ev: list[TimeEvent], *sources: str) -> TimeEvent | None:
    for s in sources:
        for e in ev:
            if e.source == s and (e.utc or e.local):
                return e
    return None


def _diff(a: TimeEvent, b: TimeEvent) -> float | None:
    """Differenza in secondi a-b se confrontabile (entrambi UTC o entrambi locali)."""
    if a.utc and b.utc:
        return (a.dt_utc - b.dt_utc).total_seconds()
    if a.local and b.local:
        return (a.dt_local - b.dt_local).total_seconds()
    return None


def analyze(ev: list[TimeEvent], now: datetime | None = None) -> list[Finding]:
    now = now or datetime.now(timezone.utc)
    f: list[Finding] = []
    meth = "Confronto dei riferimenti temporali"
    for e in ev:
        if e.note.startswith("data nulla"):
            f.append(Finding(Category.TEMPORAL, Level.INFO, f"Data nulla in {e.source}", e.note, meth, MODULE,
                             evidence=e.raw))
            continue
        if e.note.startswith("data non valida"):
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, f"Data impossibile in {e.source}", e.note, meth,
                             MODULE, evidence=e.raw, confidence="alta", significant=True))
            continue
        ref = e.dt_utc or (e.dt_local.replace(tzinfo=timezone.utc) if e.dt_local else None)
        if ref is None or e.kind == "filesystem":
            continue
        tol = timedelta(hours=14) if not e.tz_known else timedelta(minutes=5)
        if ref > now + tol:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, f"Data futura in {e.source}",
                             f"{e.raw} è successiva alla data dell'analisi ({now.isoformat(timespec='seconds')}).",
                             meth, MODULE, evidence=e.raw, confidence="alta", significant=True,
                             limitations="Può derivare da orologio del dispositivo impostato male."))
        elif ref.year < 1990 and e.kind in ("acquisizione", "digitalizzazione", "contenitore"):
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, f"Data anteriore all'era digitale in {e.source}",
                             f"{e.raw}: tipico di orologio non impostato (reset del dispositivo) o valore alterato.",
                             meth, MODULE, evidence=e.raw, confidence="media"))
    dto = _first(ev, "ExifIFD:DateTimeOriginal")
    cd = _first(ev, "ExifIFD:CreateDate")
    md = _first(ev, "IFD0:ModifyDate")
    if dto and cd:
        d = _diff(cd, dto)
        if d is not None and abs(d) > 2:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "DateTimeOriginal ≠ DateTimeDigitized",
                             f"Differenza di {d:+.0f} s.", meth, MODULE, evidence=f"{dto.raw} / {cd.raw}",
                             confidence="media", limitations="Legittimo per scansioni di pellicole o stampe."))
    if dto and md:
        d = _diff(md, dto)
        if d is not None and d < -2:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "ModifyDate precedente a DateTimeOriginal",
                             f"La data di modifica precede quella di scatto di {-d:.0f} s: sequenza non coerente.",
                             meth, MODULE, evidence=f"ModifyDate {md.raw} / DateTimeOriginal {dto.raw}",
                             confidence="alta", significant=True))
        elif d is not None and d > 60:
            f.append(Finding(Category.TEMPORAL, Level.SUSPICIOUS, "File salvato dopo lo scatto",
                             f"ModifyDate è successiva a DateTimeOriginal di {timedelta(seconds=int(d))}.", meth,
                             MODULE, evidence=f"ModifyDate {md.raw} / DateTimeOriginal {dto.raw}", confidence="media",
                             limitations="Indica un salvataggio successivo (elaborazione, rotazione, esportazione); "
                                         "non dice cosa sia cambiato."))
    xmp = _first(ev, "XMP-xmp:CreateDate", "XMP-photoshop:DateCreated", "XMP-exif:DateTimeOriginal")
    if dto and xmp:
        d = _diff(xmp, dto)
        if d is not None and abs(d) > 2:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Data XMP diversa da EXIF",
                             f"{xmp.source} differisce da DateTimeOriginal di {d:+.0f} s.", meth, MODULE,
                             evidence=f"{xmp.raw} / {dto.raw}", confidence="media",
                             limitations="Può derivare da modifica manuale della data in un catalogatore."))
    gps = _first(ev, "GPS:GPSDateStamp+GPSTimeStamp")
    if dto and gps:
        if dto.utc:
            d = (dto.dt_utc - gps.dt_utc).total_seconds()
            if abs(d) > 120:
                f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Orario GPS incoerente con lo scatto",
                                 f"DateTimeOriginal (UTC) e orario GPS differiscono di {d:+.0f} s.", meth, MODULE,
                                 evidence=f"{dto.utc} / {gps.utc}", confidence="media", significant=abs(d) > 3600,
                                 limitations="Il GPS può riportare l'ultimo fix valido, anche minuti prima."))
        else:
            d = (dto.dt_local - gps.dt_utc.replace(tzinfo=None)).total_seconds()
            hours = d / 3600
            q = round(d / 900) * 900
            if abs(d - q) <= 120 and abs(hours) <= 14:
                f.append(Finding(Category.TEMPORAL, Level.INFO, "Fuso orario dedotto dal GPS",
                                 f"La differenza tra ora locale EXIF e UTC del GPS è {q / 3600:+.2f} h, compatibile "
                                 f"con il fuso UTC{q / 3600:+.2f}.", "Confronto EXIF/GPS", MODULE,
                                 evidence=f"{dto.raw} / {gps.raw}",
                                 limitations="Deduzione, non dato dichiarato: verificare con il luogo e l'ora legale."))
            else:
                f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Orario GPS incoerente con lo scatto",
                                 f"Scarto di {d:+.0f} s non riconducibile a un fuso orario.", "Confronto EXIF/GPS",
                                 MODULE, evidence=f"{dto.raw} / {gps.raw}", confidence="media",
                                 limitations="Il GPS può riportare l'ultimo fix valido, anche minuti prima."))
    # Contenitore video: tracce e modifica
    cont = [e for e in ev if e.kind in ("contenitore", "modifica") and e.utc and
            re.match(r"^(QuickTime|Track\d+|moov)", e.source)]
    creations = [e for e in cont if "Create" in e.source or e.source.endswith(".creation")]
    if len(creations) > 1:
        ts = [e.dt_utc for e in creations]
        spread = (max(ts) - min(ts)).total_seconds()
        if spread > 2:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "Tempi di creazione diversi tra filmato e tracce",
                             f"Le date di creazione di movie/tracce/media differiscono fino a {spread:.0f} s.",
                             meth, MODULE, evidence="\n".join(f"{e.source} = {e.utc}" for e in creations),
                             confidence="media",
                             limitations="Compatibile con montaggio o remux; alcuni dispositivi scrivono comunque "
                                         "valori diversi per traccia."))
    mods = [e for e in cont if "Modify" in e.source or e.source.endswith(".modification")]
    for m in mods:
        twin = next((c for c in creations if c.source.replace("Create", "Modify") == m.source or
                     c.source.replace(".creation", ".modification") == m.source), None)
        if twin and abs((m.dt_utc - twin.dt_utc).total_seconds()) > 2:
            f.append(Finding(Category.TEMPORAL, Level.SUSPICIOUS, "Contenitore modificato dopo la creazione",
                             f"{m.source} differisce da {twin.source}.", meth, MODULE,
                             evidence=f"{twin.utc} → {m.utc}", confidence="media",
                             limitations="Indica una riscrittura del contenitore (editing, remux, alcuni "
                                         "trasferimenti)."))
            break
    fs_m = _first(ev, "Filesystem:modifica")
    cap = dto or _first(ev, "QuickTime:CreateDate", "Keys:CreationDate")
    if fs_m and cap:
        ref = cap.dt_utc if cap.utc else cap.dt_local.replace(tzinfo=timezone.utc)
        tol = timedelta(hours=14) if not cap.utc else timedelta(minutes=2)
        if fs_m.dt_utc < ref - tol:
            f.append(Finding(Category.TEMPORAL, Level.ANOMALY, "File modificato prima dello scatto",
                             f"La data di modifica nel filesystem ({fs_m.utc}) precede l'acquisizione dichiarata "
                             f"({cap.raw}).", meth, MODULE, confidence="media", significant=True,
                             limitations="I tempi del filesystem cambiano con copie e trasferimenti e non "
                                         "rappresentano la data di acquisizione."))
    if not any(e.kind in ("acquisizione", "contenitore", "digitalizzazione") and (e.utc or e.local) for e in ev):
        f.append(Finding(Category.TEMPORAL, Level.UNDETERMINED, "Nessuna data di acquisizione nei metadati",
                         "Il file non dichiara quando è stato acquisito; restano solo i tempi del filesystem.", meth,
                         MODULE, limitations="I tempi del filesystem non rappresentano la data di acquisizione."))
    return f


def timeline(ev: list[TimeEvent]) -> list[dict]:
    def key(e: TimeEvent):
        if e.utc:
            return (0, e.utc)
        if e.local:
            return (1, e.local)
        return (2, e.raw)
    return [e.to_dict() for e in sorted(ev, key=key)]
