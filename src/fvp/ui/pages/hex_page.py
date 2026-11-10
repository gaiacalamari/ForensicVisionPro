"""Hex Viewer con struttura del file sincronizzata, ricerca e scanner di firme. Sempre in sola lettura."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...engines import signature
from ...parsers.registry import parser_for
from ..widgets.common import Page, fill_table, make_table
from ..widgets.hexview import HexView


class HexPage(Page):
    title = "Byte del file (Hex)"
    lead = "Il contenuto grezzo del file, byte per byte (solo lettura)."
    intro = ("Contenuto binario in sola lettura: il file è mappato in memoria senza permessi di scrittura. "
             "Fai clic su un elemento della struttura per evidenziarne i byte; Maiusc+clic seleziona un intervallo.")

    def __init__(self, state):
        super().__init__(state)
        bar = QHBoxLayout()
        b1 = QPushButton("Apri reperto selezionato")
        b1.clicked.connect(self._open_exhibit)
        b2 = QPushButton("Apri file in sola lettura…")
        b2.clicked.connect(self._open_any)
        bar.addWidget(b1)
        bar.addWidget(b2)
        bar.addSpacing(16)
        self.goto = QLineEdit()
        self.goto.setPlaceholderText("Offset (es. 0x1A2B o 6699)")
        self.goto.setMaximumWidth(190)
        self.goto.returnPressed.connect(self._goto)
        bar.addWidget(self.goto)
        bar.addSpacing(16)
        self.mode = QComboBox()
        self.mode.addItems(["HEX", "ASCII", "UTF-16LE"])
        self.query = QLineEdit()
        self.query.setPlaceholderText("Cerca…")
        self.query.returnPressed.connect(self._find)
        bf = QPushButton("Trova successivo")
        bf.clicked.connect(self._find)
        bar.addWidget(self.mode)
        bar.addWidget(self.query, 1)
        bar.addWidget(bf)
        self.root.addLayout(bar)
        sp = QSplitter(Qt.Orientation.Horizontal)
        self.hex = HexView()
        self.hex.selectionChanged.connect(self._sel)
        sp.addWidget(self.hex)
        side = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elemento", "Offset", "Lunghezza"])
        self.tree.itemClicked.connect(lambda it, _c: self.hex.goto(*it.data(0, Qt.ItemDataRole.UserRole)))
        side.addTab(self.tree, "Struttura")
        sigw = QWidget()
        sl = QVBoxLayout(sigw)
        bs = QPushButton("Scansiona firme incorporate")
        bs.clicked.connect(self._scan)
        sl.addWidget(bs)
        self.sigs = make_table(["Offset", "Firma", "Primi byte"])
        self.sigs.cellDoubleClicked.connect(lambda r, _c: self.hex.goto(int(self.sigs.item(r, 0).text(), 16), 16))
        sl.addWidget(self.sigs, 1)
        side.addTab(sigw, "Firme")
        sp.addWidget(side)
        sp.setSizes([780, 380])
        self.root.addWidget(sp, 1)
        bot = QHBoxLayout()
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        bot.addWidget(self.info, 1)
        for txt, fn in (("Copia HEX", self._copy_hex), ("Copia ASCII", self._copy_ascii),
                        ("Esporta selezione…", self._export)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bot.addWidget(b)
        self.root.addLayout(bot)

    def open_path(self, path: str) -> None:
        self.hex.open(path)
        self.tree.clear()
        self.sigs.setRowCount(0)
        info = signature.identify(path)
        top = QTreeWidgetItem([f"{info['format_name']} ({Path(path).name})", "0x0", str(info["size"])])
        top.setData(0, Qt.ItemDataRole.UserRole, (0, 1))
        self.tree.addTopLevelItem(top)
        parser = parser_for(info["format"])
        if parser:
            try:
                res = parser(path)

                def add(parent, n):
                    it = QTreeWidgetItem([n.name + (f"  [{n.fields.get('tipo')}]" if n.fields.get("tipo") else ""),
                                          f"0x{n.offset:X}", str(n.length)])
                    it.setToolTip(0, "\n".join(f"{k}: {v}" for k, v in n.fields.items())[:2000])
                    it.setData(0, Qt.ItemDataRole.UserRole, (n.offset, n.length))
                    parent.addChild(it)
                    for c in n.children:
                        add(it, c)
                for c in res.root.children:
                    add(top, c)
            except Exception as e:  # noqa: BLE001
                top.addChild(QTreeWidgetItem([f"Analisi strutturale non riuscita: {e}", "", ""]))
        top.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        self._sel(-1, 0)
        if self.state.case:
            self.state.case.audit.append(self.state.operator, "hex_aperto", {"path": path})

    def _open_exhibit(self) -> None:
        if not (self.state.case and self.state.exhibit_id):
            return self.error("Nessun reperto selezionato.")
        self.open_path(self.state.case.exhibit(self.state.exhibit_id).working_path)

    def _open_any(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Apri in sola lettura")
        if f:
            self.open_path(f)

    def _goto(self) -> None:
        t = self.goto.text().strip()
        try:
            self.hex.goto(int(t, 16) if t.lower().startswith("0x") else int(t))
        except ValueError:
            self.error("Offset non valido.")

    def _needle(self) -> bytes | None:
        q = self.query.text()
        m = self.mode.currentText()
        try:
            if m == "HEX":
                return bytes.fromhex(q.replace(" ", ""))
            if m == "ASCII":
                return q.encode("latin-1")
            return q.encode("utf-16-le")
        except (ValueError, UnicodeEncodeError):
            self.error("Sequenza di ricerca non valida per la modalità scelta.")
            return None

    def _find(self) -> None:
        n = self._needle()
        if not n:
            return
        a, _ = self.hex.selection()
        i = self.hex.find(n, a + 1 if a >= 0 else 0)
        if i < 0:
            i = self.hex.find(n, 0)
            if i < 0 or i == a:
                self.info.setText("Nessuna occorrenza trovata.")
                return
            self.info.setText("Ricerca ripartita dall'inizio del file.")
        self.hex.goto(i, len(n))

    def _sel(self, start: int, length: int) -> None:
        if not self.hex.size:
            return
        txt = f"{Path(self.hex.path).name} · {self.hex.size:,} byte · sola lettura"
        if start >= 0:
            d = self.hex.data(start, min(length, 8))
            txt += f" · selezione 0x{start:X}–0x{start + length - 1:X} ({length} byte)"
            if len(d) >= 4:
                txt += f" · u32 LE {int.from_bytes(d[:4], 'little')} / BE {int.from_bytes(d[:4], 'big')}"
        self.info.setText(txt)

    def _sel_bytes(self) -> bytes:
        a, n = self.hex.selection()
        return self.hex.data(a, min(n, 16 * 1024 * 1024)) if a >= 0 else b""

    def _copy_hex(self) -> None:
        QApplication.clipboard().setText(self._sel_bytes().hex(" ").upper())

    def _copy_ascii(self) -> None:
        QApplication.clipboard().setText("".join(chr(b) if 32 <= b < 127 else "." for b in self._sel_bytes()))

    def _export(self) -> None:
        d = self._sel_bytes()
        if not d:
            return self.error("Seleziona prima un intervallo di byte.")
        a, n = self.hex.selection()
        f, _ = QFileDialog.getSaveFileName(self, "Esporta selezione", f"estratto_0x{a:X}_{n}.bin")
        if f:
            if Path(f).resolve() == Path(self.hex.path).resolve():
                return self.error("Non è possibile sovrascrivere il file in esame.")
            Path(f).write_bytes(d)
            if self.state.case:
                import hashlib
                self.state.case.audit.append(self.state.operator, "estrazione_byte",
                                             {"source": self.hex.path, "offset": a, "length": n, "dest": f,
                                              "sha256": hashlib.sha256(d).hexdigest()})

    def _scan(self) -> None:
        if not self.hex.size:
            return
        path = self.hex.path
        self.state.run(lambda p, c: signature.scan_signatures(path, p, c),
                       lambda hits: fill_table(self.sigs, [[f"0x{h['offset']:X}", h["signature"], h["hex"]] for h in hits]),
                       self.error)
