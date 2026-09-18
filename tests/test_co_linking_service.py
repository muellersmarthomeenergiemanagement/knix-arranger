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

    def test_ort_wird_aus_raum_uebernommen(self):
        """FA-3000: room_name wird aus dem bedienten Raum uebernommen (Ort-Spalte)."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "E/A")
        assert p.room_name == "Wohnzimmer"

    def test_zentral_ga_hat_keinen_ort(self):
        """Zentral-/Szenen-GAs sind raumlos -- room_name bleibt leer."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _central_ga("", "SZENE", "ZENTRAL Szene Abwesenheit", 1, dpt="DPST-17-1"),
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "SZENE")
        assert p.room_name == ""


# ── Doppelte Vorschlaege (FA-3000) ────────────────────────────────────────────

class TestDedupeProposals:
    """_dedupe_proposals() entfernt exakte Duplikate (identische Geraeteadresse
    + GA-Adresse + CO-Name + Richtung), die in der Tabelle nur verwirren und
    ohnehin nicht doppelt geschrieben werden koennten."""

    def test_exaktes_duplikat_wird_entfernt(self):
        p1 = CoLinkingProposal(
            device_id="d1", physical_address="1.1.1", co_name="Schalten",
            co_dpt="DPST-1-1", co_flags="KSUA", direction="empfangen",
            function_name="E/A", gewerk_code="L", ga_address="1/0/0",
            ga_designation="L_E01_01 E/A",
        )
        p2 = CoLinkingProposal(
            device_id="d1", physical_address="1.1.1", co_name="Schalten",
            co_dpt="DPST-1-1", co_flags="KSUA", direction="empfangen",
            function_name="E/A", gewerk_code="L", ga_address="1/0/0",
            ga_designation="L_E01_01 E/A",
        )
        result = CoLinkingService()._dedupe_proposals([p1, p2])
        assert result == [p1]

    def test_unterschiedliche_ga_bleibt_erhalten(self):
        """Gleiche Geraeteadresse+CO-Name, aber unterschiedliche GA -- keine
        Entfernung (z.B. Raum-GA + Zentral-GA auf demselben CO)."""
        p1 = CoLinkingProposal(
            device_id="d1", physical_address="1.1.1", co_name="Schalten",
            co_dpt="DPST-1-1", co_flags="KSUA", direction="empfangen",
            function_name="E/A", gewerk_code="L", ga_address="1/0/0",
            ga_designation="L_E01_01 E/A",
        )
        p2 = CoLinkingProposal(
            device_id="d1", physical_address="1.1.1", co_name="Schalten",
            co_dpt="DPST-1-1", co_flags="KSUA", direction="empfangen",
            function_name="E/A", gewerk_code="L", ga_address="0/0/1",
            ga_designation="ZENTRAL Alle Lichter AUS",
        )
        result = CoLinkingService()._dedupe_proposals([p1, p2])
        assert result == [p1, p2]


# ── Gateway-Geraete (FA-1307): muessen wie Aktoren behandelt werden ──────────

def _make_gateway_project(rooms: list, gateway_product: str, gas: list) -> KnxProject:
    """Wie _make_project, aber mit device_type='gateway' statt 'actor'."""
    project = _make_project(rooms, gateway_product, gas)
    device = project.topology.areas[0].lines[0].devices[0]
    device.device_type = "gateway"
    return project


class TestGatewayDevices:
    """Regression: Gateway-Geraete (DALI, Modbus, KNX-Schnittstelle/MM, ...)
    wurden bisher nirgends beruecksichtigt, da _collect_actor_rows strikt
    auf device_type == 'actor' filterte -- CO-Verknuepfung generierte fuer
    sie deshalb nie Vorschlaege, unabhaengig vom KNXPROD-Import."""

    def test_mm_gateway_ein_aus_erzeugt_vorschlag(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1")]
        project = _make_gateway_project(rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next((p for p in proposals if p.function_name == "EIN/AUS"), None)
        assert p is not None, "Kein Vorschlag fuer Gateway-Geraet generiert"
        assert p.co_name == "Ein/Aus"
        assert p.direction == "empfangen"
        assert p.confidence == "sicher"

    def test_mm_gateway_all_five_functions(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [
            _ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1"),
            _ga(room, "MM", 1, "LAUTSTAERKE", 1, "DPST-5-1"),
            _ga(room, "MM", 1, "QUELLE", 2, "DPST-5-1"),
            _ga(room, "MM", 1, "PLAY/PAUSE", 3, "DPST-1-1"),
            _ga(room, "MM", 1, "STATUS", 4, "DPST-1-1"),
        ]
        project = _make_gateway_project(rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas)

        proposals = CoLinkingService().generate_proposals(project)
        function_names = {p.function_name for p in proposals}
        assert function_names == {"EIN/AUS", "LAUTSTAERKE", "QUELLE", "PLAY/PAUSE", "STATUS"}
        status = next(p for p in proposals if p.function_name == "STATUS")
        assert status.direction == "senden"

    def test_dali_gateway_without_matching_function_map_entry(self):
        """DALI-Gateway-GAs ohne passenden _FUNCTION_MAP-Eintrag erzeugen (noch)
        keine Vorschlaege -- aber duerfen auch nicht crashen."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "LDA", 1, "IRGENDWAS", 0, "DPST-1-1")]
        project = _make_gateway_project(rooms=[room], gateway_product="DALI-Gateway 16-fach", gas=gas)

        proposals = CoLinkingService().generate_proposals(project)
        assert proposals == []

    def test_gateway_proposal_can_be_applied(self):
        """Ein Gateway-Vorschlag laesst sich wie ein Aktor-Vorschlag uebernehmen."""
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1")]
        project = _make_gateway_project(rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas)
        svc = CoLinkingService()

        proposals = svc.generate_proposals(project)
        for p in proposals:
            p.selected = True
        count = svc.apply_proposals(project, proposals)

        assert count > 0
        device = project.topology.areas[0].lines[0].devices[0]
        all_gas = [ga for co in device.communication_objects for ga in co.connected_gas]
        assert "1/0/0" in all_gas


# ── Reale KNXPROD-ComObjects bevorzugt (FA-3006) ──────────────────────────────

class TestRealComObjectPreferred:
    """Ist am Geraet ein reales (aus KNXPROD importiertes) CommunicationObject
    vorhanden, dessen Funktionsname exakt zur GA-Funktion passt, wird dieses
    reale CO (mit seinem tatsaechlichen Namen/DPT/Flags) statt des
    generischen _FUNCTION_MAP-Eintrags verwendet."""

    def test_real_co_name_and_dpt_override_generic_template(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1")]
        project = _make_gateway_project(
            rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas,
        )
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=0, name="System Ein/Aus",
            object_function="EIN/AUS", data_type="DPST-1-1", flags="KÜU",
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "EIN/AUS")
        # Realer Produktname statt generischem "Ein/Aus"
        assert p.co_name == "System Ein/Aus"
        assert p.confidence == "sicher"

    def test_real_co_covers_function_name_unknown_to_function_map(self):
        """Wurde die GA bereits aus dem echten Produkt-Schema generiert
        (AddressGenerator._build_product_schema), traegt sie einen
        beliebigen Funktionsnamen aus der KNXPROD, der nicht im generischen
        _FUNCTION_MAP steht. Vorher: kein Vorschlag. Jetzt: das passende
        reale CO wird gefunden und verwendet."""
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "BASS", 0, "DPST-6-1")]
        project = _make_gateway_project(
            rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas,
        )
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=0, name="Bass anpassen",
            object_function="BASS", data_type="DPST-6-1", flags="KÜU",
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next((p for p in proposals if p.function_name == "BASS"), None)
        assert p is not None, "Reales CO ohne _FUNCTION_MAP-Eintrag wurde nicht gefunden"
        assert p.co_name == "Bass anpassen"
        assert p.co_dpt == "DPST-6-1"

    def test_direction_derived_from_real_co_transmit_flag(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "STATUSTEXT", 0, "DPST-16-1")]
        project = _make_gateway_project(
            rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas,
        )
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=0, name="Statustext",
            object_function="STATUSTEXT", data_type="DPST-16-1", flags="KLSU",
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "STATUSTEXT")
        assert p.direction == "senden"

    def test_already_linked_detected_via_real_co(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1")]
        project = _make_gateway_project(
            rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas,
        )
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=0, name="System Ein/Aus",
            object_function="EIN/AUS", data_type="DPST-1-1", flags="KÜU",
            connected_gas=["1/0/0"],
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "EIN/AUS")
        assert p.already_linked is True
        assert p.selected is False

    def test_falls_back_to_function_map_when_no_real_co_matches(self):
        """Reale COs mit anderen Funktionsnamen duerfen den generischen
        Fallback nicht verhindern (z.B. Produkt erst nachtraeglich an ein
        Geraet mit bereits generisch geplanten GAs zugewiesen)."""
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0, "DPST-1-1")]
        project = _make_gateway_project(
            rooms=[room], gateway_product="KNX-Schnittstelle 1-fach", gas=gas,
        )
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=0, name="Zone A Mute",
            object_function="MUTE ZONE A", data_type="DPST-1-1", flags="KÜU",
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "EIN/AUS")
        assert p.co_name == "Ein/Aus"  # generischer _FUNCTION_MAP-Name


# ── Mehrdeutiger CO-Name auf demselben Kanal (FA-3000-Folgefehler) ───────────

class TestAmbiguousChannelName:
    """Regression (Chalet Franziska 2005, 1.1.10 / GA 0/4/1): ein ETS6-
    importierter Aktor kann mehrere COs mit demselben Kanalnamen ("Ausgang A")
    aber unterschiedlicher Funktion (Schalten/8-Bit-Szene/Telegr. Status)
    haben. Die reine Namenssuche in _match_real_co() traf immer das ERSTE
    davon -- unabhaengig davon, welches CO die GA tatsaechlich traegt --
    und zeigte deshalb einen falschen CO-DPT ("1 bit" statt "1 byte"), der
    dann faelschlich als Widerspruch zum echten GA-DPT auffiel."""

    def _make_device_with_ambiguous_cos(self, ga_address: str):
        room = Room(number="E01", name="Zimmer")
        project = _make_project([room], "Fremd-Aktor ohne Gewerk-Zuordnung", [])
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [
            CommunicationObject(
                object_number=10, name="Ausgang A", object_function="Schalten",
                data_type="1 bit", connected_gas=["1/0/2"],
            ),
            CommunicationObject(
                object_number=17, name="Ausgang A", object_function="8-Bit-Szene",
                data_type="1 byte", connected_gas=[ga_address],
            ),
            CommunicationObject(
                object_number=29, name="Ausgang A", object_function="Telegr. Status Schalten",
                data_type="1 bit", connected_gas=["1/0/3"],
            ),
        ]
        ga = GroupAddress(
            main_group=1, middle_group=0, sub_group=1,
            designation="Anwesenheit Chalet", datapoint_type="1 byte",
        )
        project.group_addresses.main_groups[0].middle_groups[0].group_addresses = [ga]
        return project, device

    def test_matches_the_co_that_actually_carries_the_ga(self):
        project, device = self._make_device_with_ambiguous_cos("1/0/1")

        proposals = CoLinkingService().generate_proposals(project)
        matches = [p for p in proposals if p.ga_address == "1/0/1"]
        assert len(matches) == 1
        assert matches[0].co_dpt == "1 byte"  # vom "8-Bit-Szene"-CO, nicht "Schalten"

    def test_no_false_dpt_mismatch(self):
        project, device = self._make_device_with_ambiguous_cos("1/0/1")

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.ga_address == "1/0/1")
        assert p.ga_dpt == "1 byte"
        assert p.co_dpt == p.ga_dpt
        assert p.confidence == "sicher"


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


def _central_ga(gewerk: str, fn: str, designation: str, sub: int, dpt: str = "DPST-1-1") -> GroupAddress:
    return GroupAddress(
        main_group=0, middle_group=0, sub_group=sub,
        designation=designation, gewerk_code=gewerk, function_name=fn,
        datapoint_type=dpt, central="true",
    )


class TestSzenenLinking:
    """Szenen-GAs (central=='true', function_name=='SZENE') werden ueber
    belegungsplan_service._collect_central_actor_rows in den Belegungsplan
    aufgenommen -- diese Tests decken die davon abhaengige Konfidenz-Regel
    in generate_proposals() ab (siehe co_linking_service.py)."""

    def test_szene_ohne_echtes_co_ist_manuell_pruefen(self):
        """Kein reales Szenen-CO am Geraet -> generischer _FUNCTION_MAP-
        Fallback, aber bewusst als 'manuell pruefen' markiert (nicht jeder
        Aktor unterstuetzt ueberhaupt Szenen)."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _central_ga("", "SZENE", "ZENTRAL Szene Abwesenheit", 1, dpt="DPST-17-1"),
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "SZENE")
        assert p.co_name == "Szene"
        assert p.confidence == "manuell pruefen"

    def test_szene_mit_echtem_co_ist_sicher(self):
        """Ein reales CO, dessen Name/Funktion die SZENE-Stichworte enthaelt
        (z.B. '8-Bit-Szene', typischer Herstellername statt woertlich
        'Szene'), wird gefunden -> Konfidenz 'sicher', reales CO verwendet."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _central_ga("", "SZENE", "ZENTRAL Szene Abwesenheit", 1, dpt="DPST-17-1"),
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [CommunicationObject(
            object_number=5, name="8-Bit-Szene",
            object_function="", data_type="DPST-17-1", flags="KSUA",
        )]

        proposals = CoLinkingService().generate_proposals(project)
        p = next(p for p in proposals if p.function_name == "SZENE")
        assert p.co_name == "8-Bit-Szene"
        assert p.confidence == "sicher"
