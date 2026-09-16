"""
Tests fuer BauherrFormView -- interaktive Tastenzahl-Anpassung und direkte
Gewerk-/Szenen-Auswahl fuer leere Taster-Slots.

Tastenzahl: Vorher liess sich die Kanalzahl (be.channels) einer Tastereinheit
nur in Schritt 8 (Funktionszuordnung, feste Auswahl 1/2/4/6) aendern. In der
Bauherrenberatung selbst gab es keine Moeglichkeit, zusaetzliche (leere)
Tasten sichtbar zu machen, wenn die reale Tastereinheit mehr physische
Tasten hat als bisher konfiguriert -- der Bauherr konnte fuer diese Tasten
keinen Wunsch hinterlegen.

Gewerk-/Szenen-Auswahl: der Wunsch-Combo eines leeren Slots bot bisher nur
generische Freitext-Optionen ("Licht Ein/Aus", ...), die keine GA kennen und
erst spaeter manuell ueber die Verknuepfungsmatrix aufgeloest werden mussten.
Jetzt listet derselbe Combo zusaetzlich die tatsaechlich im Raum geplanten
Gewerk-Instanzen und die benannten Szenen des Projekts -- deren Auswahl
erzeugt sofort eine vollstaendige SensorFunktion samt GA-Verknuepfung, exakt
wie die "Eigener Raum"/"Szene"-Tabs im Schritt-8-Dialog.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QGridLayout

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement,
    SensorFunktion, GewerkAssignment,
)
from knix_arranger.models.scene import Scene
from knix_arranger.ui.views.bauherr_form_view import BauherrFormView, _TasterWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_project_with_taster(channels: int, n_funktionen: int) -> tuple[KnxProject, Bedienelement]:
    room = Room(number="E01", name="Wohnzimmer")
    be = Bedienelement(
        element_type="Tastereinheit", channels=channels, participant_number="1.1.5",
        funktionen=[
            SensorFunktion(gewerk_code="L", element_number=1)
            for _ in range(n_funktionen)
        ],
    )
    room.bedienelemente.append(be)
    apt = Apartment(name="EG", rooms=[room])
    floor = Floor(name="EG", short_code="EG")
    floor.apartments = [apt]
    wing = Wing(name="Haupt", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(name="A", buildings=[building])

    project = KnxProject(name="T")
    project.areal = areal
    return project, be


def _find_taster(view: BauherrFormView) -> _TasterWidget:
    for i in range(view._content_layout.count()):
        w = view._content_layout.itemAt(i).widget()
        if isinstance(w, _TasterWidget):
            return w
    raise AssertionError("Kein _TasterWidget im Content-Layout gefunden.")


def _grid_slot_count(taster: _TasterWidget) -> tuple[int, int]:
    """(Gesamtzahl Slots, Anzahl noch offener Slots ohne gewaehlten Wert).

    Jeder Slot ist immer eine Combobox (nichts mehr schreibgeschuetzt) --
    "offen" bedeutet: Platzhalter "-- Funktion waehlen --" ist noch
    ausgewaehlt (Index 0)."""
    grid = taster.findChild(QGridLayout)
    total = grid.count()
    empty = sum(
        1 for i in range(grid.count())
        if grid.itemAt(i).widget()._combo.currentIndex() == 0
    )
    return total, empty


class TestChannelsSpinBoxVisible:
    def test_shown_for_tastereinheit(self):
        project, be = _make_project_with_taster(channels=2, n_funktionen=2)
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        assert hasattr(taster, "_channels_spin")
        assert taster._channels_spin.value() == 2

    def test_hidden_for_non_tastereinheit(self):
        room = Room(number="E01", name="Bad")
        be = Bedienelement(
            element_type="Raumthermostat", channels=1, participant_number="1.1.9",
            funktionen=[SensorFunktion(gewerk_code="H", element_number=1)],
        )
        room.bedienelemente.append(be)
        apt = Apartment(name="EG", rooms=[room])
        floor = Floor(name="EG", short_code="EG")
        floor.apartments = [apt]
        wing = Wing(name="Haupt", floors=[floor])
        building = Building(name="Haus", wings=[wing])
        areal = Areal(name="A", buildings=[building])
        project = KnxProject(name="T")
        project.areal = areal

        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        assert not hasattr(taster, "_channels_spin")


class TestChannelsAdjustment:
    def test_increasing_reveals_empty_wish_slots(self, qapp):
        project, be = _make_project_with_taster(channels=2, n_funktionen=2)
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        total_before, empty_before = _grid_slot_count(taster)
        assert (total_before, empty_before) == (2, 0)

        taster._channels_spin.setValue(4)
        qapp.processEvents()

        assert be.channels == 4
        new_taster = _find_taster(view)
        total_after, empty_after = _grid_slot_count(new_taster)
        assert (total_after, empty_after) == (4, 2)

    def test_marks_bedienelement_as_manual(self):
        project, be = _make_project_with_taster(channels=2, n_funktionen=2)
        be.is_auto = True
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        taster._channels_spin.setValue(3)

        assert be.is_auto is False

    def test_cannot_shrink_below_existing_funktionen(self):
        """Untergrenze verhindert, dass eine bereits zugewiesene Funktion durch
        Verkleinern der Tastenzahl stillschweigend aus der Anzeige faellt."""
        project, be = _make_project_with_taster(channels=4, n_funktionen=3)
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        assert taster._channels_spin.minimum() == 3

        taster._channels_spin.setValue(1)  # unterhalb Minimum -> wird geklemmt
        assert taster._channels_spin.value() == 3


def _make_project_with_room(
    gewerk_assignments: list[GewerkAssignment] | None = None,
    scenes: list[Scene] | None = None,
) -> tuple[KnxProject, Room, Bedienelement]:
    room = Room(number="E01", name="Wohnzimmer")
    room.gewerk_assignments = gewerk_assignments or []
    be = Bedienelement(
        element_type="Tastereinheit", channels=3, participant_number="1.1.5",
        funktionen=[],
    )
    room.bedienelemente.append(be)
    apt = Apartment(name="EG", rooms=[room])
    floor = Floor(name="EG", short_code="EG")
    floor.apartments = [apt]
    wing = Wing(name="Haupt", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(name="A", buildings=[building])

    project = KnxProject(name="T")
    project.areal = areal
    for scene in scenes or []:
        project.scenes.append(scene)
    return project, room, be


def _first_empty_slot(taster: _TasterWidget):
    """Erster Slot, dessen Combo noch auf dem Platzhalter steht (kein Wert
    gewaehlt) -- alle Slots sind jetzt Comboboxen, "leer" ist also eine
    Frage der aktuellen Auswahl, nicht mehr des Widget-Typs."""
    grid = taster.findChild(QGridLayout)
    for i in range(grid.count()):
        slot = grid.itemAt(i).widget()
        if slot._combo.currentIndex() == 0:
            return slot
    raise AssertionError("Kein leerer Slot gefunden.")


def _select_by_kind(combo, kind: str):
    for i in range(combo.count()):
        data = combo.itemData(i)
        if data and data[0] == kind:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"Keine Combo-Option vom Typ '{kind}' gefunden.")


class TestGewerkAndSceneSelection:
    def test_combo_lists_room_gewerk_instances(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="J", count=2)],
        )
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        gewerk_items = [
            slot._combo.itemData(i) for i in range(slot._combo.count())
            if slot._combo.itemData(i) and slot._combo.itemData(i)[0] == "gewerk"
        ]
        assert ("gewerk", "J", 1, room.id) in gewerk_items
        assert ("gewerk", "J", 2, room.id) in gewerk_items

        # Anzeige-Text nennt den Raum, damit klar ist welches Gewerk aus
        # welchem Raum ausgewaehlt wird (Ausgangspunkt dieses Fixes).
        texts = [slot._combo.itemText(i) for i in range(slot._combo.count())]
        assert any("E01 Wohnzimmer" in t for t in texts)

    def test_selecting_gewerk_sets_gewerk_code_and_marks_manual(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="J", count=1)],
        )
        be.is_auto = True
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        sf_idx = slot._sf_idx
        _select_by_kind(slot._combo, "gewerk")

        sf = be.funktionen[sf_idx]
        assert sf.gewerk_code == "J"
        assert sf.element_number == 1
        assert be.is_auto is False

    def test_combo_lists_named_scenes_not_detected_ones(self):
        project, room, be = _make_project_with_room(scenes=[
            Scene(name="Kino", scene_number=1, scope="central"),
            Scene(name="Importiert", scene_number=2, scope="central", is_detected=True),
        ])
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        texts = [slot._combo.itemText(i) for i in range(slot._combo.count())]
        assert any(t.startswith("Szene: Kino") for t in texts)
        assert not any("Importiert" in t for t in texts)

    def test_selecting_scene_sets_scene_id_and_ga_designation(self):
        scene = Scene(name="Kino", scene_number=1, scope="central")
        project, room, be = _make_project_with_room(scenes=[scene])
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        sf_idx = slot._sf_idx
        _select_by_kind(slot._combo, "scene")

        sf = be.funktionen[sf_idx]
        assert sf.scene_id == scene.id
        assert sf.ga_designation == "ZENTRAL Szenenaufruf"
        assert sf.bedienart == "Szene abrufen"
        assert sf.label == "Kino"
        assert be.is_auto is False

    def test_generic_wish_fallback_still_available_and_unresolved(self):
        """Freitext-Wuensche ohne passendes Gewerk bleiben moeglich und setzen
        bewusst KEINE gewerk_code/ga_designation (muessen spaeter ueber die
        Verknuepfungsmatrix aufgeloest werden)."""
        project, room, be = _make_project_with_room()
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        sf_idx = slot._sf_idx
        _select_by_kind(slot._combo, "wish")

        sf = be.funktionen[sf_idx]
        assert sf.label
        assert sf.gewerk_code == ""
        assert sf.ga_designation == ""
        assert sf.scene_id == ""
        assert be.is_auto is False

    def test_selecting_placeholder_again_resets_slot(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="J", count=1)],
        )
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        sf_idx = slot._sf_idx
        _select_by_kind(slot._combo, "gewerk")
        assert be.funktionen[sf_idx].gewerk_code == "J"

        slot._combo.setCurrentIndex(0)  # "-- Funktion wählen --"
        sf = be.funktionen[sf_idx]
        assert sf.gewerk_code == ""
        assert sf.label == ""


class TestAllSlotsEditable:
    """Kein Slot ist mehr schreibgeschuetzt -- auch bereits zugewiesene
    Funktionen (automatisch berechnete Gewerk-Zuweisung, bestehende Szene,
    bestehender Freitext-Wunsch) muessen sich direkt umstellen lassen, ohne
    vorher etwas zu loeschen, damit sich waehrend der Beratung schnell auf
    Aenderungswuensche reagieren laesst."""

    def test_existing_gewerk_slot_has_combo_preselected(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[
                GewerkAssignment(gewerk_code="L", count=1),
                GewerkAssignment(gewerk_code="J", count=1),
            ],
        )
        be.funktionen = [SensorFunktion(gewerk_code="L", element_number=1)]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        assert slot0._combo is not None
        assert slot0._combo.currentIndex() != 0
        assert slot0._combo.itemData(slot0._combo.currentIndex()) == (
            "gewerk", "L", 1, room.id
        )

    def test_existing_gewerk_slot_can_be_changed_to_other_gewerk(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[
                GewerkAssignment(gewerk_code="L", count=1),
                GewerkAssignment(gewerk_code="J", count=1),
            ],
        )
        be.funktionen = [SensorFunktion(gewerk_code="L", element_number=1)]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        for i in range(slot0._combo.count()):
            data = slot0._combo.itemData(i)
            if data and data[0] == "gewerk" and data[1] == "J":
                slot0._combo.setCurrentIndex(i)
                break
        else:
            raise AssertionError("Option fuer Gewerk 'J' nicht gefunden.")

        sf = be.funktionen[0]
        assert sf.gewerk_code == "J"

    def test_existing_scene_slot_has_combo_preselected(self):
        scene = Scene(name="Kino", scene_number=1, scope="central")
        project, room, be = _make_project_with_room(scenes=[scene])
        be.funktionen = [SensorFunktion(
            label="Kino", ga_designation="ZENTRAL Szenenaufruf",
            action_type="kurz", bedienart="Szene abrufen", scene_id=scene.id,
        )]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        data = slot0._combo.itemData(slot0._combo.currentIndex())
        assert data[0] == "scene"
        assert data[1] == scene.id

    def test_existing_wish_slot_has_combo_preselected(self):
        project, room, be = _make_project_with_room()
        be.funktionen = [SensorFunktion(label="Licht Ein/Aus")]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        assert slot0._combo.currentText() == "Licht Ein/Aus"

    def test_unmatched_direct_ga_slot_gets_synthetic_entry_not_lost(self):
        """Eine 'Direkte GA'-Zuweisung aus Schritt 8 (kein Gewerk, keine
        Szene) taucht in keiner Option der neuen Combo auf -- darf beim
        Rendern nicht stillschweigend verworfen werden."""
        project, room, be = _make_project_with_room()
        be.funktionen = [SensorFunktion(
            label="Flur Licht E/A", ga_designation="3/0/15 Flur Licht E/A",
            action_type="kurz",
        )]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        assert slot0._combo.currentText() == "Flur Licht E/A"
        data = slot0._combo.itemData(slot0._combo.currentIndex())
        assert data[0] == "current"
        assert data[1]["ga_designation"] == "3/0/15 Flur Licht E/A"

        # Erneutes Auswaehlen desselben synthetischen Eintrags darf nichts aendern.
        slot0._combo.setCurrentIndex(slot0._combo.currentIndex())
        sf = be.funktionen[0]
        assert sf.ga_designation == "3/0/15 Flur Licht E/A"

    def test_cross_room_gewerk_sets_source_room_id(self):
        """Ein Gewerk aus einem ANDEREN Raum auswaehlen muss source_room_id
        auf die fremde Raum-Id setzen (nicht auf die eigene)."""
        room1 = Room(number="E01", name="Wohnzimmer")
        room1.gewerk_assignments = []
        room2 = Room(number="E02", name="Küche")
        room2.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
        be = Bedienelement(
            element_type="Tastereinheit", channels=1, participant_number="1.1.5",
            funktionen=[],
        )
        room1.bedienelemente.append(be)
        apt = Apartment(name="EG", rooms=[room1, room2])
        floor = Floor(name="EG", short_code="EG")
        floor.apartments = [apt]
        wing = Wing(name="Haupt", floors=[floor])
        building = Building(name="Haus", wings=[wing])
        areal = Areal(name="A", buildings=[building])
        project = KnxProject(name="T")
        project.areal = areal

        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        for i in range(slot0._combo.count()):
            data = slot0._combo.itemData(i)
            if data and data[0] == "gewerk" and data[3] == room2.id:
                slot0._combo.setCurrentIndex(i)
                break
        else:
            raise AssertionError("Fremdraum-Gewerk nicht in der Combo gefunden.")

        sf = be.funktionen[0]
        assert sf.gewerk_code == "L"
        assert sf.source_room_id == room2.id
