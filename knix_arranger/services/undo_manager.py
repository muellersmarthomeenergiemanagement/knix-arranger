"""
Undo/Redo-Manager (NFA-031)
Command-Pattern für rueckgaengig machbare Änderungen.
"""
from __future__ import annotations
import logging
import copy
from abc import ABC, abstractmethod

logger = logging.getLogger("knix_arranger.undo")


class Command(ABC):
    """Abstrakte Basisklasse für Undo/Redo-Commands."""

    @abstractmethod
    def execute(self):
        """Fuehrt den Befehl aus."""
        ...

    @abstractmethod
    def undo(self):
        """Macht den Befehl rueckgaengig."""
        ...

    @abstractmethod
    def description(self) -> str:
        """Beschreibung des Befehls für die UI."""
        ...


class SnapshotCommand(Command):
    """Generischer Command basierend auf Objekt-Snapshots."""

    def __init__(self, target, description_text: str,
                 apply_fn=None):
        self._target = target
        self._description = description_text
        self._apply_fn = apply_fn
        self._before = None
        self._after = None

    def capture_before(self):
        """Snapshot vor der Aenderung nehmen."""
        self._before = copy.deepcopy(self._target)

    def capture_after(self):
        """Snapshot nach der Aenderung nehmen."""
        self._after = copy.deepcopy(self._target)

    def execute(self):
        if self._apply_fn:
            self._apply_fn()

    def undo(self):
        if self._before is not None:
            self._restore(self._before)

    def redo(self):
        if self._after is not None:
            self._restore(self._after)

    def _restore(self, snapshot):
        """Stellt den Zustand aus einem Snapshot wieder her."""
        if hasattr(self._target, '__dict__'):
            self._target.__dict__.update(snapshot.__dict__)

    def description(self) -> str:
        return self._description


class PropertyChangeCommand(Command):
    """Command für einfache Property-Änderungen."""

    def __init__(self, target, attr: str, old_value, new_value,
                 description_text: str = ""):
        self._target = target
        self._attr = attr
        self._old_value = old_value
        self._new_value = new_value
        self._description = description_text or f"{attr} geändert"

    def execute(self):
        setattr(self._target, self._attr, self._new_value)

    def undo(self):
        setattr(self._target, self._attr, self._old_value)

    def description(self) -> str:
        return self._description


class ListAddCommand(Command):
    """Command für das Hinzufügen eines Elements zu einer Liste."""

    def __init__(self, target_list: list, item, description_text: str = ""):
        self._list = target_list
        self._item = item
        self._description = description_text or "Element hinzugefügt"

    def execute(self):
        self._list.append(self._item)

    def undo(self):
        if self._item in self._list:
            self._list.remove(self._item)

    def description(self) -> str:
        return self._description


class ListRemoveCommand(Command):
    """Command für das Entfernen eines Elements aus einer Liste."""

    def __init__(self, target_list: list, item, description_text: str = ""):
        self._list = target_list
        self._item = item
        self._index = -1
        self._description = description_text or "Element entfernt"

    def execute(self):
        if self._item in self._list:
            self._index = self._list.index(self._item)
            self._list.remove(self._item)

    def undo(self):
        if self._index >= 0:
            self._list.insert(self._index, self._item)

    def description(self) -> str:
        return self._description


class CompositeCommand(Command):
    """Zusammengesetzter Command aus mehreren Sub-Commands."""

    def __init__(self, commands: list[Command], description_text: str = ""):
        self._commands = commands
        self._description = description_text or "Mehrere Änderungen"

    def execute(self):
        for cmd in self._commands:
            cmd.execute()

    def undo(self):
        for cmd in reversed(self._commands):
            cmd.undo()

    def description(self) -> str:
        return self._description


class ObjectStateCommand(Command):
    """Stellt einen Objektzustand anhand eines Deepcopy-Snapshots wieder her.

    Wird für die manuelle Bearbeitungsphase (Phase B/D) verwendet:
    Der Snapshot wird VOR der Änderung aufgenommen. execute() ist leer,
    da die Änderung bereits stattgefunden hat.

    Args:
        target:          Das live Objekt (z.B. KnxProject-Instanz)
        snapshot:        Deepcopy des Objekts VOR der Änderung
        description:     Anzeige-Text im Undo-Menü
        preserve_attrs:  Attribute die beim Undo NICHT wiederhergestellt werden
                         sollen (z.B. Laufzeit-Felder wie _file_path)
    """

    def __init__(self, target, snapshot, description: str,
                 preserve_attrs: tuple[str, ...] = ()):
        self._target = target
        self._snapshot = snapshot
        self._description = description
        self._preserve_attrs = preserve_attrs

    def execute(self):
        pass  # Änderung ist bereits erfolgt

    def undo(self):
        preserved = {
            a: getattr(self._target, a)
            for a in self._preserve_attrs
            if hasattr(self._target, a)
        }
        self._target.__dict__.update(self._snapshot.__dict__)
        for attr, value in preserved.items():
            setattr(self._target, attr, value)

    def description(self) -> str:
        return self._description


class UndoManager:
    """Verwaltet die Undo/Redo-Historie (NFA-031)."""

    MAX_HISTORY = 100

    def __init__(self):
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []

    def execute(self, command: Command):
        """Fuehrt einen Command aus und legt ihn auf den Undo-Stack."""
        command.execute()
        self._undo_stack.append(command)
        self._redo_stack.clear()  # Redo-Stack bei neuer Aktion leeren

        # Historie begrenzen
        if len(self._undo_stack) > self.MAX_HISTORY:
            self._undo_stack.pop(0)

        logger.debug(f"Befehl ausgeführt: {command.description()}")

    def undo(self) -> bool:
        """Macht die letzte Aktion rueckgaengig. Gibt True bei Erfolg zurück."""
        if not self._undo_stack:
            return False

        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        logger.debug(f"Rückgängig: {command.description()}")
        return True

    def redo(self) -> bool:
        """Wiederholt die letzte rueckgaengig gemachte Aktion."""
        if not self._redo_stack:
            return False

        command = self._redo_stack.pop()
        command.execute()
        self._undo_stack.append(command)
        logger.debug(f"Wiederholt: {command.description()}")
        return True

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def undo_description(self) -> str:
        """Beschreibung der naechsten Undo-Aktion."""
        if self._undo_stack:
            return self._undo_stack[-1].description()
        return ""

    @property
    def redo_description(self) -> str:
        """Beschreibung der naechsten Redo-Aktion."""
        if self._redo_stack:
            return self._redo_stack[-1].description()
        return ""

    def clear(self):
        """Leert die gesamte Historie."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    @property
    def undo_count(self) -> int:
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        return len(self._redo_stack)
