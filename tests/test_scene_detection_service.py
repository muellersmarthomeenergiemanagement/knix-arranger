"""
Tests fuer SceneDetectionService: automatische Szenen-Erkennung aus
importierten Gruppenadressen (FA-1808).
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.scene_detection_service import detect_scenes


def _project_with_gas(*ga_specs: dict) -> KnxProject:
    """Baut ein KnxProject mit einer flachen HG0-Struktur aus ga_specs.

    Jedes Spec braucht: middle_group, middle_group_name, sub_group,
    designation, datapoint_type (optional), room_number (optional).
    """
    structure = GroupAddressStructure()
    mg_by_key: dict[tuple[int, int], MiddleGroup] = {}
    hg = MainGroup(number=0, name="Zentral")
    structure.main_groups.append(hg)

    for spec in ga_specs:
        mg_num = spec["middle_group"]
        key = (0, mg_num)
        if key not in mg_by_key:
            mg = MiddleGroup(number=mg_num, name=spec.get("middle_group_name", ""))
            mg_by_key[key] = mg
            hg.middle_groups.append(mg)
        mg = mg_by_key[key]
        ga = GroupAddress(
            main_group=0, middle_group=mg_num, sub_group=spec["sub_group"],
            designation=spec["designation"],
            datapoint_type=spec.get("datapoint_type", ""),
            room_number=spec.get("room_number", ""),
        )
        mg.group_addresses.append(ga)

    project = KnxProject(name="Test")
    project.group_addresses = structure
    return project


def _room_project(room_name: str) -> KnxProject:
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    eg = Floor(name="Erdgeschoss", short_code="EG")
    apt = Apartment(name="EG")
    room = Room(number="01", name=room_name)
    apt.rooms.append(room)
    eg.apartments.append(apt)
    wing.floors.append(eg)
    building.wings.append(wing)
    areal.buildings.append(building)
    project = KnxProject(name="Test")
    project.areal = areal
    return project, room


class TestDptRule:
    def test_detects_dpst_17_scene_number(self):
        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 101,
            "designation": "Szene 01", "datapoint_type": "DPST-17-1",
        })
        detected = detect_scenes(project)
        assert len(detected) == 1
        scene = detected[0]
        assert scene.is_detected is True
        assert scene.detection_kind == "dpt"
        assert scene.scene_number == 1
        assert scene.scope == "central"
        assert scene.actions[0].ga_address == "0/4/101"

    def test_dpst_1_17_scene_ab_is_not_a_scene(self):
        """DPT 1.017 'Scene A/B' (Beschattungs-Sperrbit) ist keine echte Szene."""
        project = _project_with_gas({
            "middle_group": 1, "middle_group_name": "Jalousie", "sub_group": 4,
            "designation": "J.EG.06.1_beschattung", "datapoint_type": "DPST-1-17",
        })
        assert detect_scenes(project) == []

    def test_detects_dpst_18_scene_control_even_outside_szenen_folder(self):
        """DPT 17 und 18 sind lt. KNX-Datenpunktliste exklusiv fuer Szenen
        reserviert -- beide werden ordner-unabhaengig vertraut. Nutzt ein
        Integrator DPST-18 fehlerhaft fuer etwas anderes (z.B. eine
        Betriebsart-Wahl), soll das bewusst als Szene sichtbar werden statt
        stillschweigend uebergangen zu werden."""
        project = _project_with_gas({
            "middle_group": 2, "middle_group_name": "Heizung / Lueftung / Klima / Tore",
            "sub_group": 150, "designation": "WP Bediensbetriebsart Heizkreis_wahl",
            "datapoint_type": "DPST-18-1",
        })
        detected = detect_scenes(project)
        assert len(detected) == 1
        assert detected[0].detection_kind == "dpt"

    def test_detects_human_readable_label_from_xlsx_import(self):
        """xlsx_import_service uebernimmt die DPT-Spalte des ETS-Reports
        woertlich (menschenlesbares Label statt Rohcode DPST-x-y) --
        Regel 1 muss auch diese Form erkennen."""
        project = _project_with_gas(
            {"middle_group": 4, "middle_group_name": "Szenen", "sub_group": 101,
             "designation": "Szene 01", "datapoint_type": "Szenen Nummer"},
            {"middle_group": 2, "middle_group_name": "Heizung / Lueftung / Klima / Tore",
             "sub_group": 150, "designation": "WP Bediensbetriebsart Heizkreis_wahl",
             "datapoint_type": "Szeneninformation"},
        )
        detected = detect_scenes(project)
        assert len(detected) == 2
        assert {s.detection_kind for s in detected} == {"dpt"}

    def test_human_readable_scene_ab_label_is_not_a_scene(self):
        """'Szene A/B' (DPT 1.017 als Label) darf trotz Wortstamm 'Szene'
        nicht ueber die 'szenen'-Praefix-Heuristik durchrutschen."""
        project = _project_with_gas({
            "middle_group": 1, "middle_group_name": "Jalousie", "sub_group": 4,
            "designation": "J.EG.06.1_beschattung", "datapoint_type": "Szene A/B",
        })
        assert detect_scenes(project) == []


class TestFolderRule:
    def test_detects_generic_dpt_inside_szenen_folder(self):
        """'Szenen Speichern abrufen' hat KEINEN DPT 17/18, liegt aber im
        'Szenen'-Ordner und traegt selbst 'Szene' im Namen."""
        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 0,
            "designation": "Szenen Speichern abrufen   Chalet",
            "datapoint_type": "DPST-5-10",
        })
        detected = detect_scenes(project)
        assert len(detected) == 1
        assert detected[0].detection_kind == "folder"

    def test_ignores_non_scene_ga_in_szenen_folder(self):
        """Andere Zentral-GAs im 'Szenen'-Ordner (z.B. Anwesenheit) sind keine Szenen."""
        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 1,
            "designation": "Anwesendheit   Chalet", "datapoint_type": "DPST-5-1",
        })
        assert detect_scenes(project) == []

    # Der Fall "Szeneninformation ausserhalb des Szenen-Ordners" wird jetzt
    # bewusst ordner-unabhaengig ueber Regel 1 (DPT) erkannt, siehe
    # TestDptRule.test_detects_dpst_18_scene_control_even_outside_szenen_folder.


class TestPatternRule:
    def test_clusters_trigger_and_led_into_one_scene(self):
        project, room = _room_project("Carnozet")
        project.group_addresses = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=4, name="Tasterfunktion")
        hg.middle_groups.append(mg)
        project.group_addresses.main_groups.append(hg)
        mg.group_addresses.extend([
            GroupAddress(main_group=2, middle_group=4, sub_group=0,
                         designation="Raum1_Szene High   ( Carnozet )",
                         datapoint_type="DPST-1-1", room_number="Carnozet"),
            GroupAddress(main_group=2, middle_group=4, sub_group=4,
                         designation="Raum1_Szene High LED",
                         datapoint_type="DPST-1-1"),
            GroupAddress(main_group=2, middle_group=4, sub_group=1,
                         designation="Raum1_Szene Middle",
                         datapoint_type="DPST-1-1"),
        ])

        detected = detect_scenes(project)
        by_name = {s.name: s for s in detected}

        assert "High (Carnozet)" in by_name
        high = by_name["High (Carnozet)"]
        assert high.detection_kind == "pattern"
        assert high.scope == "room"
        assert high.scope_id == room.id
        assert len(high.actions) == 2  # Trigger + LED
        assert high.actions[0].ga_address == "2/4/0"
        assert high.actions[1].ga_address == "2/4/4"

        assert "Middle (Carnozet)" in by_name
        middle = by_name["Middle (Carnozet)"]
        assert len(middle.actions) == 1
        assert middle.scope_id == room.id

    def test_ignores_shared_dimm_step_ga(self):
        """'RaumN_Szene Dimm' ist ein stufenloser Dimm-Schritt-Befehl,
        kein abrufbares Preset -- darf keine Pseudo-Szene erzeugen."""
        project, _room = _room_project("Carnozet")
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=4, name="Tasterfunktion")
        hg.middle_groups.append(mg)
        project.group_addresses.main_groups.append(hg)
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=4, sub_group=8,
            designation="Raum1_Szene Dimm", datapoint_type="DPST-3-7",
        ))

        assert detect_scenes(project) == []


class TestGeneratedGaGuard:
    """address_generator erzeugt pro Geltungsbereich EINE gemeinsame
    Szenenaufruf-GA fuer alle manuellen Scenes dieses Bereichs, ohne
    Rueckverknuepfung -- die Erkennung darf daraus keine doppelte Szene
    machen (siehe scene_addressing.group_named_scenes)."""

    def test_does_not_duplicate_shared_central_scene_channel(self):
        from knix_arranger.models.scene import Scene as SceneModel

        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 2,
            "designation": "ZENTRAL Szenenaufruf", "datapoint_type": "DPST-17-1",
        })
        # Zwei Szenen im selben (zentralen) Geltungsbereich teilen sich lt.
        # address_generator dieselbe GA -- beide muessen die GA sperren.
        project.scenes.append(SceneModel(name="Kino", scene_number=5, scope="central"))
        project.scenes.append(SceneModel(name="Lesen", scene_number=6, scope="central"))

        assert detect_scenes(project) == []

    def test_still_detects_unrelated_scene_ga_in_same_folder(self):
        from knix_arranger.models.scene import Scene as SceneModel

        project = _project_with_gas(
            {"middle_group": 4, "middle_group_name": "Szenen", "sub_group": 2,
             "designation": "ZENTRAL Szenenaufruf", "datapoint_type": "DPST-17-1"},
            {"middle_group": 4, "middle_group_name": "Szenen", "sub_group": 1,
             "designation": "ZENTRAL Szene Abwesenheit", "datapoint_type": "DPST-17-1"},
        )
        project.scenes.append(SceneModel(name="Kino", scene_number=5, scope="central"))

        detected = detect_scenes(project)
        assert len(detected) == 1
        assert detected[0].name == "ZENTRAL Szene Abwesenheit"

    def test_room_scoped_scenes_get_their_own_reserved_channel(self):
        """Ein raumbezogener Kanal ('Szenenaufruf <Raum>') darf eine
        zentrale Szene mit demselben Namen nicht faelschlich sperren."""
        from knix_arranger.models.scene import Scene as SceneModel

        project, room = _room_project("Carnozet")
        project.scenes.append(SceneModel(
            name="Kino", scene_number=1, scope="room", scope_id=room.id,
        ))
        hg = MainGroup(number=0, name="Zentral")
        mg = MiddleGroup(number=4, name="Szenen")
        hg.middle_groups.append(mg)
        project.group_addresses.main_groups.append(hg)
        mg.group_addresses.append(GroupAddress(
            main_group=0, middle_group=4, sub_group=2,
            designation="Szenenaufruf Carnozet", datapoint_type="DPST-17-1",
        ))

        assert detect_scenes(project) == []


class TestIdempotency:
    def test_second_run_returns_nothing_new(self):
        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 101,
            "designation": "Szene 01", "datapoint_type": "DPST-17-1",
        })
        first = detect_scenes(project)
        assert len(first) == 1
        project.scenes.extend(first)

        second = detect_scenes(project)
        assert second == []

    def test_survives_ga_reimport_with_new_ids(self):
        """GroupAddress.id ist eine bei jedem Import neu vergebene UUID
        (nicht stabil ueber Re-Importe) -- die Dedup-/Verknuepfungslogik
        muss auf der Adresse ("0/4/101") basieren, nicht auf .id, sonst
        gilt eine bereits erkannte Szene nach einem Re-Import faelschlich
        wieder als 'neu' (Duplikat) und Scene.source_ga_addresses zeigt
        ins Leere (siehe scene_value_linking.py)."""
        project = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 101,
            "designation": "Szene 01", "datapoint_type": "DPST-17-1",
        })
        first = detect_scenes(project)
        project.scenes.extend(first)
        assert project.scenes[0].source_ga_addresses == ["0/4/101"]

        # Re-Import: komplett neue GroupAddress-Objekte mit neuen UUIDs,
        # aber derselben Adresse -- wie es ein echter Re-Import tut.
        project.group_addresses = _project_with_gas({
            "middle_group": 4, "middle_group_name": "Szenen", "sub_group": 101,
            "designation": "Szene 01", "datapoint_type": "DPST-17-1",
        }).group_addresses

        second = detect_scenes(project)
        assert second == [], "Re-Import darf keine Duplikat-Szene erzeugen"
