"""Tutti i dati rinvenuti: ogni risultato dell'ultima analisi del reperto, anche quando non ci sono anomalie.

In alto le anomalie e i punti di attenzione; sotto, sezione per sezione, tutto ciò che i moduli hanno estratto:
hash, formato, metadati (tutti i tag, con l'attendibilità), date e orari, dispositivo, stream video e audio,
struttura del file, persone e movimento, Sports2D/Pose2Sim, firme incorporate e versioni degli strumenti. Le chiavi
dei risultati non previste qui finiscono comunque in "Altri risultati": nessun dato resta nascosto.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem)

from ...core.findings import Level
from ..theme import C, LEVEL_COLORS
from ..widgets.common import Page

MAX_ITEMS = 2000          # elementi per lista mostrati nell'albero (l'esportazione JSON li contiene tutti)
MAX_TEXT = 400

KNOWN = {"signature": "Formato del file", "structure": "Struttura interna del file",
         "metadata": None, "timeline": None, "device": "Coerenza con il dispositivo", "video": None,
         "case_context": "Confronto con gli altri reperti", "pose": None, "sports2d": None,
         "embedded_signatures": "Firme di altri formati nel file", "artifacts": "File prodotti dall'analisi",
         "executed": "Moduli eseguiti", "executed_categories": "Categorie esaminate"}


def _short(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + " …"


class AllDataPage(Page):
    title = "Tutti i dati rinvenuti"
    intro = ("Tutto ciò che l'analisi ha estratto dal reperto selezionato, anche quando non emergono anomalie: in alto "
             "i punti di attenzione, poi metadati, date, stream, struttura, persone e movimento, hash e strumenti. "
             "Cerca per nome o valore; doppio clic su una riga per copiarne il valore.")

    def __init__(self, state):
        super().__init__(state)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca (es. GPS, CreateDate, encoder, P1)…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        b1 = QPushButton("Espandi tutto")
        b1.clicked.connect(lambda: self.tree.expandAll())
        b2 = QPushButton("Comprimi")
        b2.clicked.connect(self._collapse)
        self.export_btn = QPushButton("Esporta tutto (JSON)…")
        self.export_btn.clicked.connect(self._export)
        for b in (b1, b2, self.export_btn):
            top.addWidget(b)
        self.root.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Voce", "Valore", "Note"])
        self.tree.setColumnWidth(0, 340)
        self.tree.setColumnWidth(1, 520)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._copy)
        self.root.addWidget(self.tree, 1)
        state.exhibit_changed.connect(self.refresh)
        state.analysis_changed.connect(self.refresh)

    # ---------------------------------------------------------------- costruzione
    def _node(self, parent, key: str, value="", note: str = "", color: str | None = None) -> QTreeWidgetItem:
        it = QTreeWidgetItem(parent, [str(key), _short(value) if value != "" else "", note])
        full = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        it.setData(1, Qt.ItemDataRole.UserRole, full)
        if len(full) > MAX_TEXT or "\n" in full:
            it.setToolTip(1, full[:4000])
        if color:
            it.setForeground(0, QColor(color))
        return it

    def _generic(self, parent, value, depth: int = 0) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (dict, list)) and v:
                    n = self._node(parent, k, f"{len(v)} elementi" if isinstance(v, list) else "")
                    self._generic(n, v, depth + 1)
                else:
                    self._node(parent, k, "" if v is None else v)
        elif isinstance(value, list):
            for i, v in enumerate(value[:MAX_ITEMS]):
                label = f"[{i + 1}]"
                if isinstance(v, dict):
                    hint = next((str(v[k]) for k in ("name", "tag", "type", "file", "signature", "title", "track")
                                 if k in v), "")
                    n = self._node(parent, f"{label} {hint}".strip())
                    self._generic(n, v, depth + 1)
                elif isinstance(v, list):
                    n = self._node(parent, label, f"{len(v)} elementi")
                    self._generic(n, v, depth + 1)
                else:
                    self._node(parent, label, v)
            if len(value) > MAX_ITEMS:
                self._node(parent, "…", f"altri {len(value) - MAX_ITEMS} elementi nell'esportazione JSON")
        else:
            self._node(parent, "valore", value)

    def _section(self, title: str, count: str = "") -> QTreeWidgetItem:
        it = QTreeWidgetItem(self.tree, [title, count, ""])
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        return it

    def refresh(self) -> None:
        self.tree.clear()
        an = self.state.last_analysis()
        case, exid = self.state.case, self.state.exhibit_id
        self.export_btn.setEnabled(bool(an))
        if not an:
            self.summary.setText("Seleziona un reperto analizzato." if exid else "Nessun reperto selezionato.")
            return
        ex = case.exhibit(exid)
        r = an["results"]
        fs = an["findings"]
        att = [f for f in fs if f.level != Level.INFO]
        meta_tags = (r.get("metadata") or {}).get("tags", [])
        self.summary.setText(
            f"<b>{ex.original_name}</b> · analisi n. {an['id']} del {an['finished_utc']} · {len(fs)} risultati, "
            f"<b>{len(att)}</b> da valutare · {len(meta_tags)} tag di metadati · moduli: "
            f"{', '.join(r.get('executed', []))}")
        # 1. anomalie
        s = self._section("Anomalie e punti di attenzione", str(len(att)) if att else "nessuna")
        if not att:
            self._node(s, "Esito", "Nessuna anomalia rilevata dai moduli eseguiti: i dati estratti sono comunque "
                                   "riportati qui sotto.")
        for f in att:
            n = self._node(s, f.title, f.description, f"{f.level.value} · {f.category.value}",
                           LEVEL_COLORS.get(f.level.value))
            for k, v in (("Metodo", f.method), ("Evidenza", f.evidence), ("Affidabilità", f.confidence),
                         ("Limiti", f.limitations), ("Offset", f.offset)):
                if v not in ("", None):
                    self._node(n, k, v)
        # 2. tutti i risultati dei moduli (anche informativi)
        s = self._section("Tutti i risultati dei moduli", str(len(fs)))
        by_cat: dict[str, list] = {}
        for f in fs:
            by_cat.setdefault(f.category.value, []).append(f)
        for cat, items in sorted(by_cat.items()):
            c = self._node(s, cat, f"{len(items)} risultati")
            for f in items:
                n = self._node(c, f.title, f.description, f.level.value, LEVEL_COLORS.get(f.level.value))
                for k, v in (("Metodo", f.method), ("Evidenza", f.evidence), ("Limiti", f.limitations)):
                    if v:
                        self._node(n, k, v)
                if f.data:
                    self._generic(self._node(n, "Dati"), f.data)
        # 3. integrità
        s = self._section("Integrità e acquisizione")
        self._node(s, "File originale", ex.original_name)
        self._node(s, "Percorso di origine", ex.source_path)
        self._node(s, "Dimensione (byte)", f"{ex.size:,}")
        self._node(s, "Acquisito (UTC)", ex.acquired_utc, ex.operator)
        h = self._node(s, "Hash dell'originale")
        for k, v in ex.source_hashes.items():
            self._node(h, k.upper(), v)
        h = self._node(s, "Hash prima / dopo l'analisi", "coincidono" if an["integrity_ok"] else "DIVERSI", "",
                       C["green"] if an["integrity_ok"] else C["red"])
        for k, v in an["pre_hashes"].items():
            self._node(h, k.upper(), v, "dopo: " + an["post_hashes"].get(k, ""))
        if ex.source_stat:
            self._generic(self._node(s, "Attributi del file di origine"), ex.source_stat)
        # 4. metadati
        if meta_tags:
            s = self._section("Metadati", f"{len(meta_tags)} tag · {(r.get('metadata') or {}).get('tool', '')}")
            groups: dict[str, list] = {}
            for t in meta_tags:
                groups.setdefault(t.get("group") or "—", []).append(t)
            for g, tags in sorted(groups.items()):
                gn = self._node(s, g, f"{len(tags)} tag")
                for t in tags:
                    self._node(gn, t.get("tag"), t.get("value"), t.get("reliability", ""))
            gps = (r.get("metadata") or {}).get("gps")
            if gps:
                self._generic(self._node(s, "GPS (decimale)"), gps)
        elif "metadata" in r:
            s = self._section("Metadati", "nessun tag")
            self._node(s, "Esito", "Lo strumento non ha restituito metadati.")
        # 5. date e orari
        tl = r.get("timeline") or []
        if tl:
            s = self._section("Date e orari", f"{len(tl)} eventi")
            for e in tl[:MAX_ITEMS]:
                if isinstance(e, dict):
                    when = e.get("utc") or e.get("value") or e.get("time") or e.get("datetime") or ""
                    what = e.get("source") or e.get("tag") or e.get("label") or ""
                    n = self._node(s, f"{when}", what, e.get("reliability", ""))
                    self._generic(n, e)
                else:
                    self._node(s, "evento", e)
        # 6. video e audio
        v = r.get("video")
        if v:
            streams = v.get("streams", [])
            s = self._section("Video e audio (FFprobe)", f"{len(streams)} stream")
            self._generic(s, v)
        # 7. persone e movimento
        pr = r.get("pose")
        if pr:
            fr = pr.get("frames", {})
            s = self._section("Persone e movimento (Forensic Vision Pro)",
                              f"{len(pr.get('persons', []))} persone · {fr.get('analyzed', 1)} frame · "
                              f"{len(pr.get('transitions', []))} discontinuità")
            self._generic(s, pr)
        sp = r.get("sports2d")
        if sp:
            s = self._section("Sports2D / Pose2Sim originali",
                              f"Sports2D {sp.get('versions', {}).get('sports2d', '')} · {len(sp.get('outputs', {}))} file")
            self._generic(s, sp)
        # 8. sezioni note, poi tutto il resto
        for key, title in KNOWN.items():
            if title and r.get(key) not in (None, [], {}):
                val = r[key]
                s = self._section(title, f"{len(val)} elementi" if isinstance(val, (list, dict)) else "")
                self._generic(s, val) if isinstance(val, (dict, list)) else self._node(s, key, val)
        rest = {k: v for k, v in r.items() if k not in KNOWN and v not in (None, [], {})}
        if rest:
            s = self._section("Altri risultati", f"{len(rest)} sezioni")
            self._generic(s, rest)
        # 9. strumenti
        s = self._section("Strumenti e versioni", an.get("app_version", ""))
        self._generic(s, an.get("tools", {}))
        self._node(s, "Operatore", an.get("operator", ""))
        self._node(s, "Moduli richiesti", ", ".join(an.get("modules", [])))
        self.tree.topLevelItem(0).setExpanded(True)
        self._filter(self.search.text())

    # ---------------------------------------------------------------- azioni
    def _collapse(self) -> None:
        self.tree.collapseAll()
        if self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()

        def walk(it: QTreeWidgetItem) -> bool:
            own = not q or any(q in it.text(c).lower() for c in range(3)) or \
                q in str(it.data(1, Qt.ItemDataRole.UserRole) or "").lower()
            child = False
            for i in range(it.childCount()):
                child = walk(it.child(i)) or child
            show = own or child
            it.setHidden(not show)
            if q and child:
                it.setExpanded(True)
            return show
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _copy(self, it: QTreeWidgetItem, _col: int) -> None:
        QGuiApplication.clipboard().setText(str(it.data(1, Qt.ItemDataRole.UserRole) or it.text(1) or it.text(0)))

    def _export(self) -> None:
        an = self.state.last_analysis()
        if not an:
            return
        ex = self.state.case.exhibit(self.state.exhibit_id)
        fn, _ = QFileDialog.getSaveFileName(self, "Esporta tutti i dati", f"{ex.id}_tutti_i_dati.json", "JSON (*.json)")
        if not fn:
            return
        import hashlib
        data = {"exhibit": {k: getattr(ex, k) for k in ex.__dataclass_fields__}, "analysis_id": an["id"],
                "finished_utc": an["finished_utc"], "operator": an["operator"], "modules": an["modules"],
                "integrity_ok": an["integrity_ok"], "pre_hashes": an["pre_hashes"], "post_hashes": an["post_hashes"],
                "tools": an["tools"], "app_version": an["app_version"],
                "findings": [f.to_dict() for f in an["findings"]], "results": an["results"]}
        raw = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        Path(fn).write_bytes(raw)
        self.state.case.audit.append(self.state.operator, "esportazione_dati", {
            "exhibit": ex.id, "analysis_id": an["id"], "file": fn, "sha256": hashlib.sha256(raw).hexdigest()})
        self.summary.setText(self.summary.text() + f"<br>Esportato in {fn} (SHA-256 registrato nel registro del caso).")
