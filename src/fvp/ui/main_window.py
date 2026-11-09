"""Finestra principale.

Flusso obbligatorio: senza un caso aperto sono accessibili solo Case Management e Settings; aperto o creato un
caso si passa al caricamento delle immagini. Tema chiaro predefinito, commutabile in scuro.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__
from . import theme
from .pages.advanced import ComparisonPage, PrnuPage, SteganalysisPage
from .pages.analysis_views import AIDetectionPage, ImageForensicsPage, ManipulationPage, VideoForensicsPage
from .pages.cases_page import CasesPage
from .pages.dashboard import DashboardPage
from .pages.hex_page import HexPage
from .pages.integrity import IntegrityPage
from .pages.load_page import LoadPage
from .pages.metadata_timeline import MetadataPage, TimelinePage
from .pages.pose_page import PosePage
from .pages.misc_pages import ReportsPage, SettingsPage
from .state import AppState
from .theme import C

# None = intestazione di sezione non selezionabile
SECTIONS = [
    ("FLUSSO DI LAVORO", ["Case Management", "Carica e analizza", "Dashboard"]),
    ("ANALISI", ["Image Forensics", "Manipulation Detection", "Steganalysis", "Metadata Analyzer",
                 "Timeline Analyzer", "PRNU / Sensore", "AI Detection", "Video Forensics", "Human Pose"]),
    ("STRUMENTI", ["Comparison Tool", "Hex Viewer", "File Integrity", "Reports"]),
    ("SISTEMA", ["Settings"]),
]
NAV = [n for _, items in SECTIONS for n in items]
LABELS = {
    "Case Management": "Casi", "Carica e analizza": "Carica e analizza", "Dashboard": "Riepilogo",
    "Image Forensics": "Analisi visiva", "Manipulation Detection": "Possibili modifiche",
    "Steganalysis": "Contenuti nascosti", "Metadata Analyzer": "Metadati", "Timeline Analyzer": "Date e orari",
    "PRNU / Sensore": "Fotocamera di origine", "AI Detection": "Intelligenza artificiale",
    "Video Forensics": "Video e audio", "Human Pose": "Persone e movimento",
    "Comparison Tool": "Confronta immagini", "Hex Viewer": "Byte del file (Hex)",
    "File Integrity": "Verifica hash", "Reports": "Report", "Settings": "Impostazioni",
}
HINTS = {
    "Case Management": "Crea o apri un caso: è il primo passo obbligatorio.",
    "Carica e analizza": "Aggiungi immagini o cartelle al caso e avvia l'analisi.",
    "Dashboard": "Cosa ha trovato il programma, in parole semplici.",
    "Image Forensics": "L'immagine affiancata alle mappe di analisi (ELA, copia di regioni, contrasto esaltato…).",
    "Manipulation Detection": "Segni di ritocchi, regioni copiate, ricompressioni.",
    "Steganalysis": "Messaggi, file o testo nascosti nell'immagine o nei suoi dati.",
    "Metadata Analyzer": "Informazioni scritte nel file da fotocamera e programmi.",
    "Timeline Analyzer": "Tutte le date e gli orari del file in ordine.",
    "PRNU / Sensore": "Confronto con l'impronta del sensore di fotocamere note.",
    "AI Detection": "Indizi di generazione con intelligenza artificiale nei metadati.",
    "Video Forensics": "Tracce, durate e codifica di video e audio.",
    "Human Pose": "Posa e angoli delle persone, continuità del movimento tra i frame (Sports2D).",
    "Comparison Tool": "Confronta due immagini e trova quasi-duplicati.",
    "Hex Viewer": "Il contenuto grezzo del file, byte per byte (sola lettura).",
    "File Integrity": "Calcola e confronta le impronte hash di file e cartelle.",
    "Reports": "Genera il report HTML, JSON o CSV del caso.",
    "Settings": "Operatore, tema, percorsi e stato del sistema.",
}
ALWAYS = {"Case Management", "Settings"}


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1440, 900)
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        brand = QWidget()
        brand.setObjectName("Brand")
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(16, 14, 16, 8)
        n = QLabel(APP_NAME)
        n.setObjectName("BrandName")
        v = QLabel(f"versione {__version__}")
        v.setObjectName("Muted")
        bl.addWidget(n)
        bl.addWidget(v)
        lv.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.items: dict[str, QListWidgetItem] = {}
        for title, names in SECTIONS:
            hdr = QListWidgetItem(title)
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            f = hdr.font()
            f.setPointSize(8)
            f.setBold(True)
            hdr.setFont(f)
            self.nav.addItem(hdr)
            for nm in names:
                it = QListWidgetItem(LABELS[nm])
                it.setData(Qt.ItemDataRole.UserRole, nm)
                self.nav.addItem(it)
                self.items[nm] = it
        for w_ in (self.nav, brand):
            w_.setFixedWidth(232)
        lv.addWidget(self.nav, 1)
        h.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        ctx = QWidget()
        ctx.setObjectName("ContextBar")
        cl = QHBoxLayout(ctx)
        cl.setContentsMargins(22, 8, 22, 8)
        self.case_lbl = QLabel()
        cl.addWidget(self.case_lbl)
        cl.addSpacing(16)
        self.ex_lbl = QLabel("File")
        cl.addWidget(self.ex_lbl)
        self.ex_combo = QComboBox()
        self.ex_combo.setMinimumWidth(320)
        self.ex_combo.currentIndexChanged.connect(self._ex_selected)
        cl.addWidget(self.ex_combo)
        cl.addStretch(1)
        self.sys_lbl = QLabel()
        cl.addWidget(self.sys_lbl)
        self.strict = QLabel()
        cl.addWidget(self.strict)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self.toggle_theme)
        cl.addWidget(self.theme_btn)
        rv.addWidget(ctx)
        self.stack = QStackedWidget()
        s = state
        self.pages = {
            "Case Management": CasesPage(s), "Carica e analizza": LoadPage(s), "Dashboard": DashboardPage(s),
            "Image Forensics": ImageForensicsPage(s), "Manipulation Detection": ManipulationPage(s),
            "Steganalysis": SteganalysisPage(s), "Metadata Analyzer": MetadataPage(s),
            "Timeline Analyzer": TimelinePage(s), "PRNU / Sensore": PrnuPage(s), "AI Detection": AIDetectionPage(s),
            "Video Forensics": VideoForensicsPage(s), "Human Pose": PosePage(s),
            "Comparison Tool": ComparisonPage(s), "Hex Viewer": HexPage(s),
            "File Integrity": IntegrityPage(s), "Reports": ReportsPage(s), "Settings": SettingsPage(s)}
        for k in NAV:
            self.stack.addWidget(self.pages[k])
        rv.addWidget(self.stack, 1)
        h.addWidget(right, 1)
        self.setCentralWidget(central)
        self.nav.currentItemChanged.connect(self._nav)
        sb = self.statusBar()
        self.status_msg = QLabel("Pronto")
        sb.addWidget(self.status_msg, 1)
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(280)
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.cancel = QPushButton("Annulla")
        self.cancel.hide()
        self.cancel.clicked.connect(state.cancel)
        sb.addPermanentWidget(self.bar)
        sb.addPermanentWidget(self.cancel)
        state.progress.connect(lambda p, m: (self.bar.setValue(int(p * 1000)), self.status_msg.setText(m)))
        state.busy_changed.connect(self._busy)
        state.case_changed.connect(self._case_changed)
        state.exhibit_changed.connect(self._ctx)
        state.analysis_changed.connect(self._ctx)
        state.settings_changed.connect(self._ctx)
        state.navigate.connect(self.go_to)
        state.open_hex.connect(self._open_hex)
        state.show_map.connect(lambda k: self.pages["Image Forensics"].show_map(k) if k else None)
        self._ctx()
        self.go_to("Case Management")

    # ---------- navigazione ----------
    def go_to(self, name: str) -> None:
        it = self.items[name]
        if it.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.nav.setCurrentItem(it)

    def _nav(self, cur: QListWidgetItem, _prev) -> None:
        if not cur:
            return
        name = cur.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        page = self.pages[name]
        self.stack.setCurrentWidget(page)
        page.refresh()

    def current_name(self) -> str:
        it = self.nav.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else ""

    def _open_hex(self, path: str) -> None:
        self.go_to("Hex Viewer")
        self.pages["Hex Viewer"].open_path(path)

    def _case_changed(self) -> None:
        self._ctx()
        c = self.state.case
        if c and self.current_name() == "Case Management":
            self.go_to("Dashboard" if c.exhibits() else "Carica e analizza")
        elif not c and self.current_name() not in ALWAYS:
            self.go_to("Case Management")

    # ---------- tema ----------
    def toggle_theme(self) -> None:
        s = self.state.settings
        s.ui_theme = "light" if s.ui_theme == "dark" else "dark"
        s.save()
        theme.apply(QApplication.instance(), s.ui_theme)
        self.state.theme_changed.emit()
        self._ctx()
        self.stack.currentWidget().refresh()

    # ---------- controllo di sistema ----------
    def start_selfcheck(self) -> None:
        from ..core import selfcheck
        self.sys_lbl.setText("Controllo del sistema…")
        s = self.state.settings

        def done(checks):
            self.state.selfcheck = checks
            ok, failed = selfcheck.summary(checks)
            self._sys_text()
            if not ok:
                QMessageBox.warning(self, APP_NAME, "Alcuni componenti essenziali non sono disponibili:\n\n" +
                                    "\n".join(f"• {c.name}: {c.detail}" for c in failed) +
                                    "\n\nI moduli che li usano segnaleranno i risultati come non determinabili. "
                                    "Dettagli in Settings.")
            self.state.settings_changed.emit()
        self.state.run(lambda _p, _c: selfcheck.run(s), done,
                       lambda m: self.sys_lbl.setText(theme.span("red", "Controllo di sistema non riuscito")))

    def _sys_text(self) -> None:
        from ..core import selfcheck
        checks = self.state.selfcheck
        if not checks:
            return
        ok, failed = selfcheck.summary(checks)
        self.sys_lbl.setText(theme.span("green", "Sistema verificato") if ok else
                             theme.span("red", f"{len(failed)} problemi di sistema", True))
        self.sys_lbl.setToolTip("\n".join(f"{'OK' if c.ok else 'KO'}  {c.name}: {c.detail}" for c in checks))

    # ---------- stato ----------
    def _busy(self, b: bool) -> None:
        self.bar.setVisible(b)
        self.cancel.setVisible(b)
        if not b:
            self.status_msg.setText("Pronto")
            self.stack.currentWidget().refresh()

    def _ctx(self) -> None:
        c = self.state.case
        for name, it in self.items.items():
            enabled = name in ALWAYS or c is not None
            it.setFlags((Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable) if enabled else Qt.ItemFlag.NoItemFlags)
            it.setToolTip(HINTS[name] if enabled else "Crea o apri prima un caso nella sezione Casi")
        self.case_lbl.setText(f"Caso <b>{c.info.get('case_id')}</b>" if c else
                              f"<span style='color:{C['muted']}'>Nessun caso aperto: inizia dalla sezione Casi</span>")
        self.ex_combo.blockSignals(True)
        self.ex_combo.clear()
        if c:
            for e in c.exhibits():
                self.ex_combo.addItem(f"{e.id} · {e.label}", e.id)
            i = self.ex_combo.findData(self.state.exhibit_id)
            self.ex_combo.setCurrentIndex(max(i, 0))
        self.ex_combo.blockSignals(False)
        self.ex_combo.setVisible(bool(c))
        self.ex_lbl.setVisible(bool(c))
        st = self.state.settings.strict_forensic
        self.strict.setObjectName("Strict" if st else "StrictOff")
        self.strict.setText("Strict Forensic attiva" if st else "Strict Forensic disattivata")
        self.strict.style().unpolish(self.strict)
        self.strict.style().polish(self.strict)
        self.theme_btn.setText("Tema scuro" if self.state.settings.ui_theme != "dark" else "Tema chiaro")
        self._sys_text()

    def _ex_selected(self, _i: int) -> None:
        ex = self.ex_combo.currentData()
        if ex and ex != self.state.exhibit_id:
            self.state.set_exhibit(ex)
            self.stack.currentWidget().refresh()

    def closeEvent(self, e) -> None:
        if self.state.busy:
            if QMessageBox.question(self, APP_NAME, "Un'operazione è in corso. Annullarla e chiudere?") != \
                    QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.state.cancel()
            self.state.pool.waitForDone(10000)
        if self.state.case:
            self.state.case.audit.append(self.state.operator, "caso_chiuso", {})
            self.state.case.close()
        e.accept()
