"""Reports, Settings, Comparison Tool."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from ... import __version__
from ...core.tools import get_tool
from ...reporting import report
from ..theme import C, span
from ..widgets.common import Page, fill_table, make_table, not_implemented


class ReportsPage(Page):
    title = "Report"
    intro = ("Il report include, per ogni reperto, hash iniziali e finali, risultati automatici con metodo, "
             "evidenza, posizione, confidenza e limiti, le valutazioni dell'operatore in una sezione separata, la "
             "metodologia, le versioni degli strumenti e la catena di custodia. Ogni report generato è registrato "
             "con il suo SHA-256.")

    def __init__(self, state):
        super().__init__(state)
        row = QHBoxLayout()
        for txt, kind in (("Genera report HTML", "html"), ("Genera JSON completo", "json"),
                          ("Esporta risultati CSV", "csv")):
            b = QPushButton(txt)
            b.clicked.connect(lambda _=False, k=kind: self._gen(k))
            row.addWidget(b)
        row.addStretch(1)
        self.root.addLayout(row)
        self.root.addWidget(not_implemented("Report PDF: previsto nella milestone 3. Nel frattempo il report HTML è "
                                            "autocontenuto e stampabile in PDF dal browser."))
        self.table = make_table(["File", "Dimensione", "Modificato"])
        self.table.cellDoubleClicked.connect(self._open)
        self.root.addWidget(self.table, 1)
        state.case_changed.connect(self.refresh)

    def refresh(self) -> None:
        c = self.state.case
        self._files = sorted((c.root / "reports").glob("*"), reverse=True) if c else []
        from datetime import datetime
        fill_table(self.table, [[p.name, f"{p.stat().st_size:,}",
                                 datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")]
                                for p in self._files])

    def _gen(self, kind: str) -> None:
        c = self.state.case
        if not c:
            return self.error("Apri un caso.")
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = c.root / "reports" / f"{c.info.get('case_id', 'caso')}_{stamp}.{kind}"
        fn = {"html": report.write_html, "json": report.write_json, "csv": report.write_csv_findings}[kind]
        self.state.run(lambda _p, _c: fn(c, out), lambda p: (self.refresh(), self._open_path(p) if kind == "html" else None),
                       self.error)

    def _open(self, row: int, _c: int) -> None:
        self._open_path(self._files[row])

    @staticmethod
    def _open_path(p: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


class SettingsPage(Page):
    title = "Impostazioni"
    intro = "Le impostazioni sono salvate nella cartella utente e registrate nel caso quando cambiano."

    def __init__(self, state):
        super().__init__(state)
        s = state.settings
        g = QGroupBox("Operatore e modalità")
        f = QFormLayout(g)
        self.op = QLineEdit(s.operator)
        f.addRow("Operatore", self.op)
        self.mode = QComboBox()
        self.mode.addItems(["Basic", "Advanced", "Expert"])
        self.mode.setCurrentText(s.ui_mode)
        self.mode.setToolTip("Basic nasconde i risultati solo informativi nelle viste dei risultati.")
        f.addRow("Modalità", self.mode)
        self.theme = QComboBox()
        self.theme.addItem("Chiaro", "light")
        self.theme.addItem("Scuro", "dark")
        self.theme.setCurrentIndex(1 if s.ui_theme == "dark" else 0)
        f.addRow("Tema", self.theme)
        self.strict = QCheckBox("Strict Forensic")
        self.strict.setChecked(s.strict_forensic)
        self.strict.setToolTip("In questa versione nessuna funzione modifica i reperti, con o senza la modalità "
                               "Strict. Con Strict attiva l'indicatore resta verde e l'impostazione è registrata.")
        f.addRow("", self.strict)
        self.root.addWidget(g)
        g2 = QGroupBox("Percorsi")
        f2 = QFormLayout(g2)
        self.cases = QLineEdit(str(s.cases_path))
        self.exif = QLineEdit(s.exiftool_path)
        self.exif.setPlaceholderText("automatico (cartella bin o PATH)")
        self.ffp = QLineEdit(s.ffprobe_path)
        self.ffp.setPlaceholderText("automatico (cartella bin o PATH)")
        for lbl, w, d in (("Cartella dei casi", self.cases, True), ("ExifTool", self.exif, False),
                          ("FFprobe", self.ffp, False)):
            row = QHBoxLayout()
            row.addWidget(w, 1)
            b = QPushButton("…")
            b.setMaximumWidth(36)
            b.clicked.connect(lambda _=False, ww=w, dd=d: self._browse(ww, dd))
            row.addWidget(b)
            f2.addRow(lbl, row)
        self.timeout = QSpinBox()
        self.timeout.setRange(10, 3600)
        self.timeout.setValue(s.tool_timeout_s)
        f2.addRow("Timeout strumenti (s)", self.timeout)
        self.root.addWidget(g2)
        b = QPushButton("Salva impostazioni")
        b.setObjectName("Primary")
        b.clicked.connect(self._save)
        rb_ = QHBoxLayout()
        rb_.addWidget(b)
        rb_.addStretch(1)
        self.root.addLayout(rb_)
        g3 = QGroupBox("Stato del sistema")
        l3 = QVBoxLayout(g3)
        self.tools = QLabel()
        self.tools.setWordWrap(True)
        l3.addWidget(self.tools)
        self.checks = make_table(["Componente", "Livello", "Esito", "Dettaglio", "Versione"])
        l3.addWidget(self.checks, 1)
        rb = QPushButton("Riesegui il controllo")
        rb.clicked.connect(self._recheck)
        rr = QHBoxLayout()
        rr.addWidget(rb)
        rr.addStretch(1)
        l3.addLayout(rr)
        self.root.addWidget(g3, 1)
        state.settings_changed.connect(self.refresh)

    def refresh(self) -> None:
        from ...core import selfcheck
        checks = self.state.selfcheck
        if not checks:
            self.tools.setText(f"Forensic Vision Pro {__version__} · controllo in corso o non ancora eseguito.")
            self.checks.setRowCount(0)
            return
        ok, failed = selfcheck.summary(checks)
        self.tools.setText(f"Forensic Vision Pro {__version__} · " + (
            span("green", "tutti i componenti essenziali sono operativi") if ok else
            span("red", f"{len(failed)} componenti essenziali non operativi", True)))
        fill_table(self.checks, [[c.name, c.level, "OK" if c.ok else "NON OPERATIVO", c.detail, c.version]
                                 for c in checks],
                   [None if c.ok else QColor(C["red"] if c.level == "essenziale" else C["yellow"]) for c in checks],
                   sortable=False)

    def _recheck(self) -> None:
        from ...core import selfcheck
        get_tool.cache_clear()
        s = self.state.settings

        def done(checks):
            self.state.selfcheck = checks
            self.state.settings_changed.emit()
        self.state.run(lambda _p, _c: selfcheck.run(s), done, self.error)

    def _browse(self, w: QLineEdit, d: bool) -> None:
        p = QFileDialog.getExistingDirectory(self) if d else QFileDialog.getOpenFileName(self)[0]
        if p:
            w.setText(p)

    def _save(self) -> None:
        s = self.state.settings
        old = dict(s.__dict__)
        s.operator, s.ui_mode, s.strict_forensic = self.op.text().strip(), self.mode.currentText(), self.strict.isChecked()
        s.cases_dir, s.exiftool_path, s.ffprobe_path = self.cases.text().strip(), self.exif.text().strip(), self.ffp.text().strip()
        s.tool_timeout_s = self.timeout.value()
        new_theme = self.theme.currentData()
        theme_changed = new_theme != s.ui_theme
        s.ui_theme = new_theme
        s.save()
        if theme_changed:
            from PySide6.QtWidgets import QApplication

            from .. import theme
            theme.apply(QApplication.instance(), new_theme)
            self.state.theme_changed.emit()
        get_tool.cache_clear()
        if self.state.case:
            changed = {k: v for k, v in s.__dict__.items() if old.get(k) != v}
            if changed:
                self.state.case.audit.append(s.operator, "impostazioni_modificate", changed)
        self.state.settings_changed.emit()
        self._recheck()
