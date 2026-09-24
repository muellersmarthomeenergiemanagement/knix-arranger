"""
Icons aus knix_arranger/data/icons (Tabler Icons, MIT-Lizenz, siehe
LICENSE-tabler-icons.txt im selben Ordner).

Die SVGs zeichnen mit stroke="currentColor"; Qt kennt currentColor nicht,
daher wird die Farbe vor dem Rendern direkt eingesetzt.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QGuiApplication
from PySide6.QtSvg import QSvgRenderer

_ICON_DIR = Path(__file__).resolve().parent.parent / "data" / "icons"


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    path = _ICON_DIR / f"{name}.svg"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _pixmap(name: str, color: str, size: int) -> QPixmap:
    svg = _svg(name)
    app = QGuiApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    pix = QPixmap(QSize(int(size * ratio), int(size * ratio)))
    pix.fill(Qt.transparent)
    if svg:
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(name: str, color: str, checked_color: str | None = None, size: int = 18) -> QIcon:
    """QIcon in `color`; mit `checked_color` zusätzlich für den aktiven
    (checked) Zustand eines Buttons. Unbekannte Namen ergeben ein leeres Icon."""
    result = QIcon()
    result.addPixmap(_pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if checked_color:
        result.addPixmap(_pixmap(name, checked_color, size), QIcon.Normal, QIcon.On)
    return result
