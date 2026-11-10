"""Componenti comuni delle pagine."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)


class Page(QWidget):
    """Pagina con titolo, una riga di spiegazione e la guida completa nascosta dietro "Come funziona".

    lead  = una frase semplice, sempre visibile (cosa si trova nella pagina);
    intro = spiegazione completa (metodo, limiti, come leggere i risultati), mostrata solo a richiesta.
    In vista semplice le pagine nascondono comandi e dettagli tecnici (apply_mode)."""
    title = ""
    lead = ""
    intro = ""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.simple = bool(getattr(state.settings, "ui_simple", True))
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 16, 22, 16)
        self.root.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel(self.title)
        t.setObjectName("PageTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.help_btn = QPushButton("Come funziona")
        self.help_btn.setObjectName("HelpButton")
        self.help_btn.setCheckable(True)
        self.help_btn.setVisible(bool(self.intro))
        head.addWidget(self.help_btn)
        self.root.addLayout(head)
        lead = self.lead or first_sentence(self.intro)
        if lead:
            i = QLabel(lead)
            i.setObjectName("PageIntro")
            i.setWordWrap(True)
            self.root.addWidget(i)
        self.help_box = QLabel(self.intro)
        self.help_box.setObjectName("HelpBox")
        self.help_box.setWordWrap(True)
        self.help_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.help_box.hide()
        self.root.addWidget(self.help_box)
        self.help_btn.toggled.connect(self._toggle_help)

    def _toggle_help(self, on: bool) -> None:
        self.help_box.setVisible(on)
        self.help_btn.setText("Nascondi la guida" if on else "Come funziona")

    def set_simple(self, simple: bool) -> None:
        self.simple = simple
        self.apply_mode()

    def apply_mode(self) -> None:
        """Mostra o nasconde i controlli avanzati secondo la vista (semplice / esperta)."""

    def refresh(self) -> None:
        """Aggiorna la pagina quando diventa visibile o cambia il contesto."""

    def error(self, msg: str) -> None:
        QMessageBox.warning(self, self.title, msg)


def first_sentence(text: str) -> str:
    import re
    m = re.search(r"[.!?](\s+)(?=[A-ZÈÀÉ'«])", text or "")
    return (text[:m.start() + 1] if m else text or "").strip()


def not_implemented(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("NotImpl")
    lab.setWordWrap(True)
    return lab


def make_table(headers: list[str], stretch_last: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setWordWrap(False)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    h.setStretchLastSection(stretch_last)
    return t


def fill_table(t: QTableWidget, rows: list[list], colors: list | None = None, sortable: bool = True) -> None:
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem("" if v is None else str(v))
            it.setToolTip(str(v)[:2000] if v is not None else "")
            if colors and colors[r]:
                it.setForeground(colors[r])
            t.setItem(r, c, it)
    t.resizeColumnsToContents()
    for c in range(t.columnCount() - 1):
        if t.columnWidth(c) > 420:
            t.setColumnWidth(c, 420)
    t.setSortingEnabled(sortable)


def kv_row(label: str, widget: QWidget) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label)
    lab.setMinimumWidth(130)
    lay.addWidget(lab)
    lay.addWidget(widget, 1)
    return w


def align_right(item: QTableWidgetItem) -> QTableWidgetItem:
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def link_findings(fv, state) -> None:
    """Collega 'Apri la vista collegata' di una vista risultati alla navigazione dell'app."""
    fv.open_page.connect(lambda page, art: (state.show_map.emit(art or ""), state.navigate.emit(page)))
