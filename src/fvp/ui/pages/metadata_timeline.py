"""Pagine Metadata Analyzer e Timeline Analyzer."""
from __future__ import annotations

import csv
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSplitter)

from ...core.findings import Category
from ..theme import C
from ..widgets.common import link_findings, Page, fill_table, make_table
from ..widgets.findings_view import FindingsView

REL = {"dichiarato": "Dichiarato nel file (modificabile)", "calcolato": "Calcolato dall'analisi",
       "filesystem_copia": "Filesystem della copia di lavoro"}


class MetadataPage(Page):
    title = "Metadati"
    lead = "Le informazioni scritte nel file dalla fotocamera o dai programmi usati."
    intro = ("Tutti i metadati estratti, con la loro attendibilità. 'Dichiarato' significa scritto nel file da un "
             "dispositivo o software: può essere modificato e non si verifica da solo. I tempi del filesystem della "
             "copia di lavoro non descrivono l'originale (quelli dell'originale sono nella Timeline).")

    def __init__(self, state):
        super().__init__(state)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca in gruppo, tag o valore")
        self.search.textChanged.connect(self._filter)
        self.rel = QComboBox()
        self.rel.addItem("Tutte le attendibilità", None)
        for k, v in REL.items():
            self.rel.addItem(v, k)
        self.rel.currentIndexChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.rel)
        for txt, fn in (("Esporta JSON", self._json), ("Esporta CSV", self._csv)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.root.addLayout(bar)
        self.gps = QLabel()
        self.gps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.root.addWidget(self.gps)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.table = make_table(["Gruppo", "Tag", "Valore", "Attendibilità"])
        sp.addWidget(self.table)
        self.fv = FindingsView({Category.METADATA})
        link_findings(self.fv, state)
        sp.addWidget(self.fv)
        sp.setSizes([480, 220])
        self.root.addWidget(sp, 1)
        self.tool = QLabel()
        self.tool.setObjectName("Muted")
        self.root.addWidget(self.tool)
        self.tags: list[dict] = []
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def refresh(self) -> None:
        an = self.state.last_analysis()
        md = an["results"].get("metadata", {}) if an else {}
        self.tags = md.get("tags", [])
        self.tool.setText(f"Estratto con {md.get('tool')}" if md else "Nessun metadato: esegui un'analisi.")
        g = md.get("gps") or {}
        self.gps.setText(f"GPS dichiarato: {g['lat']:.6f}, {g['lon']:.6f}  (visualizzazione su mappa offline "
                         "prevista nella milestone 3)" if g else "")
        self.fv.set_findings(an["findings"] if an else [])
        self._filter()

    def _visible(self) -> list[dict]:
        q = self.search.text().lower().strip()
        r = self.rel.currentData()
        return [t for t in self.tags if (not r or t["reliability"] == r) and
                (not q or q in t["group"].lower() or q in t["tag"].lower() or q in t["value"].lower())]

    def _filter(self) -> None:
        vis = self._visible()
        cols = [QColor(C["muted"]) if t["reliability"] != "dichiarato" else None for t in vis]
        fill_table(self.table, [[t["group"], t["tag"], t["value"][:500], REL[t["reliability"]]] for t in vis], cols)

    def _export(self, kind: str):
        if not self.tags:
            return None
        f, _ = QFileDialog.getSaveFileName(self, "Esporta metadati", f"{self.state.exhibit_id}_metadati.{kind}")
        return f or None

    def _json(self) -> None:
        f = self._export("json")
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(self._visible(), fh, ensure_ascii=False, indent=2)
            self._log(f)

    def _csv(self) -> None:
        f = self._export("csv")
        if f:
            with open(f, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["gruppo", "tag", "valore", "attendibilita"])
                for t in self._visible():
                    w.writerow([t["group"], t["tag"], t["value"], t["reliability"]])
            self._log(f)

    def _log(self, path: str) -> None:
        self.state.case.audit.append(self.state.operator, "esportazione_metadati",
                                     {"exhibit": self.state.exhibit_id, "path": path})


class TimelinePage(Page):
    title = "Date e orari"
    lead = "Tutte le date e gli orari presenti nel file, in ordine."
    intro = ("Tutti i riferimenti temporali del reperto in ordine cronologico. Gli orari sono convertiti in UTC solo "
             "quando il fuso è dichiarato o previsto dalla specifica; gli altri restano in ora locale non "
             "determinata. I tempi del filesystem sono quelli dell'originale rilevati prima dell'acquisizione e non "
             "indicano la data di scatto.")

    def __init__(self, state):
        super().__init__(state)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.table = make_table(["UTC", "Locale (fuso ignoto)", "Sorgente", "Tipo", "Valore originale", "Nota"])
        sp.addWidget(self.table)
        self.fv = FindingsView({Category.TEMPORAL})
        link_findings(self.fv, state)
        sp.addWidget(self.fv)
        sp.setSizes([380, 300])
        self.root.addWidget(sp, 1)
        legend = QLabel(f"<span style='color:{C['text']}'>■</span> UTC determinato &nbsp; "
                        f"<span style='color:{C['yellow']}'>■</span> fuso non dichiarato &nbsp; "
                        f"<span style='color:{C['muted']}'>■</span> filesystem &nbsp; "
                        f"<span style='color:{C['red']}'>■</span> valore nullo o non valido")
        self.root.addWidget(legend)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def refresh(self) -> None:
        an = self.state.last_analysis()
        tl = an["results"].get("timeline", []) if an else []
        rows, cols = [], []
        for e in tl:
            rows.append([e["utc"] or "", e["local"] or "", e["source"], e["kind"], e["raw"], e["note"]])
            cols.append(QColor(C["red"]) if not (e["utc"] or e["local"]) else
                        QColor(C["muted"]) if e["kind"] == "filesystem" else
                        QColor(C["yellow"]) if not e["tz_known"] else None)
        fill_table(self.table, rows, cols, sortable=False)
        self.fv.set_findings(an["findings"] if an else [])


def copy_text(s: str) -> None:
    QApplication.clipboard().setText(s)
