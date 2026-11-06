"""Viste immagine affiancate con zoom e scorrimento sincronizzati."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QLabel, QVBoxLayout, QWidget



def _pillow_qimage(path: str) -> QImage:
    try:
        from PIL import Image, ImageOps

        from ...engines import heif_support
        heif_support.ensure_registered()
        with Image.open(path) as im:
            im.load()
            rgba = ImageOps.exif_transpose(im).convert("RGBA")
        data = rgba.tobytes("raw", "RGBA")
        return QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    except Exception:  # noqa: BLE001 - un'anteprima non decodificabile non blocca l'interfaccia
        return QImage()


class ImageView(QGraphicsView):
    def __init__(self, group: "SyncGroup"):
        super().__init__()
        self.group = group
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self.scene().addItem(self.item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setObjectName("ImageView")
        self.horizontalScrollBar().valueChanged.connect(lambda v: group.sync_scroll(self, "h", v))
        self.verticalScrollBar().valueChanged.connect(lambda v: group.sync_scroll(self, "v", v))

    def set_image(self, path: str | None) -> None:
        if path:
            img = QImage(path)
            if img.isNull():
                img = _pillow_qimage(path)      # HEIC/HEIF e altri formati che Qt non legge
            self.item.setPixmap(QPixmap.fromImage(img) if not img.isNull() else QPixmap())
        else:
            self.item.setPixmap(QPixmap())
        self.scene().setSceneRect(self.item.boundingRect())

    def wheelEvent(self, e) -> None:
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.group.zoom(f)


class SyncGroup:
    def __init__(self):
        self.views: list[ImageView] = []
        self._lock = False

    def new_view(self, caption: str) -> tuple[QWidget, ImageView]:
        v = ImageView(self)
        self.views.append(v)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        if caption:
            lab = QLabel(caption)
            lab.setObjectName("Muted")
            lay.addWidget(lab)
        lay.addWidget(v, 1)
        return w, v

    def zoom(self, f: float) -> None:
        for v in self.views:
            v.scale(f, f)

    def fit(self) -> None:
        for v in self.views:
            if not v.item.pixmap().isNull():
                v.fitInView(v.item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual(self) -> None:
        for v in self.views:
            v.resetTransform()

    def sync_scroll(self, src: ImageView, axis: str, val: int) -> None:
        if self._lock:
            return
        self._lock = True
        for v in self.views:
            if v is not src:
                (v.horizontalScrollBar() if axis == "h" else v.verticalScrollBar()).setValue(val)
        self._lock = False
