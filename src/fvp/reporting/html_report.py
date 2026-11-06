"""Report HTML 1.1: autocontenuto, leggibile anche da chi non è esperto.

Struttura: sintesi in linguaggio naturale → punti di attenzione del caso → panoramica dei reperti → una scheda per
reperto (riepilogo discorsivo, elementi da verificare con collegamenti ai dettagli, contenuti nascosti, mappe,
tutti i controlli, dati tecnici) → metodo e limiti → glossario → catena di custodia.
Funziona senza JavaScript (sezioni espandibili native); lo script aggiunge filtro, espandi/comprimi, ingrandimento
delle immagini e apertura automatica dei dettagli in stampa.
"""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

from PIL import Image

from ..cases.store import Case
from ..core import explain
from ..core.findings import Category, Finding, Level, Status
from ..engines import heif_support

heif_support.ensure_registered()      # anteprime HEIC nel report

STATUS_CLASS = {Status.GREEN: "ok", Status.YELLOW: "warn", Status.RED: "alert", Status.GREY: "na"}
LEVEL_CLASS = {Level.EVIDENCE: "alert", Level.ANOMALY: "alert", Level.SUSPICIOUS: "warn", Level.PROBABILISTIC: "stat",
               Level.UNDETERMINED: "na", Level.INFO: "info"}
MAP_HELP = {
    "ela": "Zone che si ricomprimono in modo diverso dal resto risultano più chiare. Bordi e dettagli fini sono "
           "sempre chiari: conta il confronto tra zone simili.",
    "ela_multi": "Come la precedente, ma su otto livelli di qualità: restano evidenti solo le differenze persistenti.",
    "ghost": "Le zone scure sono quelle che 'ricordano' una compressione precedente a qualità più bassa.",
    "noise": "Il rumore naturale della fotocamera: una zona con rumore molto diverso da aree simili è sospetta.",
    "median": "Le zone chiare sono più 'levigate' del resto, come dopo un ritocco locale o un filtro.",
    "copymove": "Le linee collegano parti dell'immagine molto simili tra loro; i contorni delimitano le aree.",
    "lsb": "L'ultimo bit di ogni pixel reso visibile. In una foto normale appare come rumore uniforme; forme, "
           "bande o zone regolari indicano dati inseriti.",
    "faint": "Il contrasto delle zone uniformi è amplificato: scritte o segni quasi invisibili diventano visibili.",
    "faces": "Volti rilevati automaticamente (riquadri).",
    "prnu_local": "Quanto ogni zona corrisponde all'impronta del sensore: zone scure in aree simili sono sospette.",
}
GLOSSARY = [
    ("Hash (impronta digitale)", "Un codice calcolato dal contenuto del file: se cambia anche un solo byte, cambia "
     "l'hash. Serve a dimostrare che il file analizzato è identico a quello acquisito."),
    ("Metadati / EXIF", "Informazioni scritte nel file da fotocamera o programmi (modello, data, software, GPS). "
     "Possono essere modificate da chiunque."),
    ("Steganografia", "Tecnica per nascondere un messaggio o un file dentro un'immagine o un audio senza che si veda."),
    ("LSB (bit meno significativo)", "L'ultima cifra binaria del valore di un pixel: cambiarla non altera l'aspetto "
     "dell'immagine, per questo è usata per nascondere dati."),
    ("ELA (Error Level Analysis)", "Ricomprime l'immagine e mostra quanto ogni zona cambia: zone ritoccate possono "
     "comportarsi diversamente."),
    ("JPEG ghost", "Tecnica che individua zone salvate in passato con una qualità JPEG diversa dal resto."),
    ("Copy-move", "Parte di un'immagine copiata e incollata in un altro punto della stessa immagine."),
    ("PRNU", "Rumore unico di ogni sensore fotografico, usato per verificare se un'immagine è compatibile con una "
     "determinata fotocamera."),
    ("Offset", "Posizione di un byte all'interno del file, contata dall'inizio."),
    ("Falso positivo", "Un segnale del programma che, verificato, risulta avere una spiegazione normale."),
    ("Catena di custodia", "Registro cronologico di chi ha acquisito, maneggiato e analizzato i reperti."),
]


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def img_uri(path: str | Path | None, max_side: int = 1400, quality: int = 80) -> str:
    if not path or not Path(path).is_file():
        return ""
    try:
        with Image.open(path) as im:
            im.load()
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            im = im.convert("RGB")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - un'immagine non decodificabile non blocca il report
        return ""


def chip(st: Status) -> str:
    return f"<span class='chip {STATUS_CLASS[st]}' title='{e(explain.STATUS_HELP[st])}'>{e(explain.STATUS_PLAIN[st])}</span>"


def lvl(f: Finding) -> str:
    return (f"<span class='chip {LEVEL_CLASS[f.level]}' title='{e(explain.LEVEL_HELP[f.level])}'>"
            f"{e(explain.LEVEL_PLAIN[f.level])}</span>")


def fid(ex_id: str, f: Finding) -> str:
    return f"f-{ex_id}-{f.id}"


CSS = """
:root{--bg:#f4f6f8;--card:#fff;--ink:#1d2732;--muted:#5c6977;--rule:#d9dee4;--soft:#eef2f5;--accent:#2a6a98;
--ok:#2e7d4f;--ok-bg:#e6f3ec;--warn:#9a6b00;--warn-bg:#fdf3dc;--alert:#b3261e;--alert-bg:#fbe7e5;--na:#5f6b78;
--na-bg:#eceff2;--stat:#2f69ad;--stat-bg:#e6eef8;--info:#5c6977;--info-bg:#f1f3f5}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:70px}
body{margin:0;font:15px/1.55 "Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--accent)}code,.mono{font-family:Consolas,"DejaVu Sans Mono",monospace;font-size:12.5px;word-break:break-all}
.top{position:sticky;top:0;z-index:20;background:var(--card);border-bottom:1px solid var(--rule);display:flex;gap:16px;
align-items:center;padding:10px 24px}
.top .title{font-weight:600}.top .sp{flex:1}.top label{font-size:13px;color:var(--muted)}
.btn{display:inline-block;border:1px solid var(--rule);background:var(--card);color:var(--ink);border-radius:6px;
padding:5px 11px;font-size:13px;text-decoration:none;cursor:pointer}
.btn:hover{border-color:var(--accent)}.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:28px;max-width:1360px;margin:0 auto;padding:24px}
nav.toc{position:sticky;top:76px;align-self:start;max-height:calc(100vh - 100px);overflow:auto;font-size:13.5px}
nav.toc a{display:block;padding:4px 10px;border-left:3px solid transparent;color:var(--ink);text-decoration:none}
nav.toc a:hover{border-left-color:var(--accent);background:var(--soft)}nav.toc .h{margin:14px 0 4px;color:var(--muted);
font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
nav.toc .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
main{min-width:0}section{margin-bottom:34px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:21px;margin:0 0 12px}h3{font-size:16.5px;margin:22px 0 10px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:20px 22px;margin-bottom:16px}
.muted{color:var(--muted)}.small{font-size:13px}
.lead{font-size:16.5px;line-height:1.65}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:16px}
.kpi{background:var(--soft);border-radius:8px;padding:12px 14px}.kpi b{display:block;font-size:24px}
.kpi.alert b{color:var(--alert)}.kpi.ok b{color:var(--ok)}
.chip{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;white-space:nowrap}
.chip.ok{color:var(--ok);background:var(--ok-bg)}.chip.warn{color:var(--warn);background:var(--warn-bg)}
.chip.alert{color:var(--alert);background:var(--alert-bg)}.chip.na{color:var(--na);background:var(--na-bg)}
.chip.stat{color:var(--stat);background:var(--stat-bg)}.chip.info{color:var(--info);background:var(--info-bg)}
.att{list-style:none;padding:0;margin:0}
.att li{display:grid;grid-template-columns:auto 1fr auto;gap:10px 14px;align-items:start;padding:12px 0;
border-top:1px solid var(--rule)}.att li:first-child{border-top:0}
.att .t{font-weight:600}.att .why{color:var(--muted);font-size:14px;margin-top:2px}.att .act{display:flex;gap:6px;flex-wrap:wrap}
.overview{width:100%;border-collapse:collapse}.overview td,.overview th{padding:10px 8px;border-top:1px solid var(--rule);
text-align:left;vertical-align:middle}.overview th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.overview img{width:72px;height:54px;object-fit:cover;border-radius:4px;border:1px solid var(--rule);background:var(--soft)}
.exhead{display:grid;grid-template-columns:240px 1fr;gap:20px;align-items:start}
.exhead img{width:100%;border-radius:8px;border:1px solid var(--rule);cursor:zoom-in;background:var(--soft)}
.facts{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;font-size:14px;margin-top:10px}.facts dt{color:var(--muted)}
.facts dd{margin:0}
.areas{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px;margin-top:6px}
.area{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;background:var(--soft);
border-radius:6px;padding:7px 10px;font-size:13.5px}
.hidden-box{border:1px solid var(--alert);background:var(--alert-bg);border-radius:8px;padding:12px 14px;margin:8px 0}
.hidden-box pre{white-space:pre-wrap;background:#fff;border:1px solid var(--rule);border-radius:6px;padding:10px;
margin:8px 0 0;font-size:13px;max-height:260px;overflow:auto}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.gallery figure{margin:0;background:var(--soft);border-radius:8px;padding:8px}.gallery img{width:100%;border-radius:4px;
cursor:zoom-in;display:block}.gallery figcaption{font-size:13px;margin-top:6px}.gallery figcaption b{display:block}
details.f{border:1px solid var(--rule);border-radius:8px;margin:8px 0;background:var(--card)}
details.f>summary{list-style:none;cursor:pointer;padding:10px 14px;display:flex;gap:10px;align-items:center}
details.f>summary::-webkit-details-marker{display:none}details.f>summary:before{content:"▸";color:var(--muted)}
details.f[open]>summary:before{content:"▾"}details.f .body{padding:0 16px 14px 34px}
details.f.target{box-shadow:0 0 0 3px var(--accent)}
.what{background:var(--soft);border-radius:6px;padding:10px 12px;margin:4px 0 10px}
.tech{display:grid;grid-template-columns:120px 1fr;gap:4px 12px;font-size:13.5px}.tech dt{color:var(--muted)}.tech dd{margin:0}
.tech pre{white-space:pre-wrap;margin:0}
details.block{border:1px solid var(--rule);border-radius:8px;background:var(--card);margin:10px 0}
details.block>summary{cursor:pointer;padding:10px 14px;font-weight:600}details.block .inner{padding:0 14px 14px;overflow-x:auto}
table.data{border-collapse:collapse;width:100%;font-size:13px}table.data th,table.data td{border:1px solid var(--rule);
padding:5px 8px;text-align:left;vertical-align:top}table.data th{background:var(--soft)}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px;color:var(--muted)}
.note{border-left:4px solid var(--accent);background:var(--soft);padding:10px 14px;border-radius:0 6px 6px 0}
#lb{position:fixed;inset:0;background:rgba(10,14,20,.88);display:none;align-items:center;justify-content:center;z-index:50;
cursor:zoom-out;padding:24px}#lb img{max-width:100%;max-height:100%;border-radius:4px}#lb.on{display:flex}
body.only-att .ok-item{display:none}
@media (max-width:980px){.layout{grid-template-columns:1fr}nav.toc{position:static;max-height:none}.exhead{grid-template-columns:1fr}}
@media print{.top,nav.toc,.act,#lb{display:none!important}.layout{display:block;padding:0}body{background:#fff}
.card,details{break-inside:avoid;border-color:#bbb}a{color:inherit;text-decoration:none}}
"""

JS = """
(function(){
 function openTarget(id){var el=document.getElementById(id);if(!el)return;var d=el.closest('details');
  while(d){d.open=true;d=d.parentElement?d.parentElement.closest('details'):null;}
  if(el.tagName==='DETAILS')el.open=true;document.querySelectorAll('.target').forEach(function(x){x.classList.remove('target')});
  el.classList.add('target');el.scrollIntoView({behavior:'smooth',block:'start'});}
 document.addEventListener('click',function(ev){var a=ev.target.closest('a[href^="#"]');
  if(a){var id=a.getAttribute('href').slice(1);if(id){ev.preventDefault();history.replaceState(null,'','#'+id);openTarget(id);}}
  var im=ev.target.closest('img.zoom');if(im){var lb=document.getElementById('lb');lb.querySelector('img').src=im.src;lb.classList.add('on');}
  if(ev.target.closest('#lb')){document.getElementById('lb').classList.remove('on');}});
 document.addEventListener('keydown',function(ev){if(ev.key==='Escape')document.getElementById('lb').classList.remove('on');});
 var only=document.getElementById('only');if(only)only.addEventListener('change',function(){document.body.classList.toggle('only-att',only.checked);});
 window.fvpExpand=function(open){document.querySelectorAll('details').forEach(function(d){d.open=open;});};
 window.addEventListener('beforeprint',function(){window.fvpExpand(true);});
 if(location.hash)setTimeout(function(){openTarget(location.hash.slice(1));},50);
})();
"""


def _finding_html(ex_id: str, f: Finding) -> str:
    ok_item = "" if explain.needs_attention(f) else " ok-item"
    tech = [f"<dt>Metodo</dt><dd>{e(f.method)}</dd>", f"<dt>Descrizione</dt><dd>{e(f.description)}</dd>"]
    if f.evidence:
        tech.append(f"<dt>Evidenza</dt><dd class='mono'><pre>{e(f.evidence)}</pre></dd>")
    if f.offset is not None:
        tech.append(f"<dt>Posizione</dt><dd class='mono'>byte {f.offset:,} (0x{f.offset:X})</dd>")
    tech += [f"<dt>Affidabilità</dt><dd>{e(f.confidence or 'n/d')}</dd>",
             f"<dt>Limiti</dt><dd>{e(f.limitations or '—')}</dd>",
             f"<dt>Modulo</dt><dd class='small muted'>{e(f.module)} · {e(f.source)} · {e(f.level.label)}</dd>"]
    step = explain.next_step(f) if explain.needs_attention(f) else ""
    return (f"<details class='f{ok_item}' id='{fid(ex_id, f)}'><summary>{lvl(f)} <span>{e(f.title)}</span>"
            f"<span class='muted small'>· {e(explain.CATEGORY_LABELS[f.category])}</span></summary><div class='body'>"
            f"<div class='what'><b>Cosa significa.</b> {e(explain.plain_explanation(f))}"
            + (f"<br><b>Cosa fare.</b> {e(step)}" if step else "") +
            f"</div><dl class='tech'>{''.join(tech)}</dl></div></details>")


def _exhibit(case: Case, item: dict) -> tuple[str, str]:
    exd, an = item["exhibit"], item["analysis"]
    ex = case.exhibit(exd["id"])
    xid = ex.id
    st = explain.overall(an)
    status = explain.status_of(an)
    r = (an or {}).get("results", {})
    kind = explain.kind_of(an)
    preview = img_uri(ex.working_path, 700, 78) if kind == "immagine" else ""
    p = [f"<section id='{xid}' class='card'>"]
    p.append(f"<h2>{e(ex.original_name)} <span class='muted small'>· {xid}</span> {chip(st)}</h2>")
    info = r.get("image_info") or {}
    sig = r.get("signature", {})
    facts = [("Tipo", f"{kind.capitalize()} · {sig.get('format_name', 'n/d')}"),
             ("Dimensioni", f"{info['width']} × {info['height']} pixel" if info.get("width") else None),
             ("Peso", f"{ex.size:,} byte".replace(",", ".")), ("Acquisito", f"{ex.acquired_utc[:19].replace('T', ' ')} UTC "
                                                                         f"da {ex.operator}"),
             ("Integrità", "verificata: hash invariati" if an and an["integrity_ok"] else
              ("NON verificata: hash diversi" if an else "analisi non eseguita")),
             ("SHA-256", f"<span class='mono'>{e(ex.source_hashes.get('sha256'))}</span>"),
             ("Percorso originale", f"<span class='mono small'>{e(ex.source_path)}</span>")]
    fh = "".join(f"<dt>{e(k)}</dt><dd>{v if k in ('SHA-256', 'Percorso originale') else e(v)}</dd>"
                 for k, v in facts if v)
    p.append(f"<div class='exhead'><div>{f'<img class=zoom alt=Anteprima src={chr(34)}{preview}{chr(34)}>' if preview else ''}"
             f"</div><div><h3 style='margin-top:0'>In breve</h3><p class='lead'>{e(explain.exhibit_summary(ex, an))}</p>"
             f"<dl class='facts'>{fh}</dl></div></div>")
    if not an:
        p.append("</section>")
        return "".join(p), ""
    att = explain.attention(an["findings"])
    arts = {k: v for k, v in r.get("artifacts", {}).items() if Path(v).is_file()}
    p.append("<h3>Cosa merita attenzione</h3>")
    if att:
        p.append("<ul class='att'>")
        for f in att:
            m = explain.related_map(f)
            btn = f"<a class='btn primary' href='#{fid(xid, f)}'>Dettagli</a>"
            if m in arts:
                btn += f"<a class='btn' href='#map-{xid}-{m}'>Vedi mappa</a>"
            p.append(f"<li>{lvl(f)}<div><div class='t'>{e(f.title)}</div><div class='why'>"
                     f"{e(explain.plain_explanation(f))}</div></div><div class='act'>{btn}</div></li>")
        p.append("</ul>")
    else:
        p.append("<p class='muted'>Nessun elemento da segnalare nei controlli eseguiti.</p>")
    hidden = explain.hidden_items(an)
    p.append("<h3>Contenuti nascosti</h3>")
    if hidden:
        for h in hidden:
            meta = " · ".join(x for x in (h["how"], f"{h['size']:,} byte" if h.get("size") else "",
                                         f"SHA-256 {h['sha256']}" if h.get("sha256") else "") if x)
            p.append(f"<div class='hidden-box'><b>{e(h['what'])}</b> <span class='small muted'>({e(h['source'])}"
                     f"{' · ' + e(meta) if meta else ''})</span>" +
                     (f"<pre>{e(h['text'][:4000])}</pre>" if h.get("text") else "") +
                     (f"<div class='small muted'>File estratto: <span class='mono'>{e(h['file'])}</span></div>"
                      if h.get("file") else "") + "</div>")
    else:
        checks = [f for f in an["findings"] if f.category == Category.STEGANOGRAPHY]
        done = [f.title for f in checks if f.level != Level.UNDETERMINED]
        flagged = [f for f in checks if explain.needs_attention(f)]
        p.append(("<p><b>Nessun contenuto è stato estratto, ma " +
                  ("un elemento va verificato" if len(flagged) == 1 else f"{len(flagged)} elementi vanno verificati") +
                  "</b> (vedi «Cosa merita attenzione»)." if flagged else
                  "<p>Nessun contenuto nascosto leggibile è stato trovato.") +
                 (f" Controlli eseguiti: {e('; '.join(done))}." if done else "") +
                 " <span class='muted'>Messaggi cifrati o inseriti con password non sono riconoscibili con questi "
                 "controlli.</span></p>")
    p.append("<h3>Esito per area</h3><div class='areas'>")
    irrelevant = {"immagine": {Category.VIDEO_INTEGRITY, Category.AUDIO_INTEGRITY, Category.DEEPFAKE},
                  "audio": {Category.IMAGE_MANIPULATION, Category.VIDEO_INTEGRITY, Category.DEEPFAKE, Category.SENSOR,
                            Category.AI_GENERATION},
                  "video": {Category.SENSOR}}.get(kind, set())
    for cat, s_ in status.items():
        if s_ == Status.GREY and (cat in irrelevant or cat == Category.SENSOR):
            continue
        p.append(f"<div class='area' title='{e(explain.CATEGORY_HELP[cat])}'><span>{e(explain.CATEGORY_LABELS[cat])}</span>"
                 f"{chip(s_)}</div>")
    p.append("</div>")
    if arts:
        from ..core.pipeline import ARTIFACT_LABELS
        p.append("<h3>Mappe di analisi</h3><p class='small muted'>Fai clic su un'immagine per ingrandirla. Ogni mappa "
                 "va letta confrontando zone con contenuto simile. Nel report le mappe sono a risoluzione ridotta; gli "
                 "originali sono nella cartella del caso (artifacts) e nell'applicazione.</p><div class='gallery'>")
        for k, path in arts.items():
            heavy = k in ("lsb", "faint", "ela", "ela_multi", "noise")      # mappe simili a rumore: pesano molto
            uri = img_uri(path, 720 if heavy else 900, 55 if heavy else 62)
            if uri:
                p.append(f"<figure id='map-{xid}-{k}'><img class='zoom' alt='{e(ARTIFACT_LABELS.get(k, k))}' src='{uri}'>"
                         f"<figcaption><b>{e(ARTIFACT_LABELS.get(k, k))}</b>{e(MAP_HELP.get(k, ''))}</figcaption></figure>")
        p.append("</div>")
    order = sorted(an["findings"], key=lambda f: (not explain.needs_attention(f), explain.SEVERITY[f.level]))
    n_att = len(att)
    p.append(f"<h3>Tutti i controlli ({len(order)})</h3><p class='small muted'>{n_att} da verificare, "
             f"{len(order) - n_att} senza anomalie o solo informativi. Apri una voce per la spiegazione e i dati "
             "tecnici.</p>")
    p += [_finding_html(xid, f) for f in order]
    if item["notes"]:
        p.append("<h3>Valutazioni dell'operatore</h3>")
        for n in item["notes"]:
            p.append(f"<div class='note'><b>{e(n['operator'])}</b> <span class='small muted'>{e(n['ts_utc'][:19])} UTC"
                     f"</span><br>{e(n['text'])}</div>")
    p.append("<details class='block ok-item'><summary>Dati tecnici del reperto</summary><div class='inner'>")
    p.append("<b>Impronte hash</b><table class='data'><tr><th>Algoritmo</th><th>Acquisizione</th><th>Inizio analisi</th>"
             "<th>Fine analisi</th></tr>")
    for alg, val in ex.source_hashes.items():
        p.append(f"<tr><td>{e(alg)}</td><td class='mono'>{e(val)}</td><td class='mono'>{e(an['pre_hashes'].get(alg))}</td>"
                 f"<td class='mono'>{e(an['post_hashes'].get(alg))}</td></tr>")
    p.append("</table>")
    rows = [("Formato effettivo", sig.get("format_name")), ("MIME", sig.get("mime")), ("Estensione", sig.get("extension")),
            ("Magic bytes", sig.get("magic_hex"))] + list(info.items()) + list((r.get("characteristics") or {}).items())
    p.append("<br><b>File</b><table class='data'>" + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in rows)
             + "</table>")
    if r.get("timeline"):
        p.append("<br><b>Date e orari</b><table class='data'><tr><th>Sorgente</th><th>Valore</th><th>UTC</th>"
                 "<th>Locale (fuso ignoto)</th><th>Nota</th></tr>")
        for t in r["timeline"]:
            p.append(f"<tr><td>{e(t['source'])}</td><td class='mono'>{e(t['raw'])}</td><td class='mono'>{e(t['utc'])}</td>"
                     f"<td class='mono'>{e(t['local'])}</td><td>{e(t['note'])}</td></tr>")
        p.append("</table>")
    if r.get("video"):
        v = r["video"]
        p.append(f"<br><b>Stream</b> <span class='small'>{e(v['container'])}, {e(v['duration_s'])} s</span>"
                 "<table class='data'><tr><th>#</th><th>Tipo</th><th>Codec</th></tr>" +
                 "".join(f"<tr><td>{s_['index']}</td><td>{e(s_['type'])}</td><td>{e(s_['codec'])}</td></tr>"
                         for s_ in v["streams"]) + "</table>")
    md = r.get("metadata", {})
    if md.get("tags"):
        p.append(f"<br><b>Metadati</b> <span class='small muted'>({len(md['tags'])} voci, {e(md.get('tool'))})</span>"
                 "<table class='data'><tr><th>Gruppo</th><th>Voce</th><th>Valore</th><th>Attendibilità</th></tr>")
        rel = {"dichiarato": "scritto nel file (modificabile)", "calcolato": "calcolato dal programma",
               "filesystem_copia": "sistema (copia di lavoro)"}
        for t in md["tags"]:
            p.append(f"<tr><td>{e(t['group'])}</td><td>{e(t['tag'])}</td><td class='mono'>{e(t['value'][:300])}</td>"
                     f"<td>{e(rel.get(t['reliability'], t['reliability']))}</td></tr>")
        p.append("</table>")
    p.append(f"<p class='small muted'>Strumenti: {e(', '.join(f'{k} {v}' for k, v in an['tools'].items()))}</p>")
    p.append("</div></details></section>")
    return "".join(p), ""


def render(case: Case, d: dict) -> str:
    c = d["case"]
    pairs = []
    for item in d["exhibits"]:
        pairs.append((case.exhibit(item["exhibit"]["id"]), item["analysis"]))
    cs = explain.case_summary(pairs)
    av = d["audit_verification"]
    toc = ["<nav class='toc'><div class='h'>Report</div><a href='#sintesi'>Sintesi</a>"
           "<a href='#attenzione'>Punti di attenzione</a><a href='#reperti'>Panoramica dei reperti</a>"
           "<div class='h'>Reperti</div>"]
    dot = {Status.GREEN: "var(--ok)", Status.YELLOW: "var(--warn)", Status.RED: "var(--alert)", Status.GREY: "var(--na)"}
    for ex, an in pairs:
        toc.append(f"<a href='#{ex.id}'><span class='dot' style='background:{dot[explain.overall(an)]}'></span>"
                   f"{e(ex.original_name)}</a>")
    toc.append("<div class='h'>Riferimenti</div><a href='#metodo'>Metodo e limiti</a><a href='#glossario'>Glossario</a>"
               "<a href='#custodia'>Catena di custodia</a></nav>")
    p = ["<!doctype html><html lang='it'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
         f"initial-scale=1'><title>Report {e(c.get('case_id'))}</title><style>{CSS}</style></head><body>"]
    p.append(f"<div class='top'><span class='title'>Caso {e(c.get('case_id'))}</span><span class='muted small'>"
             f"{e(c.get('title'))}</span><span class='sp'></span><label><input type='checkbox' id='only'> Mostra solo "
             "ciò che richiede attenzione</label><button class='btn' onclick='fvpExpand(true)'>Espandi tutto</button>"
             "<button class='btn' onclick='fvpExpand(false)'>Comprimi</button><button class='btn' "
             "onclick='window.print()'>Stampa / PDF</button></div><div class='layout'>")
    p += toc
    p.append("<main>")
    # --- sintesi
    p.append(f"<section id='sintesi' class='card'><div class='muted small'>Report di analisi forense · {e(d['app'])} · "
             f"generato il {e(d['generated_utc'][:19].replace('T', ' '))} UTC · versione report 1.1</div>"
             f"<h1>{e(c.get('title') or 'Caso ' + str(c.get('case_id')))}</h1>"
             f"<div class='muted'>Caso {e(c.get('case_id'))} · analista {e(c.get('operator'))}"
             + (f" · {e(c.get('description'))}" if c.get("description") else "") + "</div>"
             f"<h2 style='margin-top:18px'>Sintesi</h2><p class='lead'>{e(cs['text'])}</p><div class='kpis'>"
             f"<div class='kpi'><b>{cs['analysed']}</b>file analizzati</div>"
             f"<div class='kpi {'alert' if cs['red'] else ''}'><b>{cs['red']}</b>richiedono attenzione</div>"
             f"<div class='kpi'><b>{cs['attention_files'] - cs['red']}</b>da approfondire</div>"
             f"<div class='kpi {'alert' if cs['hidden_files'] else ''}'><b>{cs['hidden_files']}</b>con contenuti nascosti</div>"
             f"<div class='kpi {'ok' if cs['integrity_ok'] and av['ok'] else 'alert'}'><b>"
             f"{'Sì' if cs['integrity_ok'] and av['ok'] else 'No'}</b>integrità e registro verificati</div></div>"
             "<p class='small muted' style='margin-top:14px'>Come leggere il report: ogni file ha una scheda con un "
             "riepilogo in parole semplici, l'elenco di ciò che merita attenzione (pulsante <b>Dettagli</b> per la "
             "spiegazione completa) e, più in basso, i dati tecnici. I colori indicano dove guardare, non se un file "
             "è autentico.</p><div class='legend'>"
             + "".join(f"<span>{chip(s_)} {e(explain.STATUS_HELP[s_])}</span>" for s_ in
                       (Status.RED, Status.YELLOW, Status.GREEN, Status.GREY)) + "</div></section>")
    # --- punti di attenzione del caso
    p.append("<section id='attenzione' class='card'><h2>Punti di attenzione</h2>")
    if cs["top"]:
        p.append("<p class='small muted'>Tutti gli elementi da verificare, dal più rilevante. Ogni voce porta alla "
                 "spiegazione completa.</p><ul class='att'>")
        for ex, f in cs["top"][:40]:
            p.append(f"<li>{lvl(f)}<div><div class='t'>{e(f.title)} <span class='muted small'>· "
                     f"{e(ex.original_name)}</span></div><div class='why'>{e(explain.plain_explanation(f))}</div></div>"
                     f"<div class='act'><a class='btn primary' href='#{fid(ex.id, f)}'>Dettagli</a>"
                     f"<a class='btn' href='#{ex.id}'>Scheda file</a></div></li>")
        p.append("</ul>")
    else:
        p.append("<p>Nessun elemento da verificare nei controlli eseguiti.</p>")
    p.append("</section>")
    # --- panoramica
    p.append("<section id='reperti' class='card'><h2>Panoramica dei reperti</h2><table class='overview'><tr><th></th>"
             "<th>File</th><th>Tipo</th><th>Esito</th><th>Da verificare</th><th>Contenuti nascosti</th><th></th></tr>")
    for ex, an in pairs:
        thumb = img_uri(ex.working_path, 160, 70) if explain.kind_of(an) == "immagine" else ""
        n_att = len(explain.attention(an["findings"])) if an else 0
        hid = explain.hidden_items(an)
        p.append(f"<tr><td>{f'<img alt={chr(34)}{chr(34)} src={chr(34)}{thumb}{chr(34)}>' if thumb else ''}</td>"
                 f"<td><b>{e(ex.original_name)}</b><div class='small muted'>{ex.id}</div></td>"
                 f"<td>{e(explain.kind_of(an))}</td><td>{chip(explain.overall(an))}</td><td>{n_att}</td>"
                 f"<td>{'<span class=\"chip alert\">trovati</span>' if hid else '—'}</td>"
                 f"<td><a class='btn' href='#{ex.id}'>Apri scheda</a></td></tr>")
    p.append("</table></section>")
    for item in d["exhibits"]:
        p.append(_exhibit(case, item)[0])
    # --- metodo, glossario, custodia
    p.append(f"<section id='metodo' class='card'><h2>Metodo e limiti</h2><div class='note'>{e(d['limitations'])}</div>"
             "<details class='block'><summary>Come è stata eseguita ogni analisi</summary><div class='inner'>"
             "<table class='data'>" + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in d["methodology"])
             + "</table></div></details>"
             f"<p class='small'>Registro delle operazioni: {'catena integra' if av['ok'] else 'CATENA NON VALIDA: ' + e(av['reason'])}"
             f" ({av['entries']} voci). Hash di testa: <span class='mono'>{e(av['head_hash'])}</span></p>"
             "<h3>Conclusioni</h3><p class='muted'>Le conclusioni tecniche sono di competenza dell'analista, sulla base "
             "dei risultati e delle valutazioni registrate.</p></section>")
    p.append("<section id='glossario' class='card'><h2>Glossario</h2><dl class='facts' style='grid-template-columns:220px 1fr'>"
             + "".join(f"<dt><b>{e(k)}</b></dt><dd>{e(v)}</dd>" for k, v in GLOSSARY) + "</dl></section>")
    p.append("<section id='custodia' class='card'><h2>Catena di custodia</h2><div class='inner' style='overflow-x:auto'>"
             "<table class='data'><tr><th>#</th><th>Data e ora (UTC)</th><th>Operatore</th><th>Azione</th><th>Dettagli</th>"
             "<th>Impronta voce</th></tr>")
    for en in d["custody"]:
        det = {k: v for k, v in en["details"].items() if k != "source_stat"}
        p.append(f"<tr><td>{en['seq']}</td><td class='mono'>{e(en['ts_utc'][:19].replace('T', ' '))}</td>"
                 f"<td>{e(en['actor'])}</td><td>{e(en['action'].replace('_', ' '))}</td>"
                 f"<td class='mono small'>{e(json.dumps(det, ensure_ascii=False)[:300])}</td>"
                 f"<td class='mono small'>{e(en['entry_hash'][:16])}…</td></tr>")
    p.append("</table></div></section></main></div><div id='lb'><img alt=''></div>")
    p.append(f"<script>{JS}</script></body></html>")
    return "".join(p)
