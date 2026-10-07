"""
Steigschema (FA-905a): Gebäudeschnitt mit dem Verlauf der KNX-Linien.

Zeichnet das Modell aus services/riser_diagram.py -- dasselbe wie im
Topologie-Bericht. Klick auf eine Linie (oder ihren Eintrag rechts) hebt
sie hervor, Strg + Mausrad zoomt, Tooltips zeigen Raum, Verteiler, Linie.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsView,
    QGraphicsScene, QGraphicsRectItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsSimpleTextItem, QListWidget, QListWidgetItem, QSplitter,
    QFileDialog, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen,
    QPixmap, QImage,
)
from ...services.riser_diagram import Dot, Label, Path, Rect, build_riser_diagram
from .. import license_gate  # NFA-066: Exporte im Lesemodus gesperrt

_FONT_PX = 100.0   # Schrift in dieser Pixelgrösse setzen und auf die Punktgrösse skalieren


class _View(QGraphicsView):
    """Zoom mit Strg + Mausrad, Klick meldet die ref des getroffenen Elements."""

    def __init__(self, scene, on_click):
        super().__init__(scene)
        self._on_click = on_click
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            self._on_click(item.data(0) if item is not None else "")


class RiserDiagramView(QWidget):
    """Steigschema als eigene Ansicht (Seitenleiste "Steigschema")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._highlight = ""
        self._fitted = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        title = QLabel("Steigschema")
        title.setObjectName("title")
        toolbar.addWidget(title)
        toolbar.addStretch()
        btn_fit = QPushButton("Ganzes Schema")
        btn_fit.setObjectName("secondary")
        btn_fit.clicked.connect(self._fit)
        toolbar.addWidget(btn_fit)
        btn_png = QPushButton("Als PNG exportieren…")
        btn_png.clicked.connect(self._export_png)
        toolbar.addWidget(btn_png)
        btn_pdf = QPushButton("Als PDF exportieren…")
        btn_pdf.clicked.connect(self._export_pdf)
        toolbar.addWidget(btn_pdf)
        layout.addLayout(toolbar)

        self._info = QLabel(
            "Verlauf der Linien vom Verteiler (Schritt 4 / 8) über die Steigzone zu den "
            "Räumen mit Teilnehmern. Klick auf eine Linie hebt sie hervor · Strg + Mausrad "
            "zoomt · Tooltips zeigen Raum, Verteiler und Linie.")
        self._info.setObjectName("subtitle")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        splitter = QSplitter(Qt.Horizontal)
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QBrush(QColor("#FFFFFF")))
        self._view = _View(self._scene, self._on_click)
        splitter.addWidget(self._view)

        self._lines = QListWidget()
        self._lines.setMaximumWidth(320)
        self._lines.currentItemChanged.connect(self._on_line_selected)
        splitter.addWidget(self._lines)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    # ── Daten ────────────────────────────────────────────────────────────

    def set_project(self, project) -> None:
        self._project = project
        self._highlight = ""
        self._fitted = False
        self._rebuild()

    def _rebuild(self) -> None:
        self._scene.clear()
        if self._project is None:
            return
        diagram = build_riser_diagram(self._project, highlight=self._highlight)
        if diagram.is_empty:
            self._scene.addSimpleText("Keine Gebäudestruktur vorhanden.")
            self._fill_list(diagram)
            return
        self._draw(diagram)
        self._scene.setSceneRect(QRectF(-20, -10, diagram.width + 40, diagram.height + 20))
        self._fill_list(diagram)
        if not self._fitted:
            self._fitted = True
            self._fit()

    def _fill_list(self, diagram) -> None:
        self._lines.blockSignals(True)
        self._lines.clear()
        all_item = QListWidgetItem("Alle Linien")
        all_item.setData(Qt.UserRole, "")
        self._lines.addItem(all_item)
        for entry in diagram.legend:
            item = QListWidgetItem(f"{entry.title}\n{entry.detail}")
            pix = QPixmap(14, 14)
            pix.fill(QColor(entry.color))
            item.setIcon(QIcon(pix))
            item.setData(Qt.UserRole, entry.ref)
            self._lines.addItem(item)
            if entry.ref == self._highlight:
                self._lines.setCurrentItem(item)
        if not self._highlight:
            self._lines.setCurrentItem(all_item)
        self._lines.blockSignals(False)

    # ── Zeichnen ─────────────────────────────────────────────────────────

    def _draw(self, diagram) -> None:
        base = QFont(QApplication.font())
        base.setPixelSize(int(_FONT_PX))
        bold = QFont(base)
        bold.setBold(True)
        metrics = {False: QFontMetricsF(base), True: QFontMetricsF(bold)}
        tips = diagram.tooltips

        def finish(item, ref):
            if ref:
                item.setData(0, ref)
                tip = tips.get(ref, "")
                if tip:
                    item.setToolTip(tip)
                if ref.startswith("line:"):
                    item.setCursor(Qt.PointingHandCursor)
            self._scene.addItem(item)

        for shape in diagram.shapes:
            if isinstance(shape, Rect):
                item = QGraphicsRectItem(shape.x, shape.y, shape.w, shape.h)
                item.setBrush(QBrush(QColor(shape.fill)) if shape.fill else Qt.NoBrush)
                item.setPen(QPen(QColor(shape.stroke), shape.width) if shape.stroke
                            else QPen(Qt.NoPen))
                finish(item, shape.ref)
            elif isinstance(shape, Path):
                path = QPainterPath(QPointF(*shape.points[0]))
                for p in shape.points[1:]:
                    path.lineTo(QPointF(*p))
                pen = QPen(QColor(shape.color), shape.width)
                pen.setCapStyle(Qt.FlatCap)
                if shape.dash:
                    pen.setDashPattern([3 / shape.width, 2 / shape.width])
                item = QGraphicsPathItem(path)
                item.setPen(pen)
                finish(item, shape.ref)
            elif isinstance(shape, Dot):
                item = QGraphicsEllipseItem(shape.x - shape.r, shape.y - shape.r,
                                            2 * shape.r, 2 * shape.r)
                item.setBrush(QBrush(QColor(shape.fill)))
                item.setPen(QPen(Qt.NoPen))
                finish(item, shape.ref)
            elif isinstance(shape, Label) and shape.text:
                item = QGraphicsSimpleTextItem(shape.text)
                item.setFont(bold if shape.bold else base)
                item.setBrush(QBrush(QColor(shape.color)))
                scale = shape.size / _FONT_PX
                m = metrics[shape.bold]
                width = m.horizontalAdvance(shape.text) * scale
                dx = {"left": 0.0, "center": 0.5, "right": 1.0}[shape.align] * width
                item.setScale(scale)
                item.setPos(shape.x - dx, shape.y - m.ascent() * scale)
                finish(item, shape.ref)

    # ── Interaktion ──────────────────────────────────────────────────────

    def _on_click(self, ref) -> None:
        ref = ref or ""
        new = ref if ref.startswith("line:") else ""
        if new != self._highlight:
            self._highlight = new
            self._rebuild()

    def _on_line_selected(self, current, _previous) -> None:
        ref = current.data(Qt.UserRole) if current is not None else ""
        if ref != self._highlight:
            self._highlight = ref or ""
            self._rebuild()

    def _fit(self) -> None:
        rect = self._scene.sceneRect()
        if rect.isValid():
            self._view.fitInView(rect, Qt.KeepAspectRatio)

    # ── Export ───────────────────────────────────────────────────────────

    def _export_png(self) -> None:
        if self._project is None:
            return
        path, _ = license_gate.get_save_file_name(
            self, "Steigschema als PNG", "Steigschema.png", "PNG (*.png)")
        if not path:
            return
        rect = self._scene.sceneRect()
        image = QImage(int(rect.width() * 3), int(rect.height() * 3), QImage.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self._scene.render(painter, QRectF(image.rect()), rect)
        painter.end()
        if not image.save(path):
            QMessageBox.warning(self, "Export", f"PNG konnte nicht gespeichert werden:\n{path}")

    def _export_pdf(self) -> None:
        if self._project is None:
            return
        path, _ = license_gate.get_save_file_name(
            self, "Steigschema als PDF", "Steigschema.pdf", "PDF (*.pdf)")
        if not path:
            return
        from ...services.report_service import ReportService
        try:
            ReportService(self._project).generate_riser_report(path)
        except Exception as exc:
            QMessageBox.warning(self, "Export", f"PDF konnte nicht erstellt werden:\n{exc}")
