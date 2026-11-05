"""Pagine di analisi: Image Forensics, Manipulation Detection, Video Forensics, AI Detection."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QSplitter, QTabWidget,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...core.findings import Category
from ...engines import image
from ..widgets.common import link_findings, Page, fill_table, make_table, not_implemented
from ..widgets.findings_view import FindingsView
from ..widgets.imageviews import SyncGroup


class ImageForensicsPage(Page):
    title = "Analisi visiva"
    intro = ("Immagine e due mappe di analisi a scelta, affiancate, con zoom (rotella) e scorrimento sincronizzati. "
             "Ogni mappa evidenzia regioni da confrontare con aree di contenuto simile: nessuna mappa è da sola una "
             "prova di alterazione. Il significato di ciascuna è nei risultati di Manipulation Detection.")

    def __init__(self, state):
        super().__init__(state)
        bar = QHBoxLayout()
        for txt, fn in (("Adatta", lambda: self.sync.fit()), ("100%", lambda: self.sync.actual())):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addSpacing(20)
        bar.addWidget(QLabel("Qualità ELA"))
        self.q = QSpinBox()
        self.q.setRange(50, 99)
        self.q.setValue(90)
        bar.addWidget(self.q)
        self.recompute = QPushButton("Ricalcola ELA")
        self.recompute.clicked.connect(self._ela)
        bar.addWidget(self.recompute)
        bar.addStretch(1)
        self.root.addLayout(bar)
        sp = QSplitter(Qt.Orientation.Vertical)
        views = QWidget()
        vl = QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        self.sync = SyncGroup()
        box0 = QWidget()
        b0 = QVBoxLayout(box0)
        b0.setContentsMargins(0, 0, 0, 0)
        title0 = QComboBox()
        title0.addItem("Immagine (copia di lavoro)")
        title0.setEnabled(False)          # solo per allineare la vista alle due mappe selezionabili
        b0.addWidget(title0)
        w, _v = self.sync.new_view("")
        b0.addWidget(w, 1)
        vl.addWidget(box0)
        self.combos = []
        for default in ("ela", "ela_multi"):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            cb = QComboBox()
            cb.setProperty("default", default)
            cb.currentIndexChanged.connect(self._show_maps)
            bl.addWidget(cb)
            w, _v = self.sync.new_view("")
            bl.addWidget(w, 1)
            vl.addWidget(box)
            self.combos.append(cb)
        sp.addWidget(views)
        self.info = make_table(["Proprietà", "Valore"])
        sp.addWidget(self.info)
        sp.setSizes([540, 170])
        self.root.addWidget(sp, 1)
        self.msg = QLabel()
        self.msg.setObjectName("Muted")
        self.root.addWidget(self.msg)
        self._arts: dict = {}
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def show_map(self, key: str) -> None:
        """Mostra la mappa richiesta nella prima vista (usato dai pulsanti 'Apri vista')."""
        self._pending_map = key

    def _show_maps(self) -> None:
        for cb, view in zip(self.combos, self.sync.views[1:]):
            view.set_image(self._arts.get(cb.currentData()))
        self.sync.fit()

    def refresh(self) -> None:
        from ...core.pipeline import ARTIFACT_LABELS
        an = self.state.last_analysis()
        o = self.sync.views[0]
        if not an or "image" not in an["results"].get("executed", []):
            for v in self.sync.views:
                v.set_image(None)
            for cb in self.combos:
                cb.blockSignals(True)
                cb.clear()
                cb.blockSignals(False)
            self.info.setRowCount(0)
            self.recompute.setEnabled(False)
            self.msg.setText("Nessuna analisi d'immagine per il reperto selezionato.")
            return
        ex = self.state.case.exhibit(self.state.exhibit_id)
        self._arts = {k: v for k, v in an["results"].get("artifacts", {}).items() if Path(v).is_file()}
        for cb in self.combos:
            cur = cb.currentData() or cb.property("default")
            cb.blockSignals(True)
            cb.clear()
            for k in self._arts:
                cb.addItem(ARTIFACT_LABELS.get(k, k), k)
            i = cb.findData(cur)
            cb.setCurrentIndex(i if i >= 0 else 0)
            cb.blockSignals(False)
        pending = getattr(self, "_pending_map", "")
        if pending and self.combos[0].findData(pending) >= 0:
            self.combos[0].blockSignals(True)
            self.combos[0].setCurrentIndex(self.combos[0].findData(pending))
            self.combos[0].blockSignals(False)
        self._pending_map = ""
        o.set_image(ex.working_path)
        self._show_maps()
        self.recompute.setEnabled(True)
        r = an["results"]
        sig = r.get("signature", {})
        rows = [["Formato effettivo", sig.get("format_name")], ["MIME", sig.get("mime")],
                ["Estensione", f"{sig.get('extension')} ({'coerente' if sig.get('extension_matches') else 'NON coerente'})"],
                ["Magic bytes", sig.get("magic_hex")]]
        for section in ("image_info", "characteristics", "perceptual_hashes"):
            rows += [[k, v] for k, v in (r.get(section) or {}).items()]
        st = r.get("structure", {}).get("root", {})
        for c in st.get("children", []):
            if c["name"].startswith("DQT"):
                rows += [[f"DQT @0x{c['offset']:X}", "; ".join(f"{k}: {v}" for k, v in c["fields"].items())]]
        fill_table(self.info, rows, sortable=False)
        self.msg.setText("")

    def _ela(self) -> None:
        ex = self.state.case.exhibit(self.state.exhibit_id)
        q = self.q.value()
        out = self.state.case.artifacts_dir(ex.id) / f"ela_q{q}.png"

        def job(_p, _c):
            image.ela(ex.working_path, q, out)
            return str(out)

        def done(p):
            self._arts["ela"] = p
            self._show_maps()
            self.msg.setText(f"ELA ricalcolata a qualità {q} (viste impostate su ELA q90): {Path(p).name}")
            self.state.case.audit.append(self.state.operator, "ela_ricalcolata", {"exhibit": ex.id, "quality": q})
        self.state.run(job, done, self.error)


class FindingsPage(Page):
    categories: set[Category] = set()

    def __init__(self, state):
        super().__init__(state)
        self.fv = FindingsView(self.categories)
        link_findings(self.fv, state)
        self.extra_top()
        self.root.addWidget(self.fv, 1)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def extra_top(self) -> None:
        pass

    def refresh(self) -> None:
        an = self.state.last_analysis()
        self.fv.hide_info = self.state.settings.ui_mode == "Basic"
        self.fv.set_findings(an["findings"] if an else [])


class ManipulationPage(FindingsPage):
    title = "Possibili modifiche"
    intro = ("Risultati dei test sulla struttura del file e sull'immagine. Un indicatore sospetto è compatibile con "
             "una modifica ma non la dimostra: va letto insieme agli altri e verificato visivamente.")
    categories = {Category.IMAGE_MANIPULATION, Category.FILE_STRUCTURE, Category.INTEGRITY}

    def extra_top(self) -> None:
        self.root.addWidget(not_implemented(
            "Attivi: ELA singola e multi-qualità, JPEG ghost, doppia quantizzazione DCT, griglia 8x8, residuo di "
            "rumore, filtro mediano, copy-move, miniatura EXIF, struttura del file. Non ancora implementati: analisi "
            "di illuminazione, ombre e prospettiva; rilevatori neurali di splicing (milestone 4)."))


class AIDetectionPage(FindingsPage):
    title = "Intelligenza artificiale"
    intro = ("In questa versione il modulo cerca solo indicatori di provenienza nei metadati: tag IPTC "
             "DigitalSourceType, nomi di generatori, parametri di generazione nei PNG, segmenti C2PA.")
    categories = {Category.AI_GENERATION, Category.DEEPFAKE}

    def extra_top(self) -> None:
        self.root.addWidget(not_implemented(
            "Non ancora implementati (milestone 4): validazione crittografica C2PA, rilevamento di watermark, modelli "
            "di classificazione locali (ONNX/PyTorch) e rilevamento deepfake. Nessun risultato in questa pagina deriva "
            "da un modello statistico. L'assenza di indicatori nei metadati non esclude la generazione AI: i metadati "
            "si rimuovono facilmente."))


class VideoForensicsPage(Page):
    title = "Video e audio"
    intro = ("Contenitore, stream e coerenza tra tracce, letti con FFprobe, e albero degli atom per MP4/MOV. "
             "Durate diverse tra audio e video, tracce create in momenti diversi o un encoder di editing sono "
             "elementi da approfondire.")

    def __init__(self, state):
        super().__init__(state)
        self.root.addWidget(not_implemented(
            "Non ancora implementati (milestone 3): estrazione e confronto dei frame, frame duplicati o mancanti, "
            "analisi GOP e compressione per segmento, waveform e spettrogramma audio."))
        tabs = QTabWidget()
        self.streams = make_table(["#", "Tipo", "Codec", "Profilo", "Risoluzione", "Frame rate (nom./medio)",
                                   "Durata", "Bitrate", "Tag"])
        self.fmt = make_table(["Proprietà", "Valore"])
        self.atoms = QTreeWidget()
        self.atoms.setHeaderLabels(["Atom", "Offset", "Lunghezza", "Campi"])
        self.fv = FindingsView({Category.VIDEO_INTEGRITY, Category.AUDIO_INTEGRITY, Category.TEMPORAL,
                                Category.FILE_STRUCTURE})
        tabs.addTab(self.streams, "Stream")
        tabs.addTab(self.fmt, "Contenitore")
        tabs.addTab(self.atoms, "Struttura atom")
        tabs.addTab(self.fv, "Risultati")
        self.root.addWidget(tabs, 1)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def refresh(self) -> None:
        an = self.state.last_analysis()
        v = an["results"].get("video") if an else None
        self.atoms.clear()
        if not v:
            self.streams.setRowCount(0)
            self.fmt.setRowCount(0)
            self.fv.set_findings([])
            return
        rows = []
        for s in v["streams"]:
            res = f"{s.get('width')}x{s.get('height')}" if s.get("width") else \
                (f"{s.get('sample_rate')} Hz, {s.get('channels')} ch" if s.get("sample_rate") else "")
            fr = f"{s.get('r_frame_rate')} / {s.get('avg_frame_rate')}" if s.get("r_frame_rate") else ""
            rows.append([s["index"], s["type"], s["codec"], s.get("profile"), res, fr, s.get("duration"),
                         s.get("bit_rate"), "; ".join(f"{k}={val}" for k, val in s.get("tags", {}).items())])
        fill_table(self.streams, rows)
        fill_table(self.fmt, [["Contenitore", v["container"]], ["Durata (s)", v["duration_s"]],
                              ["Bitrate", v["bitrate"]], ["Dimensione", v["size"]]] +
                   [[f"tag: {k}", val] for k, val in v["tags"].items()])
        st = an["results"].get("structure")
        if st:
            def add(parent, node):
                it = QTreeWidgetItem([node["name"], f"0x{node['offset']:X}", str(node["length"]),
                                      "; ".join(f"{k}={val}" for k, val in node["fields"].items())[:300]])
                (parent.addChild(it) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(it))
                for c in node["children"]:
                    add(it, c)
            for c in st["root"]["children"]:
                add(self.atoms, c)
            self.atoms.expandToDepth(1)
            for i in range(4):
                self.atoms.resizeColumnToContents(i)
        self.fv.set_findings(an["findings"])
