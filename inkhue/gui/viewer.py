"""Full-resolution image viewer: wheel / pinch / +/- to zoom, drag to pan. Shows printed dots
1:1 when zoomed in (no smoothing past 100 %), smooth when zoomed out."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class _View(QGraphicsView):
    def __init__(self, on_zoom):
        super().__init__()
        self.on_zoom = on_zoom
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.darkGray)

    def wheelEvent(self, e):
        self.zoom(1.25 if e.angleDelta().y() > 0 else 0.8)

    def zoom(self, f):
        z = self.transform().m11() * f
        if 0.02 <= z <= 32:
            self.scale(f, f)
            self.on_zoom(z)


class Viewer(QDialog):
    def __init__(self, parent, img: QImage, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 760)
        self.item = QGraphicsPixmapItem(QPixmap.fromImage(img))
        scene = QGraphicsScene(self)
        scene.addItem(self.item)
        self.view = _View(self._zoomed)
        self.view.setScene(scene)
        self.info = QLabel()
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"{img.width()} × {img.height()} px"))
        bar.addStretch(1)
        bar.addWidget(self.info)
        for text, f in (("−", 0.8), ("+", 1.25)):
            b = QPushButton(text)
            b.setFixedWidth(36)
            b.clicked.connect(lambda _=False, f=f: self.view.zoom(f))
            bar.addWidget(b)
        one = QPushButton("100 %")
        one.clicked.connect(lambda: self._set(1.0))
        fit = QPushButton("Fit")
        fit.clicked.connect(self.fit)
        bar.addWidget(one)
        bar.addWidget(fit)
        v = QVBoxLayout(self)
        v.addWidget(self.view, 1)
        v.addLayout(bar)

    def showEvent(self, e):
        super().showEvent(e)
        self.fit()

    def fit(self):
        self.view.fitInView(self.item, Qt.KeepAspectRatio)
        self._zoomed(self.view.transform().m11())

    def _set(self, z):
        self.view.zoom(z / self.view.transform().m11())

    def _zoomed(self, z):
        # smooth when shrinking, crisp pixels (printer dots) when magnifying
        self.view.setRenderHint(QPainter.SmoothPixmapTransform, z < 1)
        self.item.setTransformationMode(Qt.SmoothTransformation if z < 1 else Qt.FastTransformation)
        self.info.setText(f"{z:.0%}")
