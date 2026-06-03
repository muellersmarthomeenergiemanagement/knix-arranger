"""
ProjectBus – zentraler Event-Bus für Projektänderungen.

Entkoppelt Views und Services voneinander: Jede Komponente kann
Änderungen ankündigen, ohne die anderen direkt zu kennen.

Verwendung (emittieren):
    self._bus.emit_building_changed()

Verwendung (abonnieren):
    bus.building_changed.connect(self._refresh)
    bus.any_change.connect(lambda ctx: print(f"Geändert: {ctx}"))
"""
from PySide6.QtCore import QObject, Signal


class ProjectBus(QObject):
    """Zentraler Signal-Hub für alle Projektänderungen."""

    # Granulare Signale – Views abonnieren nur was sie brauchen
    building_changed   = Signal()   # Räume, Wohnungen, Etagen geändert
    functions_changed  = Signal()   # Gewerk/Funktion pro Raum geändert
    topology_changed   = Signal()   # Linien, Gerätezuordnung geändert
    addresses_changed  = Signal()   # Gruppenadresse umbenannt/verschoben
    material_changed   = Signal()   # Produkt zugewiesen, Materialliste geändert
    project_loaded     = Signal()   # Neues Projekt geladen oder erstellt

    # Broadcast: wird bei JEDER Änderung emittiert (für einfache Views)
    # Kontext-String zeigt die Art der Änderung (z.B. "building", "topology")
    any_change = Signal(str)

    # Undo-Hook: Views rufen begin_change() VOR der Datenänderung auf.
    # MainWindow nimmt dann einen Projektsnapshot für den Undo-Stack auf.
    change_started = Signal(str)  # Beschreibung der geplanten Änderung

    def begin_change(self, description: str):
        """VOR jeder manuellen Datenänderung aufrufen – setzt einen Undo-Punkt."""
        self.change_started.emit(description)

    # -- Emit-Helfer: immer granulares Signal + any_change zusammen --

    def emit_building_changed(self):
        self.building_changed.emit()
        self.any_change.emit("building")

    def emit_functions_changed(self):
        self.functions_changed.emit()
        self.any_change.emit("functions")

    def emit_topology_changed(self):
        self.topology_changed.emit()
        self.any_change.emit("topology")

    def emit_addresses_changed(self):
        self.addresses_changed.emit()
        self.any_change.emit("addresses")

    def emit_material_changed(self):
        self.material_changed.emit()
        self.any_change.emit("material")

    def emit_project_loaded(self):
        self.project_loaded.emit()
        self.any_change.emit("project_loaded")
