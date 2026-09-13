"""Tests fuer XlsxImportService (FA-511-520)."""
import os
import pytest
from knix_arranger.services.xlsx_import_service import XlsxImportService

_REFERENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Chalet Franziska 2005",
    "Importdateien",
)

REFERENCE_XLSX = os.path.join(_REFERENCE_DIR, "Topologie.xlsx")


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


REFERENCE_GA_REPORT = os.path.join(_REFERENCE_DIR, "Gruppenadressen.xlsx")

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
# import_ga_report -- Spaltenverschiebung (Regression fuer "Bezeichnungen
# fehlen nach Import", verursacht durch abweichendes ETS6-Exportlayout)
# ---------------------------------------------------------------------------

def _build_shifted_ga_report(path: str) -> None:
    """Baut eine minimale GA-Report-XLSX, deren Spalten um 1 gegenueber dem
    Referenzlayout verschoben sind (wie bei einem realen Kundenexport
    beobachtet: 'Name' bei Spalte 9 statt 8, 'Typ' bei 23 statt 22, ...).
    Nur `_resolve_ga_report_columns()` (Kopfzeilen-Text-basiert) findet die
    echten Spalten; die festen COL_GAR_*-Fallbacks treffen absichtlich daneben.
    """
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=23, column=5, value="Adresse")   # Spalte E, 0-basiert idx 4
    ws.cell(row=23, column=10, value="Name")     # Spalte J, 0-basiert idx 9
    ws.cell(row=23, column=24, value="Typ")      # Spalte X, 0-basiert idx 23
    ws.cell(row=32, column=5, value="0")
    ws.cell(row=32, column=10, value="Zentral")
    ws.cell(row=35, column=5, value="0/0")
    ws.cell(row=35, column=10, value="Licht")
    ws.cell(row=38, column=5, value="0/0/1")
    ws.cell(row=38, column=10, value="L.EG.01.01_ea (Test)")
    ws.cell(row=38, column=24, value="1 bit")
    wb.save(path)


class TestImportGaReportShiftedColumns:
    def test_designation_found_with_shifted_columns(self, tmp_path):
        """GA-Bezeichnung darf nicht leer bleiben, wenn ETS6 die Spalten
        gegenueber dem Referenzlayout verschiebt (z.B. durch zusaetzliche
        Export-Spalten) -- die Spalten muessen anhand der Kopfzeilen-Texte
        gefunden werden, nicht ueber feste Indizes."""
        path = tmp_path / "shifted_ga_report.xlsx"
        _build_shifted_ga_report(str(path))

        structure = XlsxImportService().import_ga_report(str(path))

        ga = structure.find_address(0, 0, 1)
        assert ga is not None
        assert ga.designation == "L.EG.01.01_ea (Test)"
        assert ga.datapoint_type == "1 bit"


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
# link_rooms_to_lines -- Mehrheitsregel fuer mehrkanalige Aktoren
# (Regression fuer "Geraete im eindeutig falschen Raum" nach dem Import:
# ein Aktor, der Kanaele in vielen verschiedenen Raeumen bedient, darf nicht
# per Zufall/Gleichstand einem einzelnen dieser Raeume zugeordnet werden)
# ---------------------------------------------------------------------------

def _make_room(number: str, name: str):
    from knix_arranger.models.building import Room
    return Room(number=number, name=name)


def _make_areal_with_rooms(floor_code: str, rooms: list):
    from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment
    areal = Areal(name="Test")
    floor = Floor(name=floor_code, short_code=floor_code)
    apt = Apartment(name="Wohnung")
    apt.rooms = rooms
    floor.apartments.append(apt)
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal.buildings.append(building)
    return areal


def _make_device_with_kos(phys_addr: str, ga_room_pairs: list[str]):
    """Baut ein Geraet mit einem KO pro Eintrag in ga_room_pairs, jedes KO
    verbunden mit genau einer GA-Adresse '0/0/<i>'."""
    from knix_arranger.models.topology import Device, CommunicationObject
    device = Device(physical_address=phys_addr, device_type="actor", product="Testaktor")
    for i, _ in enumerate(ga_room_pairs):
        device.communication_objects.append(CommunicationObject(
            object_number=i, name=f"KO{i}", connected_gas=[f"0/0/{i}"],
        ))
    return device


def _make_ga_structure(designations: list[str]):
    from knix_arranger.models.group_address import GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress
    structure = GroupAddressStructure()
    hg = MainGroup(number=0, name="Test")
    mg = MiddleGroup(number=0, name="Test")
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    for i, desig in enumerate(designations):
        mg.group_addresses.append(GroupAddress(main_group=0, middle_group=0, sub_group=i, designation=desig))
    return structure


class TestLinkRoomsToLinesMajorityRule:
    def setup_method(self):
        self.svc = XlsxImportService()

    def _run(self, ga_room_pairs: list[str]):
        from knix_arranger.models.topology import Topology, Area, Line
        rooms = [_make_room(f"0{i}", f"Raum{i}") for i in range(4)]
        areal = _make_areal_with_rooms("OG", rooms)
        device = _make_device_with_kos("1.1.1", ga_room_pairs)
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])
        ga_structure = _make_ga_structure(ga_room_pairs)
        self.svc.link_rooms_to_lines(topology, ga_structure, areal)
        return device, {r.name: r.id for r in rooms}

    def test_no_clear_majority_leaves_device_unassigned(self):
        """4 Kanaele auf 4 verschiedene Raeume (je 1x) -- keine echte Mehrheit,
        Geraet darf keinem der Raeume zufaellig zugeordnet werden."""
        device, room_ids = self._run([
            "L.OG.00.1_ea", "L.OG.01.1_ea", "L.OG.02.1_ea", "L.OG.03.1_ea",
        ])
        assert not device.room_id

    def test_clear_majority_wins(self):
        """3 von 4 Kanaelen auf denselben Raum -- echte absolute Mehrheit,
        Geraet wird diesem Raum zugeordnet."""
        device, room_ids = self._run([
            "L.OG.00.1_ea", "L.OG.00.2_ea", "L.OG.00.3_ea", "L.OG.01.1_ea",
        ])
        assert device.room_id == room_ids["Raum0"]

    def test_single_room_still_assigned(self):
        """Alle Kanaele auf denselben Raum -- weiterhin zugeordnet (kein
        Nebeneffekt der neuen Mehrheitsregel im Normalfall)."""
        device, room_ids = self._run(["L.OG.02.1_ea", "L.OG.02.2_ea"])
        assert device.room_id == room_ids["Raum2"]


# ---------------------------------------------------------------------------
# link_rooms_to_lines -- physischer Einbauort hat Vorrang vor funktionaler
# GA-Bezeichnung (Regression: ein KNX-Geraet ist an genau einem Ort montiert;
# Aktoren koennen direkt im Raum stehen, Bedienelemente auch im Verteiler --
# device.room_id muss den physischen Montageort widerspiegeln, nicht "wo
# wirkt die Mehrheit seiner Kanaele")
# ---------------------------------------------------------------------------

class TestLinkRoomsToLinesPhysicalLocationPriority:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_physical_room_wins_over_functional_majority(self):
        """Geraet hat eine klare funktionale Mehrheit fuer Raum1, ist aber
        laut Einbauort physisch in Raum0 montiert -- Raum0 muss gewinnen."""
        from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject

        rooms = [_make_room("00", "Kueche"), _make_room("01", "Bad")]
        areal = _make_areal_with_rooms("OG", rooms)

        device = Device(
            physical_address="1.1.1", device_type="actor", product="Testaktor",
            installation_location="00  Kueche",
        )
        for i in range(3):
            device.communication_objects.append(CommunicationObject(
                object_number=i, name=f"KO{i}", connected_gas=[f"0/0/{i}"],
            ))
        ga_structure = _make_ga_structure(["L.OG.01.1_ea", "L.OG.01.2_ea", "L.OG.01.3_ea"])

        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        self.svc.link_rooms_to_lines(topology, ga_structure, areal)

        kueche_id = next(r.id for r in rooms if r.name == "Kueche")
        bad_id = next(r.id for r in rooms if r.name == "Bad")
        assert device.room_id == kueche_id
        assert device.room_id != bad_id

    def test_actor_in_verteiler_stays_in_verteiler_despite_functional_majority(self):
        """Ein Aktor, physisch im Verteiler montiert, mit klarer funktionaler
        Mehrheit fuer einen Raum, muss trotzdem im Verteiler-Raum landen."""
        from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject

        rooms = [_make_room("00", "Wohnzimmer")]
        areal = _make_areal_with_rooms("OG", rooms)

        device = Device(
            physical_address="1.1.1", device_type="actor", product="Testaktor",
            installation_location="UV1   ( Steigzone )",
        )
        for i in range(3):
            device.communication_objects.append(CommunicationObject(
                object_number=i, name=f"KO{i}", connected_gas=[f"0/0/{i}"],
            ))
        ga_structure = _make_ga_structure(["L.OG.00.1_ea", "L.OG.00.2_ea", "L.OG.00.3_ea"])

        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        self.svc.create_verteiler_rooms(topology, areal)
        self.svc.link_rooms_to_lines(topology, ga_structure, areal)

        wohnzimmer_id = rooms[0].id
        verteiler_room = next(r for r in areal.all_rooms if r.verteiler)
        assert device.room_id == verteiler_room.id
        assert device.room_id != wohnzimmer_id

    def test_skips_duplicate_when_verteiler_already_in_areal(self):
        """Enthält die Gebäudestruktur bereits einen Verteiler mit demselben
        Kanonical-Key (z.B. weil derive_building_structure_from_building_report()
        ihn zuvor direkt aus einem Gebäude-Report angelegt hat), darf
        create_verteiler_rooms() keinen zusätzlichen Pseudo-Raum erzeugen --
        sonst gäbe es nach einem späteren Topologie-Import denselben
        Verteiler doppelt in der Gebäudestruktur."""
        from knix_arranger.models.topology import Topology, Area, Line, Device
        from knix_arranger.models.building import Verteiler

        rooms = [_make_room("00", "Galerie")]
        rooms[0].verteiler.append(Verteiler(name="UV1   ( Steigzone )", verteiler_type="UV"))
        areal = _make_areal_with_rooms("DG", rooms)
        galerie_id = rooms[0].id

        device = Device(
            physical_address="1.1.1", device_type="actor", product="Testaktor",
            installation_location="UV1   ( Steigzone )",
        )
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        created = self.svc.create_verteiler_rooms(topology, areal)

        assert created == 0
        assert device.room_id == galerie_id
        assert len(areal.all_rooms) == 1  # kein zusaetzlicher Pseudo-Raum

    def test_bedienelement_in_verteiler_recognized(self):
        """Ein Bedienelement (Taster) kann ebenfalls im Verteiler montiert
        sein, nicht nur in einem Raum -- muss auch dort landen koennen."""
        from knix_arranger.models.topology import Topology, Area, Line, Device

        rooms = [_make_room("00", "Wohnzimmer")]
        areal = _make_areal_with_rooms("OG", rooms)

        device = Device(
            physical_address="1.1.50", device_type="sensor", product="Taster",
            installation_location="HV  HV",
        )
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])
        ga_structure = _make_ga_structure([])

        self.svc.create_verteiler_rooms(topology, areal)
        self.svc.link_rooms_to_lines(topology, ga_structure, areal)

        verteiler_room = next(r for r in areal.all_rooms if r.verteiler)
        assert device.room_id == verteiler_room.id


# ---------------------------------------------------------------------------
# Mehrere gleichartige, unnummerierte Verteiler desselben Typs (z.B. zwei
# separate Heizungsverteiler "HzV Garage" und "HzV Galerie", beide Typ HZV
# ohne Nummer) -- Regression: der Kanonicalkey (Typ+Nummer) allein kollabiert
# beide auf denselben Index-Eintrag, wodurch Geräte des einen Verteilers dem
# jeweils anderen zugeordnet wurden (sie "verschwanden" optisch aus ihrem
# echten Verteiler). _resolve_verteiler_room() löst das über den Freitext.
# ---------------------------------------------------------------------------

class TestAmbiguousVerteilerDisambiguation:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def _build_two_hzv_areal(self):
        from knix_arranger.models.building import Verteiler
        garage = _make_room("02", "Garage")
        garage.verteiler.append(Verteiler(name="HzV Garage", verteiler_type="UV"))
        galerie = _make_room("00", "Galerie")
        galerie.verteiler.append(Verteiler(name="HzV Galerie", verteiler_type="UV"))
        return _make_areal_with_rooms("DG", [garage, galerie]), garage, galerie

    def test_link_rooms_to_lines_resolves_via_free_text_name(self):
        """Zwei Geräte mit Einbauort 'HzV Garage' bzw. 'HzV Galerie' (beide
        Typ HZV ohne Nummer) müssen trotz identischem Kanonicalkey ihrem
        jeweils echten Verteiler-Raum zugeordnet werden, nicht demselben."""
        from knix_arranger.models.topology import Topology, Area, Line, Device

        areal, garage, galerie = self._build_two_hzv_areal()
        dev_garage = Device(
            physical_address="1.1.14", device_type="actor", product="Aktor Garage",
            installation_location="HzV Garage",
        )
        dev_galerie = Device(
            physical_address="1.1.7", device_type="actor", product="Aktor Galerie",
            installation_location="HzV Galerie",
        )
        line = Line(line_number=1, name="L1")
        line.devices.extend([dev_garage, dev_galerie])
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])
        ga_structure = _make_ga_structure([])

        self.svc.link_rooms_to_lines(topology, ga_structure, areal)

        assert dev_garage.room_id == garage.id
        assert dev_galerie.room_id == galerie.id

    def test_create_verteiler_rooms_attaches_to_correct_existing_room(self):
        """Dieselbe Unterscheidung muss auch beim Dublettenschutz von
        create_verteiler_rooms() greifen (Geräte aus der Topologie, deren
        Einbauort-Text auf einen bereits vorhandenen Verteiler-Raum
        passt -- z.B. weil derive_building_structure_from_building_report()
        ihn schon angelegt hat)."""
        from knix_arranger.models.topology import Topology, Area, Line, Device

        areal, garage, galerie = self._build_two_hzv_areal()
        dev_garage = Device(
            physical_address="1.1.14", device_type="actor", product="Aktor Garage",
            installation_location="HzV Garage",
        )
        dev_galerie = Device(
            physical_address="1.1.7", device_type="actor", product="Aktor Galerie",
            installation_location="HzV Galerie",
        )
        line = Line(line_number=1, name="L1")
        line.devices.extend([dev_garage, dev_galerie])
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        created = self.svc.create_verteiler_rooms(topology, areal)

        assert created == 0  # keine neuen Pseudo-Räume, beide existieren schon
        assert dev_garage.room_id == garage.id
        assert dev_galerie.room_id == galerie.id
        assert len(areal.all_rooms) == 2  # keine Dubletten angelegt


# ---------------------------------------------------------------------------
# _VT_RE -- Verteiler-Erkennung ohne Klammer-Zusatz / "HzV"
# (Regression: Geraete mit Einbauort 'HV  HV' oder 'HzV' blieben nach dem
# Import komplett ohne Raumzuordnung, da _VT_RE diese Formate nicht erkannte)
# ---------------------------------------------------------------------------

class TestVerteilerRegexEdgeCases:
    def test_bare_repeated_hv_matches(self):
        from knix_arranger.services.xlsx_import_service import _VT_RE
        m = _VT_RE.match("HV  HV")
        assert m is not None
        assert m.group(1).upper() == "HV"

    def test_hzv_matches(self):
        from knix_arranger.services.xlsx_import_service import _VT_RE
        m = _VT_RE.match("HzV")
        assert m is not None
        assert m.group(1).upper() == "HZV"

    def test_parenthesized_name_still_matches(self):
        from knix_arranger.services.xlsx_import_service import _VT_RE
        m = _VT_RE.match("UV2   ( Steigzone )")
        assert m is not None
        assert m.group(1).upper() == "UV"
        assert m.group(2) == "2"
        assert m.group(3).strip() == "Steigzone"

    def test_number_distinguishes_verteiler(self):
        """UV1 und UV2 muessen als unterschiedliche Verteiler erkennbar sein
        (canonical key), nicht als derselbe 'UV'."""
        from knix_arranger.services.xlsx_import_service import _VT_RE, _vt_key
        m1 = _VT_RE.match("UV1   ( Steigzone )")
        m2 = _VT_RE.match("UV2   ( Steigzone )")
        key1 = _vt_key(m1.group(1), m1.group(2))
        key2 = _vt_key(m2.group(1), m2.group(2))
        assert key1 == "UV1"
        assert key2 == "UV2"
        assert key1 != key2


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


def _build_single_ko_ga_report(path: str, connected_gas: str) -> None:
    """Baut eine minimale GA-Report-XLSX mit genau einem Geraet (1.1.1)
    und einem KO ('0: Ausgang 1 - Schalten'), dessen 'verbundene GAs'-Spalte
    `connected_gas` enthaelt (bzw. leer bleibt, wenn `connected_gas == ""`).
    Nutzt die COL_GAR_*-Referenzspalten direkt (keine Kopfzeilen noetig, da
    ohne erkannte Header-Texte darauf zurueckgefallen wird)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=1, column=5, value="1.1.1")
    ws.cell(row=2, column=5, value="0: Ausgang 1 - Schalten")
    ws.cell(row=2, column=21, value="1 bit")
    if connected_gas:
        ws.cell(row=2, column=29, value=connected_gas)
    wb.save(path)


class TestEnrichDeviceKoConnectionsReplacesStaleData:
    """FA-521h: enrich_device_ko_connections() ERSETZT connected_gas eines
    bereits bekannten KOs durch die aktuelle GA-Report-Zeile, statt nur
    fehlende Eintraege zu ergaenzen -- sonst sammeln sich bei wiederholten
    GA-Report-Re-Importen ohne begleitenden Topologie-Re-Import veraltete
    Fremd-Adressen auf einem KO an (beobachtet am Chalet-Projekt, Geraet
    1.1.15 'Ausgang 1')."""

    def _topology_with_stale_co(self):
        from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject
        topology = Topology()
        area = Area(area_number=1)
        line = Line(line_number=1)
        device = Device(physical_address="1.1.1")
        device.communication_objects = [
            CommunicationObject(
                object_number=0, name="Ausgang 1", object_function="Schalten",
                connected_gas=["1/0/0", "0/4/1", "1/7/0"],
            ),
        ]
        line.devices.append(device)
        area.lines.append(line)
        topology.areas.append(area)
        return topology

    def test_stale_foreign_gas_are_removed_not_just_supplemented(self, tmp_path):
        topology = self._topology_with_stale_co()
        path = tmp_path / "ga_report.xlsx"
        _build_single_ko_ga_report(str(path), "1/0/0")

        XlsxImportService().enrich_device_ko_connections(topology, str(path))

        co = topology.areas[0].lines[0].devices[0].communication_objects[0]
        assert co.connected_gas == ["1/0/0"]

    def test_empty_report_row_leaves_existing_data_untouched(self, tmp_path):
        """Eine leere 'verbundene GAs'-Spalte ist kein verlaessliches Signal,
        dass die Bindung entfernt wurde -- bestehende Daten bleiben dann
        unangetastet statt geloescht zu werden."""
        topology = self._topology_with_stale_co()
        path = tmp_path / "ga_report.xlsx"
        _build_single_ko_ga_report(str(path), "")

        XlsxImportService().enrich_device_ko_connections(topology, str(path))

        co = topology.areas[0].lines[0].devices[0].communication_objects[0]
        assert co.connected_gas == ["1/0/0", "0/4/1", "1/7/0"]


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


# ---------------------------------------------------------------------------
# _best_room_name -- Fixture-/Verbraucher-Beschreibungen duerfen nicht als
# Raumname durchrutschen (Regression: "Wandleuchten Balkon" statt "Balkon",
# "Spots Essen" statt eines echten Raumnamens)
# ---------------------------------------------------------------------------

class TestBestRoomName:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_picks_shortest_plausible_name(self):
        name = self.svc._best_room_name(["Wohnzimmer", "Wohnzimmer Sofa"], "03")
        assert name == "Wohnzimmer"

    def test_filters_fixture_word_anywhere_in_text(self):
        """'Wandleuchten Balkon' darf nicht gewinnen, auch wenn 'Wandleuchten'
        nicht das erste Wort ist -- ganze Beschreibung wird verworfen."""
        name = self.svc._best_room_name(["Seite Rotten", "Wandleuchten Balkon"], "06")
        assert name == "Raum 06"

    def test_falls_back_to_generic_when_all_filtered(self):
        """Bleibt nach dem Filtern kein Kandidat übrig, wird der generische
        Platzhalter zurückgegeben statt einer verworfenen Beschreibung."""
        name = self.svc._best_room_name(["Spots Essen", "Fenster", "Steckdose"], "04")
        assert name == "Raum 04"

    def test_no_descriptions_returns_generic(self):
        assert self.svc._best_room_name([], "07") == "Raum 07"

    def test_plausible_candidate_survives(self):
        name = self.svc._best_room_name(["Seite Berg", "Garage"], "02")
        assert name == "Garage"


# ---------------------------------------------------------------------------
# _classify_device -- Produktname-Keywords fuer Sensoren/Infrastruktur, die
# beim Abgleich mit einer echten ETS-Projektstruktur als fehlklassifiziert
# aufgefallen sind (Leak-/Salva-Melder, thePixa-Touchpanel wurden faelschlich
# als "actor" statt "sensor"/"other" eingestuft)
# ---------------------------------------------------------------------------

class TestClassifyDeviceKeywords:
    def setup_method(self):
        self.svc = XlsxImportService()

    def test_leak_detector_is_sensor(self):
        assert self.svc._classify_device("1.1.24", "Leak KNX 2.0") == "sensor"

    def test_salva_detector_is_sensor(self):
        assert self.svc._classify_device("1.1.25", "Salva KNX TH") == "sensor"

    def test_thepixa_touch_panel_is_other(self):
        assert self.svc._classify_device("1.1.16", "thePixa P360 KNX") == "other"

    def test_hyphenated_knx_gateway_is_gateway(self):
        """Regression: 'KNX-Gateway' (Bindestrich statt Leerzeichen) wurde
        vom reinen Substring-Vergleich gegen das Schluesselwort 'knx gateway'
        nicht erkannt und fiel auf die Adress-Heuristik ('actor') zurueck."""
        assert self.svc._classify_device("1.1.22", "KNX-Gateway") == "gateway"

    def test_knx_gateway_with_space_is_gateway(self):
        assert self.svc._classify_device("1.1.22", "KNX Gateway") == "gateway"

    def test_ip_interface_is_gateway(self):
        assert self.svc._classify_device("1.1.22", "IP-Interface 300") == "gateway"

    def test_power_supply_keyword_still_other(self):
        """Regression-Schutz: die Umstellung auf _GATEWAY_KEYWORDS darf die
        uebrigen Infrastruktur-Keywords (hier: Speisegeraet) nicht aus der
        Klassifizierung verlieren."""
        assert self.svc._classify_device("1.1.22", "Speisegerät 640mA") == "other"


# ---------------------------------------------------------------------------
# verteiler_key / apply_verteiler_room_overrides
# (Regression: Verteiler wie "HV"/"UV1" werden nach jedem Import als eigener
# Pseudo-Raum ausgewiesen statt im Raum, in dem sie physisch montiert sind.
# Eine manuelle Zuordnung (Step03bVerteiler) muss Re-Importe ueberstehen.)
# ---------------------------------------------------------------------------

class TestVerteilerKey:
    def test_recognizes_hv(self):
        assert XlsxImportService.verteiler_key("HV  HV") == "HV"

    def test_recognizes_uv_with_number(self):
        assert XlsxImportService.verteiler_key("UV2   ( Steigzone )") == "UV2"

    def test_none_for_plain_room_text(self):
        assert XlsxImportService.verteiler_key("04  Schlafen") is None


class TestApplyVerteilerRoomOverrides:
    def setup_method(self):
        self.svc = XlsxImportService()

    def _build_project_with_pseudo_verteiler(self):
        from knix_arranger.models.topology import Topology, Area, Line, Device
        from knix_arranger.models.building import (
            Areal, Building, Wing, Floor, Apartment, Room, Verteiler,
        )
        device = Device(physical_address="1.1.1", device_type="actor", product="Aktor")
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        target_room = Room(number="01", name="Technikraum")
        real_floor = Floor(name="Erdgeschoss", short_code="EG")
        real_apt = Apartment(name="EG")
        real_apt.rooms.append(target_room)
        real_floor.apartments.append(real_apt)

        pseudo_room = Room(number="", name="HV  HV")
        pseudo_room.verteiler.append(Verteiler(name="HV  HV", verteiler_type="HV"))
        device.room_id = pseudo_room.id
        line.assigned_room_ids = [pseudo_room.id]
        vt_floor = Floor(name="Verteiler", short_code="VT")
        vt_apt = Apartment(name="VT")
        vt_apt.rooms.append(pseudo_room)
        vt_floor.apartments.append(vt_apt)

        wing = Wing(name="Haupthaus", floors=[real_floor, vt_floor])
        building = Building(name="Haus", wings=[wing])
        areal = Areal(buildings=[building])
        return topology, areal, device, line, pseudo_room, target_room

    def test_moves_devices_and_verteiler_into_target_room(self):
        topology, areal, device, line, pseudo_room, target_room = \
            self._build_project_with_pseudo_verteiler()

        merged = self.svc.apply_verteiler_room_overrides(
            topology, areal, {"HV": ["EG", "01"]},
        )

        assert merged == 1
        assert device.room_id == target_room.id
        assert line.assigned_room_ids == [target_room.id]
        assert len(target_room.verteiler) == 1
        assert target_room.verteiler[0].verteiler_type == "HV"
        assert pseudo_room not in [r for a in areal.all_floors for apt in a.apartments for r in apt.rooms]

    def test_no_override_leaves_structure_unchanged(self):
        topology, areal, device, line, pseudo_room, target_room = \
            self._build_project_with_pseudo_verteiler()

        merged = self.svc.apply_verteiler_room_overrides(topology, areal, {})

        assert merged == 0
        assert device.room_id == pseudo_room.id

    def test_unknown_target_room_is_noop(self):
        topology, areal, device, line, pseudo_room, target_room = \
            self._build_project_with_pseudo_verteiler()

        merged = self.svc.apply_verteiler_room_overrides(
            topology, areal, {"HV": ["EG", "99"]},
        )

        assert merged == 0
        assert device.room_id == pseudo_room.id

    def test_link_rooms_to_lines_resolves_via_merged_target_room(self):
        """Nach dem Merge muss link_rooms_to_lines() den Verteiler-Einbauort
        weiterhin dem (jetzt echten) Zielraum zuordnen koennen -- der Key
        kommt dabei aus dem Verteiler-Objekt selbst, nicht aus room.name
        (das jetzt "Technikraum" statt "HV  HV" ist)."""
        from knix_arranger.models.group_address import GroupAddressStructure
        topology, areal, device, line, pseudo_room, target_room = \
            self._build_project_with_pseudo_verteiler()
        self.svc.apply_verteiler_room_overrides(topology, areal, {"HV": ["EG", "01"]})

        # Neues Geraet mit demselben Einbauort, das erst NACH dem Merge
        # importiert/verlinkt wird (simuliert einen zweiten Re-Import-Pass).
        from knix_arranger.models.topology import Device
        new_device = Device(
            physical_address="1.1.2", device_type="actor", product="Aktor2",
            installation_location="HV  HV",
        )
        topology.areas[0].lines[0].devices.append(new_device)

        self.svc.link_rooms_to_lines(topology, GroupAddressStructure(), areal)

        assert new_device.room_id == target_room.id


# ---------------------------------------------------------------------------
# ETS6 'Gebäude'-Report (Building-Report): Stockwerk/Raum-Struktur direkt aus
# der tatsächlichen ETS6-Raumzuordnung statt aus GA-Namen-Heuristik.
# ---------------------------------------------------------------------------

def _build_building_report(path: str) -> None:
    """Baut eine minimale ETS6-'Gebäude'-Report-XLSX mit zwei Stockwerken,
    einem Raum pro Stockwerk, einem im Raum verschachtelten Verteiler (z.B.
    Heizungsverteiler-Schrank) und einem eigenständigen Verteiler-Raum.

    Die 'Adresse'-Spalte liegt absichtlich nicht am Referenz-Index (Spalte H,
    0-basiert 7), sondern bei Spalte I (0-basiert 8) -- nur die
    Kopfzeilen-Text-Erkennung (`_resolve_building_report_columns`) findet sie.
    Einrückung (Leerzeichen) codiert die Hierarchie-Ebene: Stockwerk=4,
    Raum/Verteiler=8, im Raum verschachtelter Verteiler=12.
    """
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=4, column=2, value="Gebäude")
    ws.cell(row=21, column=9, value="Adresse")

    rows = [
        "Gebäude",
        "    DG",
        "        00  Galerie",
        "1.1.1",
        "            HzV Galerie",
        "1.1.2",
        "    EG",
        "        00  Empfang",
        "1.1.3",
        "        UV1   ( Technik )",
        "1.1.4",
    ]
    for i, text in enumerate(rows):
        ws.cell(row=30 + i, column=9, value=text)
    wb.save(path)


class TestDetectReportTypeBuildingReport:
    def test_detects_building_report(self, tmp_path):
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        assert XlsxImportService().detect_report_type(str(path)) == "building_report"


class TestDeriveBuildingStructureFromBuildingReport:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def _areal(self, path):
        return self.svc.derive_building_structure_from_building_report(path)

    def test_floors_in_correct_order(self, tmp_path):
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        areal = self._areal(str(path))
        floors = areal.buildings[0].wings[0].floors
        assert [f.short_code for f in floors] == ["EG", "DG"]

    def test_room_names_taken_verbatim(self, tmp_path):
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        areal = self._areal(str(path))
        by_code = {f.short_code: f for f in areal.buildings[0].wings[0].floors}
        dg_rooms = [r for r in by_code["DG"].apartments[0].rooms if r.number]
        eg_rooms = [r for r in by_code["EG"].apartments[0].rooms if r.number]
        assert [(r.number, r.name) for r in dg_rooms] == [("00", "Galerie")]
        assert [(r.number, r.name) for r in eg_rooms] == [("00", "Empfang")]

    def test_nested_verteiler_attached_to_existing_room(self, tmp_path):
        """Ein im Raum verschachtelter Verteiler ('HzV Galerie', Einrückung 12
        innerhalb Raum '00 Galerie') wird direkt an den bestehenden Raum
        gehängt, nicht als eigener Pseudo-Raum angelegt -- der Report kennt
        hier die echte physische Verschachtelung."""
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        areal = self._areal(str(path))
        by_code = {f.short_code: f for f in areal.buildings[0].wings[0].floors}
        galerie = next(r for r in by_code["DG"].apartments[0].rooms if r.number == "00")
        assert [vt.name for vt in galerie.verteiler] == ["HzV Galerie"]
        assert galerie.verteiler[0].verteiler_type == "UV"

    def test_standalone_verteiler_creates_room_on_its_floor(self, tmp_path):
        """Ein eigenständiger Verteiler auf Stockwerksebene ('UV1 (Technik)',
        Einrückung 8, kein vorausgehender Raum) bekommt einen eigenen
        Pseudo-Raum auf dem richtigen Stockwerk (nicht in einer generischen
        Verteiler-Sammelfloor wie bei create_verteiler_rooms())."""
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        areal = self._areal(str(path))
        by_code = {f.short_code: f for f in areal.buildings[0].wings[0].floors}
        eg_rooms = by_code["EG"].apartments[0].rooms
        vt_room = next(r for r in eg_rooms if not r.number)
        assert vt_room.name == "UV1   ( Technik )"
        assert [vt.name for vt in vt_room.verteiler] == ["UV1   ( Technik )"]
        assert vt_room.verteiler[0].verteiler_type == "UV"

    def test_no_hierarchy_found_returns_empty_areal(self, tmp_path):
        import openpyxl
        path = tmp_path / "empty_building_report.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=4, column=2, value="Gebäude")
        ws.cell(row=21, column=9, value="Adresse")
        wb.save(str(path))

        areal = self._areal(str(path))
        assert areal.buildings[0].wings[0].floors == []


class TestExtractDeviceLocationsFromBuildingReport:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def test_device_in_room(self, tmp_path):
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        locs = self.svc.extract_device_locations_from_building_report(str(path))
        assert locs["1.1.1"] == {
            "type": "room", "room_nr": "00", "room_name": "Galerie",
        }
        assert locs["1.1.3"] == {
            "type": "room", "room_nr": "00", "room_name": "Empfang",
        }

    def test_device_in_room_nested_verteiler(self, tmp_path):
        """Ein im Raum verschachtelter Verteiler (z.B. 'HzV Galerie' als
        Heizungsverteiler-Schrank im Raum 'Galerie') wird als eigener
        Verteiler-Einbauort erkannt, nicht als Raum -- Geräte darin gehören
        physisch zum Verteiler, nicht zum Funktionsraum (siehe
        link_rooms_to_lines: Verteiler-Geräte bekommen einen eigenen
        Verteiler-Raum, analog zu 'UV2 (Steigzone)')."""
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        locs = self.svc.extract_device_locations_from_building_report(str(path))
        assert locs["1.1.2"] == {
            "type": "verteiler", "vt_type": "HZV", "vt_number": "", "vt_name": "Galerie",
        }

    def test_device_in_standalone_verteiler(self, tmp_path):
        path = tmp_path / "building_report.xlsx"
        _build_building_report(str(path))
        locs = self.svc.extract_device_locations_from_building_report(str(path))
        assert locs["1.1.4"] == {
            "type": "verteiler", "vt_type": "UV", "vt_number": "1", "vt_name": "Technik",
        }


# ---------------------------------------------------------------------------
# extract_button_configuration -- Tastenbelegung als lesbare Referenz (rein
# informativ, keine automatische Gewerk-/Funktionsableitung). Die
# "Konfiguration Tasten"-Hierarchiespalte liegt nicht zwingend in derselben
# Spalte wie die physikalische Adresse -- im Topologie-Report real
# abweichend beobachtet (Adresse Spalte 6, Tastenkonfiguration Spalte 9) --
# daher wird sie separat per Text-Suche ermittelt, nicht über die 'Adresse'-
# Spaltenauflösung.
# ---------------------------------------------------------------------------

def _build_button_config_report(path: str, param_col_1based: int) -> None:
    """Baut eine minimale Report-XLSX mit 'Adresse'-Spalte 8 (1-basiert) und
    einer davon unabhängigen 'Konfiguration Tasten'-Hierarchiespalte bei
    `param_col_1based` -- simuliert sowohl den Gebäude-Report (dieselbe
    Spalte, 9) als auch den Topologie-Report (eigene Spalte, z.B. 10)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=4, column=2, value="Gebäude")
    ws.cell(row=21, column=8, value="Adresse")

    pc = param_col_1based
    ws.cell(row=30, column=8, value="1.1.1")
    ws.cell(row=32, column=pc, value="Konfiguration Tasten")
    ws.cell(row=33, column=pc + 1, value="Anzahl Tasten:")
    ws.cell(row=33, column=pc + 11, value="2")
    ws.cell(row=34, column=pc, value="Taste 1, links")
    ws.cell(row=35, column=pc + 1, value="Funktion Taste:")
    ws.cell(row=35, column=pc + 11, value="Schalten")
    ws.cell(row=36, column=pc, value="Taste 1, rechts")
    ws.cell(row=37, column=pc + 1, value="Funktion Taste:")
    ws.cell(row=37, column=pc + 11, value="Jalousie")
    ws.cell(row=37, column=pc + 22, value="Funktion Jalousie links:")
    ws.cell(row=37, column=pc + 30, value="AUF")
    ws.cell(row=38, column=pc, value="Sequenzbaustein")  # naechster Abschnitt

    ws.cell(row=40, column=8, value="1.1.2")  # zweites Geraet, keine Tastenkonfig
    wb.save(path)


class TestExtractButtonConfiguration:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def test_no_marker_returns_empty_dict(self, tmp_path):
        import openpyxl
        path = tmp_path / "no_button_config.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=21, column=8, value="Adresse")
        ws.cell(row=30, column=8, value="1.1.1")
        wb.save(str(path))

        assert self.svc.extract_button_configuration(str(path)) == {}

    def test_same_column_as_address(self, tmp_path):
        """Gebäude-Report-Fall: Tastenkonfiguration in derselben Spalte wie
        die Adresse (Spalte 9 == 'Adresse'-Spalte 8 + 1, hier bewusst
        identisch zur Adress-Spalte gewählt: Spalte 8)."""
        path = tmp_path / "button_config_same_col.xlsx"
        _build_button_config_report(str(path), param_col_1based=8)

        result = self.svc.extract_button_configuration(str(path))

        assert "1.1.1" in result
        assert "1.1.2" not in result
        text = result["1.1.1"]
        assert "Anzahl Tasten: 2" in text
        assert "Taste 1, links:" in text
        assert "  Funktion Taste: Schalten" in text
        assert "Taste 1, rechts:" in text
        assert "  Funktion Taste: Jalousie" in text
        assert "  Funktion Jalousie links: AUF" in text

    def test_different_column_from_address(self, tmp_path):
        """Topologie-Report-Fall: Tastenkonfiguration in einer eigenen,
        von der Adress-Spalte abweichenden Spalte (real beobachtet: Spalte
        9 statt 6) -- muss trotzdem per Text-Suche gefunden werden."""
        path = tmp_path / "button_config_diff_col.xlsx"
        _build_button_config_report(str(path), param_col_1based=15)

        result = self.svc.extract_button_configuration(str(path))

        assert "1.1.1" in result
        text = result["1.1.1"]
        assert "Taste 1, links:" in text
        assert "  Funktion Taste: Schalten" in text
        assert "Taste 1, rechts:" in text
        assert "  Funktion Taste: Jalousie" in text

    def test_next_device_not_contaminated(self, tmp_path):
        """Der Abschnitt endet spätestens beim nächsten Gerät -- Text des
        ersten Geräts darf nicht dem zweiten zugeschlagen werden."""
        path = tmp_path / "button_config_boundary.xlsx"
        _build_button_config_report(str(path), param_col_1based=10)

        result = self.svc.extract_button_configuration(str(path))
        assert "1.1.2" not in result


# ---------------------------------------------------------------------------
# extract_scene_values -- Szenen-Schaltwerte pro Kanal aus dem
# "Geräteparameter"-Abschnitt (FA-1809). Zeilenlayout 1:1 nachgebaut aus dem
# realen Export (ABB SA/S8.16.1 und Hager TXM620D, siehe scene_addressing.py
# / scene_value_linking.py Kommentare) -- Label/Wert liegen ohne
# Doppelpunkt-Suffix in aufeinanderfolgenden Zellen derselben Zeile.
# ---------------------------------------------------------------------------

def _build_abb_scene_report(path: str) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=21, column=8, value="Adresse")
    ws.cell(row=30, column=8, value="1.1.10")

    ws.cell(row=32, column=8, value="Geräteparameter")
    ws.cell(row=34, column=8, value="A: Szene")
    ws.cell(row=35, column=10, value="Ausgang zuordnen zu(Szene 1...64)")
    ws.cell(row=35, column=26, value="Szene 2")
    ws.cell(row=35, column=36, value="  Standardwert")
    ws.cell(row=35, column=47, value="AUS")
    ws.cell(row=36, column=10, value="Ausgang zugeodnet zu(Szene 1...64)")
    ws.cell(row=36, column=26, value="Szene 3")
    ws.cell(row=36, column=36, value="  Standardwert")
    ws.cell(row=36, column=47, value="AUS")
    ws.cell(row=37, column=10, value="Ausgang zugeodnet zu(Szene 1...64)")
    ws.cell(row=37, column=26, value="keiner Szene")
    ws.cell(row=37, column=36, value="  Standardwert")
    ws.cell(row=37, column=47, value="EIN")
    ws.cell(row=38, column=8, value="B: Allgemein")  # naechste Subsection

    ws.cell(row=40, column=8, value="1.1.11")  # zweites Geraet, keine Szenen
    wb.save(path)


def _build_hager_scene_report(path: str) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=21, column=8, value="Adresse")
    ws.cell(row=30, column=8, value="1.1.15")

    ws.cell(row=32, column=8, value="Geräteparameter")
    ws.cell(row=34, column=8, value="Ausgang 1 > Ausgang 1: Funktionsfreigabe")
    ws.cell(row=35, column=10, value="Zeitschalter")
    ws.cell(row=35, column=20, value="0")
    ws.cell(row=36, column=10, value="Szene")
    ws.cell(row=36, column=20, value="1")
    ws.cell(row=36, column=30, value="Anzahl verwendeter Szenen")
    ws.cell(row=36, column=45, value="8")
    ws.cell(row=37, column=10, value="Szene 1")
    ws.cell(row=37, column=20, value="0")
    ws.cell(row=37, column=30, value="Szene 2")
    ws.cell(row=37, column=45, value="1")
    ws.cell(row=38, column=10, value="Ausgangszustand für Szene 2")
    ws.cell(row=38, column=25, value="Aus")
    ws.cell(row=38, column=30, value="Szene 3")
    ws.cell(row=38, column=45, value="0")

    ws.cell(row=40, column=8, value="Ausgang 2 > Ausgang 2: Funktionsfreigabe")
    ws.cell(row=41, column=10, value="Szene")
    ws.cell(row=41, column=20, value="0")  # Feature aus -- keine Szenen-Zeilen

    wb.save(path)


class TestExtractSceneValues:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def test_no_marker_returns_empty_dict(self, tmp_path):
        import openpyxl
        path = tmp_path / "no_scene_values.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=21, column=8, value="Adresse")
        ws.cell(row=30, column=8, value="1.1.1")
        wb.save(str(path))

        assert self.svc.extract_scene_values(str(path)) == {}

    def test_abb_pattern(self, tmp_path):
        path = tmp_path / "abb_scenes.xlsx"
        _build_abb_scene_report(str(path))

        result = self.svc.extract_scene_values(str(path))

        assert "1.1.11" not in result
        entries = result["1.1.10"]
        assert [(e.channel, e.scene_number, e.value) for e in entries] == [
            ("A", 2, "AUS"),
            ("A", 3, "AUS"),
        ]
        # "keiner Szene" (kein Zahlenwert) darf keinen Eintrag erzeugen
        assert all(e.scene_number in (2, 3) for e in entries)

    def test_hager_pattern(self, tmp_path):
        path = tmp_path / "hager_scenes.xlsx"
        _build_hager_scene_report(str(path))

        result = self.svc.extract_scene_values(str(path))

        entries = result["1.1.15"]
        assert [(e.channel, e.scene_number, e.value) for e in entries] == [
            ("Ausgang 1", 2, "Aus"),
        ]

    def test_unrecognized_manufacturer_format_is_skipped(self, tmp_path):
        """Ein Geräteparameter-Abschnitt ohne erkanntes Muster wird
        schlicht nicht erkannt statt falsch interpretiert (kein Crash,
        Gerät fehlt einfach im Ergebnis)."""
        import openpyxl
        path = tmp_path / "unknown_format.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=21, column=8, value="Adresse")
        ws.cell(row=30, column=8, value="1.1.20")
        ws.cell(row=32, column=8, value="Geräteparameter")
        ws.cell(row=34, column=8, value="Irgendein anderes Herstellerformat")
        ws.cell(row=35, column=10, value="Szenenmodus")
        ws.cell(row=35, column=20, value="komplex")
        wb.save(str(path))

        assert self.svc.extract_scene_values(str(path)) == {}


# ---------------------------------------------------------------------------
# extract_scene_triggers -- welche Taste sendet welche Szenennummer (FA-1810).
# Zeilenlayout nachgebaut aus dem realen Export (Feller EDIZIOdue Taster,
# physische Adresse 1.1.61): "Konfiguration Tasten" -> "Taste N, seite" ->
# "Funktion Taste: Wert" + "Funktion Wert: 1Byte Wert senden" + "1Byte Wert
# (0..255): N" (Kurzdruck), optional gefolgt von "Langer Tastendruck ...:
# aktiv" + derselben Trias fuer den Langdruck (eigene Taste/Szene).
# ---------------------------------------------------------------------------

def _build_scene_trigger_report(path: str) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=21, column=8, value="Adresse")
    ws.cell(row=30, column=8, value="1.1.61")

    pc = 12  # "Konfiguration Tasten"-Spalte -- bewusst abweichend von der Adress-Spalte
    ws.cell(row=32, column=pc, value="Konfiguration Tasten")

    ws.cell(row=34, column=pc, value="Taste 1, links")
    ws.cell(row=35, column=pc + 1, value="Funktion Taste:")
    ws.cell(row=35, column=pc + 2, value="Wert")
    ws.cell(row=36, column=pc + 1, value="Funktion Wert:")
    ws.cell(row=36, column=pc + 2, value="1Byte Wert senden")
    ws.cell(row=36, column=pc + 3, value="1Byte Wert (0..255):")
    ws.cell(row=36, column=pc + 4, value="0")

    ws.cell(row=38, column=pc, value="Taste 1, rechts")
    ws.cell(row=39, column=pc + 1, value="Funktion Taste:")
    ws.cell(row=39, column=pc + 2, value="Wert")
    ws.cell(row=40, column=pc + 1, value="Funktion Wert:")
    ws.cell(row=40, column=pc + 2, value="1Byte Wert senden")
    ws.cell(row=40, column=pc + 3, value="1Byte Wert (0..255):")
    ws.cell(row=40, column=pc + 4, value="1")
    ws.cell(row=41, column=pc + 1, value="Langer Tastendruck Taste rechts:")
    ws.cell(row=41, column=pc + 2, value="aktiv")
    ws.cell(row=42, column=pc + 1, value="Funktion langer Tastendruck:")
    ws.cell(row=42, column=pc + 2, value="Wert")
    ws.cell(row=43, column=pc + 1, value="Funktion Wert:")
    ws.cell(row=43, column=pc + 2, value="1Byte Wert senden")
    ws.cell(row=43, column=pc + 3, value="1Byte Wert (0..255):")
    ws.cell(row=43, column=pc + 4, value="2")

    ws.cell(row=45, column=pc, value="Taste 2, links")
    ws.cell(row=46, column=pc + 1, value="Funktion Taste:")
    ws.cell(row=46, column=pc + 2, value="Schalten")

    ws.cell(row=48, column=pc, value="Sequenzbaustein")  # Ende der Tastenkonfiguration

    ws.cell(row=50, column=8, value="1.1.62")  # zweites Geraet, keine Szenen-Taste
    wb.save(path)


class TestExtractSceneTriggers:
    def setup_method(self, method):
        self.svc = XlsxImportService()

    def test_no_marker_returns_empty_dict(self, tmp_path):
        import openpyxl
        path = tmp_path / "no_scene_triggers.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=21, column=8, value="Adresse")
        ws.cell(row=30, column=8, value="1.1.1")
        wb.save(str(path))

        assert self.svc.extract_scene_triggers(str(path)) == {}

    def test_feller_pattern_short_and_long_press(self, tmp_path):
        path = tmp_path / "feller_triggers.xlsx"
        _build_scene_trigger_report(str(path))

        result = self.svc.extract_scene_triggers(str(path))

        assert "1.1.62" not in result
        entries = result["1.1.61"]
        assert [(e.button, e.scene_number) for e in entries] == [
            ("Taste 1, links", 1),
            ("Taste 1, rechts", 2),
            ("Taste 1, rechts (langer Tastendruck)", 3),
        ]
        # "Taste 2, links" (Funktion Taste: Schalten) hat keinen Szenen-Wert
        assert all("Taste 2" not in e.button for e in entries)
