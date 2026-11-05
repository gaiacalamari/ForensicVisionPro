from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...core import explain
from ..theme import C, LEVEL_COLORS, STATUS_COLORS
from ..widgets.common import Page, fill_table, make_table
from ..widgets.findings_view import FindingsView, StatusGrid, status_for



class Stat(QWidget):
    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("Stat")
        lay = QVBoxLayout(self)
        self.v = QLabel("0")
        self.v.setObjectName("StatValue")
        lab = QLabel(label)
        lab.setObjectName("Muted")
        lay.addWidget(self.v)
        lay.addWidget(lab)


class DashboardPage(Page):
    title = "Riepilogo"
    intro = ("Cosa ha trovato il programma, in parole semplici: prima la sintesi del caso, poi il file selezionato. "
             "I colori indicano dove guardare, non se un file è autentico.")

    def __init__(self, state):
        super().__init__(state)
        self.case_text = QLabel()
        self.case_text.setObjectName("Notice")
        self.case_text.setWordWrap(True)
        self.root.addWidget(self.case_text)
        row = QHBoxLayout()
        self.s = {k: Stat(lbl) for k, lbl in (("files", "File analizzati"), ("red", "Richiedono attenzione"),
                                              ("yellow", "Da approfondire"), ("hidden", "Con contenuti nascosti"))}
        for w in self.s.values():
            row.addWidget(w)
        self.root.addLayout(row)
        mid = QHBoxLayout()
        g1 = QGroupBox("File selezionato")
        l1 = QVBoxLayout(g1)
        self.ex_label = QLabel()
        self.ex_label.setWordWrap(True)
        self.ex_label.setTextFormat(Qt.TextFormat.RichText)
        l1.addWidget(self.ex_label)
        self.att_box = QGroupBox("Cosa merita attenzione")
        self.att_outer = QVBoxLayout(self.att_box)
        self.att_widget = QWidget()
        self.att_outer.addWidget(self.att_widget)
        l1.addWidget(self.att_box)
        self.fv = FindingsView()
        self.fv.open_page.connect(self._open)
        l1.addWidget(self.fv, 1)
        mid.addWidget(g1, 3)
        side = QVBoxLayout()
        g2 = QGroupBox("Esito per area")
        l2 = QVBoxLayout(g2)
        self.grid = StatusGrid(columns=1)
        l2.addWidget(self.grid)
        side.addWidget(g2)
        g3 = QGroupBox("Attività recenti del caso")
        l3 = QVBoxLayout(g3)
        self.activity = make_table(["Data e ora (UTC)", "Operatore", "Azione"])
        l3.addWidget(self.activity)
        side.addWidget(g3, 1)
        mid.addLayout(side, 2)
        self.root.addLayout(mid, 1)
        state.case_changed.connect(self.refresh)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def _open(self, page: str, art: str) -> None:
        self.state.show_map.emit(art or "")
        self.state.navigate.emit(page)

    def _fill_attention(self, an) -> None:
        # il contenitore viene sostituito a ogni aggiornamento: nessun residuo delle voci precedenti
        old = self.att_widget
        self.att_widget = QWidget()
        lay = QVBoxLayout(self.att_widget)
        lay.setContentsMargins(0, 0, 0, 0)
        self.att_outer.replaceWidget(old, self.att_widget)
        old.setParent(None)
        old.deleteLater()
        att = explain.attention(an["findings"]) if an else []
        if not att:
            lab = QLabel("Nessun elemento da segnalare nei controlli eseguiti." if an else "—")
            lab.setObjectName("Muted")
            lay.addWidget(lab)
            return
        for f in att[:6]:
            row = QHBoxLayout()
            lab = QLabel(f"<b style='color:{LEVEL_COLORS[f.level.value]}'>{explain.LEVEL_PLAIN[f.level]}</b> · "
                         f"<b>{html.escape(f.title)}</b><br><span style='color:{C['muted']}'>"
                         f"{html.escape(explain.plain_explanation(f))}</span>")
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(lab, 1)
            b = QPushButton("Dettagli")
            b.setToolTip("Mostra la spiegazione completa e i dati tecnici qui sotto")
            b.clicked.connect(lambda _=False, i=f.id: self.fv.select(i))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
            page = explain.related_page(f)
            if page:
                b2 = QPushButton("Apri vista")
                b2.setToolTip("Apre la sezione collegata a questo risultato")
                b2.clicked.connect(lambda _=False, p=page, m=explain.related_map(f) or "": self._open(p, m))
                row.addWidget(b2, 0, Qt.AlignmentFlag.AlignTop)
            lay.addLayout(row)
        if len(att) > 6:
            more = QLabel(f"… e altri {len(att) - 6}: attiva il filtro «Solo ciò che merita attenzione» qui sotto.")
            more.setObjectName("Muted")
            lay.addWidget(more)

    def refresh(self) -> None:
        case = self.state.case
        if not case:
            self.case_text.setText("Nessun caso aperto.")
            self.activity.setRowCount(0)
            return
        ent = case.audit.entries()[-30:][::-1]
        fill_table(self.activity, [[e["ts_utc"][:19].replace("T", " "), e["actor"], e["action"].replace("_", " ")]
                                   for e in ent], sortable=False)
        pairs = []
        for ex in case.exhibits():
            an = case.analyses(ex.id)
            pairs.append((ex, an[-1] if an else None))
        cs = explain.case_summary(pairs)
        self.case_text.setText(f"<b>Sintesi del caso.</b> {html.escape(cs['text'])}")
        self.s["files"].v.setText(str(cs["analysed"]))
        self.s["red"].v.setText(str(cs["red"]))
        self.s["yellow"].v.setText(str(cs["attention_files"] - cs["red"]))
        self.s["hidden"].v.setText(str(cs["hidden_files"]))
        an = self.state.last_analysis()
        if self.state.exhibit_id:
            ex = case.exhibit(self.state.exhibit_id)
            ov = explain.overall(an)
            self.ex_label.setText(f"<span style='font-size:12pt'><b>{html.escape(ex.original_name)}</b></span> "
                                  f"<span style='color:{STATUS_COLORS[ov.value]}'>● {explain.STATUS_PLAIN[ov]}</span>"
                                  f"<br>{html.escape(explain.exhibit_summary(ex, an))}")
        else:
            self.ex_label.setText("Nessun file selezionato: caricane uno da «Carica e analizza».")
        self._fill_attention(an)
        self.grid.set_status(status_for(an))
        self.fv.hide_info = self.state.settings.ui_mode == "Basic"
        self.fv.set_findings(an["findings"] if an else [])
