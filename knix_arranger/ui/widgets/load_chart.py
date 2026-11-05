"""
Balkendiagramm Busbelegung je Minute (Busanalyse, FA-640g).

Ein Balken je Minute (bei langen Mitschnitten mehrere Minuten, Höchstwert),
Richtwerte als waagrechte Linien, Uhrzeit unten, Wert als Tooltip.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ...services.bus_checks import LOAD_HINT, LOAD_WARN, LoadPoint, load_buckets
from ..styles import COLOR_ERROR, COLOR_OK, COLOR_WARNING, FONT_SMALL, TEXT_MUTED


class LoadChart(QWidget):
    _LEFT, _RIGHT, _TOP, _BOTTOM = 44, 12, 12, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[LoadPoint] = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_points(self, points: list[LoadPoint]) -> None:
        self._points = load_buckets(points)
        self.update()

    def _scale(self) -> float:
        top = max((p.percent for p in self._points), default=0)
        return max(LOAD_WARN + 10, -(-top // 10) * 10)

    def _plot(self) -> QRectF:
        return QRectF(self._LEFT, self._TOP, self.width() - self._LEFT - self._RIGHT,
                      self.height() - self._TOP - self._BOTTOM)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        font = QFont(self.font())
        font.setPixelSize(FONT_SMALL - 1)
        painter.setFont(font)
        plot = self._plot()
        muted = QColor(TEXT_MUTED)
        if not self._points:
            painter.setPen(muted)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Keine Busbelegung gespeichert – Mitschnitt neu einlesen")
            return
        scale = self._scale()

        def y(value: float) -> float:
            return plot.bottom() - plot.height() * min(value, scale) / scale

        # Achse und Gitter
        painter.setPen(QPen(QColor("#E0E0E0"), 1))
        for step in range(0, int(scale) + 1, 10):
            painter.drawLine(QPointF(plot.left(), y(step)), QPointF(plot.right(), y(step)))
            painter.setPen(muted)
            painter.drawText(QRectF(0, y(step) - 8, self._LEFT - 6, 16),
                             Qt.AlignRight | Qt.AlignVCenter, f"{step} %")
            painter.setPen(QPen(QColor("#E0E0E0"), 1))
        # Balken
        n = len(self._points)
        width = plot.width() / n
        for i, p in enumerate(self._points):
            color = (COLOR_ERROR if p.percent >= LOAD_WARN else
                     COLOR_WARNING if p.percent >= LOAD_HINT else COLOR_OK)
            top = y(p.percent)
            painter.fillRect(QRectF(plot.left() + i * width + width * 0.1, top,
                                    max(width * 0.8, 1.0), plot.bottom() - top), QColor(color))
        # Richtwerte
        for value, color in ((LOAD_HINT, COLOR_WARNING), (LOAD_WARN, COLOR_ERROR)):
            painter.setPen(QPen(QColor(color), 1, Qt.DashLine))
            painter.drawLine(QPointF(plot.left(), y(value)), QPointF(plot.right(), y(value)))
        # Uhrzeiten
        painter.setPen(muted)
        for i in sorted({0, n // 2, n - 1}):
            x = plot.left() + (i + 0.5) * width
            painter.drawText(QRectF(x - 40, plot.bottom() + 4, 80, 18), Qt.AlignCenter,
                             self._points[i].minute[11:16])

    def point_at(self, x: float) -> LoadPoint | None:
        plot = self._plot()
        if not self._points or not plot.left() <= x <= plot.right():
            return None
        index = int((x - plot.left()) / (plot.width() / len(self._points)))
        return self._points[min(index, len(self._points) - 1)]

    def mouseMoveEvent(self, event) -> None:
        p = self.point_at(event.position().x())
        if p is None:
            QToolTip.hideText()
            return
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"{p.minute.replace('T', ' ')}: {p.percent:.1f} % belegt, "
                          f"{p.frames} Rahmen", self)
