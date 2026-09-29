"""Tests fuer den Undo/Redo-Manager."""
import pytest
from knix_arranger.services.undo_manager import (
    UndoManager, PropertyChangeCommand, ListAddCommand,
    ListRemoveCommand, CompositeCommand,
)


class TestUndoManagerBasic:
    def test_empty_manager(self):
        mgr = UndoManager()
        assert not mgr.can_undo()
        assert not mgr.can_redo()
        assert mgr.undo_count == 0

    def test_execute_command(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        cmd = PropertyChangeCommand(obj, "value", 10, 20, "Wert aendern")
        mgr.execute(cmd)

        assert obj.value == 20
        assert mgr.can_undo()
        assert not mgr.can_redo()

    def test_undo(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        cmd = PropertyChangeCommand(obj, "value", 10, 20, "Wert aendern")
        mgr.execute(cmd)

        result = mgr.undo()
        assert result is True
        assert obj.value == 10
        assert not mgr.can_undo()
        assert mgr.can_redo()

    def test_redo(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        cmd = PropertyChangeCommand(obj, "value", 10, 20, "Wert aendern")
        mgr.execute(cmd)
        mgr.undo()

        result = mgr.redo()
        assert result is True
        assert obj.value == 20

    def test_undo_empty_returns_false(self):
        mgr = UndoManager()
        assert mgr.undo() is False

    def test_redo_empty_returns_false(self):
        mgr = UndoManager()
        assert mgr.redo() is False

    def test_new_command_clears_redo(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        mgr.execute(PropertyChangeCommand(obj, "value", 10, 20))
        mgr.undo()
        assert mgr.can_redo()

        mgr.execute(PropertyChangeCommand(obj, "value", 10, 30))
        assert not mgr.can_redo()

    def test_description(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        mgr.execute(PropertyChangeCommand(obj, "value", 10, 20, "Test-Aenderung"))
        assert mgr.undo_description == "Test-Aenderung"

    def test_clear(self):
        mgr = UndoManager()

        class Obj:
            value = 10

        obj = Obj()
        mgr.execute(PropertyChangeCommand(obj, "value", 10, 20))
        mgr.clear()
        assert not mgr.can_undo()
        assert mgr.undo_count == 0


class TestObjectStateCommand:
    """Der Snapshot-Befehl des Hauptfensters: Wiederholen tat früher nichts."""

    def test_undo_redo_undo(self):
        import copy
        from knix_arranger.services.undo_manager import ObjectStateCommand

        class Project:
            def __init__(self):
                self.name = "vorher"
                self.items = [1]
                self._file_path = "a.knxarr"

        project = Project()
        snapshot = copy.deepcopy(project)
        project.name = "nachher"
        project.items.append(2)
        project._file_path = "b.knxarr"

        mgr = UndoManager()
        mgr.execute(ObjectStateCommand(project, snapshot, "Test",
                                       preserve_attrs=("_file_path",)))
        assert project.name == "nachher"      # execute ändert nichts

        mgr.undo()
        assert (project.name, project.items) == ("vorher", [1])
        mgr.redo()
        assert (project.name, project.items) == ("nachher", [1, 2])
        mgr.undo()
        assert (project.name, project.items) == ("vorher", [1])
        assert project._file_path == "b.knxarr"   # Laufzeitfeld bleibt


class TestListCommands:
    def test_list_add(self):
        items = [1, 2, 3]
        cmd = ListAddCommand(items, 4, "Element hinzufuegen")
        cmd.execute()
        assert 4 in items

        cmd.undo()
        assert 4 not in items

    def test_list_remove(self):
        items = [1, 2, 3]
        cmd = ListRemoveCommand(items, 2, "Element entfernen")
        cmd.execute()
        assert 2 not in items

        cmd.undo()
        assert items == [1, 2, 3]

    def test_list_remove_preserves_order(self):
        items = ["a", "b", "c", "d"]
        cmd = ListRemoveCommand(items, "b")
        cmd.execute()
        assert items == ["a", "c", "d"]

        cmd.undo()
        assert items == ["a", "b", "c", "d"]


class TestCompositeCommand:
    def test_composite_execute(self):
        class Obj:
            x = 0
            y = 0

        obj = Obj()
        composite = CompositeCommand([
            PropertyChangeCommand(obj, "x", 0, 10),
            PropertyChangeCommand(obj, "y", 0, 20),
        ], "Beide aendern")

        composite.execute()
        assert obj.x == 10
        assert obj.y == 20

    def test_composite_undo(self):
        class Obj:
            x = 0
            y = 0

        obj = Obj()
        composite = CompositeCommand([
            PropertyChangeCommand(obj, "x", 0, 10),
            PropertyChangeCommand(obj, "y", 0, 20),
        ])

        composite.execute()
        composite.undo()
        assert obj.x == 0
        assert obj.y == 0
