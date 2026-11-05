"""Hex Viewer read-only per file di qualsiasi dimensione (mmap, disegno delle sole righe visibili)."""
from __future__ import annotations

import mmap
import os

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractScrollArea

from ..theme import C, mono_font

BPR = 16  # byte per riga


class HexView(QAbstractScrollArea):
    selectionChanged = Signal(int, int)   # inizio, lunghezza

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(mono_font(10))
        self._fh = None
        self._mm: mmap.mmap | None = None
        self.size = 0
        self.path = ""
        self.sel_start, self.sel_end = -1, -1   # end inclusivo
        self._anchor = -1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._metrics()

    # ---------- file ----------
    def open(self, path: str) -> None:
        self.close()
        self.path = path
        self.size = os.path.getsize(path)
        self._fh = open(path, "rb")                     # sola lettura
        if self.size:
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        self.sel_start = self.sel_end = -1
        self._update_scroll()
        self.verticalScrollBar().setValue(0)
        self.viewport().update()

    def close(self) -> None:
        if self._mm:
            self._mm.close()
        if self._fh:
            self._fh.close()
        self._mm = self._fh = None
        self.size = 0

    def data(self, start: int, length: int) -> bytes:
        if not self._mm or start >= self.size:
            return b""
        return bytes(self._mm[start:min(self.size, start + length)])

    def find(self, needle: bytes, start: int) -> int:
        if not self._mm or not needle:
            return -1
        return self._mm.find(needle, max(0, start))

    def selection(self) -> tuple[int, int]:
        if self.sel_start < 0:
            return -1, 0
        a, b = sorted((self.sel_start, self.sel_end))
        return a, b - a + 1

    # ---------- navigazione ----------
    def goto(self, offset: int, length: int = 1) -> None:
        if not self.size:
            return
        offset = max(0, min(offset, self.size - 1))
        self.sel_start, self.sel_end = offset, min(self.size - 1, offset + max(length, 1) - 1)
        row = offset // BPR
        vis = self._visible_rows()
        sb = self.verticalScrollBar()
        if not (sb.value() <= row < sb.value() + vis - 1):
            sb.setValue(max(0, row - vis // 3))
        self.viewport().update()
        self.selectionChanged.emit(*self.selection())

    # ---------- geometria ----------
    def _metrics(self) -> None:
        fm = QFontMetrics(self.font())
        self.cw = fm.horizontalAdvance("0")
        self.lh = fm.height() + 2
        self.asc = fm.ascent()
        self.x_hex = self.cw * 12
        self.x_asc = self.x_hex + self.cw * (BPR * 3 + 2)

    def _visible_rows(self) -> int:
        return max(1, self.viewport().height() // self.lh)

    def _update_scroll(self) -> None:
        rows = (self.size + BPR - 1) // BPR
        self.verticalScrollBar().setRange(0, max(0, rows - self._visible_rows() + 1))
        self.verticalScrollBar().setPageStep(self._visible_rows())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_scroll()

    def _offset_at(self, x: int, y: int) -> int:
        row = self.verticalScrollBar().value() + y // self.lh
        if self.x_hex <= x < self.x_asc - self.cw:
            col = (x - self.x_hex) // (self.cw * 3)
        elif x >= self.x_asc:
            col = (x - self.x_asc) // self.cw
        else:
            return -1
        off = row * BPR + min(int(col), BPR - 1)
        return off if 0 <= off < self.size else -1

    # ---------- input ----------
    def mousePressEvent(self, e) -> None:
        off = self._offset_at(int(e.position().x()), int(e.position().y()))
        if off < 0:
            return
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._anchor >= 0:
            self.sel_start, self.sel_end = self._anchor, off
        else:
            self._anchor = self.sel_start = self.sel_end = off
        self.viewport().update()
        self.selectionChanged.emit(*self.selection())

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton and self._anchor >= 0:
            off = self._offset_at(int(e.position().x()), int(e.position().y()))
            if off >= 0:
                self.sel_start, self.sel_end = self._anchor, off
                self.viewport().update()
                self.selectionChanged.emit(*self.selection())

    def keyPressEvent(self, e) -> None:
        sb = self.verticalScrollBar()
        k = e.key()
        if k == Qt.Key.Key_PageDown:
            sb.setValue(sb.value() + sb.pageStep())
        elif k == Qt.Key.Key_PageUp:
            sb.setValue(sb.value() - sb.pageStep())
        elif k == Qt.Key.Key_Home and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            sb.setValue(0)
        elif k == Qt.Key.Key_End and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            sb.setValue(sb.maximum())
        else:
            super().keyPressEvent(e)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    # ---------- disegno ----------
    def paintEvent(self, _e) -> None:
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(C["panel"]))
        p.setFont(self.font())
        if not self.size:
            p.setPen(QColor(C["muted"]))
            p.drawText(self.viewport().rect().adjusted(12, 12, 0, 0), Qt.AlignmentFlag.AlignLeft,
                       "Nessun file aperto. Apri il reperto corrente o un file in sola lettura.")
            return
        first = self.verticalScrollBar().value()
        rows = self._visible_rows() + 1
        a, ln = self.selection()
        b = a + ln - 1
        sel_bg = QColor(C["select"])
        off_c, txt_c, dim_c, zero_c = QColor(C["muted"]), QColor(C["text"]), QColor(C["grey"]), QColor(C["zero"])
        p.fillRect(QRect(0, 0, self.x_hex - self.cw, self.viewport().height()), QColor(C["panel2"]))
        for r in range(rows):
            row = first + r
            base = row * BPR
            if base >= self.size:
                break
            y = r * self.lh
            chunk = self._mm[base:min(self.size, base + BPR)]
            p.setPen(off_c)
            p.drawText(self.cw // 2, y + self.asc, f"{base:010X}")
            for i, byte in enumerate(chunk):
                off = base + i
                xh = self.x_hex + i * 3 * self.cw + (self.cw if i >= 8 else 0)
                xa = self.x_asc + i * self.cw
                if a <= off <= b:
                    p.fillRect(QRect(xh - 2, y, self.cw * 2 + 4, self.lh), sel_bg)
                    p.fillRect(QRect(xa, y, self.cw, self.lh), sel_bg)
                p.setPen(zero_c if byte == 0 else txt_c)
                p.drawText(xh, y + self.asc, f"{byte:02X}")
                ch = chr(byte) if 32 <= byte < 127 else "·"
                p.setPen(txt_c if 32 <= byte < 127 else dim_c)
                p.drawText(xa, y + self.asc, ch)
