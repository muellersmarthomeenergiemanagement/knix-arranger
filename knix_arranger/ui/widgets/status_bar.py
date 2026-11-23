"""
Statusleiste mit Projektinfo (NFA-023)

Gegliedert: links die letzte Meldung (lange Texte gekürzt, voller Text im
Tooltip), rechts fest Projekt, MG-Variante und Anzahl GAs, durch Trennstriche
getrennt. Vorher standen alle vier Felder ohne Abgrenzung nebeneinander, und
eine lange Import-Meldung schob die Projektangaben aus dem Bild.
"""
from __future__ import annotations
from PySide6.QtWidgets import QStatusBar, QLabel, QFrame, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter

from ..styles import TEXT_MUTED


class _ElidedLabel(QLabel):
    """Label, das zu lange Texte mit «…» kürzt; text() bleibt vollständig."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(80)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt-Name)
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        rect = self.contentsRect()
        elided = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        painter.drawText(rect, int(self.alignment() | Qt.AlignVCenter), elided)


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setFrameShadow(QFrame.Plain)
    line.setStyleSheet(f"color: {TEXT_MUTED};")
    return line


class KnxStatusBar(QStatusBar):
    """Erweiterte Statusleiste mit Projektinformationen."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._status_label = _ElidedLabel("Bereit")
        self._project_label = QLabel("Kein Projekt geladen")
        self._variant_label = QLabel("")
        self._ga_count_label = QLabel("")
        for label in (self._variant_label, self._ga_count_label):
            label.setStyleSheet(f"color: {TEXT_MUTED};")
        self._project_label.setStyleSheet("font-weight: bold;")

        # links: Meldung (nimmt die Restbreite, wird gekürzt)
        self.addWidget(self._status_label, 1)
        # rechts, fest: Projekt | Variante | GAs
        self.addPermanentWidget(_separator())
        self.addPermanentWidget(self._project_label)
        self._variant_separator = _separator()
        self.addPermanentWidget(self._variant_separator)
        self.addPermanentWidget(self._variant_label)
        self._ga_separator = _separator()
        self.addPermanentWidget(self._ga_separator)
        self.addPermanentWidget(self._ga_count_label)
        self._update_separators()

    def _update_separators(self) -> None:
        self._variant_separator.setVisible(bool(self._variant_label.text()))
        self._ga_separator.setVisible(bool(self._ga_count_label.text()))

    def set_project_name(self, name: str):
        self._project_label.setText(f"Projekt: {name}")

    def set_variant(self, variant: str):
        self._variant_label.setText(f"Variante {variant}")
        self._update_separators()

    def set_ga_count(self, count: int):
        self._ga_count_label.setText(f"{count} Gruppenadressen")
        self._update_separators()

    def set_status(self, text: str):
        # Nur im eigenen Feld: eine temporäre Meldung (showMessage) zeichnete
        # Qt über die Felder links, die Texte lagen übereinander
        self._status_label.setText(text)

    def showMessage(self, text: str, timeout: int = 0):  # noqa: N802 (Qt-Name)
        """Auch Aufrufe von showMessage (z.B. Live-Monitor) landen im
        Meldungsfeld statt als Qt-Meldung über den anderen Feldern."""
        self.set_status(text)
