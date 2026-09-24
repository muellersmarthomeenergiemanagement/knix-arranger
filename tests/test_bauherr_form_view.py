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
from PySide6.QtWidgets import QApplication, QGridLayout, QDialog

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


def _tagged_ga_structure(room: Room):
    """Eine GroupAddressStructure mit genau einer function_name-getaggten GA
    -- simuliert ein wizard-generiertes Projekt (Schritt 7 gelaufen). Ohne
    ein solches Tag kann SensorService._expand_funktionen eine
    gewerk_code-basierte SensorFunktion NIE zu einer GA aufloesen (siehe
    TestGewerkPickWithoutTaggedAddresses fuer den Gegenfall: rein
    importiertes Projekt ohne Schritt-7-Adressen)."""
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
    )
    gas = GroupAddressStructure()
    hg = MainGroup(number=1, name="Test")
    mg = MiddleGroup(number=0, name="Test")
    hg.middle_groups.append(mg)
    gas.main_groups.append(hg)
    mg.group_addresses.append(GroupAddress(
        main_group=1, middle_group=0, sub_group=1,
        designation="Test-Tag", gewerk_code="L", function_name="E/A",
        room_id=room.id,
    ))
    return gas


def _make_project_with_room(
    gewerk_assignments: list[GewerkAssignment] | None = None,
    scenes: list[Scene] | None = None,
    tagged_gas: bool = True,
) -> tuple[KnxProject, Room, Bedienelement]:
    """tagged_gas=True (Standard) simuliert ein wizard-generiertes Projekt
    (Schritt 7 gelaufen, GAs tragen function_name) -- so wie es die
    urspruengliche Gewerk-Quick-Pick-Funktion voraussetzt. tagged_gas=False
    simuliert ein rein importiertes Projekt ohne Schritt-7-Adressen (siehe
    TestGewerkPickWithoutTaggedAddresses)."""
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

    if tagged_gas:
        project.group_addresses = _tagged_ga_structure(room)

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
        _select_by_kind(slot._combo, "gewerk")

        sf = slot._sf
        assert sf.gewerk_code == "J"
        assert sf.element_number == 1
        assert be.is_auto is False

    def test_combo_lists_named_and_detected_numbered_scenes_not_channels(self):
        """Erkannte Szenen mit Nummer (z.B. "Komponieren" aus dem Import) sind
        aufrufbar; erkannte Szenenaufruf-Kanaele ohne Nummer (Nr. 0) nicht."""
        project, room, be = _make_project_with_room(scenes=[
            Scene(name="Kino", scene_number=1, scope="central"),
            Scene(name="Importiert", scene_number=2, scope="central", is_detected=True),
            Scene(name="ZENTRAL Szenenaufruf", scene_number=0, scope="central",
                  is_detected=True),
        ])
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        texts = [slot._combo.itemText(i) for i in range(slot._combo.count())]
        assert any(t.startswith("Szene: Kino") for t in texts)
        assert any(t.startswith("Szene: Importiert") for t in texts)
        assert not any(t.startswith("Szene: ZENTRAL Szenenaufruf") for t in texts)

    def test_detected_scene_uses_its_imported_ga(self):
        from knix_arranger.models.group_address import GroupAddress
        scene = Scene(name="Komponieren", scene_number=1, scope="central",
                      is_detected=True, source_ga_addresses=["1/0/15"])
        project, room, be = _make_project_with_room(scenes=[scene])
        project.group_addresses.main_groups[0].middle_groups[0].group_addresses.append(
            GroupAddress(main_group=1, middle_group=0, sub_group=15,
                         designation="LDA_M01_01 SZENE", gewerk_code="LDA",
                         function_name="SZENE")
        )
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        _select_by_kind(slot._combo, "scene")

        assert slot._sf.scene_id == scene.id
        assert slot._sf.ga_designation == "LDA_M01_01 SZENE"

    def test_selecting_scene_sets_scene_id_and_ga_designation(self):
        scene = Scene(name="Kino", scene_number=1, scope="central")
        project, room, be = _make_project_with_room(scenes=[scene])
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        _select_by_kind(slot._combo, "scene")

        sf = slot._sf
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
        _select_by_kind(slot._combo, "wish")

        sf = slot._sf
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
        _select_by_kind(slot._combo, "gewerk")
        assert slot._sf.gewerk_code == "J"

        slot._combo.setCurrentIndex(0)  # "-- Funktion wählen --"
        sf = slot._sf
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
        project.group_addresses = _tagged_ga_structure(room2)

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


# ---------------------------------------------------------------------------
# Fremdsteuerung-Funktionen (FA-1410d, role="fremdsteuerung") sind keine
# bedienbare physische Taste (z.B. LED-Nachtabsenkung) -- duerfen im Bauherr-
# Raster nicht als eigener, editierbarer Taster-Slot auftauchen.
# ---------------------------------------------------------------------------

class TestFremdsteuerungExcludedFromSlots:
    def test_fremdsteuerung_funktion_not_shown_as_slot(self):
        project, room, be = _make_project_with_room()
        be.channels = 1
        be.funktionen = [
            SensorFunktion(gewerk_code="L", element_number=1, primary_role="befehl"),
            SensorFunktion(label="Nachtabsenkung LED's", ga_designation="0/4/1 Nacht",
                            primary_role="fremdsteuerung"),
        ]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        assert grid.count() == 1  # nur die echte Taste, nicht die Fremdsteuerung

    def test_fremdsteuerung_not_counted_for_channels_minimum(self):
        project, room, be = _make_project_with_room()
        be.funktionen = [
            SensorFunktion(gewerk_code="L", element_number=1, primary_role="befehl"),
            SensorFunktion(label="Nachtabsenkung LED's", ga_designation="0/4/1 Nacht",
                            primary_role="fremdsteuerung"),
        ]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        assert taster._channels_spin.minimum() == 1  # nur 1 echte Funktion, nicht 2


# ---------------------------------------------------------------------------
# Echtes Loeschen einzelner Tasten (statt der Kanalzahl-Verkleinerung, die
# eine zugewiesene Funktion nie tatsaechlich entfernt hat).
# ---------------------------------------------------------------------------

class TestSlotDeletion:
    def test_delete_button_hidden_for_empty_slot(self):
        project, room, be = _make_project_with_room()
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        assert slot._btn_delete.isHidden() is True

    def test_delete_removes_sensorfunktion_from_be(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)],
        )
        be.channels = 1
        be.funktionen = [SensorFunktion(gewerk_code="L", element_number=1)]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        target_sf = slot0._sf
        assert target_sf in be.funktionen

        slot0._on_delete()

        assert target_sf not in be.funktionen

    def test_delete_marks_manual_and_triggers_rebuild(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)],
        )
        be.is_auto = True
        be.channels = 1
        be.funktionen = [SensorFunktion(gewerk_code="L", element_number=1)]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        slot0._on_delete()

        assert be.is_auto is False
        assert be.funktionen == []
        # Raster wurde neu aufgebaut (structure_changed -> _load_room) --
        # der einzige Slot ist jetzt wieder ein leerer Platzhalter.
        new_taster = _find_taster(view)
        new_slot0 = new_taster.findChild(QGridLayout).itemAt(0).widget()
        assert new_slot0._sf is None


# ---------------------------------------------------------------------------
# Gewerk-Label nennt jetzt ALLE Funktionen der Instanz (z.B. Schalten UND
# Dimmen bei "LD"), nicht mehr nur die erste -- eine Gewerk-Auswahl deckt sie
# ohnehin automatisch alle ab (siehe SensorService.GEWERK_PRIMARY_FUNCTIONS /
# _expand_funktionen), das war vorher nur in der Anzeige nicht ersichtlich.
# ---------------------------------------------------------------------------

class TestGewerkLabelShowsAllFunctions:
    def test_dimmable_gewerk_label_mentions_both_functions(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="LD", count=1)],
        )
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        texts = [slot._combo.itemText(i) for i in range(slot._combo.count())]
        match = next(t for t in texts if t.startswith("LD"))
        assert "Licht schalten" in match
        assert "Licht dimmen" in match


# ---------------------------------------------------------------------------
# Gruppierte Combo-Abschnitte (Kopfzeilen) statt einer einzigen flachen
# Liste aus Gewerken, Szenen und Freitext-Wuenschen.
# ---------------------------------------------------------------------------

class TestComboSectionHeaders:
    def test_headers_present_and_not_selectable(self):
        scene = Scene(name="Kino", scene_number=1, scope="central")
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)],
            scenes=[scene],
        )
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        combo = slot._combo
        header_texts = [
            combo.itemText(i) for i in range(combo.count())
            if combo.itemData(i) == ("header",)
        ]
        assert any("Gewerke in" in t for t in header_texts)
        assert any("Szenen" in t for t in header_texts)
        assert any("Freitext" in t for t in header_texts)
        for i in range(combo.count()):
            if combo.itemData(i) == ("header",):
                item = combo.model().item(i)
                assert item.isEnabled() is False


# ---------------------------------------------------------------------------
# Mehrere GAs an derselben Taste fuer importierte "Direkte GA"-Zuweisungen
# (FA-1410d, extra_gas) -- z.B. Schalten- UND Dimmen-GA auf demselben Taster,
# wenn kein Gewerk bekannt ist (sonst deckt die Gewerk-Auswahl das schon
# automatisch ab, siehe TestGewerkLabelShowsAllFunctions).
# ---------------------------------------------------------------------------

class TestExtraGasOnDirectGaSlot:
    def _direct_ga_project(self):
        project, room, be = _make_project_with_room()
        be.channels = 1
        be.funktionen = [SensorFunktion(
            label="Aussenleuchte", ga_designation="2/0/75 Aussenleuchte E/A",
        )]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)
        return view, be

    def test_add_ga_button_visible_only_for_direct_ga_slot(self):
        view, be = self._direct_ga_project()
        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        assert slot0._btn_add_ga.isHidden() is False

    def test_add_ga_button_hidden_for_gewerk_slot(self):
        project, room, be = _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)],
        )
        be.funktionen = [SensorFunktion(gewerk_code="L", element_number=1)]
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        slot0 = grid.itemAt(0).widget()
        assert slot0._btn_add_ga.isHidden() is True

    def test_add_ga_appends_extra_ga_via_picker_dialog(self, monkeypatch):
        from knix_arranger.models.group_address import GroupAddress
        import knix_arranger.ui.views.bauherr_form_view as mod

        view, be = self._direct_ga_project()
        taster = _find_taster(view)
        slot0 = taster.findChild(QGridLayout).itemAt(0).widget()

        picked = GroupAddress(main_group=2, middle_group=0, sub_group=76,
                               designation="Aussenleuchte DIM")

        class _FakeDialog:
            Accepted = QDialog.Accepted
            def __init__(self, *a, **kw):
                self.selected_ga = picked
            def exec(self):
                return QDialog.Accepted

        monkeypatch.setattr(mod, "GaPickerDialog", _FakeDialog)
        slot0._on_add_ga()

        assert len(slot0._sf.extra_gas) == 1
        # Adresse UND Bezeichnung (nicht nur der Text) -- sonst fehlt die
        # eigentliche Gruppenadressnummer in Gebäude-Ansicht/Schritt 9.
        assert slot0._sf.extra_gas[0].ga_designation == "2/0/76  Aussenleuchte DIM"
        assert slot0._sf.extra_gas[0].description == picked.designation
        assert slot0._sf.extra_gas[0].role == "befehl"
        assert be.is_auto is False

    def test_remove_extra_ga(self):
        from knix_arranger.models.building import SensorFunktionGa
        view, be = self._direct_ga_project()
        taster = _find_taster(view)
        slot0 = taster.findChild(QGridLayout).itemAt(0).widget()
        extra = SensorFunktionGa(ga_designation="2/0/76 DIM", role="befehl")
        slot0._sf.extra_gas.append(extra)
        slot0._rebuild_extra_row()

        slot0._on_remove_extra(extra)

        assert slot0._sf.extra_gas == []

    def test_switching_combo_selection_clears_extra_gas(self):
        from knix_arranger.models.building import SensorFunktionGa
        view, be = self._direct_ga_project()
        taster = _find_taster(view)
        slot0 = taster.findChild(QGridLayout).itemAt(0).widget()
        slot0._sf.extra_gas.append(SensorFunktionGa(ga_designation="2/0/76 DIM", role="befehl"))

        # Slot auf einen Freitext-Wunsch umstellen -- die alte(n) Extra-GA(s)
        # gehoerten zum vorherigen Ziel und muessen verworfen werden.
        _select_by_kind(slot0._combo, "wish")

        assert slot0._sf.extra_gas == []


# ---------------------------------------------------------------------------
# Regression: ein rein importiertes Projekt (kein Schritt-7-Lauf, also keine
# GA mit gesetztem function_name) konnte eine Gewerk-Auswahl im Bauherr-
# Formular NIE zu einer echten GA aufloesen (SensorService._expand_funktionen
# braucht function_name fuer den Lookup) -- die SensorFunktion bekam
# gewerk_code gesetzt, aber nie eine GA, und verlor beim naechsten Refresh
# (Topologie/Matrix oeffnen) kommentarlos die Verknuepfung. Eine
# Gewerk-Auswahl muss in diesem Fall sofort ueber den GA-Picker eine echte
# GA festlegen statt sich auf die spaeter scheiternde Lazy-Ableitung zu
# verlassen.
# ---------------------------------------------------------------------------

class TestGewerkPickWithoutTaggedAddresses:
    def _project(self):
        return _make_project_with_room(
            gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)],
            tagged_gas=False,
        )

    def test_gewerk_lookup_available_false_without_tags(self):
        project, room, be = self._project()
        from knix_arranger.services.bauherr_form_service import BauherrFormService
        assert BauherrFormService(project).gewerk_lookup_available() is False

    def test_gewerk_lookup_available_true_with_tags(self):
        project, room, be = _make_project_with_room(tagged_gas=True)
        from knix_arranger.services.bauherr_form_service import BauherrFormService
        assert BauherrFormService(project).gewerk_lookup_available() is True

    def test_picking_gewerk_opens_picker_and_sets_real_ga(self, monkeypatch):
        import knix_arranger.ui.views.bauherr_form_view as mod
        from knix_arranger.models.group_address import GroupAddress

        project, room, be = self._project()
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        picked = GroupAddress(main_group=1, middle_group=0, sub_group=5,
                               designation="Echte GA")

        class _FakeDialog:
            Accepted = QDialog.Accepted
            def __init__(self, *a, **kw):
                self.selected_ga = picked
            def exec(self):
                return QDialog.Accepted

        monkeypatch.setattr(mod, "GaPickerDialog", _FakeDialog)
        _select_by_kind(slot._combo, "gewerk")

        sf = slot._sf
        assert sf.gewerk_code == "L"
        # Adresse UND Bezeichnung (nicht nur der Text) -- sonst fehlt die
        # eigentliche Gruppenadressnummer in Gebäude-Ansicht/Schritt 9
        # (Regression: nur "Echte GA" statt "1/0/5  Echte GA").
        assert sf.ga_designation == "1/0/5  Echte GA"
        assert be.is_auto is False

        # Regression: "+GA" pruefte urspruenglich "not sf.gewerk_code" --
        # dieser Picker-Fallback setzt aber BEIDES (gewerk_code nur zur
        # Beschriftung, ga_designation ist das eigentlich massgebliche Feld
        # fuer SensorService._expand_funktionen). Ohne den Fix war "+GA" nach
        # so einer Auswahl unsichtbar -- eine zweite GA (z.B. Dimmen) liess
        # sich dann nicht mehr hinzufuegen.
        slot._rebuild_extra_row()
        assert slot._btn_add_ga.isHidden() is False

    def test_cancelling_picker_reverts_selection_without_data_loss(self, monkeypatch):
        import knix_arranger.ui.views.bauherr_form_view as mod

        project, room, be = self._project()
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        slot = _first_empty_slot(_find_taster(view))
        prev_index = slot._combo.currentIndex()

        class _FakeDialog:
            Accepted = QDialog.Accepted
            Rejected = QDialog.Rejected
            def __init__(self, *a, **kw):
                self.selected_ga = None
            def exec(self):
                return QDialog.Rejected

        monkeypatch.setattr(mod, "GaPickerDialog", _FakeDialog)
        _select_by_kind(slot._combo, "gewerk")

        assert slot._combo.currentIndex() == prev_index
        assert slot._sf is None


# ---------------------------------------------------------------------------
# Physische Grid-Position (FA-1502c): importierte Tasten mit Label "Taste N,
# links/rechts" landen an ihrer echten Wand-Position statt an ihrer
# Listenposition; Tasten ohne diese Konvention (wizard-geplant, neu
# hinzugefuegt) fuellen die verbleibenden Zellen sequenziell auf.
# ---------------------------------------------------------------------------

from knix_arranger.ui.views.bauherr_form_view import (
    _parse_taste_position, _assign_grid_positions,
)


class TestParseTastePosition:
    def test_parses_row_and_side(self):
        assert _parse_taste_position("Taste 1, links") == (0, 0)
        assert _parse_taste_position("Taste 1, rechts") == (0, 1)
        assert _parse_taste_position("Taste 3, links") == (2, 0)

    def test_case_insensitive_and_whitespace_tolerant(self):
        assert _parse_taste_position("taste  2 , RECHTS") == (1, 1)

    def test_non_matching_labels_return_none(self):
        assert _parse_taste_position("") is None
        assert _parse_taste_position("Licht Wohnzimmer") is None
        assert _parse_taste_position("Kanal A") is None
        assert _parse_taste_position("Taste 1") is None  # keine Seite


class TestAssignGridPositions:
    def test_positioned_labels_keep_their_real_cell(self):
        sf_1l = SensorFunktion(label="Taste 1, links")
        sf_1r = SensorFunktion(label="Taste 1, rechts")
        sf_2l = SensorFunktion(label="Taste 2, links")
        sf_2r = SensorFunktion(label="Taste 2, rechts")
        cells = _assign_grid_positions([sf_1l, sf_1r, sf_2l, sf_2r], n_slots=4)
        assert cells == {(0, 0): sf_1l, (0, 1): sf_1r, (1, 0): sf_2l, (1, 1): sf_2r}

    def test_unpositioned_entries_fill_remaining_cells_row_major(self):
        sf_positioned = SensorFunktion(label="Taste 1, rechts")  # nur (0,1) belegt
        sf_other = SensorFunktion(gewerk_code="L")  # kein Positions-Label
        cells = _assign_grid_positions([sf_positioned, sf_other], n_slots=3)
        # (0,0) ist frei -> sf_other landet dort; der 3. (Platzhalter-)Slot
        # landet in Zeile 1.
        assert cells[(0, 1)] is sf_positioned
        assert cells[(0, 0)] is sf_other
        assert cells[(1, 0)] is None

    def test_empty_placeholder_slots_beyond_funktionen_count(self):
        cells = _assign_grid_positions([], n_slots=2)
        assert cells == {(0, 0): None, (0, 1): None}


class TestGridPositionInTasterWidget:
    def _project_with_positioned_taster(self):
        room = Room(number="E01", name="Wohnzimmer")
        be = Bedienelement(
            element_type="Tastereinheit", channels=4, participant_number="1.1.5",
            funktionen=[
                SensorFunktion(label="Taste 1, links", ga_designation="1/0/0 A"),
                SensorFunktion(label="Taste 1, rechts", ga_designation="1/0/1 B"),
                SensorFunktion(label="Taste 2, links", ga_designation="1/0/2 C"),
                SensorFunktion(label="Taste 2, rechts", ga_designation="1/0/3 D"),
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

    def _label_of(self, slot) -> str:
        return slot.layout().itemAt(0).layout().itemAt(0).widget().text()

    def test_slots_rendered_at_their_physical_grid_position(self):
        from PySide6.QtWidgets import QGridLayout

        project, be = self._project_with_positioned_taster()
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        grid = taster.findChild(QGridLayout)
        by_pos = {}
        for i in range(grid.count()):
            row, col, *_ = grid.getItemPosition(i)
            slot = grid.itemAt(i).widget()
            by_pos[(row, col)] = (self._label_of(slot), slot._combo.currentText())

        assert by_pos[(0, 0)] == ("1 links", "Taste 1, links")
        assert by_pos[(0, 1)] == ("1 rechts", "Taste 1, rechts")
        assert by_pos[(1, 0)] == ("2 links", "Taste 2, links")
        assert by_pos[(1, 1)] == ("2 rechts", "Taste 2, rechts")

    def test_unpositioned_taste_falls_back_to_sequential_label(self):
        project, be = _make_project_with_taster(channels=2, n_funktionen=2)
        view = BauherrFormView()
        view.set_project(project)
        view._room_list.setCurrentRow(0)

        taster = _find_taster(view)
        from PySide6.QtWidgets import QGridLayout
        grid = taster.findChild(QGridLayout)
        seq_labels = sorted(
            self._label_of(grid.itemAt(i).widget()) for i in range(grid.count())
        )
        assert seq_labels == ["T1", "T2"]
