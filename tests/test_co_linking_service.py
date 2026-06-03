"""
Tests fuer CoLinkingService (FA-3000 bis FA-3005).
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.co_linking_service import (
    CoLinkingService, CoLinkingProposal, _dpt_compatible, _dpt_normalize,
)


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project(rooms: list, actor_product: str, gas: list) -> KnxProject:
    """Minimales Testprojekt mit einer Linie und einem Aktor."""
    project = KnxProject(name="Test")
    apt = Apartment(name="WG")
    apt.rooms = rooms
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    line = Line(name="Linie 1", line_number=1)
    line.assigned_room_ids = [r.id for r in rooms]
    actor = Device(device_type="actor", product=actor_product, physical_address="1.1.1")
    line.devices = [actor]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topology = Topology()
    topology.areas = [area]
    project.topology = topology

    mg = MiddleGroup(number=0, name="Test")
    mg.group_addresses = gas
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    structure = GroupAddressStructure()
    structure.main_groups = [hg]
    project.group_addresses = structure
    return project


def _ga(room: Room, gewerk: str, elem: int, fn: str, sub: int, dpt: str = "DPST-1-1") -> GroupAddress:
    return GroupAddress(
        main_group=1, middle_group=0, sub_group=sub,
        designation=f"{gewerk}_{room.number}_{elem:02d} {fn}",
        gewerk_code=gewerk,
        room_id=room.id,
        room_number=room.number,
        element_number=elem,
        function_name=fn,
        datapoint_type=dpt,
    )


# ── DPT-Hilfsfunktionen ────────────────────────────────────────────────────────

class TestDptCompatible:

    def test_exakter_treffer(self):
        assert _dpt_compatible("DPST-1-1", "DPST-1-1")

    def test_dpst_vs_dpt(self):
        """DPST-1-1 und DPT-1-1 gelten als kompatibel."""
        assert _dpt_compatible("DPST-1-1", "DPT-1-1")

    def test_gleicher_haupttyp(self):
        """DPST-5-1 und DPST-5-100 haben gleichen Haupttyp DPT-5."""
        assert _dpt_compatible("DPST-5-1", "DPST-5-100")

    def test_verschiedene_typen(self):
        """DPST-1-1 und DPST-5-1 sind inkompatibel."""
        assert not _dpt_compatible("DPST-1-1", "DPST-5-1")

    def test_leerer_co_dpt(self):
        """Fehlender CO-DPT → kein Fehler, kompatibel."""
        assert _dpt_compatible("", "DPST-1-1")

    def test_leerer_ga_dpt(self):
        """Fehlender GA-DPT → kompatibel."""
        assert _dpt_compatible("DPST-1-1", "")

    def test_beide_leer(self):
        assert _dpt_compatible("", "")

    def test_grosskleinschreibung(self):
        assert _dpt_compatible("dpst-1-1", "DPST-1-1")


# ── Vorschlag-Generierung (FA-3001/3002) ──────────────────────────────────────

class TestGenerateProposals:

    def test_vorschlaege_werden_generiert(self):
        """FA-3001: Vorschlaege werden generiert wenn GA vorhanden."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        assert len(proposals) > 0

    def test_schalten_erzeugt_co_vorschlag(self):
        """E/A-GA → CO 'Schalten' mit DPST-1-1."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next((p for p in proposals if p.function_name == "E/A"), None)
        assert p is not None
        assert p.co_name == "Schalten"
        assert p.co_dpt == "DPST-1-1"
        assert p.direction == "empfangen"

    def test_rm_ga_erzeugt_senden_co(self):
        """RM-GA → CO 'Status Schalten', Richtung senden."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "RM", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next((p for p in proposals if p.function_name == "RM"), None)
        assert p is not None
        assert p.direction == "senden"

    def test_jalousie_auf_ab_co(self):
        """AUF/AB-GA → CO 'Auf/Ab', DPST-1-8."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "J", 1, "AUF/AB", 0, "DPST-1-8")]
        project = _make_project([room], "Jalousieaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next((p for p in proposals if p.function_name == "AUF/AB"), None)
        assert p is not None
        assert p.co_name == "Auf/Ab"
        assert p.co_dpt == "DPST-1-8"

    def test_physikalische_adresse_stimmt(self):
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        assert all(p.physical_address == "1.1.1" for p in proposals)

    def test_kein_vorschlag_ohne_ga(self):
        """Ohne GAs werden keine Vorschlaege generiert."""
        room = Room(number="E01", name="Zimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        proposals = CoLinkingService().generate_proposals(project)
        assert proposals == []


# ── DPT-Kompatibilitaetspruefung (FA-3004) ────────────────────────────────────

class TestDptKompatibilitaet:

    def test_passender_dpt_ist_sicher(self):
        """GA-DPT = CO-DPT → Konfidenz 'sicher'."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "E/A")
        assert p.confidence == "sicher"

    def test_falscher_dpt_ist_manuell_pruefen(self):
        """GA-DPT passt nicht zu CO-DPT → Konfidenz 'manuell pruefen'."""
        room = Room(number="E01", name="Zimmer")
        # E/A erwartet DPST-1-1, aber GA hat DPST-5-1 (falsch)
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-5-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "E/A")
        assert p.confidence == "manuell pruefen"

    def test_ga_dpt_wird_gespeichert(self):
        """GA-DPT wird im Vorschlag als ga_dpt gespeichert."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "E/A")
        assert p.ga_dpt == "DPST-1-1"

    def test_leerer_ga_dpt_bleibt_sicher(self):
        """Fehlender GA-DPT → keine Warnung, 'sicher'."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "")]  # kein DPT
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "E/A")
        assert p.confidence == "sicher"


# ── Vorschlaege uebernehmen (FA-3003/3005) ────────────────────────────────────

class TestApplyProposals:

    def test_ausgewaehlte_vorschlaege_werden_geschrieben(self):
        """FA-3003: Ausgewaehlte Vorschlaege werden in COs eingetragen."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        svc = CoLinkingService()

        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = True
        count = svc.apply_proposals(project, proposals)

        assert count > 0
        # CO muss in Device eingetragen sein
        device = project.topology.areas[0].lines[0].devices[0]
        assert len(device.communication_objects) > 0
        all_gas = [ga for co in device.communication_objects for ga in co.connected_gas]
        assert "1/0/0" in all_gas

    def test_abgewaehlte_vorschlaege_werden_nicht_geschrieben(self):
        """Nicht ausgewaehlte Vorschlaege werden ignoriert."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        svc = CoLinkingService()

        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = False
        count = svc.apply_proposals(project, proposals)

        assert count == 0
        device = project.topology.areas[0].lines[0].devices[0]
        assert len(device.communication_objects) == 0

    def test_bereits_verknuepfte_werden_nicht_doppelt_geschrieben(self):
        """FA-3005: Bereits verknuepfte COs werden nicht ein zweites Mal eingetragen."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        svc = CoLinkingService()

        # Erste Anwendung
        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = True
        count1 = svc.apply_proposals(project, proposals)
        assert count1 > 0

        # Zweite Anwendung: bereits_linked sollte None neue Verknuepfungen ergeben
        proposals2 = svc.generate_proposals(project)
        for p in proposals2:
            p.selected = True
        count2 = svc.apply_proposals(project, proposals2)
        assert count2 == 0

    def test_co_erhaelt_korrekte_ga_adresse(self):
        """Das CO bekommt die GA-Adresse '1/0/0' aus der Test-GA."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        svc = CoLinkingService()

        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = True
        svc.apply_proposals(project, proposals)

        device = project.topology.areas[0].lines[0].devices[0]
        schalten_co = next(
            (co for co in device.communication_objects if co.name == "Schalten"), None
        )
        assert schalten_co is not None
        assert "1/0/0" in schalten_co.connected_gas

    def test_bereits_linked_flag(self):
        """Nach apply: generate_proposals markiert bereits verknuepfte als already_linked."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0, "DPST-1-1")]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        svc = CoLinkingService()

        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = True
        svc.apply_proposals(project, proposals)

        proposals2 = svc.generate_proposals(project)
        ea_proposals = [p for p in proposals2 if p.function_name == "E/A"]
        assert all(p.already_linked for p in ea_proposals)
