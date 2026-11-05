"""Componenti comuni delle pagine."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)


class Page(QWidget):
    title = ""
    intro = ""      # cosa analizza, perché è utile, come leggere i risultati

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 16, 22, 16)
        self.root.setSpacing(10)
        t = QLabel(self.title)
        t.setObjectName("PageTitle")
        self.root.addWidget(t)
        if self.intro:
            i = QLabel(self.intro)
            i.setObjectName("PageIntro")
            i.setWordWrap(True)
            self.root.addWidget(i)

    def refresh(self) -> None:
        """Aggiorna la pagina quando diventa visibile o cambia il contesto."""

    def error(self, msg: str) -> None:
        QMessageBox.warning(self, self.title, msg)


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
