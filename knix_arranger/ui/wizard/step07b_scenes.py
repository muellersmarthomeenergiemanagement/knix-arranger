"""
Wizard Schritt 10: Szenen definieren

Eingebettete SceneView im Wizard-Flow, nach der GA-Generierung (Schritt 9):
Szenen-Aktionen verweisen auf vorhandene GAs, Aktor-Kanäle und
Nummernkonflikte (FA-1813) sind damit sofort sichtbar. Die Szenenaufruf-GAs
erzeugt dieser Schritt selbst nach (beim Verlassen bzw. «Jetzt generieren»).
"""
from __future__ import annotations
from PySide6.QtWidgets import QLabel, QMessageBox
from ...models.project import KnxProject
from ...services.address_generator import regenerate_addresses
from ..views.scene_view import SceneView
from .recompute_guard import RecomputeGuard, KEY_ADDRESSES


class Step07bScenes(SceneView):
    """Szenen-Definition als Wizard-Schritt (zwischen GA-Generierung und
    Funktionszuordnung)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        # Vom WizardController durch eine gemeinsame Instanz ersetzt
        self._guard = RecomputeGuard()

        info = QLabel(
            "Definieren Sie hier die Szenen des Projekts. Aktionen wählen Sie "
            "aus den Gruppenadressen von Schritt 9.\n"
            "Szenen mit gleichem Geltungsbereich teilen sich eine Szenenaufruf-GA; "
            "sie wird beim Verlassen dieses Schritts erzeugt.\n"
            "In Schritt 11 (Funktionszuordnung) legen Sie die Szenen auf Taster."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #1565C0; padding-bottom: 6px;")
        self.layout().insertWidget(0, info)

        # «Jetzt generieren» im Hinweisbanner: im Wizard direkt hier erzeugen
        # statt den Wizard ein zweites Mal zu öffnen (Hauptfenster)
        self.request_generate_addresses.connect(self._generate_now)

    def on_enter(self):
        """Wird beim Betreten des Schritts aufgerufen."""
        self.set_project(self._project)

    def on_leave(self):
        """Szenenaufruf-GAs nachführen, damit Schritt 11 die Szenen auf
        Taster legen kann. Wie Schritt 5: nur bei Änderungen, nie bei
        importierten Projekten (deren GAs nur Schritt 9 mit Rückfrage
        neu erzeugt)."""
        if self._project.topology.is_imported:
            return
        if not any(r.gewerk_assignments for r in self._project.all_rooms):
            return
        if not self._guard.is_stale(self._project, KEY_ADDRESSES):
            return
        regenerate_addresses(self._project)
        self._guard.mark_done(self._project, KEY_ADDRESSES)

    def _generate_now(self):
        if self._project.topology.is_imported:
            QMessageBox.information(
                self, "Importiertes Projekt",
                "Die Gruppenadressen dieses Projekts stammen aus der ETS und werden "
                "nicht automatisch neu erzeugt. Szenenaufruf-GAs legen Sie in "
                "Schritt 9 an (Generieren mit Rückfrage oder manuell).",
            )
            return
        regenerate_addresses(self._project)
        self._guard.mark_done(self._project, KEY_ADDRESSES)
        self._refresh_table()
