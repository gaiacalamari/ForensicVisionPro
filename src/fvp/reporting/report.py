"""Reporting Engine: JSON (completo, macchina) e HTML (autocontenuto, stampabile).

Il report separa i risultati automatici dalle valutazioni dell'operatore e non
contiene alcun giudizio complessivo di autenticità generato dal software.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .. import APP_NAME, __version__
from ..cases.store import Case
from ..core.audit import utc_now
from ..core.findings import Category, category_status

METHODOLOGY = [
    ("Acquisizione", "Il reperto è copiato in una cartella del caso calcolando gli hash durante la lettura; la "
                     "copia è verificata con una seconda lettura indipendente e resa di sola lettura. I tempi del "
                     "filesystem dell'originale sono registrati prima della lettura."),
    ("Integrità", "Gli hash della copia di lavoro sono ricalcolati prima e dopo ogni analisi e confrontati con "
                  "quelli dell'acquisizione."),
    ("Struttura", "Parsing read-only dei marker JPEG, dei chunk PNG (con verifica CRC-32) e degli atom ISO BMFF, "
                  "con ricerca di dati accodati, strutture troncate e incoerenze."),
    ("Metadati", "Estrazione con ExifTool (tutti i gruppi, tag duplicati e sconosciuti inclusi); ogni tag è "
                 "classificato come calcolato, dichiarato nel file o relativo al filesystem della copia."),
    ("Analisi temporale", "Normalizzazione in UTC solo quando il fuso è dichiarato o previsto dalla specifica; "
                          "confronto tra EXIF, XMP, GPS, contenitore e filesystem dell'originale."),
    ("Immagine", "Error Level Analysis (ricompressione JPEG q90), mappa del residuo di rumore (mediano 3x3, "
                 "deviazione standard su blocchi 16x16), confronto localizzato miniatura EXIF / immagine."),
    ("Storia JPEG", "ELA a 8 qualità (60–95) con persistenza delle anomalie per blocco; JPEG ghost (Farid, 2009) su "
                    "qualità 40–95; periodicità degli istogrammi DCT dei primi 9 modi AC (Popescu & Farid, 2004); "
                    "allineamento della griglia 8x8 tramite differenze seconde."),
    ("Filtro mediano", "Frazione di pixel invariati dopo un mediano 3x3, globale e per blocchi 32x32; segnalate solo "
                       "le regioni molto più stabili del resto dell'immagine."),
    ("Copy-move", "Punti SIFT confrontati con l'immagine stessa (g2NN, rapporto 0,5, distanza minima 40 px) e verifica "
                  "geometrica RANSAC di una trasformazione di similitudine (Amerini et al., 2011). Ogni gruppo è poi "
                  "confermato riallineando i pixel (correlazione normalizzata ≥ 0,85) e scartato come ripetizione "
                  "naturale se la zona è testuale."),
    ("Contenuti nascosti", "Estrazione del flusso dei bit meno significativi in 56 combinazioni (immagini) e 4 (audio "
                           "WAV), con ricerca di file, frasi in qualunque punto del flusso, messaggi con prefisso di "
                           "lunghezza (2, 4, 8 byte), testo in Base64 e intestazioni di strumenti; testo nei campi dei "
                           "metadati e frasi leggibili nei byte del file fuori dalle aree di metadati; spazi non "
                           "standard dei BMP; segni a bassissimo contrasto su zone uniformi; chi-quadro sui "
                           "coefficienti DCT dei JPEG (attacco a JSteg)."),
    ("Steganalisi", "RS steganalysis (Fridrich et al., 2001) e attacco chi-quadro sequenziale (Westfeld & Pfitzmann, "
                    "1999) per canale, solo su formati senza perdita."),
    ("PRNU", "Residuo di rumore con filtro di Wiener adattivo, impronta di massima verosimiglianza su immagini di "
             "riferimento, PCE con soglia 60 sul ritaglio centrale 1024x1024 (Lukáš, Fridrich & Goljan, 2006)."),
    ("Video", "FFprobe: contenitore, stream, codec, frame rate, durate, encoder e tempi."),
]
LIMITS = ("Nessun risultato automatico costituisce da solo prova di autenticità o di manipolazione. I metadati "
          "dichiarati sono modificabili. Gli algoritmi probabilistici producono falsi positivi e falsi negativi e "
          "vanno interpretati dall'operatore. L'assenza di anomalie significa solo che i test eseguiti non ne hanno "
          "rilevate. I moduli non eseguiti sono indicati in grigio.")


def collect(case: Case) -> dict:
    exhibits = []
    for ex in case.exhibits():
        an = case.analyses(ex.id)
        last = an[-1] if an else None
        executed = {Category(c) for c in (last["results"].get("executed_categories", []) if last else [])}
        status = category_status(last["findings"], executed) if last else {}
        exhibits.append({"exhibit": ex.__dict__, "analysis": last, "status": {k.value: v.value for k, v in status.items()},
                         "notes": case.notes(ex.id), "analyses_count": len(an)})
    v = case.audit.verify()
    return {"generated_utc": utc_now(), "app": f"{APP_NAME} {__version__}", "case": case.info, "exhibits": exhibits,
            "custody": case.audit.entries(kind="custody"), "audit": case.audit.entries(),
            "audit_verification": {"ok": v.ok, "entries": v.entries, "head_hash": v.head, "broken_at": v.broken_at,
                                   "reason": v.reason}, "methodology": METHODOLOGY, "limitations": LIMITS}


def _jsonable(o):
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


def write_json(case: Case, out: Path) -> Path:
    data = collect(case)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_jsonable), encoding="utf-8")
    _register(case, out, "json")
    return out


def write_csv_findings(case: Case, out: Path) -> Path:
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["reperto", "file", "area", "livello", "titolo", "spiegazione", "cosa fare", "descrizione tecnica",
                    "metodo", "evidenza", "offset", "confidenza", "limiti", "fonte", "modulo"])
        for ex in case.exhibits():
            an = case.analyses(ex.id)
            if not an:
                continue
            from ..core import explain
            for f in an[-1]["findings"]:
                w.writerow([ex.id, ex.original_name, explain.CATEGORY_LABELS[f.category], explain.LEVEL_PLAIN[f.level],
                            f.title, explain.plain_explanation(f), explain.next_step(f), f.description, f.method,
                            f.evidence, f.offset if f.offset is not None else "", f.confidence, f.limitations,
                            f.source, f.module])
    _register(case, out, "csv")
    return out


def _register(case: Case, out: Path, kind: str) -> None:
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    case.audit.append(case.info.get("operator", ""), "report_generato", {"format": kind, "path": str(out), "sha256": h})


def write_html(case: Case, out: Path) -> Path:
    from .html_report import render
    out.write_text(render(case, collect(case)), encoding="utf-8")
    _register(case, out, "html")
    return out
