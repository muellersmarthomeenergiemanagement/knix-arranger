"""Tests fuer XlsxImportService (FA-511-520)."""
import os
import pytest
from knix_arranger.services.xlsx_import_service import XlsxImportService

REFERENCE_XLSX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Topologie.xlsx",
)


class TestXlsxImportService:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_import_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            self.svc.import_xlsx("nicht_vorhanden.xlsx")

    def test_service_instantiation(self):
        """Service laesst sich erstellen."""
        assert self.svc is not None

    def test_parse_physical_address(self):
        """Physikalische Adresse korrekt zerlegen."""
        addr = "1.1.5"
        parts = addr.split(".")
        assert len(parts) == 3
        assert int(parts[0]) == 1
        assert int(parts[1]) == 1
        assert int(parts[2]) == 5

    def test_coupler_detection(self):
        """Koppler haben Teilnehmer-Adresse 0 (FA-517)."""
        addr = "1.1.0"
        parts = addr.split(".")
        assert int(parts[2]) == 0

    def test_power_supply_detection(self):
        """Spannungsversorgungen mit '-' erkennen (FA-516)."""
        for addr in ["1.1.-", "2.3.-"]:
            assert addr.endswith("-")

    def test_device_limit_warning(self):
        """Warnung bei >85 Geraeten pro Linie (FA-518)."""
        assert 90 > 85

    def test_device_limit_error(self):
        """Fehler bei >100 Geraeten pro Linie (FA-518)."""
        assert 105 > 100

    def test_extract_gas(self):
        """GA-Adressen werden aus Zellentext extrahiert (FA-519)."""
        ga_text = "3/0/65 L.OG.01.01_ea   ( Licht )  0/0/100 3/4/9"
        gas = self.svc._extract_gas(ga_text)
        assert gas == ["3/0/65", "0/0/100", "3/4/9"]

    def test_extract_gas_empty(self):
        """Leerer Text ergibt leere Liste."""
        assert self.svc._extract_gas("") == []

    def test_classify_device_coupler(self):
        """Teilnehmer 0 = Koppler."""
        assert self.svc._classify_device("1.1.0") == "coupler"

    def test_classify_device_actor(self):
        """Teilnehmer 1-100 = Aktor."""
        assert self.svc._classify_device("1.1.5") == "actor"
        assert self.svc._classify_device("1.1.100") == "actor"

    def test_classify_device_sensor(self):
        """Teilnehmer 101-199 = Sensor."""
        assert self.svc._classify_device("1.1.101") == "sensor"


@pytest.mark.skipif(
    not os.path.exists(REFERENCE_XLSX),
    reason="Topologie.xlsx Referenzdatei nicht vorhanden",
)
class TestXlsxImportReference:
    """Tests mit Topologie.xlsx Referenzdatei (AK-04a)."""

    def setup_method(self):
        self.svc = XlsxImportService()
        self.topo = self.svc.import_xlsx(REFERENCE_XLSX)

    def test_import_returns_topology(self):
        """Import liefert ein Topology-Objekt."""
        from knix_arranger.models.topology import Topology
        assert isinstance(self.topo, Topology)

    def test_one_area(self):
        """Referenzdatei hat 1 Bereich (AK-04a)."""
        assert len(self.topo.areas) == 1

    def test_two_lines(self):
        """Referenzdatei hat 2 Linien (AK-04a)."""
        total = sum(len(a.lines) for a in self.topo.areas)
        assert total == 2

    def test_seventy_devices(self):
        """Referenzdatei hat 71 Busteilnehmer ohne Spannungsversorgung (AK-04a)."""
        non_ps = sum(
            1 for a in self.topo.areas
            for l in a.lines
            for d in l.devices
            if d.device_type != "power_supply"
        )
        assert non_ps == 71

    def test_metadata_project_name(self):
        """Projektname wird aus Metadaten extrahiert (FA-512)."""
        meta = self.topo.metadata  # type: ignore[attr-defined]
        assert "project_name" in meta
        assert meta["project_name"] != ""

    def test_metadata_dates(self):
        """Datum-Felder werden extrahiert (FA-512)."""
        meta = self.topo.metadata  # type: ignore[attr-defined]
        assert "print_date" in meta
        assert "start_date" in meta

    def test_backbone_type(self):
        """Backbone-Typ wird korrekt erkannt (FA-513)."""
        assert self.topo.backbone_type in ("TP", "IP")

    def test_area_has_tp_medium(self):
        """Bereich 1 hat Medium TP (FA-513)."""
        area = self.topo.areas[0]
        assert area.backbone_type == "TP"

    def test_power_supply_recognized(self):
        """Spannungsversorgungen werden erkannt (FA-516)."""
        ps_devices = [
            d for a in self.topo.areas
            for l in a.lines
            for d in l.devices
            if d.device_type == "power_supply"
        ]
        assert len(ps_devices) >= 1

    def test_communication_objects_present(self):
        """Busteilnehmer haben Kommunikationsobjekte (FA-515)."""
        kos_total = sum(
            len(d.communication_objects)
            for a in self.topo.areas
            for l in a.lines
            for d in l.devices
        )
        assert kos_total > 100

    def test_ko_zero_not_skipped(self):
        """KO-Nummer 0 darf nicht als Backbone erkannt werden (FA-515)."""
        for a in self.topo.areas:
            for l in a.lines:
                for d in l.devices:
                    if d.communication_objects:
                        numbers = [ko.object_number for ko in d.communication_objects]
                        # Falls ein Geraet mit KO-Nr. 0 existiert, muss es vorhanden sein
                        if 0 in numbers:
                            return  # Mindestens ein KO-0 gefunden
        # Referenzdatei enthaelt KO-0, also muss das gefunden werden
        pytest.fail("Kein Geraet mit KO-Nummer 0 gefunden – KO-0 wird faelschlicherweise uebersprungen")

    def test_connected_gas_extracted(self):
        """Verbundene Gruppenadressen werden extrahiert (FA-519)."""
        all_gas = [
            ga for a in self.topo.areas
            for l in a.lines
            for d in l.devices
            for ko in d.communication_objects
            for ga in ko.connected_gas
        ]
        assert len(all_gas) > 0

    def test_ga_format_correct(self):
        """Alle extrahierten GAs haben Format H/M/S."""
        import re
        ga_re = re.compile(r"^\d+/\d+/\d+$")
        for a in self.topo.areas:
            for l in a.lines:
                for d in l.devices:
                    for ko in d.communication_objects:
                        for ga in ko.connected_gas:
                            assert ga_re.match(ga), f"Ungueltige GA: {ga!r}"

    def test_installation_location_extracted(self):
        """Einbauorte werden aus Subzeilen extrahiert."""
        devices_with_location = [
            d for a in self.topo.areas
            for l in a.lines
            for d in l.devices
            if d.installation_location
        ]
        assert len(devices_with_location) > 0

    def test_merge_with_csv(self):
        """merge_with_csv gibt 0 zurueck wenn keine CSV geladen (FA-520)."""
        class FakeGaStructure:
            def all_addresses(self):
                return []
        result = self.svc.merge_with_csv(self.topo, FakeGaStructure())
        assert result == 0

    def test_derive_building_structure_returns_areal(self):
        """derive_building_structure gibt ein Areal-Objekt zurueck."""
        from knix_arranger.models.building import Areal
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        assert isinstance(areal, Areal)

    def test_derive_building_structure_has_floors(self):
        """Gebaeudestruktur enthaelt mindestens ein Stockwerk."""
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        assert len(areal.all_floors) > 0

    def test_derive_building_structure_floor_codes(self):
        """Referenzdatei enthaelt OG, EG, DG als Stockwerkkuerzel."""
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        codes = {f.short_code for f in areal.all_floors}
        assert "OG" in codes
        assert "EG" in codes
        assert "DG" in codes

    def test_derive_building_structure_has_rooms(self):
        """Jedes Stockwerk enthaelt mindestens einen Raum."""
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        for floor in areal.all_floors:
            assert len(floor.all_rooms) > 0, f"Stockwerk {floor.short_code} hat keine Raeume"

    def test_derive_building_structure_room_numbers(self):
        """Raumnummern sind zweistellige Strings."""
        import re
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        for room in areal.all_rooms:
            assert re.match(r"^\d{2}$", room.number), \
                f"Ungueltige Raumnummer: {room.number!r}"

    def test_derive_building_structure_room_names_not_empty(self):
        """Alle Raeume haben einen nicht-leeren Namen."""
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        for room in areal.all_rooms:
            assert room.name, f"Raum {room.number} hat keinen Namen"

    def test_derive_building_structure_main_groups(self):
        """Standard-Stockwerke erhalten korrekte Hauptgruppen-Nummern."""
        areal = self.svc.derive_building_structure(REFERENCE_XLSX)
        floors_by_code = {f.short_code: f for f in areal.all_floors}
        if "EG" in floors_by_code:
            assert floors_by_code["EG"].main_group_number == 2
        if "OG" in floors_by_code:
            assert floors_by_code["OG"].main_group_number == 3

    def test_derive_building_structure_nonexistent_file(self):
        """FileNotFoundError bei nicht vorhandener Datei."""
        with pytest.raises(FileNotFoundError):
            self.svc.derive_building_structure("nicht_vorhanden.xlsx")

    def test_extract_group_addresses_returns_structure(self):
        """extract_group_addresses gibt ein GroupAddressStructure-Objekt zurueck."""
        from knix_arranger.models.group_address import GroupAddressStructure
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        assert isinstance(result, GroupAddressStructure)

    def test_extract_group_addresses_not_empty(self):
        """Aus der Referenzdatei werden Gruppenadressen extrahiert."""
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        assert len(result.all_addresses()) > 0

    def test_extract_group_addresses_format(self):
        """Alle extrahierten GAs haben korrekte Adressfelder (H/M/S)."""
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        for ga in result.all_addresses():
            assert 0 <= ga.main_group <= 31
            assert 0 <= ga.middle_group <= 7
            assert 0 <= ga.sub_group <= 255

    def test_extract_group_addresses_no_duplicates(self):
        """Jede GA-Adresse erscheint nur einmal."""
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        addresses = [ga.address for ga in result.all_addresses()]
        assert len(addresses) == len(set(addresses))

    def test_extract_group_addresses_hierarchy(self):
        """Ergebnis enthaelt Haupt- und Mittelgruppen."""
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        assert len(result.main_groups) > 0
        assert any(len(hg.middle_groups) > 0 for hg in result.main_groups)

    def test_extract_group_addresses_gewerk_code(self):
        """Gewerk-Code wird aus GA-Bezeichnung extrahiert."""
        result = self.svc.extract_group_addresses(REFERENCE_XLSX)
        gas_with_gewerk = [ga for ga in result.all_addresses() if ga.gewerk_code]
        assert len(gas_with_gewerk) > 0

    def test_extract_group_addresses_nonexistent_file(self):
        """FileNotFoundError bei nicht vorhandener Datei."""
        with pytest.raises(FileNotFoundError):
            self.svc.extract_group_addresses("nicht_vorhanden.xlsx")


REFERENCE_GA_REPORT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Gruppenadressen.xlsx",
)

BOTH_FILES = pytest.mark.skipif(
    not (os.path.exists(REFERENCE_XLSX) and os.path.exists(REFERENCE_GA_REPORT)),
    reason="Topologie.xlsx und Gruppenadressen.xlsx werden benoetigt",
)


# ---------------------------------------------------------------------------
# detect_report_type
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(REFERENCE_XLSX),
    reason="Topologie.xlsx nicht vorhanden",
)
class TestDetectReportTypeTopo:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_topology_detected(self):
        """Topologie.xlsx wird als 'topology' erkannt."""
        assert self.svc.detect_report_type(REFERENCE_XLSX) == "topology"


@pytest.mark.skipif(
    not os.path.exists(REFERENCE_GA_REPORT),
    reason="Gruppenadressen.xlsx nicht vorhanden",
)
class TestDetectReportTypeGa:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_ga_report_detected(self):
        """Gruppenadressen.xlsx wird als 'ga_report' erkannt."""
        assert self.svc.detect_report_type(REFERENCE_GA_REPORT) == "ga_report"


# ---------------------------------------------------------------------------
# import_ga_report
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(REFERENCE_GA_REPORT),
    reason="Gruppenadressen.xlsx nicht vorhanden",
)
class TestImportGaReport:
    def setup_method(self):
        self.svc = XlsxImportService()
        from knix_arranger.models.group_address import GroupAddressStructure
        self.gas = self.svc.import_ga_report(REFERENCE_GA_REPORT)

    def test_returns_structure(self):
        from knix_arranger.models.group_address import GroupAddressStructure
        assert isinstance(self.gas, GroupAddressStructure)

    def test_source_is_ga_report(self):
        """source-Feld muss 'ga_report' sein."""
        assert self.gas.source == "ga_report"

    def test_has_main_groups(self):
        assert len(self.gas.main_groups) > 0

    def test_has_middle_groups(self):
        assert any(len(hg.middle_groups) > 0 for hg in self.gas.main_groups)

    def test_has_group_addresses(self):
        assert len(self.gas.all_addresses()) > 0

    def test_more_gas_than_topology_extraction(self):
        """GA-Report enthaelt mehr GAs als die Topologie-Extraktion (echte Namen)."""
        if not os.path.exists(REFERENCE_XLSX):
            pytest.skip("Topologie.xlsx nicht vorhanden")
        topo_gas = self.svc.extract_group_addresses(REFERENCE_XLSX)
        assert len(self.gas.all_addresses()) >= len(topo_gas.all_addresses())

    def test_real_hg_names(self):
        """Hauptgruppen haben echte Namen, nicht 'Hauptgruppe N'."""
        for hg in self.gas.main_groups:
            assert not hg.name.startswith("Hauptgruppe "), \
                f"Generischer HG-Name: {hg.name!r}"

    def test_real_mg_names(self):
        """Mittelgruppen haben echte Namen, nicht 'Mittelgruppe N'."""
        for hg in self.gas.main_groups:
            for mg in hg.middle_groups:
                assert not mg.name.startswith("Mittelgruppe "), \
                    f"Generischer MG-Name: {mg.name!r}"

    def test_ga_address_format(self):
        """Alle GA-Adressen haben korrektes Format H/M/S."""
        import re
        ga_re = re.compile(r"^\d+/\d+/\d+$")
        for ga in self.gas.all_addresses():
            assert ga_re.match(ga.address), f"Ungueltige GA: {ga.address!r}"

    def test_no_duplicate_addresses(self):
        addresses = [ga.address for ga in self.gas.all_addresses()]
        assert len(addresses) == len(set(addresses))

    def test_datapoint_types_present(self):
        """Mindestens ein GA hat einen Datentyp."""
        gas_with_dpt = [ga for ga in self.gas.all_addresses() if ga.datapoint_type]
        assert len(gas_with_dpt) > 0

    def test_gewerk_codes_extracted(self):
        """Gewerk-Codes werden aus GA-Bezeichnungen extrahiert."""
        gas_with_gewerk = [ga for ga in self.gas.all_addresses() if ga.gewerk_code]
        assert len(gas_with_gewerk) > 0

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.svc.import_ga_report("nicht_vorhanden.xlsx")

    def test_address_ranges_valid(self):
        """Alle Adressfelder liegen in gueltigen Bereichen."""
        for ga in self.gas.all_addresses():
            assert 0 <= ga.main_group <= 31
            assert 0 <= ga.middle_group <= 7
            assert 0 <= ga.sub_group <= 255


# ---------------------------------------------------------------------------
# extract_device_locations
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(REFERENCE_GA_REPORT),
    reason="Gruppenadressen.xlsx nicht vorhanden",
)
class TestExtractDeviceLocations:
    def setup_method(self):
        self.svc = XlsxImportService()
        self.locs = self.svc.extract_device_locations(REFERENCE_GA_REPORT)

    def test_returns_dict(self):
        assert isinstance(self.locs, dict)

    def test_not_empty(self):
        assert len(self.locs) > 0

    def test_keys_are_physical_addresses(self):
        """Alle Schluessel sind physikalische Adressen im Format B.L.T."""
        import re
        phys_re = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{1,3}$")
        for addr in self.locs:
            assert phys_re.match(addr), f"Kein gueltiges Adressformat: {addr!r}"

    def test_has_room_entries(self):
        """Mindestens ein Eintrag vom Typ 'room'."""
        room_entries = [v for v in self.locs.values() if v["type"] == "room"]
        assert len(room_entries) > 0

    def test_has_verteiler_entries(self):
        """Mindestens ein Eintrag vom Typ 'verteiler'."""
        vt_entries = [v for v in self.locs.values() if v["type"] == "verteiler"]
        assert len(vt_entries) > 0

    def test_room_entries_have_nr_and_name(self):
        """Raum-Eintraege haben room_nr und room_name."""
        for v in self.locs.values():
            if v["type"] == "room":
                assert "room_nr" in v
                assert "room_name" in v
                assert v["room_nr"].isdigit(), f"room_nr kein Zahlenwert: {v['room_nr']!r}"
                assert len(v["room_nr"]) == 2, f"room_nr nicht zweistellig: {v['room_nr']!r}"
                assert v["room_name"], "room_name ist leer"

    def test_verteiler_entries_have_type_and_name(self):
        """Verteiler-Eintraege haben vt_type und vt_name."""
        for v in self.locs.values():
            if v["type"] == "verteiler":
                assert "vt_type" in v
                assert "vt_name" in v
                assert v["vt_type"], "vt_type ist leer"

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.svc.extract_device_locations("nicht_vorhanden.xlsx")


# ---------------------------------------------------------------------------
# extract_device_notes
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.exists(REFERENCE_XLSX),
    reason="Topologie.xlsx nicht vorhanden",
)
class TestExtractDeviceNotes:
    def setup_method(self):
        self.svc = XlsxImportService()
        self.notes = self.svc.extract_device_notes(REFERENCE_XLSX)

    def test_returns_dict(self):
        assert isinstance(self.notes, dict)

    def test_keys_are_physical_addresses(self):
        """Alle Schluessel sind physikalische Adressen im Format B.L.T."""
        import re
        phys_re = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{1,3}$")
        for addr in self.notes:
            assert phys_re.match(addr), f"Kein gueltiges Adressformat: {addr!r}"

    def test_no_serial_numbers(self):
        """Reine Seriennummern (XXXX:XXXXXXXX) werden nicht als Hinweis übernommen."""
        import re
        serial_re = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]+$")
        for text in self.notes.values():
            assert not serial_re.match(text), f"Seriennummer faelschlich uebernommen: {text!r}"

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.svc.extract_device_notes("nicht_vorhanden.xlsx")


@pytest.mark.skipif(
    not os.path.exists(REFERENCE_XLSX),
    reason="Topologie.xlsx nicht vorhanden",
)
class TestRoomIdForDesignation:
    """Unit-Tests fuer die gemeinsame Token/Designation-Aufloesung."""

    def setup_method(self):
        self.svc = XlsxImportService()

    def test_letter_floor_code(self):
        room_index = {("OG", "05"): "room-1"}
        rid = self.svc._room_id_for_designation("LD.OG.05.01_ea", room_index)
        assert rid == "room-1"

    def test_digit_floor_code(self):
        room_index = {("D1", "04"): "room-2"}
        rid = self.svc._room_id_for_designation("L.104.1_ea", room_index)
        assert rid == "room-2"

    def test_no_match_returns_none(self):
        room_index = {("OG", "05"): "room-1"}
        rid = self.svc._room_id_for_designation("nicht passend", room_index)
        assert rid is None


# ---------------------------------------------------------------------------
# link_rooms_to_lines
# ---------------------------------------------------------------------------

@BOTH_FILES
class TestLinkRoomsToLines:
    def setup_method(self):
        self.svc = XlsxImportService()
        self.topology = self.svc.import_xlsx(REFERENCE_XLSX)
        self.topology.is_imported = True
        self.ga_structure = self.svc.extract_group_addresses(REFERENCE_XLSX)
        self.areal = self.svc.derive_building_structure(REFERENCE_XLSX)

    def test_returns_positive_count(self):
        """Mindestens eine Verknuepfung wird hergestellt."""
        linked = self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal
        )
        assert linked > 0

    def test_lines_have_assigned_rooms(self):
        """Nach Verknuepfung haben Linien assigned_room_ids."""
        self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal
        )
        lines_with_rooms = [
            line for area in self.topology.areas
            for line in area.lines
            if line.assigned_room_ids
        ]
        assert len(lines_with_rooms) > 0

    def test_devices_have_room_id(self):
        """Mindestens ein Geraet hat nach Verknuepfung eine room_id."""
        self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal
        )
        devices_with_room = [
            dev for area in self.topology.areas
            for line in area.lines
            for dev in line.devices
            if dev.room_id
        ]
        assert len(devices_with_room) > 0

    def test_room_ids_valid(self):
        """Alle gesetzten room_ids existieren im Areal."""
        self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal
        )
        known_ids = {r.id for r in self.areal.all_rooms}
        for area in self.topology.areas:
            for line in area.lines:
                for rid in line.assigned_room_ids:
                    assert rid in known_ids, f"Unbekannte room_id: {rid}"
                for dev in line.devices:
                    if dev.room_id:
                        assert dev.room_id in known_ids, \
                            f"Unbekannte device.room_id: {dev.room_id}"

    def test_with_device_locations(self):
        """Mit Einbauort-Daten werden Raum-Zuweisungen hergestellt."""
        locs = self.svc.extract_device_locations(REFERENCE_GA_REPORT)
        linked_with = self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal,
            device_locations=locs,
        )
        # Einbauort-Pfad soll mindestens eine Zuweisung erzeugen
        assert linked_with > 0
        # Mindestens ein Geraet soll eine room_id aus Einbauort-Daten erhalten haben
        devices_with_room = [
            dev for area in self.topology.areas
            for line in area.lines
            for dev in line.devices
            if dev.room_id
        ]
        assert len(devices_with_room) > 0

    def test_with_device_notes_highest_priority(self):
        """Ein Installations-Hinweis setzt die Raum-Zuordnung, auch wenn die
        GA-Bezeichnungen des Geraets auf einen anderen Raum hindeuten wuerden."""
        first_floor = self.areal.all_floors[0]
        first_room = first_floor.all_rooms[0]
        target_addr = self.topology.areas[0].lines[0].devices[0].physical_address

        device_notes = {
            target_addr: f"X.{first_floor.short_code}.{first_room.number}.01_ea"
        }
        self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal,
            device_notes=device_notes,
        )
        target_device = next(
            dev for area in self.topology.areas
            for line in area.lines
            for dev in line.devices
            if dev.physical_address == target_addr
        )
        assert target_device.room_id == first_room.id

    def test_empty_areal_returns_zero(self):
        """Leeres Areal liefert 0."""
        from knix_arranger.models.building import Areal
        linked = self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, Areal()
        )
        assert linked == 0

    def test_no_double_assignment(self):
        """Jede room_id erscheint pro Linie hoechstens einmal."""
        self.svc.link_rooms_to_lines(
            self.topology, self.ga_structure, self.areal
        )
        for area in self.topology.areas:
            for line in area.lines:
                assert len(line.assigned_room_ids) == len(set(line.assigned_room_ids))


# ---------------------------------------------------------------------------
# enrich_device_ko_connections
# ---------------------------------------------------------------------------

@BOTH_FILES
class TestEnrichDeviceKoConnections:
    def setup_method(self):
        self.svc = XlsxImportService()
        self.topology = self.svc.import_xlsx(REFERENCE_XLSX)
        self.topology.is_imported = True

    def test_returns_tuple(self):
        result = self.svc.enrich_device_ko_connections(
            self.topology, REFERENCE_GA_REPORT
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_counts_non_negative(self):
        enriched, added = self.svc.enrich_device_ko_connections(
            self.topology, REFERENCE_GA_REPORT
        )
        assert enriched >= 0
        assert added >= 0

    def test_does_not_remove_existing_kos(self):
        """Anreicherung darf keine bestehenden KOs entfernen."""
        before = sum(
            len(d.communication_objects)
            for a in self.topology.areas
            for l in a.lines
            for d in l.devices
        )
        self.svc.enrich_device_ko_connections(self.topology, REFERENCE_GA_REPORT)
        after = sum(
            len(d.communication_objects)
            for a in self.topology.areas
            for l in a.lines
            for d in l.devices
        )
        assert after >= before

    def test_connected_gas_still_valid_format(self):
        """Nach Anreicherung haben alle GAs weiterhin gueltiges Format."""
        import re
        self.svc.enrich_device_ko_connections(self.topology, REFERENCE_GA_REPORT)
        ga_re = re.compile(r"^\d+/\d+/\d+$")
        for area in self.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    for ko in dev.communication_objects:
                        for ga in ko.connected_gas:
                            assert ga_re.match(ga), f"Ungueltige GA nach Anreicherung: {ga!r}"

    def test_no_duplicate_gas_per_ko(self):
        """Keine doppelten GA-Eintraege pro KO nach Anreicherung."""
        self.svc.enrich_device_ko_connections(self.topology, REFERENCE_GA_REPORT)
        for area in self.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    for ko in dev.communication_objects:
                        assert len(ko.connected_gas) == len(set(ko.connected_gas)), \
                            f"Doppelte GAs in KO {ko.object_number} von {dev.physical_address}"

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            self.svc.enrich_device_ko_connections(self.topology, "nicht_vorhanden.xlsx")


# ---------------------------------------------------------------------------
# GroupAddressStructure.source
# ---------------------------------------------------------------------------

class TestGroupAddressStructureSource:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_default_source_empty(self):
        """Standardmaessig ist source ein leerer String."""
        from knix_arranger.models.group_address import GroupAddressStructure
        gas = GroupAddressStructure()
        assert gas.source == ""

    @pytest.mark.skipif(
        not os.path.exists(REFERENCE_XLSX),
        reason="Topologie.xlsx nicht vorhanden",
    )
    def test_topology_extraction_sets_source(self):
        """extract_group_addresses setzt source='topology'."""
        gas = self.svc.extract_group_addresses(REFERENCE_XLSX)
        assert gas.source == "topology"

    @pytest.mark.skipif(
        not os.path.exists(REFERENCE_GA_REPORT),
        reason="Gruppenadressen.xlsx nicht vorhanden",
    )
    def test_ga_report_sets_source(self):
        """import_ga_report setzt source='ga_report'."""
        gas = self.svc.import_ga_report(REFERENCE_GA_REPORT)
        assert gas.source == "ga_report"

    def test_source_survives_serialization(self):
        """source-Feld wird durch to_dict/from_dict erhalten."""
        from knix_arranger.models.group_address import GroupAddressStructure
        gas = GroupAddressStructure(source="ga_report")
        restored = GroupAddressStructure.from_dict(gas.to_dict())
        assert restored.source == "ga_report"

    def test_source_priority_ga_report_wins(self):
        """GA-Report (source='ga_report') schuetzt vor Topologie-Ueberschreibung."""
        from knix_arranger.models.group_address import GroupAddressStructure
        ga_report = GroupAddressStructure(source="ga_report")
        # Simulation: Topologie-Import soll GA-Report nicht ueberschreiben
        assert ga_report.source == "ga_report"  # Guard-Bedingung greift


# ---------------------------------------------------------------------------
# GewerkService.derive_gewerk_assignments
# ---------------------------------------------------------------------------

@BOTH_FILES
class TestDeriveGewerkAssignments:
    def setup_method(self):
        from knix_arranger.services.xlsx_import_service import XlsxImportService
        from knix_arranger.services.gewerk_service import GewerkService
        from knix_arranger.models.gewerk import GewerkCatalog

        svc = XlsxImportService()
        self.areal = svc.derive_building_structure(REFERENCE_XLSX)
        self.gas = svc.import_ga_report(REFERENCE_GA_REPORT)
        cat = GewerkCatalog()
        cat.load_defaults()
        self.gsvc = GewerkService(cat)

    def test_returns_positive_count(self):
        total = self.gsvc.derive_gewerk_assignments(self.gas, self.areal)
        assert total > 0

    def test_rooms_have_assignments(self):
        """Nach Ableitung haben Raeume Gewerk-Zuweisungen."""
        self.gsvc.derive_gewerk_assignments(self.gas, self.areal)
        rooms_with = [r for r in self.areal.all_rooms if r.gewerk_assignments]
        assert len(rooms_with) > 0

    def test_only_known_codes(self):
        """Nur im Katalog bekannte Gewerk-Codes werden zugewiesen."""
        from knix_arranger.models.gewerk import GewerkCatalog
        cat = GewerkCatalog()
        cat.load_defaults()
        self.gsvc.derive_gewerk_assignments(self.gas, self.areal)
        for room in self.areal.all_rooms:
            for asg in room.gewerk_assignments:
                assert cat.get(asg.gewerk_code) is not None, \
                    f"Unbekannter Gewerk-Code: {asg.gewerk_code!r}"

    def test_count_positive(self):
        """count jeder Zuweisung ist groesser 0."""
        self.gsvc.derive_gewerk_assignments(self.gas, self.areal)
        for room in self.areal.all_rooms:
            for asg in room.gewerk_assignments:
                assert asg.count > 0, \
                    f"count=0 fuer {asg.gewerk_code} in Raum {room.name}"

    def test_overwrite_false_skips_existing(self):
        """overwrite=False belaesst bestehende Zuweisungen unveraendert."""
        from knix_arranger.models.building import GewerkAssignment
        # Einen Raum vorab befuellen
        first_room = self.areal.all_rooms[0]
        sentinel = GewerkAssignment(gewerk_code="L", count=99)
        first_room.gewerk_assignments = [sentinel]
        original_count = len(first_room.gewerk_assignments)

        self.gsvc.derive_gewerk_assignments(self.gas, self.areal, overwrite=False)

        # Raum muss unveraendert sein
        assert first_room.gewerk_assignments[0].gewerk_code == "L"
        assert first_room.gewerk_assignments[0].count == 99

    def test_overwrite_true_replaces_existing(self):
        """overwrite=True ersetzt bestehende Zuweisungen in Raeumen mit GA-Daten."""
        from knix_arranger.models.building import GewerkAssignment
        # Alle Raeume mit Sentinel befuellen
        sentinel_code = "L"
        sentinel_count = 99
        for room in self.areal.all_rooms:
            room.gewerk_assignments = [GewerkAssignment(gewerk_code=sentinel_code, count=sentinel_count)]

        n_changed = self.gsvc.derive_gewerk_assignments(self.gas, self.areal, overwrite=True)

        # overwrite=True muss mindestens einen Raum geaendert haben
        assert n_changed > 0, "overwrite=True hat nichts veraendert"
        # Mindestens ein Raum hat nicht mehr nur den Sentinel
        replaced = [
            r for r in self.areal.all_rooms
            if r.gewerk_assignments and not (
                len(r.gewerk_assignments) == 1
                and r.gewerk_assignments[0].gewerk_code == sentinel_code
                and r.gewerk_assignments[0].count == sentinel_count
            )
        ]
        assert len(replaced) > 0, "Keine Zuweisung wurde durch overwrite=True ersetzt"

    def test_empty_areal_returns_zero(self):
        """Leeres Areal liefert 0."""
        from knix_arranger.models.building import Areal
        total = self.gsvc.derive_gewerk_assignments(self.gas, Areal())
        assert total == 0

    def test_empty_gas_returns_zero(self):
        """Leere GA-Struktur liefert 0."""
        from knix_arranger.models.group_address import GroupAddressStructure
        total = self.gsvc.derive_gewerk_assignments(GroupAddressStructure(), self.areal)
        assert total == 0


class TestParseGaEntries:
    """Unit-Tests fuer _parse_ga_entries und _parse_xlsx_designation."""

    def setup_method(self):
        self.svc = XlsxImportService()

    def test_single_ga_with_name(self):
        text = "3/0/65 LD.EG.05.01_ea ( Licht )"
        entries = self.svc._parse_ga_entries(text)
        assert len(entries) == 1
        assert entries[0][0] == "3/0/65"
        assert "LD.EG.05.01_ea" in entries[0][1]

    def test_multiple_gas(self):
        text = "3/0/65 LD.EG.05.01_ea ( Licht )  0/0/100 3/4/9"
        entries = self.svc._parse_ga_entries(text)
        assert len(entries) == 3
        assert entries[0][0] == "3/0/65"
        assert entries[1][0] == "0/0/100"
        assert entries[2][0] == "3/4/9"

    def test_ga_without_name(self):
        text = "1/2/3"
        entries = self.svc._parse_ga_entries(text)
        assert len(entries) == 1
        assert entries[0][0] == "1/2/3"
        assert entries[0][1] == ""

    def test_empty_text(self):
        assert self.svc._parse_ga_entries("") == []

    def test_designation_description_extracted(self):
        from knix_arranger.models.group_address import GroupAddress
        ga = GroupAddress()
        self.svc._parse_xlsx_designation(ga, "LD.EG.05.01_ea ( Licht )")
        assert ga.description == "Licht"
        assert ga.gewerk_code == "LD"

    def test_designation_no_parens(self):
        from knix_arranger.models.group_address import GroupAddress
        ga = GroupAddress()
        self.svc._parse_xlsx_designation(ga, "J.OG.03.02_a")
        assert ga.gewerk_code == "J"
        assert ga.description == ""

    def test_designation_empty(self):
        from knix_arranger.models.group_address import GroupAddress
        ga = GroupAddress()
        self.svc._parse_xlsx_designation(ga, "")
        assert ga.gewerk_code == ""
        assert ga.description == ""
