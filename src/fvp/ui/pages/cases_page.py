"""Case Management e Chain of Custody."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from ...cases.store import Case, CaseError
from ..theme import C, span
from ..widgets.common import Page, fill_table, make_table


class CasesPage(Page):
    title = "Casi"
    lead = "Crea un caso nuovo oppure apri un caso già esistente."
    intro = ("Primo passo obbligatorio: crea un nuovo caso o aprine uno esistente. Le altre sezioni si attivano "
             "quando un caso è aperto. Ogni caso è una cartella autonoma con database, copie di lavoro, mappe di "
             "analisi e report; il registro delle operazioni è a catena di hash, quindi alterazioni e cancellazioni "
             "sono rilevabili con 'Verifica catena'.")

    def __init__(self, state):
        super().__init__(state)
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Nuovo caso")
        f = QFormLayout(g)
        self.cid, self.ctitle, self.cop = QLineEdit(), QLineEdit(), QLineEdit()
        self.cid.setPlaceholderText("es. RGNR 1234/2026 o PROC-2026-0142")
        self.cop.setPlaceholderText("Nome e cognome dell'analista")
        self.cdesc = QPlainTextEdit()
        self.cdesc.setMaximumHeight(70)
        f.addRow("Operatore", self.cop)
        f.addRow("Numero del caso", self.cid)
        f.addRow("Titolo", self.ctitle)
        f.addRow("Descrizione", self.cdesc)
        bc = QPushButton("Crea caso")
        bc.setObjectName("Primary")
        bc.clicked.connect(self._create)
        f.addRow(bc)
        ll.addWidget(g)
        g2 = QGroupBox("Casi esistenti")
        l2 = QVBoxLayout(g2)
        self.cases = make_table(["Numero", "Titolo", "Operatore", "Reperti", "Aperto (UTC)"])
        self.cases.cellDoubleClicked.connect(self._open_row)
        l2.addWidget(self.cases)
        bo = QPushButton("Apri caso selezionato")
        bo.clicked.connect(lambda: self._open_row(self.cases.currentRow(), 0))
        l2.addWidget(bo)
        ll.addWidget(g2, 1)
        sp.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.cur = QLabel()
        self.cur.setWordWrap(True)
        top.addWidget(self.cur, 1)
        self.close_btn = QPushButton("Chiudi caso")
        self.close_btn.clicked.connect(self._close_case)
        top.addWidget(self.close_btn)
        rl.addLayout(top)
        tabs = QTabWidget()
        exw = QWidget()
        el = QVBoxLayout(exw)
        self.exh = make_table(["ID", "Etichetta", "File originale", "Dimensione", "Acquisito (UTC)", "SHA-256"])
        self.exh.itemSelectionChanged.connect(self._pick_ex)
        el.addWidget(self.exh, 1)
        self.notes_w = QWidget()
        nl = QVBoxLayout(self.notes_w)
        nl.setContentsMargins(0, 0, 0, 0)
        nrow = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Valutazione dell'operatore sul reperto selezionato (finisce nel report)")
        bn = QPushButton("Aggiungi valutazione")
        bn.clicked.connect(self._add_note)
        nrow.addWidget(self.note, 1)
        nrow.addWidget(bn)
        nl.addLayout(nrow)
        self.notes = make_table(["UTC", "Operatore", "Valutazione"])
        self.notes.setMaximumHeight(150)
        nl.addWidget(self.notes)
        el.addWidget(self.notes_w)
        tabs.addTab(exw, "File del caso")
        cw = QWidget()
        cl = QVBoxLayout(cw)
        crow = QHBoxLayout()
        bcv = QPushButton("Registra evento di custodia…")
        bcv.clicked.connect(self._custody)
        bv = QPushButton("Verifica catena")
        bv.clicked.connect(self._verify)
        crow.addWidget(bcv)
        crow.addWidget(bv)
        crow.addStretch(1)
        cl.addLayout(crow)
        self.chain = QLabel()
        self.chain.setWordWrap(True)
        cl.addWidget(self.chain)
        self.custody = make_table(["#", "UTC", "Operatore", "Azione", "Tipo", "Dettagli", "Hash voce"])
        cl.addWidget(self.custody, 1)
        tabs.addTab(cw, "Registro delle operazioni")
        rl.addWidget(tabs, 1)
        sp.addWidget(right)
        sp.setSizes([420, 800])
        self.root.addWidget(sp, 1)
        state.case_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    def apply_mode(self) -> None:
        # le valutazioni dell'operatore restano disponibili; in vista semplice compaiono solo con un caso aperto
        self.notes_w.setVisible(not self.simple or self.state.case is not None)

    def refresh(self) -> None:
        self.apply_mode()
        if not self.cop.text():
            self.cop.setText(self.state.settings.operator)
        self._cases = Case.list_cases(self.state.settings.cases_path)
        fill_table(self.cases, [[c.get("case_id"), c.get("title"), c.get("operator"), c["exhibits"],
                                 (c.get("opened_utc") or "")[:19]] for c in self._cases])
        case = self.state.case
        self.close_btn.setEnabled(case is not None)
        if not case:
            self.cur.setText("Nessun caso aperto.")
            for t in (self.exh, self.custody, self.notes):
                t.setRowCount(0)
            return
        i = case.info
        self.cur.setText(f"<b>{i.get('case_id')}</b> — {i.get('title')}<br><span style='color:{C['muted']}'>"
                         f"{case.root}</span>")
        self._exs = case.exhibits()
        fill_table(self.exh, [[e.id, e.label, e.source_path, f"{e.size:,}", e.acquired_utc[:19],
                               e.source_hashes.get("sha256", "")] for e in self._exs])
        for r, e in enumerate(self._exs):
            if e.id == self.state.exhibit_id:
                self.exh.blockSignals(True)
                self.exh.selectRow(r)
                self.exh.blockSignals(False)
        fill_table(self.custody, [[e["seq"], e["ts_utc"][:23], e["actor"], e["action"], e["kind"],
                                   str({k: v for k, v in e["details"].items() if k != "source_stat"})[:300],
                                   e["entry_hash"][:20] + "…"] for e in case.audit.entries()])
        self._notes()

    def _notes(self) -> None:
        if self.state.case and self.state.exhibit_id:
            fill_table(self.notes, [[n["ts_utc"][:19], n["operator"], n["text"]]
                                    for n in self.state.case.notes(self.state.exhibit_id)])

    def _set_operator(self) -> bool:
        op = self.cop.text().strip()
        if not op:
            self.error("Indica il nome dell'operatore.")
            return False
        if op != self.state.settings.operator:
            self.state.settings.operator = op
            self.state.settings.save()
            self.state.settings_changed.emit()
        return True

    def _create(self) -> None:
        if not self._set_operator():
            return
        if not self.cid.text().strip() or not self.ctitle.text().strip():
            return self.error("Inserisci il numero del caso e un titolo.")
        try:
            c = Case.create(self.state.settings.cases_path, self.cid.text().strip(), self.ctitle.text().strip(),
                            self.state.settings.operator, self.cdesc.toPlainText().strip())
        except (CaseError, OSError) as e:
            return self.error(str(e))
        self.cid.clear()
        self.ctitle.clear()
        self.cdesc.clear()
        self.state.set_case(c)

    def _open_row(self, row: int, _col: int) -> None:
        if row < 0 or row >= len(self._cases) or not self._set_operator():
            return
        try:
            self.state.set_case(Case.open(self._cases[row]["path"], self.state.settings.operator))
        except (CaseError, OSError) as e:
            self.error(str(e))

    def _close_case(self) -> None:
        if self.state.case and not self.state.busy:
            self.state.case.audit.append(self.state.operator, "caso_chiuso", {})
            self.state.set_case(None)

    def _pick_ex(self) -> None:
        rows = self.exh.selectionModel().selectedRows()
        if rows:
            ex_id = self.exh.item(rows[0].row(), 0).text()
            if ex_id != self.state.exhibit_id:
                self.state.set_exhibit(ex_id)
            self._notes()

    def _add_note(self) -> None:
        t = self.note.text().strip()
        if not (t and self.state.case and self.state.exhibit_id):
            return
        self.state.case.add_note(self.state.exhibit_id, self.state.operator, t)
        self.note.clear()
        self.refresh()

    def _custody(self) -> None:
        if not self.state.case:
            return
        actions = ["trasferimento", "consegna", "ricezione", "sigillatura", "apertura_sigillo", "copia_su_supporto",
                   "restituzione", "altro"]
        act, ok = QInputDialog.getItem(self, "Evento di custodia", "Tipo di evento", actions, 0, False)
        if not ok:
            return
        det, ok = QInputDialog.getMultiLineText(self, "Evento di custodia",
                                                "Dettagli (da chi, a chi, supporto, sigilli, luogo):")
        if ok:
            self.state.case.record_custody(self.state.operator, act, {"exhibit": self.state.exhibit_id, "note": det})
            self.refresh()

    def _verify(self) -> None:
        if not self.state.case:
            return
        v = self.state.case.audit.verify()
        self.chain.setText(f"{span('green', 'Catena integra')}: {v.entries} voci. Hash di testa "
                           f"<code>{v.head}</code>" if v.ok else
                           span('red', f'Catena non valida alla voce {v.broken_at}: {v.reason}', True))
