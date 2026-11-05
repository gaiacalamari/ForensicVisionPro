"""Traduzione dei risultati in linguaggio comprensibile, condivisa da interfaccia e report.

Nessun testo qui esprime un giudizio di autenticità: si descrive cosa è stato trovato, cosa può significare e
cosa conviene verificare. Le frasi sono costruite solo dai risultati dei moduli (nessuna generazione libera).
"""
from __future__ import annotations

import re
from pathlib import Path

from .findings import Category, Finding, Level, Status, category_status

CATEGORY_LABELS = {
    Category.INTEGRITY: "Integrità del file", Category.METADATA: "Metadati",
    Category.TEMPORAL: "Date e orari", Category.IMAGE_MANIPULATION: "Possibili modifiche all'immagine",
    Category.AI_GENERATION: "Intelligenza artificiale", Category.DEEPFAKE: "Deepfake",
    Category.VIDEO_INTEGRITY: "Video", Category.AUDIO_INTEGRITY: "Audio",
    Category.FILE_STRUCTURE: "Struttura del file", Category.STEGANOGRAPHY: "Contenuti nascosti",
    Category.SENSOR: "Fotocamera di origine",
}
CATEGORY_HELP = {
    Category.INTEGRITY: "Conferma che il file analizzato è identico a quello acquisito (hash invariati).",
    Category.METADATA: "Informazioni scritte nel file da fotocamera o programmi: modello, software, autore.",
    Category.TEMPORAL: "Coerenza tra le date e gli orari registrati nel file e nel sistema.",
    Category.IMAGE_MANIPULATION: "Tracce lasciate da ritocchi, copie di regioni, ricompressioni o filtri.",
    Category.AI_GENERATION: "Indizi, nei metadati, di creazione o modifica con strumenti di intelligenza artificiale.",
    Category.DEEPFAKE: "Analisi di volti manipolati nei video (non inclusa in questa versione).",
    Category.VIDEO_INTEGRITY: "Coerenza di tracce, durate e codifica dei video.",
    Category.AUDIO_INTEGRITY: "Coerenza delle tracce audio.",
    Category.FILE_STRUCTURE: "Correttezza interna del file: parti mancanti, dati aggiunti, formato reale.",
    Category.STEGANOGRAPHY: "Messaggi, file o testo nascosti dentro l'immagine o nei suoi dati.",
    Category.SENSOR: "Confronto con l'impronta del sensore di fotocamere note (PRNU).",
}
LEVEL_PLAIN = {
    Level.EVIDENCE: "Fatto accertato", Level.ANOMALY: "Anomalia", Level.SUSPICIOUS: "Da verificare",
    Level.PROBABILISTIC: "Indicazione statistica", Level.UNDETERMINED: "Non verificabile", Level.INFO: "Informazione",
}
LEVEL_HELP = {
    Level.EVIDENCE: "Un fatto oggettivo e ripetibile (ad esempio dati estratti o una struttura danneggiata).",
    Level.ANOMALY: "Qualcosa che si discosta da quanto previsto dagli standard o dal comportamento normale.",
    Level.SUSPICIOUS: "Un elemento compatibile con una modifica o un occultamento, che ha però anche spiegazioni lecite.",
    Level.PROBABILISTIC: "L'esito di un calcolo statistico o di una mappa da interpretare: da solo non indica nulla.",
    Level.UNDETERMINED: "Il controllo non ha potuto concludere (formato non adatto, dati mancanti).",
    Level.INFO: "Un'informazione utile, nessuna anomalia.",
}
STATUS_PLAIN = {Status.GREEN: "Nessun problema rilevato", Status.YELLOW: "Da approfondire",
                Status.RED: "Richiede attenzione", Status.GREY: "Non verificato"}
STATUS_HELP = {Status.GREEN: "I controlli eseguiti non hanno trovato anomalie (non è una garanzia di autenticità).",
               Status.YELLOW: "Ci sono elementi da guardare, con spiegazioni anche normali.",
               Status.RED: "Almeno un elemento rilevante da esaminare con attenzione.",
               Status.GREY: "Controllo non eseguito, non applicabile al formato o senza esito."}

# (espressione sul titolo, spiegazione semplice, cosa fare, pagina dell'app, mappa collegata)
RULES: list[tuple[str, str, str, str, str | None]] = [
    (r"^Contenuto nascosto estratto", "Nei bit meno significativi dei pixel (o dei campioni audio) è nascosto un contenuto "
     "che il programma è riuscito a estrarre e leggere. È il segno tipico della steganografia.",
     "Leggi il contenuto estratto e valutane il significato; conserva il file estratto (il suo hash è nel report).",
     "Steganalysis", "lsb"),
    (r"^Testo leggibile in aree non previste", "Nel file ci sono frasi leggibili in punti dove normalmente non c'è testo, "
     "ad esempio dopo la fine dell'immagine.", "Leggi il testo nell'evidenza e verifica la posizione con l'Hex Viewer.",
     "Hex Viewer", None),
    (r"^Contenuti codificati nei metadati", "Alcuni campi descrittivi del file contengono dati codificati (ad esempio "
     "Base64) che, decodificati, diventano testo o file.", "Leggi il contenuto decodificato riportato nell'evidenza.",
     "Metadata Analyzer", None),
    (r"^Possibili segni quasi invisibili", "In una zona uniforme ci sono segni di colore quasi identico allo sfondo, "
     "disposti come lettere o righe: potrebbe essere testo reso invisibile all'occhio.",
     "Apri la mappa 'Contrasto esaltato' e osserva l'area indicata.", "Image Forensics", "faint"),
    (r"^Byte di riempimento delle righe non nulli|^Dati tra intestazione e pixel|^Campi riservati",
     "Il file BMP contiene dati in spazi che dovrebbero essere vuoti: è un modo noto per nascondere informazioni.",
     "Esamina i byte indicati con l'Hex Viewer.", "Hex Viewer", None),
    (r"^Coefficienti DCT compatibili", "Le statistiche della compressione JPEG sono compatibili con un programma che "
     "nasconde dati nei coefficienti (tipo JSteg).", "Considera un'analisi con strumenti specifici e, se possibile, "
     "il confronto con l'originale.", "Steganalysis", None),
    (r"^Stima RS elevata ma poco affidabile", "Il test statistico sui pixel dà un valore alto, ma l'immagine ha molte "
     "zone completamente uniformi che falsano il calcolo: da solo non indica dati nascosti.",
     "Fa fede l'estrazione dei contenuti: controlla se ha trovato qualcosa.", "Steganalysis", None),
    (r"^Stima RS elevata", "Il test statistico stima che una parte dei pixel abbia l'ultimo bit modificato, come accade "
     "quando si nascondono dati.", "Controlla la scheda 'Contenuti estratti'; se è vuota, i dati potrebbero essere "
     "cifrati.", "Steganalysis", "lsb"),
    (r"^Chi-quadro compatibile", "Le statistiche dei pixel all'inizio dell'immagine sono compatibili con un messaggio "
     "inserito in sequenza.", "Controlla la scheda 'Contenuti estratti'.", "Steganalysis", "lsb"),
    (r"^Statistiche LSB non compatibili", "I bit meno significativi sembrano completamente casuali, cosa insolita per "
     "una fotografia: possibile riempimento con dati.", "Controlla la scheda 'Contenuti estratti'.", "Steganalysis", "lsb"),
    (r"^Regioni duplicate", "Due zone dell'immagine sono praticamente identiche anche pixel per pixel: è il segno tipico "
     "di una parte copiata e incollata (per coprire o duplicare qualcosa).", "Apri la mappa 'Copy-move' e confronta le "
     "due aree collegate.", "Image Forensics", "copymove"),
    (r"^Elementi ripetuti, non confermati", "Il programma ha trovato parti simili, ma si tratta con ogni probabilità di "
     "scritte o motivi che si ripetono naturalmente: non è stata confermata una copia.",
     "Nessuna azione necessaria, salvo dubbi specifici sull'area.", "Image Forensics", "copymove"),
    (r"^JPEG ghost", "Una zona dell'immagine sembra essere stata salvata in passato con una qualità diversa dal resto: "
     "succede quando si inserisce un pezzo proveniente da un'altra immagine.", "Apri la mappa 'JPEG ghost' e osserva "
     "l'area indicata.", "Image Forensics", "ghost"),
    (r"^Regione con elaborazione diversa", "Una zona ha caratteristiche diverse dal resto (più levigata o compressa "
     "diversamente), come avviene dopo un ritocco locale.", "Apri la mappa 'Stabilità sotto filtro mediano'.",
     "Image Forensics", "median"),
    (r"^Indizi di doppia compressione", "L'immagine è stata salvata in JPEG almeno due volte. È normale per foto "
     "modificate ma anche per foto solo inviate o ricondivise.", "Valuta insieme agli altri indizi.", "Image Forensics",
     "ela_multi"),
    (r"^Griglia JPEG non allineata", "L'immagine è stata probabilmente ritagliata dopo essere stata salvata in JPEG.",
     "Valuta se un ritaglio è coerente con la storia dichiarata del file.", "Image Forensics", None),
    (r"^Storia di compressione JPEG", "L'immagine è stata JPEG prima di essere salvata in questo formato: non è un "
     "originale senza perdita.", "Valuta se è coerente con quanto dichiarato sulla provenienza.", "Image Forensics", None),
    (r"^Contenuto della miniatura diverso|^Proporzioni della miniatura", "La piccola anteprima salvata nel file non "
     "corrisponde all'immagine: spesso succede quando l'immagine viene modificata con un programma che non aggiorna "
     "l'anteprima.", "Confronta la miniatura con l'immagine nell'area indicata.", "Image Forensics", None),
    (r"^Software di elaborazione", "Il file dichiara di essere stato salvato da un programma di modifica o conversione.",
     "Accerta se e come il file è stato elaborato; il dato è modificabile.", "Metadata Analyzer", None),
    (r"^Metadati riferiti a generazione AI", "I metadati citano strumenti di intelligenza artificiale o dichiarano un "
     "contenuto generato.", "Verifica la provenienza dichiarata; i metadati possono essere aggiunti o rimossi.",
     "AI Detection", None),
    (r"^Data futura|^Data impossibile|^Data anteriore", "Una data registrata nel file è impossibile o fuori dal normale.",
     "Verifica l'orologio del dispositivo e la storia del file.", "Timeline Analyzer", None),
    (r"^ModifyDate precedente", "La data di modifica risulta precedente a quella dello scatto: le date sono state "
     "alterate o l'orologio era impostato male.", "Confronta tutte le date nella pagina Date e orari.",
     "Timeline Analyzer", None),
    (r"^File salvato dopo lo scatto", "Il file è stato salvato di nuovo dopo lo scatto (modifica, rotazione o "
     "esportazione).", "Valuta insieme al software dichiarato.", "Timeline Analyzer", None),
    (r"^Orario GPS incoerente", "L'orario del GPS non corrisponde a quello dello scatto.", "Verifica fuso orario e "
     "impostazioni del dispositivo.", "Timeline Analyzer", None),
    (r"^File modificato prima dello scatto|^Tempi di creazione diversi|^Contenitore modificato", "Le date nel file non "
     "sono coerenti tra loro.", "Confronta tutte le date nella pagina Date e orari.", "Timeline Analyzer", None),
    (r"^Dati dopo la fine|^Dati dopo IEND|^Dati dopo la matrice", "Dopo la fine dell'immagine ci sono dati aggiuntivi, "
     "che non vengono mostrati: possono essere innocui o un file nascosto.", "Esamina i byte con l'Hex Viewer.",
     "Hex Viewer", None),
    (r"^Firme di altri formati", "All'interno del file ci sono le intestazioni di altri tipi di file (es. un archivio).",
     "Esamina gli offset indicati con l'Hex Viewer.", "Hex Viewer", None),
    (r"^Estensione non coerente", "Il nome del file indica un formato diverso da quello reale.",
     "Considera il formato reale indicato.", "Hex Viewer", None),
    (r"^EOI mancante|^IEND mancante|^Chunk troncato|^Segmento troncato|^Matrice dei pixel troncata|^Atom",
     "Il file è incompleto o danneggiato.", "Verifica la fonte del file e, se possibile, recupera una copia integra.",
     "Hex Viewer", None),
    (r"^CRC errato", "Una parte del file è stata alterata o si è danneggiata dopo il salvataggio.",
     "Verifica la fonte del file.", "Hex Viewer", None),
    (r"^Compatibile con il sensore", "Il rumore dell'immagine è compatibile con quello di una fotocamera di cui è "
     "registrata l'impronta.", "Valuta il valore PCE e la qualità delle immagini di riferimento.", "PRNU / Sensore",
     "prnu_local"),
    (r"^Formato non riconosciuto", "Il programma non riconosce il tipo di file dai suoi primi byte.",
     "Esamina l'inizio del file con l'Hex Viewer.", "Hex Viewer", None),
    (r"^Durata audio e video diverse", "Audio e video hanno durate molto diverse, come può succedere dopo un montaggio.",
     "Riproduci il file e controlla la sincronia.", "Video Forensics", None),
    (r"^Encoder dichiarato", "Il file dichiara il programma usato per codificarlo o impacchettarlo.",
     "Valuta se è coerente con la provenienza dichiarata.", "Video Forensics", None),
]


def rule_for(f: Finding):
    for rx, plain, todo, page, art in RULES:
        if re.search(rx, f.title):
            return plain, todo, page, art
    return None


def plain_explanation(f: Finding) -> str:
    r = rule_for(f)
    return r[0] if r else f.description


def next_step(f: Finding) -> str:
    r = rule_for(f)
    return r[1] if r else ""


def related_page(f: Finding) -> str | None:
    r = rule_for(f)
    return r[2] if r else None


def related_map(f: Finding) -> str | None:
    r = rule_for(f)
    return r[3] if r else None


SEVERITY = {Level.EVIDENCE: 0, Level.ANOMALY: 1, Level.SUSPICIOUS: 2, Level.PROBABILISTIC: 3, Level.UNDETERMINED: 4,
            Level.INFO: 5}


def needs_attention(f: Finding) -> bool:
    if f.category == Category.INTEGRITY:
        return f.level == Level.EVIDENCE
    return f.level in (Level.EVIDENCE, Level.ANOMALY, Level.SUSPICIOUS) or (f.significant and f.level != Level.INFO)


def attention(findings: list[Finding]) -> list[Finding]:
    return sorted([f for f in findings if needs_attention(f)], key=lambda f: (SEVERITY[f.level], not f.significant))


def status_of(analysis: dict | None) -> dict[Category, Status]:
    if not analysis:
        return {}
    ex = {Category(c) for c in analysis["results"].get("executed_categories", [])}
    return category_status(analysis["findings"], ex)


def overall(analysis: dict | None) -> Status:
    if not analysis:
        return Status.GREY
    st = status_of(analysis).values()
    if Status.RED in st:
        return Status.RED
    if Status.YELLOW in st:
        return Status.YELLOW
    return Status.GREEN if Status.GREEN in st else Status.GREY


def kind_of(analysis: dict | None) -> str:
    fmt = (analysis or {}).get("results", {}).get("signature", {}).get("format")
    if fmt in ("jpeg", "png", "gif", "tiff", "bmp", "webp", "heif", "avif"):
        return "immagine"
    if fmt in ("mp4", "mov", "3gp", "avi", "mkv", "webm", "mpeg_ps", "mpeg_ts", "m2ts"):
        return "video"
    if fmt in ("wav", "mp3", "flac", "ogg", "aac"):
        return "audio"
    return "file"


def hidden_items(analysis: dict | None) -> list[dict]:
    """Contenuti nascosti effettivamente estratti o letti (testo, file, dati codificati)."""
    if not analysis:
        return []
    r = analysis["results"]
    out = []
    for h in r.get("stegointel", {}).get("hits", []):
        txt = ""
        if h.get("file") and h.get("ext") == "txt" and Path(h["file"]).is_file():
            txt = Path(h["file"]).read_text(encoding="utf-8", errors="replace")
        out.append({"source": "pixel" if h.get("channels") != "campioni PCM" else "audio", "what": h["detail"],
                     "text": txt or h.get("preview", ""), "file": h.get("file"), "sha256": h.get("sha256"),
                     "size": h.get("size"), "how": f"{h['channels']} · {h['bits']} bit · ordine {h['order']} · "
                                                    f"{'MSB' if h['msb_first'] else 'LSB'} prima"})
    for f in analysis["findings"]:
        if f.title.startswith("Testo leggibile in aree non previste"):
            for hh in f.data.get("hits", [])[:5]:
                out.append({"source": "file", "what": f"Testo nel file ({hh['location']})", "text": hh["text"],
                            "file": None, "sha256": None, "size": None, "how": f"offset 0x{hh['offset']:X}"})
        if f.title.startswith("Contenuti codificati nei metadati"):
            for e in f.data.get("encoded", [])[:5]:
                out.append({"source": "metadati", "what": "Dato codificato nei metadati", "text": e, "file": None,
                            "sha256": None, "size": None, "how": ""})
    return out


def _fmt_list(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


def exhibit_summary(ex, analysis: dict | None) -> str:
    """Riepilogo discorsivo di un reperto (testo semplice, frasi complete)."""
    name = ex.original_name
    if not analysis:
        return f"Il file {name} è stato acquisito ma non ancora analizzato."
    r = analysis["results"]
    kind = kind_of(analysis)
    sig = r.get("signature", {})
    info = r.get("image_info") or {}
    dims = f" di {info['width']}×{info['height']} pixel" if info.get("width") else ""
    art = {"immagine": "un’immagine", "video": "un video", "audio": "un file audio", "file": "un file"}[kind]
    parts = [f"{name} è {art} {sig.get('format_name', '')}{dims}."]
    if not sig.get("extension_matches", True) and sig.get("format"):
        parts.append(f"Attenzione: il nome termina con «{sig.get('extension')}» ma il formato reale è "
                     f"{sig.get('format_name')}.")
    parts.append("Il file analizzato è identico a quello acquisito (impronte hash invariate)." if analysis["integrity_ok"]
                 else "ATTENZIONE: il file è cambiato durante l'analisi (impronte hash diverse).")
    att = attention(analysis["findings"])
    hidden = hidden_items(analysis)
    if hidden:
        h = hidden[0]
        preview = re.sub(r"\s+", " ", h["text"] or "").strip()[:140]
        what = re.sub(r"\s*\(.*?\)", "", h["what"]).lower()
        parts.append(f"È stato trovato un contenuto nascosto – {what}" + (f": «{preview}»." if preview else "."))
    if att:
        titles = [f"«{f.title}» ({CATEGORY_LABELS[f.category].lower()})" for f in att[:4]]
        n = len(att)
        parts.append(f"{'Un elemento merita' if n == 1 else f'{n} elementi meritano'} attenzione: {_fmt_list(titles)}"
                     + (" e altri." if n > 4 else "."))
    else:
        parts.append("I controlli eseguiti non hanno evidenziato elementi da segnalare.")
    undet = [CATEGORY_LABELS[c].lower() for c, st in status_of(analysis).items()
             if st == Status.GREY and c in {Category(x) for x in r.get("executed_categories", [])}]
    if undet:
        parts.append(f"Non è stato possibile verificare: {_fmt_list(undet)}.")
    return " ".join(parts)


def case_summary(exhibits: list[tuple]) -> dict:
    """exhibits: [(Exhibit, analysis|None)]. Restituisce testo e numeri per la sintesi iniziale."""
    n = len(exhibits)
    analysed = [(e, a) for e, a in exhibits if a]
    kinds: dict[str, int] = {}
    for _e, a in analysed:
        kinds[kind_of(a)] = kinds.get(kind_of(a), 0) + 1
    red = [(e, a) for e, a in analysed if overall(a) == Status.RED]
    yellow = [(e, a) for e, a in analysed if overall(a) == Status.YELLOW]
    clean = [(e, a) for e, a in analysed if overall(a) == Status.GREEN]
    hidden = [(e, a) for e, a in analysed if hidden_items(a)]
    integrity_bad = [e for e, a in analysed if not a["integrity_ok"]]
    kind_txt = _fmt_list([f"{v} {k if v == 1 else {'immagine': 'immagini', 'video': 'video', 'audio': 'audio', 'file': 'file'}[k]}"
                          for k, v in kinds.items()])
    s = [f"Sono stati analizzati {len(analysed)} file su {n} acquisiti" + (f" ({kind_txt})." if kind_txt else ".")]
    s.append("Tutti i file analizzati sono rimasti identici a quelli acquisiti: le impronte hash coincidono prima e "
             "dopo ogni analisi." if not integrity_bad else
             f"ATTENZIONE: {len(integrity_bad)} file risultano cambiati durante l'analisi.")
    for e_, a_ in hidden:
        h = hidden_items(a_)[0]
        txt = re.sub(r"\s+", " ", h["text"] or "").strip()
        what = re.sub(r"\s*\(.*?\)", "", h["what"]).lower()
        s.append(f"In {e_.original_name} è stato trovato un contenuto nascosto – {what}"
                 + (f": «{txt[:120]}{'…' if len(txt) > 120 else ''}»." if txt else "."))
    if red:
        s.append(f"{len(red)} file {'richiede' if len(red) == 1 else 'richiedono'} attenzione: "
                 + _fmt_list([e.original_name for e, _ in red]) + ".")
    if yellow:
        s.append(f"{len(yellow)} file {'presenta' if len(yellow) == 1 else 'presentano'} elementi da approfondire: "
                 + _fmt_list([e.original_name for e, _ in yellow]) + ".")
    if clean:
        s.append(f"In {len(clean)} file i controlli non hanno trovato elementi da segnalare: "
                 + _fmt_list([e.original_name for e, _ in clean]) + ".")
    s.append("Nessuno di questi risultati, da solo, dimostra che un file sia autentico o falsificato: indicano dove "
             "concentrare la verifica dell'analista.")
    top = []
    for e, a in analysed:
        for f in attention(a["findings"]):
            top.append((SEVERITY[f.level], not f.significant, e, f))
    top.sort(key=lambda t: (t[0], t[1]))
    return {"text": " ".join(s), "files": n, "analysed": len(analysed), "attention_files": len(red) + len(yellow),
            "red": len(red), "hidden_files": len(hidden), "integrity_ok": not integrity_bad,
            "top": [(e, f) for _s, _g, e, f in top]}
