"""
Tests fuer SceneValueLinkingService: Verknuepfung erkannter Szenen mit
echten Aktor-Schaltwerten aus Geräteparametern (FA-1809).
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.topology import (
    Topology, Area, Line, Device, CommunicationObject, SceneValueEntry,
)
from knix_arranger.models.scene import Scene
from knix_arranger.models.topology import SceneTriggerEntry
from knix_arranger.services.scene_value_linking import link_scene_values, link_scene_triggers


def _project_with_channel_scene(recall_ga_designation="Anwesendheit   Chalet",
                                 recall_ga_address=("0", "4", "1")):
    """Baut ein Projekt mit einer zentralen, ungezielten 'Kanal'-Szene
    (scene_number=0, wie sie die Erkennung fuer einen Multi-Szenen-Kanal
    anlegt) plus der zugehoerigen Gruppenadresse."""
    m, mi, s = recall_ga_address
    structure = GroupAddressStructure()
    hg = MainGroup(number=int(m), name="Zentral")
    mg = MiddleGroup(number=int(mi), name="Szenen")
    recall_ga = GroupAddress(
        main_group=int(m), middle_group=int(mi), sub_group=int(s),
        designation=recall_ga_designation, datapoint_type="DPST-18-1",
    )
    mg.group_addresses.append(recall_ga)
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)

    project = KnxProject(name="Test")
    project.group_addresses = structure

    channel_scene = Scene(
        name=recall_ga_designation, scene_number=0, scope="central",
        is_detected=True, detection_kind="dpt",
        source_ga_addresses=[recall_ga.address],
    )
    project.scenes.append(channel_scene)
    return project, recall_ga, channel_scene


def _add_output_ga(project, designation, main=0, middle=2, sub=55):
    ga = GroupAddress(main_group=main, middle_group=middle, sub_group=sub,
                       designation=designation)
    hg = next((h for h in project.group_addresses.main_groups if h.number == main), None)
    if hg is None:
        hg = MainGroup(number=main, name="Test")
        project.group_addresses.main_groups.append(hg)
    mg = next((m for m in hg.middle_groups if m.number == middle), None)
    if mg is None:
        mg = MiddleGroup(number=middle, name="Test")
        hg.middle_groups.append(mg)
    mg.group_addresses.append(ga)
    return ga


def _add_abb_style_device(project, phys_addr, recall_ga_address: str,
                           output_ga_address: str, scene_values: list):
    device = Device(physical_address=phys_addr, manufacturer="ABB")
    device.communication_objects = [
        CommunicationObject(
            object_number=1, name="Ausgang A", object_function="Schalten",
            connected_gas=[output_ga_address],
        ),
        CommunicationObject(
            object_number=2, name="Ausgang A", object_function="8-Bit-Szene",
            connected_gas=[recall_ga_address],
        ),
        CommunicationObject(
            object_number=3, name="Ausgang A",
            object_function="Telegr. Status Schalten",
            connected_gas=[output_ga_address],
        ),
    ]
    device.scene_values = scene_values

    topology = Topology()
    area = Area(area_number=1)
    line = Line(line_number=1)
    line.devices.append(device)
    area.lines.append(line)
    topology.areas.append(area)
    project.topology = topology
    return device


def _add_feller_style_device(project, phys_addr, recall_ga_address: str,
                              scene_triggers: list, installation_location=""):
    """Fuegt einen Feller-artigen Taster hinzu -- ergaenzt eine bestehende
    Topologie (z.B. aus _add_abb_style_device), statt sie zu ersetzen, damit
    Sensor und Aktor im selben Test kombiniert werden koennen."""
    device = Device(
        physical_address=phys_addr, manufacturer="Feller",
        installation_location=installation_location,
    )
    device.communication_objects = [
        CommunicationObject(
            object_number=i, name=entry.button, object_function="senden, Wert",
            data_type="Szenen Nummer", connected_gas=[recall_ga_address],
        )
        for i, entry in enumerate(scene_triggers)
    ]
    device.scene_triggers = scene_triggers

    if not project.topology.areas:
        area = Area(area_number=1)
        area.lines.append(Line(line_number=1))
        project.topology.areas.append(area)
    project.topology.areas[0].lines[0].devices.append(device)
    return device


class TestLinkSceneValues:
    def test_splits_shared_channel_into_numbered_scenes(self):
        project, recall_ga, channel_scene = _project_with_channel_scene()
        output_ga = _add_output_ga(project, "HS.OG.05.01_ea   ( Kochherd )")
        _add_abb_style_device(
            project, "1.1.10", recall_ga.address, output_ga.address,
            scene_values=[
                SceneValueEntry(channel="A", scene_number=2, value="AUS"),
                SceneValueEntry(channel="A", scene_number=3, value="AUS"),
            ],
        )

        added = link_scene_values(project)

        assert added == 2
        numbered = {s.scene_number: s for s in project.scenes if s.scene_number > 0}
        assert set(numbered) == {2, 3}
        for n in (2, 3):
            scene = numbered[n]
            assert scene.is_detected is True
            assert len(scene.actions) == 1
            assert scene.actions[0].group_address == "HS.OG.05.01_ea   ( Kochherd )"
            assert scene.actions[0].value == "AUS"
            assert scene.actions[0].ga_address == output_ga.address
        # Die urspruengliche Kanal-Szene (Nr. 0) bleibt unangetastet
        assert channel_scene.actions == []

    def test_already_numbered_scene_gets_actions_directly(self):
        """Wurde die Szene bereits mit einer konkreten Nummer erkannt
        (z.B. 'Szene 01' als eigene GA), werden Aktionen direkt an sie
        angehaengt -- keine zusaetzliche Szene wird erzeugt."""
        project, recall_ga, channel_scene = _project_with_channel_scene(
            recall_ga_designation="Szene 02",
        )
        channel_scene.scene_number = 2
        output_ga = _add_output_ga(project, "L.UG.01.1_ea  ( Technikraum )")
        _add_abb_style_device(
            project, "1.1.10", recall_ga.address, output_ga.address,
            scene_values=[SceneValueEntry(channel="A", scene_number=2, value="AUS")],
        )

        added = link_scene_values(project)

        assert added == 1
        assert len(project.scenes) == 1
        assert channel_scene.actions[0].value == "AUS"

    def test_idempotent_on_repeated_call(self):
        project, recall_ga, channel_scene = _project_with_channel_scene()
        output_ga = _add_output_ga(project, "HS.OG.05.01_ea   ( Kochherd )")
        _add_abb_style_device(
            project, "1.1.10", recall_ga.address, output_ga.address,
            scene_values=[SceneValueEntry(channel="A", scene_number=2, value="AUS")],
        )

        first = link_scene_values(project)
        second = link_scene_values(project)

        assert first == 1
        assert second == 0
        assert len([s for s in project.scenes if s.scene_number == 2]) == 1

    def test_survives_ga_reimport_with_new_ids(self):
        """GroupAddress.id wird bei jedem Import neu vergeben (Zufalls-UUID,
        nicht stabil ueber Re-Importe). Ein Re-Import ersetzt
        project.group_addresses komplett durch neue GroupAddress-Objekte
        mit derselben Adresse, aber anderer .id -- die Verknuepfung muss
        trotzdem funktionieren, weil sie auf der Adresse basiert."""
        project, recall_ga, channel_scene = _project_with_channel_scene()
        output_ga = _add_output_ga(project, "HS.OG.05.01_ea   ( Kochherd )")
        _add_abb_style_device(
            project, "1.1.10", recall_ga.address, output_ga.address,
            scene_values=[SceneValueEntry(channel="A", scene_number=2, value="AUS")],
        )

        # Re-Import: komplett neue GroupAddressStructure mit neuen UUIDs,
        # gleichen Adressen -- wie main_window._import_xlsx es real tut.
        reimported_project, _new_recall_ga, _ = _project_with_channel_scene()
        assert reimported_project.group_addresses.all_addresses()[0].id != recall_ga.id
        project.group_addresses = reimported_project.group_addresses
        # Auch die Ausgangs-GA neu importieren (neue id, gleiche Adresse)
        new_output_ga = _add_output_ga(
            project, "HS.OG.05.01_ea   ( Kochherd )",
        )
        assert new_output_ga.id != output_ga.id
        assert new_output_ga.address == output_ga.address

        added = link_scene_values(project)

        assert added == 1
        numbered = [s for s in project.scenes if s.scene_number == 2]
        assert len(numbered) == 1
        assert numbered[0].actions[0].value == "AUS"

    def test_ignores_device_not_listening_to_this_channel(self):
        """Ein Geraet, dessen Szenen-Trigger-ComObject an eine ANDERE GA
        angeschlossen ist, darf nicht faelschlich verknuepft werden."""
        project, recall_ga, channel_scene = _project_with_channel_scene()
        output_ga = _add_output_ga(project, "irrelevant")
        _add_abb_style_device(
            project, "1.1.10", "9/9/9",  # andere Recall-GA
            output_ga.address,
            scene_values=[SceneValueEntry(channel="A", scene_number=2, value="AUS")],
        )

        added = link_scene_values(project)

        assert added == 0
        assert len(project.scenes) == 1

    def test_ignores_scenes_without_source_ga(self):
        """Manuell angelegte Szenen (kein is_detected/source_ga_ids) werden
        nicht angefasst -- fuer sie gibt es keine bekannte Empfangs-GA."""
        project = KnxProject(name="Test")
        project.scenes.append(Scene(name="Manuell", scene_number=1, scope="central"))
        project.topology = Topology()

        assert link_scene_values(project) == 0


class TestLinkSceneTriggers:
    def test_creates_numbered_scene_with_trigger_description(self):
        project, recall_ga, channel_scene = _project_with_channel_scene()
        _add_feller_style_device(
            project, "1.1.61", recall_ga.address,
            scene_triggers=[SceneTriggerEntry(button="Taste 1, links", scene_number=1)],
            installation_location="00  Haupteingang",
        )

        updated = link_scene_triggers(project)

        assert updated == 1
        numbered = [s for s in project.scenes if s.scene_number == 1]
        assert len(numbered) == 1
        assert numbered[0].trigger == "Taster 1.1.61 (00  Haupteingang), Taste 1, links"
        assert numbered[0].is_detected is True
        assert channel_scene.trigger == ""  # Kanal-Szene bleibt unangetastet

    def test_combines_with_actuator_actions_on_same_numbered_scene(self):
        """Taste und Aktor, die dieselbe Szenennummer auf demselben
        Recall-Kanal bedienen, muessen auf derselben Scene landen."""
        project, recall_ga, channel_scene = _project_with_channel_scene()
        output_ga = _add_output_ga(project, "HS.OG.05.01_ea   ( Kochherd )")
        _add_abb_style_device(
            project, "1.1.10", recall_ga.address, output_ga.address,
            scene_values=[SceneValueEntry(channel="A", scene_number=2, value="AUS")],
        )
        _add_feller_style_device(
            project, "1.1.61", recall_ga.address,
            scene_triggers=[SceneTriggerEntry(button="Taste 1, rechts", scene_number=2)],
        )

        link_scene_values(project)
        link_scene_triggers(project)

        numbered = [s for s in project.scenes if s.scene_number == 2]
        assert len(numbered) == 1
        scene = numbered[0]
        assert scene.actions[0].value == "AUS"
        assert scene.trigger == "Taster 1.1.61, Taste 1, rechts"

    def test_idempotent_on_repeated_call(self):
        project, recall_ga, channel_scene = _project_with_channel_scene()
        _add_feller_style_device(
            project, "1.1.61", recall_ga.address,
            scene_triggers=[SceneTriggerEntry(button="Taste 1, links", scene_number=1)],
        )

        first = link_scene_triggers(project)
        second = link_scene_triggers(project)

        assert first == 1
        assert second == 0
        numbered = [s for s in project.scenes if s.scene_number == 1]
        assert len(numbered) == 1
        assert numbered[0].trigger.count("Taste 1, links") == 1

    def test_no_channel_scene_means_nothing_happens(self):
        """Ohne eine bereits erkannte Kanal-Szene (scene_number=0) fuer die
        Recall-GA gibt es keine Namens-/Scope-Vorlage -- best effort, kein
        Fehler."""
        project = KnxProject(name="Test")
        _add_feller_style_device(
            project, "1.1.61", "0/4/1",
            scene_triggers=[SceneTriggerEntry(button="Taste 1, links", scene_number=1)],
        )

        assert link_scene_triggers(project) == 0
        assert project.scenes == []
