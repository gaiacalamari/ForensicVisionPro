"""File Integrity & Hashing."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton)

from ...engines.hashing import ALGORITHMS, hash_directory, hash_file
from ..widgets.common import Page, fill_table, make_table


class IntegrityPage(Page):
    title = "Verifica hash"
    intro = ("Calcolo di hash su file o cartelle, confronto con un valore atteso e verifica dei reperti del caso. "
             "Gli hash confermano che i byte non sono cambiati, non che il contenuto sia autentico.")

    def __init__(self, state):
        super().__init__(state)
        g = QGroupBox("Algoritmi")
        gl = QHBoxLayout(g)
        self.algs = {}
        for k, v in ALGORITHMS.items():
            c = QCheckBox(v)
            c.setChecked(k in ("md5", "sha1", "sha256"))
            self.algs[k] = c
            gl.addWidget(c)
        gl.addStretch(1)
        self.root.addWidget(g)
        row = QHBoxLayout()
        for txt, fn in (("Hash di un file…", self._file), ("Hash di una cartella…", self._dir)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        self.expected = QLineEdit()
        self.expected.setPlaceholderText("Hash atteso da confrontare (facoltativo)")
        row.addWidget(self.expected, 1)
        self.root.addLayout(row)
        g2 = QGroupBox("Reperti del caso")
        l2 = QHBoxLayout(g2)
        self.verify = QPushButton("Verifica reperto selezionato")
        self.verify.clicked.connect(lambda: self._verify(False))
        self.verify_src = QPushButton("Verifica anche l'originale")
        self.verify_src.setToolTip("Rilegge il file originale dal percorso di acquisizione, se ancora accessibile.")
        self.verify_src.clicked.connect(lambda: self._verify(True))
        l2.addWidget(self.verify)
        l2.addWidget(self.verify_src)
        l2.addStretch(1)
        self.root.addWidget(g2)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.root.addWidget(self.result)
        self.table = make_table(["File", "Dimensione", "Algoritmo", "Hash", "Esito confronto"])
        self.root.addWidget(self.table, 1)

    def _selected(self) -> list[str]:
        return [k for k, c in self.algs.items() if c.isChecked()] or ["sha256"]

    def _rows(self, items: list[dict]) -> list[list]:
        exp = self.expected.text().strip().lower()
        rows = []
        for it in items:
            if "error" in it:
                rows.append([it["path"], "", "", it["error"], ""])
                continue
            for a, h in it["hashes"].items():
                rows.append([it["path"], it["size"], ALGORITHMS[a], h,
                             ("CORRISPONDE" if h == exp else "diverso") if exp else ""])
        return rows

    def _file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "File da verificare")
        if not f:
            return
        algs = self._selected()
        import os
        self.state.run(lambda p, c: [{"path": f, "size": os.path.getsize(f), "hashes": hash_file(f, algs, p, c)}],
                       self._show, self.error)

    def _dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Cartella da verificare")
        if d:
            algs = self._selected()
            self.state.run(lambda p, c: hash_directory(d, algs, p, c), self._show, self.error)

    def _show(self, items: list[dict]) -> None:
        fill_table(self.table, self._rows(items))
        exp = self.expected.text().strip().lower()
        if exp:
            ok = any(exp == h for it in items for h in it.get("hashes", {}).values())
            self.result.setText("Il valore atteso corrisponde a uno degli hash calcolati." if ok else
                                "<b>Il valore atteso non corrisponde a nessun hash calcolato.</b>")
        else:
            self.result.setText(f"{len(items)} file elaborati.")
        if self.state.case:
            self.state.case.audit.append(self.state.operator, "calcolo_hash",
                                         {"files": len(items), "first": items[0]["path"] if items else ""})

    def _verify(self, src: bool) -> None:
        if not (self.state.case and self.state.exhibit_id):
            return self.error("Nessun reperto selezionato.")
        case, ex, op = self.state.case, self.state.exhibit_id, self.state.operator

        def done(r: dict) -> None:
            parts = [f"Copia di lavoro di {ex}: " + ("integra." if r["working_copy_ok"] else "<b>HASH DIVERSI</b>.")]
            if r.get("source_checked"):
                parts.append("Originale: " + ("invariato." if r.get("source_ok") else "<b>diverso dall'acquisizione</b>."))
            elif src:
                parts.append("Originale non accessibile dal percorso registrato.")
            self.result.setText(" ".join(parts))
            fill_table(self.table, [[f"{ex} (copia di lavoro)", "", a, h, "corrisponde" if
                                     case.exhibit(ex).working_hashes.get(a) == h else "DIVERSO"]
                                    for a, h in r.get("working_copy_hashes", {}).items()])
        self.state.run(lambda p, c: case.verify_exhibit(ex, op, src), done, self.error)
