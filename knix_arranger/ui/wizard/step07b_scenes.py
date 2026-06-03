"""
Wizard Schritt 7b: Szenen definieren

Eingebettete SceneView im Wizard-Flow, so dass Szenen-GAs
vor der GA-Generierung (Schritt 8) bekannt sind.
"""
from __future__ import annotations
from PySide6.QtWidgets import QVBoxLayout, QLabel
from ...models.project import KnxProject
from ..views.scene_view import SceneView


class Step07bScenes(SceneView):
    """Szenen-Definition als Wizard-Schritt (zwischen Aktoren und GA-Generierung)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        # Info-Banner oben einfügen
        info = QLabel(
            "Definieren Sie hier die Szenen des Projekts.\n"
            "Im nächsten Schritt werden für jede Szene automatisch "
            "eine Gruppenadresse generiert.\n"
            "Szenen können danach in Schritt 9 (Sensor-Ermittlung) "
            "auf Taster gelegt werden."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #1565C0; padding-bottom: 6px;")
        # Vor das erste Widget einfügen
        self.layout().insertWidget(0, info)

    def on_enter(self):
        """Wird beim Betreten des Schritts aufgerufen."""
        self.set_project(self._project)
