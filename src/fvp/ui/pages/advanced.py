"""Steganalisi, PRNU / sensore e Comparison Tool."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from ...core.findings import Category
from ...engines import compare, prnu, stegointel
from ..widgets.common import link_findings, Page, fill_table, make_table
from ..widgets.findings_view import FindingsView
from ..widgets.imageviews import SyncGroup


STEGO_TOOLS = [
    ("Stegsolve", "Piani di bit e canali", "Integrato: scheda 'Piani di bit'."),
    ("StegoVeritas / zsteg", "Estrazione LSB in più combinazioni, testo e file nascosti",
     "Integrato: 56 combinazioni su immagini, 4 su audio WAV; contenuti salvati con SHA-256."),
    ("OpenStego", "Inserimento LSB con intestazione propria", "Integrato il riconoscimento dell'intestazione in chiaro; "
     "i dati cifrati con password non sono estraibili."),
    ("Stegosuite, OutGuess, Steghide", "Inserimento protetto da password",
     "Non estraibili senza password. Steghide non è incluso: è fermo dal 2003 e ha vulnerabilità note, quindi non "
     "va eseguito su reperti non attendibili."),
    ("Steganografia su file", "Dati accodati o file incorporati",
     "Integrato: moduli struttura (dati dopo EOI/IEND) e scanner di firme."),
    ("Analisi statistica", "Stima della quantità di dati inseriti", "Integrato: RS steganalysis e chi-quadro."),
]


class SteganalysisPage(Page):
    title = "Contenuti nascosti"
    lead = "Messaggi, testi o file nascosti nell'immagine o nei suoi dati."
    intro = ("Cerca messaggi, file o testo nascosti: dentro i pixel o i campioni audio (steganografia), nei campi "
             "descrittivi del file, nei suoi byte e sotto forma di scritte quasi invisibili. Se qualcosa viene "
             "trovato e decodificato, appare qui sotto. Messaggi cifrati o protetti da password non sono leggibili.")

    def __init__(self, state):
        super().__init__(state)
        self.found = QLabel()
        self.found.setWordWrap(True)
        self.found.setTextFormat(Qt.TextFormat.RichText)
        self.found.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.root.addWidget(self.found)
        tabs = QTabWidget()
        # risultati
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        self.table = make_table(["Canale", "Stima RS", "χ² p 1%", "χ² p 5%", "χ² p 25%", "χ² p 100%", "Frazione LSB = 1"])
        self.table.setMaximumHeight(130)
        self.fv = FindingsView({Category.STEGANOGRAPHY, Category.FILE_STRUCTURE, Category.METADATA})
        link_findings(self.fv, state)
        l1.addWidget(self.fv, 1)
        tabs.addTab(w1, "Tutti i controlli")
        # contenuti estratti
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        self.hits = make_table(["Contenuto", "Combinazione", "Dimensione", "SHA-256", "Anteprima", "File"])
        l2.addWidget(self.hits, 1)
        bh = QPushButton("Apri il contenuto selezionato nell'Hex Viewer")
        bh.clicked.connect(self._open_hit)
        row = QHBoxLayout()
        row.addWidget(bh)
        row.addStretch(1)
        l2.addLayout(row)
        tabs.addTab(w2, "Contenuti estratti")
        # piani di bit
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        stat_lbl = QLabel("Test statistici per canale (stima RS = frazione stimata di pixel modificati; χ² = "
                          "probabilità che le coppie di valori siano equalizzate, calcolata su porzioni crescenti)")
        stat_lbl.setObjectName("Muted")
        stat_lbl.setWordWrap(True)
        l3.addWidget(stat_lbl)
        l3.addWidget(self.table)
        bar = QHBoxLayout()
        self.chan = QComboBox()
        for k, v in (("R", "Rosso"), ("G", "Verde"), ("B", "Blu"), ("A", "Alfa"), ("L", "Luminanza")):
            self.chan.addItem(v, k)
        self.bit = QSpinBox()
        self.bit.setRange(0, 7)
        self.bit.setPrefix("bit ")
        for wdg in (QLabel("Canale"), self.chan, self.bit):
            bar.addWidget(wdg)
        for txt, fn in (("Adatta", lambda: self.sync.fit()), ("100%", lambda: self.sync.actual())):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        l3.addLayout(bar)
        hint = QLabel("Bit 0 è il meno significativo. In un'immagine naturale i piani alti mostrano il soggetto e quelli "
                      "bassi rumore uniforme; forme, bande o aree regolari nei piani bassi indicano dati inseriti.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        l3.addWidget(hint)
        views = QWidget()
        vl = QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        self.sync = SyncGroup()
        for cap in ("Immagine", "Piano di bit selezionato"):
            w, _v = self.sync.new_view(cap)
            vl.addWidget(w)
        l3.addWidget(views, 1)
        self.chan.currentIndexChanged.connect(self._plane)
        self.bit.valueChanged.connect(self._plane)
        tabs.addTab(w3, "Esplora i bit (avanzato)")
        # riferimenti
        w4 = QWidget()
        l4 = QVBoxLayout(w4)
        ref = make_table(["Strumento citato da StegoIntelligence", "Tecnica", "In Forensic Vision Pro"])
        fill_table(ref, [list(t) for t in STEGO_TOOLS], sortable=False)
        ref.setWordWrap(True)
        l4.addWidget(ref, 1)
        src = QLabel("Fonte: github.com/CScorza/StegoIntelligence (catalogo di tecniche e strumenti). Le tecniche sono "
                     "implementate in modo nativo: nessuno strumento esterno viene eseguito sui reperti.")
        src.setObjectName("Muted")
        src.setWordWrap(True)
        l4.addWidget(src)
        tabs.addTab(w4, "Strumenti e tecniche")
        self.root.addWidget(tabs, 1)
        self._arr = None
        self._hits: list[dict] = []
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def refresh(self) -> None:
        import html as _h

        from ...core import explain
        from ..theme import C
        an = self.state.last_analysis()
        r = (an or {}).get("results", {})
        hidden = explain.hidden_items(an)
        if not an:
            self.found.setText("")
            self.found.setObjectName("")
        elif hidden:
            rows = []
            for h in hidden[:5]:
                txt = _h.escape((h["text"] or "")[:600])
                rows.append(f"<p style='margin:4px 0'><b>{_h.escape(h['what'])}</b> <span style='color:{C['muted']}'>"
                            f"({_h.escape(h['source'])}{' · ' + _h.escape(h['how']) if h['how'] else ''})</span>"
                            + (f"<br><span style='font-family:monospace;white-space:pre-wrap'>{txt}</span>" if txt else "")
                            + "</p>")
            n = len(hidden)
            self.found.setText(f"<b style='color:{C['red']}'>{'Trovato 1 contenuto nascosto' if n == 1 else f'Trovati {n} contenuti nascosti'}.</b>"
                               + "".join(rows))
            self.found.setObjectName("Notice")
        else:
            checks = [f for f in an["findings"] if f.category.value == "Steganography" and f.level.value != "non_determinabile"]
            self.found.setText(f"<b>Nessun contenuto nascosto leggibile trovato</b> ({len(checks)} controlli eseguiti). "
                               "Messaggi cifrati o inseriti con password non sono riconoscibili con questi controlli.")
            self.found.setObjectName("Notice")
        self.found.style().unpolish(self.found)
        self.found.style().polish(self.found)
        self.fv.hide_info = self.state.settings.ui_mode == "Basic"
        self.fv.set_findings(an["findings"] if an else [])
        rows = []
        for ch, v in r.get("stego", {}).get("channels", {}).items():
            p = {x["percent"]: x["p"] for x in v["chi_sequence"]}
            rows.append([ch, "non stimabile" if v["rs"] != v["rs"] else f"{v['rs']:.1%}", p.get(1), p.get(5),
                         p.get(25), p.get(100), v["lsb_ones"]])
        fill_table(self.table, rows, sortable=False)
        self._hits = [h for h in r.get("stegointel", {}).get("hits", []) if h.get("file")]
        fill_table(self.hits, [[h["detail"], f"{h['channels']} · {h['bits']} bit · {h['order']} · "
                                f"{'MSB' if h['msb_first'] else 'LSB'}", f"{h['size']:,}", h["sha256"],
                                h.get("preview", "")[:80], h["file"]] for h in self._hits], sortable=False)
        self._arr = None
        if self.state.case and self.state.exhibit_id and an and "image" in r.get("executed", []):
            try:
                self._arr = stegointel.to_array(self.state.case.exhibit(self.state.exhibit_id).working_path)
            except Exception:  # noqa: BLE001
                self._arr = None
        self.sync.views[0].set_image(self.state.case.exhibit(self.state.exhibit_id).working_path
                                     if self._arr is not None else None)
        self._plane()
        self.sync.fit()

    def _plane(self) -> None:
        v = self.sync.views[1]
        if self._arr is None:
            v.set_image(None)
            return
        plane = stegointel.bit_plane(self._arr, self.chan.currentData(), self.bit.value())
        img = QImage(plane.data, plane.shape[1], plane.shape[0], plane.strides[0], QImage.Format.Format_Grayscale8)
        v.item.setPixmap(QPixmap.fromImage(img.copy()))
        v.scene().setSceneRect(v.item.boundingRect())

    def _open_hit(self) -> None:
        rows = self.hits.selectionModel().selectedRows()
        if rows and rows[0].row() < len(self._hits):
            self.state.open_hex.emit(self._hits[rows[0].row()]["file"])


class PrnuPage(Page):
    title = "Fotocamera di origine"
    lead = "Verifica se una foto è stata scattata da una certa fotocamera."
    intro = ("Il PRNU è un rumore caratteristico di ogni sensore. Con almeno 5 immagini di riferimento dello stesso "
             "dispositivo (meglio 20 o più, di scene luminose e uniformi, non ridimensionate) si costruisce "
             "un'impronta; un'immagine con PCE superiore a 60 è compatibile con quel sensore. Le impronte valgono per "
             "tutti i casi e ogni confronto è registrato nel caso aperto.")

    def __init__(self, state):
        super().__init__(state)
        g = QGroupBox("Nuova impronta")
        f = QFormLayout(g)
        self.label, self.model = QLineEdit(), QLineEdit()
        self.label.setPlaceholderText("es. Smartphone sequestrato reperto 3")
        self.model.setPlaceholderText("es. Samsung SM-S918B")
        f.addRow("Etichetta", self.label)
        f.addRow("Modello dichiarato", self.model)
        b = QPushButton("Scegli immagini di riferimento e crea impronta…")
        b.clicked.connect(self._add)
        f.addRow(b)
        self.root.addWidget(g)
        row = QHBoxLayout()
        bm = QPushButton("Confronta il reperto selezionato con tutte le impronte")
        bm.setObjectName("Primary")
        bm.clicked.connect(self._match)
        bd = QPushButton("Elimina impronta selezionata")
        bd.clicked.connect(self._delete)
        row.addWidget(bm)
        row.addWidget(bd)
        row.addStretch(1)
        self.root.addLayout(row)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.table = make_table(["ID", "Etichetta", "Modello", "Riferimenti", "Ritaglio", "Creata (UTC)", "Operatore"])
        sp.addWidget(self.table)
        self.res = make_table(["Impronta", "PCE", "Esito", "Nota"])
        sp.addWidget(self.res)
        self.fv = FindingsView({Category.SENSOR})
        link_findings(self.fv, state)
        sp.addWidget(self.fv)
        self.root.addWidget(sp, 1)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    @property
    def store(self) -> prnu.PrnuStore:
        return prnu.PrnuStore(self.state.settings.prnu_path)

    def refresh(self) -> None:
        self._items = self.store.list()
        fill_table(self.table, [[i["id"], i["label"], i["model"], len(i["references"]), f"{i['shape'][1]}x{i['shape'][0]}",
                                 i["created_utc"], i["operator"]] for i in self._items])
        an = self.state.last_analysis()
        rows = []
        for r in (an or {}).get("results", {}).get("prnu", []):
            rows.append([r["label"], r.get("pce"), "" if r.get("pce") is None else
                         ("compatibile" if r["pce"] >= prnu.PCE_THRESHOLD else "non compatibile"), r.get("note", "")])
        fill_table(self.res, rows)
        self.fv.set_findings(an["findings"] if an else [])

    def _add(self) -> None:
        if not self.label.text().strip():
            return self.error("Indica un'etichetta per l'impronta.")
        files, _ = QFileDialog.getOpenFileNames(self, "Immagini di riferimento dello stesso dispositivo")
        if not files:
            return
        label, model, op = self.label.text().strip(), self.model.text().strip(), self.state.operator

        def done(item):
            self.label.clear()
            self.model.clear()
            if self.state.case:
                self.state.case.audit.append(op, "prnu_impronta_creata", {k: item[k] for k in
                                             ("id", "label", "model", "fingerprint_sha256", "references")})
            self.refresh()
        self.state.run(lambda _p, _c: self.store.add(label, model, files, op), done, self.error)

    def _delete(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        fid = self.table.item(rows[0].row(), 0).text()
        self.store.remove(fid)
        if self.state.case:
            self.state.case.audit.append(self.state.operator, "prnu_impronta_eliminata", {"id": fid})
        self.refresh()

    def _match(self) -> None:
        if not (self.state.case and self.state.exhibit_id):
            return self.error("Nessun reperto selezionato.")
        if not self._items:
            return self.error("Nessuna impronta disponibile: creane una con le immagini di riferimento.")
        from ...core.pipeline import analyze_exhibit
        case, ex, op, s = self.state.case, self.state.exhibit_id, self.state.operator, self.state.settings
        self.state.run(lambda p, c: analyze_exhibit(case, ex, op, s, ["integrity", "signature", "prnu"], p, c),
                       lambda _r: self.state.analysis_changed.emit(), self.error)


class ComparisonPage(Page):
    title = "Confronta immagini"
    lead = "Confronta due immagini e mostra dove sono diverse."
    intro = ("Confronto tra due immagini: hash crittografici e percettivi, SSIM, PSNR, mappa delle differenze e "
             "relazione geometrica (ritaglio, scala, rotazione). Se le dimensioni differiscono, B viene allineata ad A "
             "con un'omografia o, in mancanza di corrispondenze, ridimensionata. 'Trova quasi-duplicati' confronta "
             "gli hash percettivi di tutti i reperti del caso.")

    def __init__(self, state):
        super().__init__(state)
        row = QHBoxLayout()
        self.a, self.b = QComboBox(), QComboBox()
        for cb in (self.a, self.b):
            cb.setMinimumWidth(260)
        row.addWidget(QLabel("A"))
        row.addWidget(self.a)
        row.addWidget(QLabel("B"))
        row.addWidget(self.b)
        bf = QPushButton("B da file…")
        bf.clicked.connect(self._file_b)
        row.addWidget(bf)
        bc = QPushButton("Confronta")
        bc.setObjectName("Primary")
        bc.clicked.connect(self._compare)
        row.addWidget(bc)
        bd = QPushButton("Trova quasi-duplicati nel caso")
        bd.clicked.connect(self._dups)
        row.addWidget(bd)
        row.addStretch(1)
        self.root.addLayout(row)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.root.addWidget(self.verdict)
        sp = QSplitter(Qt.Orientation.Vertical)
        views = QWidget()
        vl = QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        self.sync = SyncGroup()
        for cap in ("A", "B", "Differenza assoluta", "Dissimilarità SSIM (1 - SSIM)"):
            w, _v = self.sync.new_view(cap)
            vl.addWidget(w)
        sp.addWidget(views)
        self.table = make_table(["Misura", "Valore"])
        sp.addWidget(self.table)
        sp.setSizes([420, 260])
        self.root.addWidget(sp, 1)
        self._file_path: str | None = None
        state.case_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def refresh(self) -> None:
        exs = self.state.case.exhibits() if self.state.case else []
        for cb in (self.a, self.b):
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            for e in exs:
                cb.addItem(f"{e.id} · {e.label}", e.working_path)
            if cb is self.b and self._file_path:
                cb.addItem(f"File: {Path(self._file_path).name}", self._file_path)
            i = cb.findData(cur)
            cb.setCurrentIndex(i if i >= 0 else (1 if cb is self.b and cb.count() > 1 else 0))
            cb.blockSignals(False)

    def _file_b(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Immagine B (sola lettura)")
        if f:
            self._file_path = f
            self.refresh()
            self.b.setCurrentIndex(self.b.count() - 1)

    def _compare(self) -> None:
        pa, pb = self.a.currentData(), self.b.currentData()
        if not (pa and pb):
            return self.error("Seleziona due immagini.")
        case = self.state.case
        out = (case.root / "artifacts" / "compare") if case else Path.home()
        out.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha256(f"{pa}|{pb}".encode()).hexdigest()[:10]
        d, s, o = out / f"{tag}_diff.png", out / f"{tag}_ssim.png", out / f"{tag}_overlay.png"

        def job(_p, _c):
            r = compare.compare(pa, pb, d, s, o)
            from ...engines.hashing import hash_file
            r["sha256"] = {"a": hash_file(pa)["sha256"], "b": hash_file(pb)["sha256"]}
            return r

        def done(r):
            for v, p in zip(self.sync.views, (pa, pb, d, s)):
                v.set_image(str(p))
            self.sync.fit()
            self.verdict.setText(f"<b>{compare.interpret(r)}</b> — indicazione descrittiva, da verificare sulle mappe.")
            dist = r["hashes"]["distance"]
            rows = [["SHA-256 A", r["sha256"]["a"]], ["SHA-256 B", r["sha256"]["b"]],
                    ["File identici", "sì" if r["sha256"]["a"] == r["sha256"]["b"] else "no"],
                    ["Dimensioni A / B", f"{r['size_a'][0]}x{r['size_a'][1]} / {r['size_b'][0]}x{r['size_b'][1]}"],
                    ["Allineamento", r["aligned"] + (f" (sovrapposizione {r['overlap_fraction']:.0%})"
                                                     if "overlap_fraction" in r else "")],
                    ["SSIM", r["ssim"]], ["PSNR (dB)", r["psnr_db"]], ["Pixel con differenza > 10", r["diff_pixels_over_10"]],
                    ["Corrispondenze ORB / inlier", f"{r['geometry']['matches']} / {r['geometry']['inliers']}"]]
            rows += [[f"Distanza {k} (bit su 64)", v] for k, v in dist.items()]
            rows += [[f"{k} A / B", f"{r['hashes']['a'][k]} / {r['hashes']['b'][k]}"] for k in dist]
            fill_table(self.table, rows, sortable=False)
            if case:
                case.audit.append(self.state.operator, "confronto_immagini",
                                  {"a": pa, "b": pb, "sha256": r["sha256"], "ssim": r["ssim"], "phash_distance": dist["phash"]})
                (out / f"{tag}_result.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
        self.state.run(job, done, self.error)

    def _dups(self) -> None:
        case = self.state.case
        if not case:
            return self.error("Apri un caso.")
        items = []
        for e in case.exhibits():
            an = case.analyses(e.id)
            ph = an[-1]["results"].get("perceptual_hashes") if an else None
            if ph:
                items.append((e, ph))
        rows = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ea, ha), (eb, hb) = items[i], items[j]
                d = compare.hamming(ha["phash"], hb["phash"])
                if d <= 12:
                    esito = ("file identici" if ea.working_hashes["sha256"] == eb.working_hashes["sha256"] else
                             "quasi-duplicati" if d <= 6 else "simili")
                    rows.append([f"{ea.id} ↔ {eb.id}", f"{esito}: pHash {d} bit, dHash "
                                 f"{compare.hamming(ha['dhash'], hb['dhash'])} bit"])
        fill_table(self.table, rows or [["Nessuna coppia", f"su {len(items)} reperti con hash percettivi"]])
        self.verdict.setText(f"Quasi-duplicati: soglia pHash ≤ 12 bit. {len(rows)} coppie trovate.")
