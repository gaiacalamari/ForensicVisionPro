"""Vista dei risultati: elenco filtrabile con etichette semplici e scheda di dettaglio che spiega prima cosa
significa il risultato e poi riporta i dati tecnici."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QSplitter, QTableWidgetItem,
                               QTextBrowser, QVBoxLayout, QWidget)

from ...core import explain
from ...core.findings import Category, Finding, Level, Status
from ..theme import C, LEVEL_COLORS, STATUS_COLORS
from .common import make_table


class StatusGrid(QWidget):
    def __init__(self, parent=None, columns: int = 3):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.columns = columns
        self.labels: dict[Category, QLabel] = {}
        for i, cat in enumerate(Category):
            lab = QLabel()
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            self.grid.addWidget(lab, i // columns, i % columns)
            self.labels[cat] = lab
        self.set_status({})

    def set_status(self, status: dict[Category, Status], hide_unverified: bool = False) -> None:
        """hide_unverified: in vista semplice non mostra le aree non esaminate (es. "Audio" per una foto)."""
        for cat, lab in self.labels.items():
            st = status.get(cat, Status.GREY)
            lab.setVisible(not (hide_unverified and st == Status.GREY))
            lab.setText(f"<span style='color:{STATUS_COLORS[st.value]};font-size:13pt'>●</span>&nbsp; "
                        f"{explain.CATEGORY_LABELS[cat]} <span style='color:{C['muted']}'>· "
                        f"{explain.STATUS_PLAIN[st].lower()}</span>")
            lab.setToolTip(f"{explain.CATEGORY_HELP[cat]}\n\n{explain.STATUS_HELP[st]}")
        # le voci visibili si dispongono una dopo l'altra, senza buchi lasciati da quelle nascoste
        for lab in self.labels.values():
            self.grid.removeWidget(lab)
        i = 0
        for lab in self.labels.values():
            if not lab.isHidden():
                self.grid.addWidget(lab, i // self.columns, i % self.columns)
                i += 1


class FindingsView(QWidget):
    open_page = Signal(str, str)        # pagina dell'app, mappa collegata (può essere "")

    def __init__(self, categories: set[Category] | None = None, parent=None, detail_outside: bool = False):
        """detail_outside=True: il riquadro dei dettagli (self.detail) non è sotto la tabella, ma lo colloca la
        pagina dove preferisce (il Riepilogo lo mette a destra)."""
        super().__init__(parent)
        self.categories = categories
        self.findings: list[Finding] = []
        self.hide_info = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.only = QCheckBox("Solo ciò che merita attenzione")
        self.only.toggled.connect(self._fill)
        bar.addWidget(self.only)
        self.level = QComboBox()
        self.level.addItem("Tutti gli esiti", None)
        for lv in Level:
            self.level.addItem(explain.LEVEL_PLAIN[lv], lv)
        self.level.currentIndexChanged.connect(self._fill)
        bar.addWidget(self.level)
        bar.addStretch(1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        bar.addWidget(self.count)
        lay.addLayout(bar)
        sp = QSplitter(Qt.Orientation.Vertical)
        self.table = make_table(["Esito", "Area", "Risultato", "Posizione"])
        self.table.itemSelectionChanged.connect(self._show)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(self._link)
        sp.addWidget(self.table)
        if not detail_outside:
            sp.addWidget(self.detail)
            sp.setSizes([300, 220])
        lay.addWidget(sp, 1)
        self._vis: list[Finding] = []

    def set_findings(self, findings: list[Finding]) -> None:
        self.findings = [f for f in findings if not self.categories or f.category in self.categories]
        self._fill()

    def _visible(self) -> list[Finding]:
        lv = self.level.currentData()
        out = [f for f in self.findings if lv is None or f.level == lv]
        if self.only.isChecked():
            out = [f for f in out if explain.needs_attention(f)]
        elif self.hide_info and lv is None:
            out = [f for f in out if f.level != Level.INFO]
        return sorted(out, key=lambda f: (not explain.needs_attention(f), explain.SEVERITY[f.level]))

    def _fill(self) -> None:
        vis = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(vis))
        for r, f in enumerate(vis):
            vals = [explain.LEVEL_PLAIN[f.level], explain.CATEGORY_LABELS[f.category], f.title,
                    "" if f.offset is None else f"byte 0x{f.offset:X}"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QColor(LEVEL_COLORS[f.level.value]))
                    it.setToolTip(explain.LEVEL_HELP[f.level])
                if c == 2:
                    it.setToolTip(explain.plain_explanation(f))
                self.table.setItem(r, c, it)
        self._vis = vis
        self.table.clearSelection()
        self.table.resizeColumnsToContents()
        n_att = sum(explain.needs_attention(f) for f in vis)
        self.count.setText(f"{len(vis)} risultati · {n_att} da verificare")
        self.detail.setHtml(f"<p style='color:{C['muted']}'>" + (
            "Seleziona un risultato: vedrai cosa significa, cosa conviene fare e i dati tecnici." if vis else
            "Nessun risultato per i filtri scelti. Se il reperto non è ancora stato analizzato, usa Carica e analizza.")
            + "</p>")

    def select(self, finding_id: str) -> None:
        """Seleziona un risultato e ne mostra i dettagli (anche se era già selezionato o la tabella è chiusa)."""
        for attempt in (0, 1):
            if attempt:
                self.only.setChecked(False)
                self.level.setCurrentIndex(0)
            for r, f in enumerate(self._vis):
                if f.id == finding_id:
                    self.table.selectRow(r)
                    self.table.scrollToItem(self.table.item(r, 0))
                    self._show()
                    return

    def _show(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        f = self._vis[rows[0].row()]
        e = html.escape
        col = LEVEL_COLORS[f.level.value]
        page, art = explain.related_page(f), explain.related_map(f)
        step = explain.next_step(f)
        link = (f"<p><a href='open:{page}:{art or ''}'>Apri la vista collegata »</a></p>" if page else "")
        parts = [f"<p style='margin:0'><b style='color:{col}'>{e(explain.LEVEL_PLAIN[f.level])}</b>"
                 f" · {e(explain.CATEGORY_LABELS[f.category])}</p><h3 style='margin:4px 0 8px 0'>{e(f.title)}</h3>",
                 f"<p><b>Cosa significa.</b> {e(explain.plain_explanation(f))}</p>"]
        if step and explain.needs_attention(f):
            parts.append(f"<p><b>Cosa fare.</b> {e(step)}</p>")
        parts.append(link)
        parts.append(f"<p style='color:{C['muted']};margin-bottom:2px'><b>Dati tecnici</b></p><table cellpadding='3'>"
                     f"<tr><td style='color:{C['muted']}'>Descrizione</td><td>{e(f.description)}</td></tr>"
                     f"<tr><td style='color:{C['muted']}'>Metodo</td><td>{e(f.method)}</td></tr>")
        if f.evidence:
            parts.append(f"<tr><td style='color:{C['muted']}'>Evidenza</td><td><pre>{e(f.evidence)}</pre></td></tr>")
        if f.offset is not None:
            parts.append(f"<tr><td style='color:{C['muted']}'>Posizione</td><td>byte {f.offset:,} (0x{f.offset:X})</td></tr>")
        parts.append(f"<tr><td style='color:{C['muted']}'>Affidabilità</td><td>{e(f.confidence or 'n/d')}</td></tr>"
                     f"<tr><td style='color:{C['muted']}'>Limiti</td><td>{e(f.limitations or '—')}</td></tr>"
                     f"<tr><td style='color:{C['muted']}'>Modulo</td><td>{e(f.module)} ({e(f.level.label)})</td></tr></table>")
        self.detail.setHtml("".join(parts))

    def _link(self, url) -> None:
        s = url.toString()
        if s.startswith("open:"):
            _, page, art = s.split(":", 2)
            self.open_page.emit(page, art)


def status_for(analysis: dict | None) -> dict[Category, Status]:
    return explain.status_of(analysis)
