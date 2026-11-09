"""Pagina Persone e movimento: posa, angoli, discontinuità ed esportazioni del modulo pose (metodologia Sports2D)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from ...core.findings import Category
from ...engines.pose import ANGLE_LABELS_IT
from ..widgets.common import Page, fill_table, link_findings, make_table, not_implemented
from ..widgets.findings_view import FindingsView
from ..widgets.imageviews import SyncGroup

POSE_ARTS = ("pose", "pose_jumps", "pose_motion")


class PosePage(Page):
    title = "Persone e movimento"
    intro = ("Stima della posa di ogni persona (26 punti del corpo), angoli articolari e segmentali con le "
             "definizioni di Sports2D, tracciamento tra i frame e ricerca di discontinuità: salti di posizione o di "
             "scala e persone sostituite da un frame al successivo, confrontati con i timestamp e con il cambiamento "
             "complessivo dell'immagine. I keypoint sono in pixel: non sono misure del corpo in centimetri.")

    def __init__(self, state):
        super().__init__(state)
        self.root.addWidget(not_implemented(
            "Le discontinuità sono calcolate sui dati grezzi, prima di qualsiasi filtro. Gli angoli sono filtrati "
            "(Butterworth 4° ordine, 6 Hz, fase zero) come in Sports2D. Senza calibrazione della camera non si "
            "stimano statura né distanze; la cadenza è un dato descrittivo, non identificativo."))
        bar = QHBoxLayout()
        self.run_btn = QPushButton("Analizza persone e movimento")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._run)
        bar.addWidget(self.run_btn)
        self.open_btn = QPushButton("Apri la cartella delle esportazioni")
        self.open_btn.clicked.connect(self._open_dir)
        bar.addWidget(self.open_btn)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        bar.addWidget(self.status, 1)
        self.root.addLayout(bar)

        self.tabs = QTabWidget()
        self.persons = make_table(["Persona", "Frame", "Da (s)", "A (s)", "Copertura", "Altezza (px)", "Confidenza",
                                   "Lato", "Cadenza (passi/min)"])
        self.angles = make_table(["Persona", "Angolo", "Min (°)", "Max (°)", "Media (°)", "Campioni"])
        self.trans = make_table(["Frame", "Tempo (s)", "Classe", "Persone coinvolte", "Salto max (altezze)",
                                 "Velocità (alt./s)", "Scala", "Intervallo ×", "Cambio immagine ×", "Persone sostituite"])
        imgs = QWidget()
        il = QVBoxLayout(imgs)
        il.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.art_combo = QComboBox()
        self.art_combo.currentIndexChanged.connect(self._show_art)
        row.addWidget(self.art_combo, 1)
        self.sync = SyncGroup()
        for txt, fn in (("Adatta", self.sync.fit), ("100%", self.sync.actual)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        il.addLayout(row)
        w, self.view = self.sync.new_view("")
        il.addWidget(w, 1)
        self.exports = make_table(["File", "SHA-256", "Byte"])
        self.engine = make_table(["Proprietà", "Valore"])
        self.fv = FindingsView({Category.HUMAN_POSE})
        link_findings(self.fv, state)
        self.tabs.addTab(self.fv, "Risultati")
        self.tabs.addTab(imgs, "Immagini")
        self.tabs.addTab(self.trans, "Discontinuità")
        self.tabs.addTab(self.persons, "Persone")
        self.tabs.addTab(self.angles, "Angoli")
        self.tabs.addTab(self.exports, "Esportazioni")
        self.tabs.addTab(self.engine, "Modelli e parametri")
        self.root.addWidget(self.tabs, 1)
        self._arts: dict[str, str] = {}
        self._pending = ""
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)
        state.show_map.connect(self._want_map)

    # ---------------------------------------------------------------- dati
    def _pose(self) -> tuple[dict | None, dict | None]:
        an = self.state.last_analysis()
        return an, (an or {}).get("results", {}).get("pose")

    def refresh(self) -> None:
        an, pr = self._pose()
        self.fv.hide_info = self.state.settings.ui_mode == "Basic"
        self.fv.set_findings(an["findings"] if an else [])
        self.run_btn.setEnabled(bool(self.state.case and self.state.exhibit_id) and not self.state.busy)
        if not pr:
            for t in (self.persons, self.angles, self.trans, self.exports, self.engine):
                t.setRowCount(0)
            self.art_combo.clear()
            self.view.set_image(None)
            self.open_btn.setEnabled(False)
            self.status.setText("Nessuna stima della posa per il reperto selezionato." if self.state.exhibit_id else "")
            return
        fr = pr.get("frames", {})
        persons = pr.get("persons", [])
        trans = pr.get("transitions", [])
        self.status.setText(
            f"{len(persons)} persone · {fr.get('analyzed', 1)} frame analizzati · "
            f"{sum(1 for e in trans if e['class'] == 'scena')} discontinuità di scena, "
            f"{sum(1 for e in trans if e['class'] == 'isolata')} isolate")
        fill_table(self.persons, [[f"P{p['track']}", p.get("frames"), p.get("first_s"), p.get("last_s"),
                                   f"{p['coverage'] * 100:.0f}%" if p.get("coverage") is not None else "",
                                   p.get("height_px"), p.get("mean_score"), p.get("side"),
                                   (p.get("cadence") or {}).get("steps_per_min")] for p in persons])
        fill_table(self.angles, [[f"P{p['track']}", ANGLE_LABELS_IT.get(n, n), a["min"], a["max"], a["mean"], a["n"]]
                                 for p in persons for n, a in p.get("angles", {}).items()])
        fill_table(self.trans, [[e.get("source_frame", e["frame"]), e["time_s"], e["class"], ", ".join(f"P{t}" for t in e["tracks_flagged"]),
                                 max([j["jump_h"] for j in e["jumps"]] or [None], key=lambda v: v or 0),
                                 max([j["speed_h_s"] for j in e["jumps"]] or [None], key=lambda v: v or 0),
                                 ", ".join(f"×{s['ratio']}" for s in e["scale"]), e.get("dt_ratio"),
                                 e.get("visual_ratio"), "sì" if e["replaced"] else ""] for e in trans])
        fill_table(self.exports, [[Path(v["path"]).name, v["sha256"], v["size"]]
                                  for v in pr.get("exports", {}).values()])
        eng = pr.get("engine", {})
        rows = [["Runtime", eng.get("runtime")], ["Provider", eng.get("provider")]]
        for role in ("detector", "pose"):
            m = eng.get(role) or {}
            if m:
                rows += [[f"Modello {role}", m.get("file")], [f"SHA-256 {role}", m.get("sha256")],
                         [f"Verificato con tools.lock.json ({role})", "sì" if m.get("verified_against_lock") else "no"]]
        rows += [[f"parametro: {k}", v] for k, v in pr.get("params", {}).items()]
        rows += [[f"video: {k}", v] for k, v in fr.items()]
        fill_table(self.engine, rows, sortable=False)
        from ...core.pipeline import ARTIFACT_LABELS
        self._arts = {k: v for k, v in an["results"].get("artifacts", {}).items()
                      if k in POSE_ARTS and Path(v).is_file()}
        cur = self._pending or self.art_combo.currentData() or "pose_jumps"
        self.art_combo.blockSignals(True)
        self.art_combo.clear()
        for k in POSE_ARTS:
            if k in self._arts:
                self.art_combo.addItem(ARTIFACT_LABELS.get(k, k), k)
        i = self.art_combo.findData(cur)
        self.art_combo.setCurrentIndex(i if i >= 0 else 0)
        self.art_combo.blockSignals(False)
        if self._pending in self._arts:
            self.tabs.setCurrentIndex(1)
        self._pending = ""
        self.open_btn.setEnabled(bool(pr.get("exports")))
        self._show_art()

    def _show_art(self) -> None:
        self.view.set_image(self._arts.get(self.art_combo.currentData()))
        self.sync.fit()

    def _want_map(self, key: str) -> None:
        if key in POSE_ARTS:
            self._pending = key

    # ---------------------------------------------------------------- azioni
    def _open_dir(self) -> None:
        _an, pr = self._pose()
        ex = next(iter((pr or {}).get("exports", {}).values()), None)
        if ex:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(ex["path"]).parent)))

    def _run(self) -> None:
        if not (self.state.case and self.state.exhibit_id):
            return self.error("Nessun reperto selezionato.")
        from ...core.pipeline import analyze_exhibit
        case, ex, op, s = self.state.case, self.state.exhibit_id, self.state.operator, self.state.settings
        self.state.run(lambda p, c: analyze_exhibit(case, ex, op, s, ["integrity", "signature", "pose"], p, c),
                       lambda _r: self.state.analysis_changed.emit(), self.error)
