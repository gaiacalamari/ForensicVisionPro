"""Lettore del video annotato e grafico degli angoli sincronizzati, come la visualizzazione di Sports2D.

Il lettore decodifica con OpenCV (nessun codec di sistema necessario) e permette l'avanzamento frame per frame;
il grafico mostra gli angoli nel tempo con un cursore che segue il video, e un clic sul grafico sposta il video in
quel punto. Entrambi lavorano in sola lettura sui file prodotti dall'analisi.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
                               QWidget)

from ..theme import C

SERIES_COLORS = ["#2f69ad", "#c0620f", "#2e7d4f", "#bd3a2e", "#7b4fa3", "#a87a05", "#178a8a", "#b0457a"]


class VideoPlayer(QWidget):
    """Lettore frame-accurato per i video prodotti dall'analisi (sola lettura)."""
    position_changed = Signal(float)          # secondi dall'inizio del video

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cap: cv2.VideoCapture | None = None
        self.path = ""
        self.fps = 25.0
        self.count = 0
        self.index = -1
        self._frame: np.ndarray | None = None
        self.screen = QLabel("Nessun video")
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setMinimumHeight(240)
        self.screen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.screen.setStyleSheet("background:#111; color:#bbb;")
        self.play_btn = QPushButton("▶ Riproduci")
        self.play_btn.clicked.connect(self.toggle)
        self.prev_btn = QPushButton("◀ frame")
        self.prev_btn.clicked.connect(lambda: self.seek_frame(self.index - 1))
        self.next_btn = QPushButton("frame ▶")
        self.next_btn.clicked.connect(lambda: self.seek_frame(self.index + 1))
        self.speed = QComboBox()
        for s in (0.1, 0.25, 0.5, 1.0, 2.0):
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(3)
        self.speed.currentIndexChanged.connect(self._retime)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._slider)
        self.info = QLabel("")
        self.info.setObjectName("Muted")
        bar = QHBoxLayout()
        for w in (self.play_btn, self.prev_btn, self.next_btn, QLabel("Velocità"), self.speed):
            bar.addWidget(w)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.info)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.screen, 1)
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._set_enabled(False)

    # ------------------------------------------------------------------ caricamento
    def load(self, path: str | Path | None) -> bool:
        self.stop()
        if self.cap is not None:
            self.cap.release()
        self.cap, self.path, self.index, self._frame = None, "", -1, None
        if not path or not Path(path).is_file():
            self.screen.setPixmap(QPixmap())
            self.screen.setText("Nessun video annotato per questo reperto.")
            self.slider.setRange(0, 0)
            self.info.setText("")
            self._set_enabled(False)
            return False
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            self.screen.setText(f"Impossibile aprire {Path(path).name}")
            self._set_enabled(False)
            return False
        self.cap, self.path = cap, str(path)
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, self.count - 1))
        self.slider.blockSignals(False)
        self._set_enabled(True)
        self.seek_frame(0)
        return True

    def _set_enabled(self, on: bool) -> None:
        for w in (self.play_btn, self.prev_btn, self.next_btn, self.speed, self.slider):
            w.setEnabled(on)

    # ------------------------------------------------------------------ navigazione
    def seek_frame(self, i: int) -> None:
        if self.cap is None:
            return
        i = max(0, min(i, self.count - 1 if self.count else i))
        if i != self.index + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = self.cap.read()
        if not ok:
            self.stop()
            return
        self.index, self._frame = i, fr
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self._show()
        t = i / self.fps if self.fps else 0.0
        self.info.setText(f"{i + 1}/{self.count} · {t:.3f} s")
        self.position_changed.emit(t)

    def seek_time(self, t: float) -> None:
        self.seek_frame(int(round(t * self.fps)))

    def _slider(self, v: int) -> None:
        self.seek_frame(v)

    def toggle(self) -> None:
        if self.timer.isActive():
            self.stop()
        else:
            if self.count and self.index >= self.count - 1:
                self.seek_frame(0)
            self._retime()
            self.timer.start()
            self.play_btn.setText("❚❚ Pausa")

    def stop(self) -> None:
        self.timer.stop()
        self.play_btn.setText("▶ Riproduci")

    def _retime(self) -> None:
        sp = self.speed.currentData() or 1.0
        self.timer.setInterval(max(5, int(1000 / (self.fps * sp))))

    def _tick(self) -> None:
        if self.count and self.index >= self.count - 1:
            self.stop()
            return
        self.seek_frame(self.index + 1)

    # ------------------------------------------------------------------ disegno
    def _show(self) -> None:
        if self._frame is None:
            return
        rgb = cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qi = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(qi).scaled(self.screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
        self.screen.setPixmap(pm)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._show()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.stop()
        if self.cap is not None:
            self.cap.release()
        super().closeEvent(e)


class AngleChart(QWidget):
    """Angoli nel tempo con cursore sincronizzato al video; clic = salta a quel tempo."""
    seek = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.times = np.zeros(0)
        self.series: dict[str, np.ndarray] = {}
        self.visible: list[str] = []
        self.cursor = float("nan")
        self.marks: list[tuple[float, str]] = []      # (tempo, colore) per discontinuità
        self.title = ""
        self.unit = "°"
        self.setMouseTracking(True)

    def set_data(self, times: np.ndarray, series: dict[str, np.ndarray], visible: list[str] | None = None,
                 title: str = "", unit: str = "°") -> None:
        self.times, self.series, self.title, self.unit = np.asarray(times, float), series, title, unit
        self.visible = [v for v in (visible or list(series)[:4]) if v in series]
        self.update()

    def set_visible(self, names: list[str]) -> None:
        self.visible = [n for n in names if n in self.series]
        self.update()

    def set_cursor(self, t: float) -> None:
        self.cursor = t
        self.update()

    def _area(self) -> QRectF:
        return QRectF(52, 26, max(10, self.width() - 64), max(10, self.height() - 52))

    def _range(self):
        vals = [self.series[n][np.isfinite(self.series[n])] for n in self.visible]
        vals = [v for v in vals if len(v)]
        if not vals or len(self.times) < 2:
            return None
        lo, hi = min(float(v.min()) for v in vals), max(float(v.max()) for v in vals)
        if hi - lo < 10:
            lo, hi = (lo + hi) / 2 - 5, (lo + hi) / 2 + 5
        pad = (hi - lo) * 0.05
        return float(np.nanmin(self.times)), float(np.nanmax(self.times)), lo - pad, hi + pad

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C["panel"]))
        txt, rule, muted = QColor(C["text"]), QColor(C["rule"]), QColor(C["muted"])
        a = self._area()
        p.setPen(txt)
        p.drawText(QRectF(8, 2, self.width() - 16, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.title)
        r = self._range()
        if r is None:
            p.setPen(muted)
            p.drawText(a, Qt.AlignmentFlag.AlignCenter, "Nessun dato da mostrare: scegli una persona e almeno un angolo.")
            return
        t0, t1, lo, hi = r
        X = lambda t: a.left() + (t - t0) / max(t1 - t0, 1e-9) * a.width()      # noqa: E731
        Y = lambda v: a.bottom() - (v - lo) / max(hi - lo, 1e-9) * a.height()  # noqa: E731
        p.setPen(QPen(rule, 1))
        p.drawRect(a)
        for i in range(5):
            v = lo + (hi - lo) * i / 4
            y = Y(v)
            p.setPen(QPen(rule, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - 8, 48, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{v:.0f}{self.unit}")
        for i in range(6):
            t = t0 + (t1 - t0) * i / 5
            p.drawText(QRectF(X(t) - 30, a.bottom() + 2, 60, 16), Qt.AlignmentFlag.AlignCenter, f"{t:.1f} s")
        for t, col in self.marks:
            if t0 <= t <= t1:
                p.setPen(QPen(QColor(col), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(X(t), a.top()), QPointF(X(t), a.bottom()))
        lx = a.left() + 6
        for k, n in enumerate(self.visible):
            col = QColor(SERIES_COLORS[k % len(SERIES_COLORS)])
            p.setPen(QPen(col, 1.6))
            path, pen_down = QPainterPath(), False
            for t, v in zip(self.times, self.series[n]):
                if not (math.isfinite(t) and math.isfinite(v)):
                    pen_down = False
                    continue
                pt = QPointF(X(t), Y(v))
                if pen_down:
                    path.lineTo(pt)
                else:
                    path.moveTo(pt)
                    pen_down = True
            p.drawPath(path)
            p.fillRect(QRectF(lx, a.top() + 6, 10, 10), col)
            p.setPen(txt)
            label = n
            if math.isfinite(self.cursor) and len(self.times):
                i = int(np.argmin(np.abs(self.times - self.cursor)))
                if math.isfinite(self.series[n][i]):
                    label += f" {self.series[n][i]:.1f}{self.unit}"
            p.drawText(QPointF(lx + 14, a.top() + 15), label)
            lx += 24 + p.fontMetrics().horizontalAdvance(label)
        if math.isfinite(self.cursor) and t0 <= self.cursor <= t1:
            p.setPen(QPen(QColor(C["red"]), 1.5))
            p.drawLine(QPointF(X(self.cursor), a.top()), QPointF(X(self.cursor), a.bottom()))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        r = self._range()
        a = self._area()
        if r and a.left() <= e.position().x() <= a.right():
            t0, t1 = r[0], r[1]
            self.seek.emit(t0 + (e.position().x() - a.left()) / a.width() * (t1 - t0))
