"""Pagina Persone e movimento: posa, angoli, discontinuità ed esportazioni del modulo pose (metodologia Sports2D)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from ...core.findings import Category
from ...engines.pose import ANGLE_LABELS_IT, ANGLE_NAMES, read_mot
from ..theme import C
from ..widgets.common import Page, fill_table, link_findings, make_table, not_implemented
from ..widgets.findings_view import FindingsView
from ..widgets.imageviews import SyncGroup
from ..widgets.motion import AngleChart, VideoPlayer

POSE_ARTS = ("pose", "pose_angles", "pose_jumps", "pose_motion", "sports2d_angles")
SRC_FVP, SRC_S2D, SRC_IK = "fvp", "sports2d", "opensim"
IK_DEFAULT = ("knee angle r", "knee angle l", "hip flexion r", "hip flexion l")


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
        self.anim = self._build_animation()
        self.s2d = self._build_sports2d()
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
        self.tabs.addTab(self.anim, "Video e angoli")
        self.tabs.addTab(self.fv, "Risultati")
        self.tabs.addTab(imgs, "Immagini")
        self.tabs.addTab(self.trans, "Discontinuità")
        self.tabs.addTab(self.persons, "Persone")
        self.tabs.addTab(self.angles, "Angoli")
        self.tabs.addTab(self.exports, "Esportazioni")
        self.tabs.addTab(self.engine, "Modelli e parametri")
        self.tabs.addTab(self.s2d, "Sports2D / Pose2Sim originali")
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
        self._refresh_animation(an)
        self._refresh_sports2d(an)
        if not pr:
            for t in (self.persons, self.angles, self.trans, self.exports, self.engine):
                t.setRowCount(0)
            self.art_combo.clear()
            self.view.set_image(None)
            self.open_btn.setEnabled(False)
            msg = "Nessuna stima della posa per il reperto selezionato."
            if an and any(f.title == "Stima della posa non disponibile" for f in an["findings"]):
                msg = ("Stima della posa non disponibile: i modelli non sono installati (vedi la scheda Risultati e "
                       "il manuale, 'Installare i modelli per Persone e movimento').")
            elif an and "pose" not in an.get("modules", []):
                msg += " Il modulo non era tra quelli eseguiti: premi 'Analizza persone e movimento'."
            self.status.setText(msg if self.state.exhibit_id else "")
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
        self._analyze({"pose"})

    def _analyze(self, extra: set[str]) -> None:
        """Rianalizza conservando i moduli dell'analisi precedente: così le altre pagine non perdono i loro dati."""
        from ...core.pipeline import analyze_exhibit
        case, ex, op, s = self.state.case, self.state.exhibit_id, self.state.operator, self.state.settings
        an = self.state.last_analysis()
        mods = sorted(set((an or {}).get("modules", [])) | {"integrity", "signature"} | extra)
        mods.remove("integrity")
        mods = ["integrity"] + mods
        self.state.run(lambda p, c: analyze_exhibit(case, ex, op, s, mods, p, c),
                       lambda _r: self.state.analysis_changed.emit(), self.error)

    # ---------------------------------------------------------------- animazione (video + angoli)
    def _build_animation(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Fonte"))
        self.src = QComboBox()
        self.src.currentIndexChanged.connect(self._load_source)
        row.addWidget(self.src)
        row.addWidget(QLabel("Persona"))
        self.person = QComboBox()
        self.person.currentIndexChanged.connect(self._load_person)
        row.addWidget(self.person)
        self.anim_info = QLabel()
        self.anim_info.setObjectName("Muted")
        self.anim_info.setWordWrap(True)
        row.addWidget(self.anim_info, 1)
        lay.addLayout(row)
        split = QSplitter(Qt.Orientation.Vertical)
        self.player = VideoPlayer()
        split.addWidget(self.player)
        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        self.angle_list = QListWidget()
        self.angle_list.setMaximumWidth(220)
        self.angle_list.itemChanged.connect(self._angles_changed)
        bl.addWidget(self.angle_list)
        self.chart = AngleChart()
        bl.addWidget(self.chart, 1)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self.player.position_changed.connect(self.chart.set_cursor)
        self.chart.seek.connect(self.player.seek_time)
        self._sources: dict[str, dict] = {}
        return w

    def _refresh_animation(self, an: dict | None) -> None:
        r = (an or {}).get("results", {})
        srcs: dict[str, dict] = {}
        pr = r.get("pose")
        if pr and pr.get("kind") == "video":
            exp = pr.get("exports", {})
            persons = [(f"P{p['track']}", exp[p["mot"]]["path"]) for p in pr.get("persons", [])
                       if p.get("mot") in exp]
            marks = [(e["time_s"], C["red"] if e["class"] == "scena" else C["orange"]) for e in pr.get("transitions", [])]
            srcs[SRC_FVP] = {"label": "Forensic Vision Pro", "video": r.get("artifacts", {}).get("pose_video", ""),
                             "persons": persons, "marks": marks}
        sp = r.get("sports2d")
        if sp and (sp.get("video") or sp.get("mot")):
            persons = [(Path(m).stem.replace("reperto_Sports2D_", "").replace("reperto_", ""), m) for m in sp.get("mot", [])]
            srcs[SRC_S2D] = {"label": f"Sports2D {sp.get('versions', {}).get('sports2d', '')} originale",
                             "video": sp.get("video", ""), "persons": persons, "marks": []}
        osm = (sp or {}).get("opensim") or {}
        if osm.get("motion"):
            srcs[SRC_IK] = {"label": "OpenSim: cinematica inversa (Pose2Sim)", "video": sp.get("video", ""),
                            "persons": [(Path(m).stem.replace("reperto_Sports2D_", ""), m) for m in osm["motion"]],
                            "marks": []}
        cur = self.src.currentData()
        self._sources = srcs
        self.src.blockSignals(True)
        self.src.clear()
        for k, v in srcs.items():
            self.src.addItem(v["label"], k)
        i = self.src.findData(cur)
        self.src.setCurrentIndex(i if i >= 0 else 0)
        self.src.blockSignals(False)
        if not srcs:
            self.player.load(None)
            self.person.clear()
            self.angle_list.clear()
            self.chart.set_data([], {})
            self.anim_info.setText("Il video annotato e i grafici degli angoli compaiono dopo l'analisi Persone e "
                                   "movimento di un video." if self.state.exhibit_id else "")
            return
        self._load_source()

    def _load_source(self) -> None:
        src = self._sources.get(self.src.currentData())
        if not src:
            return
        ok = self.player.load(src["video"])
        self.chart.marks = src["marks"]
        self.person.blockSignals(True)
        self.person.clear()
        for name, path in src["persons"]:
            self.person.addItem(name, path)
        self.person.blockSignals(False)
        self.anim_info.setText(
            ("" if ok else "Video annotato non presente: rianalizza il reperto per generarlo. ")
            + "Scheletro, angoli e numero di frame sono impressi su ogni fotogramma; il cursore rosso del grafico "
              "segue il video, un clic sul grafico sposta il video. Linee tratteggiate: discontinuità.")
        self._load_person()

    def _load_person(self) -> None:
        path = self.person.currentData()
        prev = {self.angle_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.angle_list.count())
                if self.angle_list.item(i).checkState() == Qt.CheckState.Checked}
        self.angle_list.blockSignals(True)
        self.angle_list.clear()
        if not path or not Path(path).is_file():
            self.angle_list.blockSignals(False)
            self.chart.set_data([], {})
            return
        try:
            times, cols = read_mot(path)
        except (OSError, ValueError) as e:
            self.angle_list.blockSignals(False)
            self.chart.set_data([], {}, title=f"{Path(path).name}: {e}")
            return
        order = [n for n in ANGLE_NAMES if n in cols] + [n for n in cols if n not in ANGLE_NAMES]
        default = prev & set(order) or {n for n in ("right knee", "left knee", "right hip", "left hip") + IK_DEFAULT
                                        if n in cols}
        if not default:
            default = set(order[:4])
        series = {}
        for n in order:
            label = ANGLE_LABELS_IT.get(n, n)
            series[label] = cols[n]
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if n in default else Qt.CheckState.Unchecked)
            self.angle_list.addItem(it)
        self.angle_list.blockSignals(False)
        self.chart.set_data(times, series, [ANGLE_LABELS_IT.get(n, n) for n in order if n in default],
                            f"{self.person.currentText()} · angoli nel tempo ({Path(path).name})")

    def _angles_changed(self, _it=None) -> None:
        self.chart.set_visible([self.angle_list.item(i).text() for i in range(self.angle_list.count())
                                if self.angle_list.item(i).checkState() == Qt.CheckState.Checked])

    # ---------------------------------------------------------------- Sports2D / Pose2Sim originali
    def _build_sports2d(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        info = QLabel("Esegue Sports2D e Pose2Sim originali (David Pagnon, BSD-3-Clause) su una copia verificata del "
                      "reperto, in un ambiente Python separato. Video annotato, angoli (.mot) e traiettorie (.trc) "
                      "prodotti dai programmi originali si vedono nella scheda 'Video e angoli' scegliendo la fonte "
                      "Sports2D, affiancati a quelli di Forensic Vision Pro. Ogni file è registrato con SHA-256.")
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        self.s2d_check = QPushButton("Verifica ambiente")
        self.s2d_check.clicked.connect(self._s2d_status)
        self.s2d_run = QPushButton("Esegui Sports2D originale sul reperto")
        self.s2d_run.setObjectName("Primary")
        self.s2d_run.clicked.connect(lambda: self._analyze({"pose", "sports2d"}))
        self.s2d_open = QPushButton("Apri la cartella dei risultati")
        self.s2d_open.clicked.connect(self._s2d_open_dir)
        self.osim_open = QPushButton("Apri il modello in OpenSim")
        self.osim_open.setToolTip("Apre il file .osim con il programma associato (OpenSim). Poi in OpenSim: File > "
                                  "Load Motion e scegliere il file *_ik.mot della stessa persona.")
        self.osim_open.clicked.connect(self._osim_open)
        for b in (self.s2d_check, self.s2d_run, self.s2d_open, self.osim_open):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.osim_info = QLabel()
        self.osim_info.setWordWrap(True)
        self.osim_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.osim_info)
        self.s2d_status = QLabel("Ambiente non ancora verificato.")
        self.s2d_status.setWordWrap(True)
        self.s2d_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.s2d_status)
        self.s2d_files = make_table(["File", "SHA-256", "Byte"])
        lay.addWidget(self.s2d_files, 1)
        self.s2d_meta = make_table(["Proprietà", "Valore"])
        lay.addWidget(self.s2d_meta, 1)
        return w

    def _s2d_status(self) -> None:
        from ...engines import sports2d_ext
        st = sports2d_ext.status(self.state.settings)
        if st["ok"]:
            self.s2d_status.setText(f"Ambiente pronto: {st['detail']} · {st['python']}")
        else:
            self.s2d_status.setText(
                f"Sports2D non disponibile: {st['detail']}.<br>Per installarlo (serve Internet e Python 3.11+): "
                f"<code>py -3.12 tools\\install_sports2d.py</code> dalla cartella del progetto, oppure indica "
                f"l'interprete in Impostazioni.")

    def _refresh_sports2d(self, an: dict | None) -> None:
        sp = (an or {}).get("results", {}).get("sports2d")
        self.s2d_run.setEnabled(bool(self.state.case and self.state.exhibit_id) and not self.state.busy)
        self.s2d_open.setEnabled(bool(sp))
        osm = (sp or {}).get("opensim") or {}
        self.osim_open.setEnabled(bool(osm.get("model")))
        if osm.get("model"):
            hn = (f"statura presunta {osm['height_m']:g} m (non documentata): dimensioni in scala arbitraria"
                  if osm.get("height_assumed") else f"statura documentata {osm.get('height_m')} m")
            self.osim_info.setText(
                f"<b>Modello OpenSim pronto</b> ({hn}).<br>Modello: {', '.join(Path(m).name for m in osm['model'])}"
                f"<br>Movimento: {', '.join(Path(m).name for m in osm['motion'])}<br>In OpenSim: File &gt; Open "
                "Model (.osim), poi File &gt; Load Motion (*_ik.mot) e Play. OpenSim si scarica gratis da "
                "simtk.org/projects/opensim. Le curve della cinematica inversa sono anche nella scheda 'Video e "
                "angoli', fonte 'OpenSim'.")
        elif osm.get("requested"):
            self.osim_info.setText("Modello OpenSim richiesto ma non prodotto: vedi la scheda Risultati e sports2d.log.")
        else:
            self.osim_info.setText("")
        if not sp:
            self.s2d_files.setRowCount(0)
            self.s2d_meta.setRowCount(0)
            return
        log = sp.get("log")
        fill_table(self.s2d_files, [[e["rel"], e["sha256"], e["size"]] for e in sp.get("outputs", {}).values()]
                   + ([[log["rel"], log["sha256"], log["size"]]] if log else []))
        rows = [["Interprete", sp.get("python")], ["Codice di uscita", sp.get("returncode")],
                ["Durata (s)", sp.get("duration_s")], ["Comando", " ".join(sp.get("command", []))],
                ["Input (copia verificata)", sp.get("input", {}).get("sha256")]]
        rows += [[f"versione {k}", v] for k, v in sp.get("versions", {}).items() if v]
        rows += [[f"modello in cache: {m['file']}", m["sha256"]] for m in sp.get("models_cache", [])]
        fill_table(self.s2d_meta, rows, sortable=False)

    def _osim_open(self) -> None:
        an = self.state.last_analysis()
        osm = ((an or {}).get("results", {}).get("sports2d") or {}).get("opensim") or {}
        if osm.get("model"):
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(osm["model"][0])):
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(osm["model"][0]).parent)))
            self.state.case.audit.append(self.state.operator, "apertura_esterna", {
                "exhibit": self.state.exhibit_id, "file": osm["model"][0], "programma": "OpenSim"})

    def _s2d_open_dir(self) -> None:
        an = self.state.last_analysis()
        sp = (an or {}).get("results", {}).get("sports2d")
        if sp and sp.get("log"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(sp["log"]["path"]).parent)))
