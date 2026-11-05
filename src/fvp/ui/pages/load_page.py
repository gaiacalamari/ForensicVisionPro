"""Carica e analizza: una o più immagini, oppure intere cartelle, nel caso aperto."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from ...core.pipeline import AUDIO_FORMATS, IMAGE_FORMATS, VIDEO_FORMATS, analyze_exhibit
from ...core.tasks import Cancelled
from ...engines import signature
from ..widgets.common import Page, fill_table, make_table

MODS = [("signature", "Formato reale del file"), ("structure", "Struttura interna del file"),
        ("metadata", "Metadati (fotocamera, software, GPS)"), ("timestamps", "Coerenza di date e orari"),
        ("image", "Mappe di base: ELA, rumore, miniatura"),
        ("jpeg_advanced", "Storia della compressione JPEG"),
        ("median", "Ritocchi locali (filtro mediano)"), ("copymove", "Regioni copiate (copy-move)"),
        ("stego", "Test statistici per dati nascosti"),
        ("stegointel", "Estrazione di contenuti nascosti (StegoIntelligence)"),
        ("hidden_text", "Testo nascosto: metadati, byte del file, scritte quasi invisibili"),
        ("quality", "Caratteristiche, volti, hash percettivi"), ("prnu", "Confronto con fotocamere note (PRNU)"),
        ("video", "Video e audio (FFprobe)"), ("carving_scan", "File incorporati nel file")]
PRESETS = {
    "Completa (consigliata)": [k for k, _ in MODS],
    "Rapida: struttura, metadati, date, ELA": ["signature", "structure", "metadata", "timestamps", "image",
                                               "carving_scan"],
    "Contenuti nascosti": ["signature", "structure", "metadata", "stego", "stegointel", "hidden_text", "carving_scan"],
    "Personalizzata": None,
}
PICTURE = IMAGE_FORMATS | {"heif", "avif"}
MEDIA = PICTURE | VIDEO_FORMATS | AUDIO_FORMATS


class LoadPage(Page):
    title = "Carica e analizza"
    intro = ("Aggiungi una o più immagini, oppure una cartella intera, al caso aperto. Ogni file diventa un reperto: "
             "viene copiato con hash verificati, la copia è resa di sola lettura e le analisi lavorano solo su di "
             "essa. Puoi anche trascinare file e cartelle in questa pagina.")

    def __init__(self, state):
        super().__init__(state)
        self.setAcceptDrops(True)
        self.case_lbl = QLabel()
        self.case_lbl.setObjectName("Notice")
        self.case_lbl.setWordWrap(True)
        self.root.addWidget(self.case_lbl)
        row = QHBoxLayout()
        b1 = QPushButton("Aggiungi immagini…")
        b1.clicked.connect(self._add_files)
        b2 = QPushButton("Aggiungi cartella…")
        b2.clicked.connect(self._add_folder)
        self.recursive = QCheckBox("includi sottocartelle")
        self.recursive.setChecked(True)
        self.only_img = QCheckBox("solo immagini (riconosciute dai magic bytes, non dall'estensione)")
        self.only_img.setChecked(True)
        self.only_img.setToolTip("Se disattivato vengono acquisiti anche video, audio WAV e qualsiasi altro file.")
        b3 = QPushButton("Svuota elenco")
        b3.clicked.connect(self._clear)
        for w in (b1, b2, self.recursive, self.only_img):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(b3)
        self.root.addLayout(row)
        self.drop = QLabel("Trascina qui immagini o cartelle")
        self.drop.setObjectName("DropZone")
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(self.drop)
        self.table = make_table(["File", "Dimensione", "Formato rilevato", "Stato"])
        self.root.addWidget(self.table, 1)
        g = QGroupBox("Analisi")
        gl = QVBoxLayout(g)
        top = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(PRESETS))
        self.preset.currentTextChanged.connect(self._apply_preset)
        top.addWidget(QLabel("Profilo"))
        top.addWidget(self.preset)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Descrizione facoltativa (es. 'Foto ricevute via WhatsApp'), applicata ai reperti")
        top.addWidget(self.label, 1)
        gl.addLayout(top)
        grid = QGridLayout()
        self.checks = {}
        for i, (k, lbl) in enumerate(MODS):
            c = QCheckBox(lbl)
            c.setChecked(True)
            c.toggled.connect(lambda _on: self._custom())
            self.checks[k] = c
            grid.addWidget(c, i // 3, i % 3)
        gl.addLayout(grid)
        note = QLabel("Integrità (hash prima e dopo ogni analisi) è sempre eseguita. Ogni modulo si applica solo ai "
                      "formati pertinenti.")
        note.setObjectName("Muted")
        gl.addWidget(note)
        self.root.addWidget(g)
        row2 = QHBoxLayout()
        self.start = QPushButton("Acquisisci e analizza")
        self.start.setObjectName("Primary")
        self.start.clicked.connect(self._start)
        self.again = QPushButton("Rianalizza il reperto selezionato")
        self.again.clicked.connect(self._reanalyze)
        row2.addWidget(self.start)
        row2.addWidget(self.again)
        row2.addStretch(1)
        self.root.addLayout(row2)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        self.root.addWidget(self.msg)
        self.queue: list[dict] = []
        state.case_changed.connect(self.refresh)
        state.busy_changed.connect(lambda _b: self.refresh())

    # ---------- elenco ----------
    def refresh(self) -> None:
        c = self.state.case
        self.case_lbl.setText(f"Caso <b>{c.info.get('case_id')}</b> — {c.info.get('title')} · operatore "
                              f"<b>{self.state.operator}</b> · {len(c.exhibits())} reperti già acquisiti" if c else
                              "Nessun caso aperto: crea o apri un caso nella sezione Casi.")
        pending = [q for q in self.queue if q["status"] == "in attesa"]
        self.start.setText(f"Acquisisci e analizza {len(pending)} file" if pending else "Acquisisci e analizza")
        self.start.setEnabled(bool(c and pending) and not self.state.busy)
        self.again.setEnabled(bool(c and self.state.exhibit_id) and not self.state.busy)
        fill_table(self.table, [[q["path"], f"{q['size']:,}", q["format"], q["status"]] for q in self.queue],
                   sortable=False)

    def _add_paths(self, paths: list[Path]) -> None:
        files: list[Path] = []
        for p in paths:
            if p.is_dir():
                it = p.rglob("*") if self.recursive.isChecked() else p.glob("*")
                files += sorted(x for x in it if x.is_file())
            elif p.is_file():
                files.append(p)
        known = {q["path"] for q in self.queue}
        skipped = 0
        for f in files:
            if str(f) in known:
                continue
            try:
                info = signature.identify(f)
            except OSError:
                skipped += 1
                continue
            if self.only_img.isChecked() and info["format"] not in PICTURE:
                skipped += 1
                continue
            self.queue.append({"path": str(f), "size": info["size"], "format": info["format_name"],
                               "status": "in attesa"})
            known.add(str(f))
        self.msg.setText(f"{len(files) - skipped} file aggiunti" + (f", {skipped} esclusi (non immagini o illeggibili)."
                                                                     if skipped else "."))
        self.refresh()

    def _add_files(self) -> None:
        fs, _ = QFileDialog.getOpenFileNames(self, "Immagini da acquisire", "",
                                             "Immagini (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif *.webp *.heic *.heif);;"
                                             "Tutti i file (*)")
        if fs:
            self._add_paths([Path(f) for f in fs])

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella da acquisire")
        if d:
            self._add_paths([Path(d)])

    def _clear(self) -> None:
        self.queue = [q for q in self.queue if q["status"] != "in attesa"] if self.state.busy else []
        self.refresh()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and self.state.case:
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        self._add_paths([Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------- moduli ----------
    def _apply_preset(self, name: str) -> None:
        mods = PRESETS.get(name)
        if mods is None:
            return
        for k, c in self.checks.items():
            c.blockSignals(True)
            c.setChecked(k in mods)
            c.blockSignals(False)

    def _custom(self) -> None:
        sel = sorted(k for k, c in self.checks.items() if c.isChecked())
        match = next((n for n, m in PRESETS.items() if m is not None and sorted(m) == sel), "Personalizzata")
        self.preset.blockSignals(True)
        self.preset.setCurrentText(match)
        self.preset.blockSignals(False)

    def _modules(self) -> list[str]:
        return ["integrity"] + [k for k, c in self.checks.items() if c.isChecked()]

    # ---------- esecuzione ----------
    def _start(self) -> None:
        case, op, mods, lbl = self.state.case, self.state.operator, self._modules(), self.label.text().strip()
        items = [q for q in self.queue if q["status"] == "in attesa"]
        if not items:
            return
        case.audit.append(op, "caricamento_avviato", {"files": len(items), "modules": mods}, kind="custody")
        settings = self.state.settings

        def job(progress, cancel):
            last = None
            for i, q in enumerate(items):
                base, span = i / len(items), 1 / len(items)
                f = Path(q["path"])
                tag = f"{i + 1}/{len(items)} {f.name}"
                try:
                    ex = case.acquire(f, op, f"{lbl} · {f.name}" if lbl else f.name, cancel=cancel,
                                      progress=lambda p, m: progress(base + span * 0.3 * p, f"{tag}: {m}"))
                    q["status"] = f"acquisito come {ex.id}"
                    analyze_exhibit(case, ex.id, op, settings, mods,
                                    lambda p, m: progress(base + span * (0.3 + 0.7 * p), f"{tag}: {m}"), cancel)
                    q["status"] = f"analizzato · {ex.id}"
                    last = ex.id
                except Cancelled:
                    q["status"] = "annullato"
                    raise
                except Exception as e:  # noqa: BLE001 - un file problematico non interrompe il lotto
                    q["status"] = f"errore: {e}"
            return last

        def done(last):
            errors = [q for q in items if q["status"].startswith("errore")]
            self.msg.setText(f"{len(items) - len(errors)} file acquisiti e analizzati"
                             + (f", {len(errors)} con errori (vedi colonna Stato)." if errors else "."))
            case.audit.append(op, "caricamento_completato", {"ok": len(items) - len(errors), "errors": len(errors)},
                              kind="custody")
            if last:
                self.state.set_exhibit(last)
                self.state.case_changed.emit()
                self.state.analysis_changed.emit()
            self.refresh()
            if len(items) == 1 and last:
                self.state.navigate.emit("Dashboard")

        def failed(m):
            self.msg.setText(m.split("\n")[0])
            self.refresh()
        self.state.run(job, done, failed)

    def _reanalyze(self) -> None:
        case, ex_id, op, mods = self.state.case, self.state.exhibit_id, self.state.operator, self._modules()
        self.msg.setText(f"Analisi di {ex_id} in corso…")

        def done(_r):
            self.msg.setText(f"Analisi di {ex_id} completata.")
            self.state.analysis_changed.emit()
        self.state.run(lambda pr, ca: analyze_exhibit(case, ex_id, op, self.state.settings, mods, pr, ca), done,
                       lambda m: self.msg.setText(m.split("\n")[0]))

