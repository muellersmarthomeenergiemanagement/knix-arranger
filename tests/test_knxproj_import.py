"""
Tests fuer KnxprojImportService (FA-521 bis FA-526).
Nutzt die echte Referenzdatei 241114_Chalet.knxproj.
"""
from __future__ import annotations
import os
import zipfile
import xml.etree.ElementTree as ET
import pytest
from knix_arranger.services.knxproj_import_service import (
    KnxprojImportService,
    KnxprojImportError,
)

CHALET = os.path.join(os.path.dirname(__file__), "..", "241114_Chalet 64.knxproj")


@pytest.fixture
def project():
    svc = KnxprojImportService()
    return svc.import_knxproj(CHALET)


# ------------------------------------------------------------------
# FA-521: Datei oeffnen
# ------------------------------------------------------------------

def test_file_not_found():
    svc = KnxprojImportService()
    with pytest.raises(FileNotFoundError):
        svc.import_knxproj("nicht_vorhanden.knxproj")


def test_invalid_zip(tmp_path):
    bad = tmp_path / "bad.knxproj"
    bad.write_bytes(b"this is not a zip file")
    svc = KnxprojImportService()
    with pytest.raises(KnxprojImportError):
        svc.import_knxproj(str(bad))


# ------------------------------------------------------------------
# FA-522: Projektmetadaten
# ------------------------------------------------------------------

def test_project_name(project):
    assert "chalet" in project.name.lower() or len(project.name) > 0


# ------------------------------------------------------------------
# FA-522: Gruppenadressen
# ------------------------------------------------------------------

def test_ga_count(project):
    assert len(project.group_addresses.all_addresses()) == 1044


def test_main_group_count(project):
    assert len(project.group_addresses.main_groups) == 6


def test_main_group_names(project):
    names = {hg.name for hg in project.group_addresses.main_groups}
    assert "Zentral" in names
    assert "OG" in names


def test_ga_address_decoding(project):
    """Alle GAs muessen gueltige Adressen haben."""
    for ga in project.group_addresses.all_addresses():
        assert 0 <= ga.main_group <= 31
        assert 0 <= ga.middle_group <= 7
        assert 0 <= ga.sub_group <= 255


def test_ga_dpt_present(project):
    """Mindestens einige GAs sollen einen DPT haben."""
    dpts = [ga.datapoint_type for ga in project.group_addresses.all_addresses()
            if ga.datapoint_type]
    assert len(dpts) > 10


# ------------------------------------------------------------------
# FA-522b: Description-Fallback aus Klammer-Zusatz (Paritaet zum XLSX-Import)
# ------------------------------------------------------------------

def _installation_with_ga(name: str, description: str = "", comment: str = "") -> ET.Element:
    """Baut ein minimales <Installation>-Fragment mit einer einzigen GA (Adresse 0/0/1)."""
    ns = "http://knx.org/xml/project/23"
    ET.register_namespace("", ns)
    installation = ET.Element(f"{{{ns}}}Installation")
    gas = ET.SubElement(installation, f"{{{ns}}}GroupAddresses")
    ranges = ET.SubElement(gas, f"{{{ns}}}GroupRanges")
    hg = ET.SubElement(ranges, f"{{{ns}}}GroupRange", RangeStart="0", Name="HG")
    mg = ET.SubElement(hg, f"{{{ns}}}GroupRange", RangeStart="0", Name="MG")
    attribs = {"Address": "1", "Name": name}
    if description:
        attribs["Description"] = description
    if comment:
        attribs["Comment"] = comment
    ET.SubElement(mg, f"{{{ns}}}GroupAddress", **attribs)
    return installation


def test_description_fallback_from_parentheses():
    """Ist ETS-Description/Comment leer, wird der Klammer-Zusatz aus der
    Bezeichnung als Description uebernommen (Paritaet zum XLSX-Import)."""
    installation = _installation_with_ga("L.004.1_ea ( Dusche / WC )")
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == "Dusche / WC"


def test_description_fallback_does_not_override_real_description():
    """Eine echte, gepflegte ETS-Description hat Vorrang vor dem Klammer-Fallback."""
    installation = _installation_with_ga(
        "L.004.1_ea ( Dusche / WC )", description="Echte ETS-Beschreibung"
    )
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == "Echte ETS-Beschreibung"


def test_description_fallback_empty_without_parentheses():
    """Ohne Klammer-Zusatz und ohne ETS-Description bleibt description leer."""
    installation = _installation_with_ga("L.004.1_ea")
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == ""


# ------------------------------------------------------------------
# FA-523: Gebaeudestruktur
# ------------------------------------------------------------------

def test_building_count(project):
    assert len(project.areal.buildings) == 1


def test_floor_count(project):
    assert len(project.areal.all_floors) >= 2


def test_room_count(project):
    assert len(project.areal.all_rooms) > 5


# ------------------------------------------------------------------
# Topologie
# ------------------------------------------------------------------

def test_area_count(project):
    assert len(project.topology.areas) >= 1


def test_device_count(project):
    total = sum(
        len(line.devices)
        for area in project.topology.areas
        for line in area.lines
    )
    assert total > 0


def test_physical_address_format(project):
    """Physikalische Adressen muessen das Format B.L.T haben."""
    for area in project.topology.areas:
        for line in area.lines:
            for dev in line.devices:
                parts = dev.physical_address.split(".")
                assert len(parts) == 3, f"Ungueltige Adresse: {dev.physical_address}"


# ------------------------------------------------------------------
# FA-1404: Bedienelement-Typ/Kanalanzahl aus Produktname + KO-Namen
# (Regression: ein Leckage-/Wassermelder ohne "Taste N"-KOs und ohne
# Taster-Keyword im Produktnamen wurde faelschlich als "Tastereinheit"
# eingelesen -- der alte Fallback war pauschal "Tastereinheit" fuer JEDEN
# unbekannten Sensor. Und: die Kanalanzahl eines echten Tasters wurde aus
# der Produktname-Bereichsangabe wie "1-8fach" gelesen (Produktfamilien-
# Maximalgroesse, nicht die tatsaechlich verbaute Tastenanzahl) statt aus
# den echten "Taste N"-KO-Namen.)
# ------------------------------------------------------------------

from knix_arranger.models.topology import CommunicationObject


def _kos(*names: str) -> list[CommunicationObject]:
    return [
        CommunicationObject(object_number=i, name=name)
        for i, name in enumerate(names)
    ]


class TestInferElementType:
    def test_leak_sensor_not_classified_as_tastereinheit(self):
        """Regression: 'Leak KNX 2.0' (kein Taster-Keyword, keine
        'Taste N'-KOs) darf nicht mehr pauschal als Tastereinheit gelten."""
        kos = _kos(
            "Softwareversion",
            "Leckage Sensorfehler (1 = An | 0 = Aus)",
            "Leckage Alarm (0 = Aus | 1 = An)",
        )
        assert KnxprojImportService._infer_element_type("Leak KNX 2.0", kos) == "Wassermelder"

    def test_leak_keyword_variants(self):
        for name in ("Leckagemelder", "Water Sensor Pro"):
            assert KnxprojImportService._infer_element_type(name, []) == "Wassermelder"

    def test_salva_smoke_detector_not_classified_as_wassermelder(self):
        """Regression: 'Salva' ist der Hersteller, nicht die Funktion -- er
        baut sowohl Rauch- als auch Wassermelder. Das reale Chalet-Gerät
        1.1.25 'Salva KNX TH' ist ein Rauchmelder (KO-Namen 'Rauchm.:...'),
        wurde aber wegen des Marken-Keywords 'salva' faelschlich als
        Wassermelder eingelesen."""
        kos = _kos(
            "Softwareversion", "Temp.Sensor: Messwert", "Feuchte Sensor: Messwert",
            "Rauchm.:Alarm (0: Aktiv)", "Rauchm.:Störung (1: Aktiv)",
            "Rauchm.: Warnung Rauchkammer (1: defekt)",
        )
        assert KnxprojImportService._infer_element_type("Salva KNX TH", kos) == "Rauchmelder"

    def test_smoke_detector_ko_names_detected_without_product_keyword(self):
        kos = _kos("Rauchmelder Alarm", "Rauchmelder Batterie")
        assert KnxprojImportService._infer_element_type("Unbekanntes Geraet X1", kos) == "Rauchmelder"

    def test_rauchmelder_keyword_in_product_name(self):
        assert KnxprojImportService._infer_element_type("ABC Rauchmelder 3000", []) == "Rauchmelder"

    def test_real_taster_without_keyword_still_detected_via_kos(self):
        """Ein echter Taster, dessen Produktname kein Taster-Keyword enthaelt
        (z.B. Feller EDIZIOdue), muss weiterhin ueber seine 'Taste N'-KOs als
        Tastereinheit erkannt werden -- die Fallback-Aenderung darf das
        nicht regressieren."""
        kos = _kos("Taste 1, links", "Taste 1, links, Signal-LED", "Taste 2, links")
        assert (
            KnxprojImportService._infer_element_type("Taster EDIZIOdue 1-8fach", kos)
            == "Tastereinheit"
        )

    def test_explicit_taster_keyword_still_wins(self):
        assert KnxprojImportService._infer_element_type("Universaltaster 4-fach", []) == "Tastereinheit"

    def test_unmatched_sensor_falls_back_to_generic(self):
        assert KnxprojImportService._infer_element_type("Unbekanntes Gadget X200", []) == "Sensor"

    def test_specific_categories_take_priority_over_taste_kos(self):
        """Ein Praesenzmelder mit (hypothetisch) einem KO namens 'Taste 1'
        soll trotzdem als Praesenzmelder gelten -- Produktname-Kategorien
        haben Vorrang vor der KO-basierten Tastereinheit-Erkennung."""
        kos = _kos("Taste 1")
        assert (
            KnxprojImportService._infer_element_type("Präsenzmelder 360", kos)
            == "Präsenzmelder"
        )


class TestInferChannelCount:
    def test_real_button_count_from_ko_names_not_product_range(self):
        """Regression: 'Taster EDIZIOdue 1-8fach' beschreibt die maximale
        Produktfamiliengroesse, nicht die tatsaechlich verbaute Tastenzahl.
        Das echte Chalet-Geraet 1.1.53 hat 3 Tasten (KO-Nummern
        0,2,3,5,6,8,9,11,12,13,14,16 fuer Taste 1/2/3) -- vorher lieferte
        die Regex faelschlich 8 (aus '1-8fach')."""
        kos = _kos(
            "Taste 1, links", "Taste 1, links, Signal-LED",
            "Taste 1, rechts", "Taste 1, rechts, Signal-LED",
            "Taste 2, links", "Taste 2, links, Signal-LED",
            "Taste 2, rechts", "Taste 2, rechts, Signal-LED",
            "Taste 3", "Taste 3", "Taste 3, Signal-LED", "Taste 3, Doppelklick",
        )
        assert (
            KnxprojImportService._infer_channel_count("Taster EDIZIOdue 1-8fach", kos) == 3
        )

    def test_falls_back_to_product_name_without_taste_kos(self):
        assert KnxprojImportService._infer_channel_count("Schaltaktor 4-fach", []) == 4

    def test_falls_back_to_one_without_any_signal(self):
        assert KnxprojImportService._infer_channel_count("Leak KNX 2.0", []) == 1


class TestCreateBedienelementeFromTopology:
    def test_leak_sensor_gets_wassermelder_type_and_single_channel(self):
        from knix_arranger.models.topology import Topology, Area, Line, Device
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room

        room = Room(number="04", name="Liftschacht")
        apartment = Apartment(name="UG")
        apartment.rooms.append(room)
        floor = Floor(name="Untergeschoss", short_code="UG")
        floor.apartments.append(apartment)
        wing = Wing(name="Hauptgebäude")
        wing.floors.append(floor)
        building = Building(name="Gebäude")
        building.wings.append(wing)
        areal = Areal(name="Test")
        areal.buildings.append(building)

        device = Device(
            physical_address="1.1.24", device_type="sensor", product="Leak KNX 2.0",
            room_id=room.id,
        )
        device.communication_objects = _kos(
            "Softwareversion", "Leckage Sensorfehler", "Leckage Alarm",
        )
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        KnxprojImportService._create_bedienelemente_from_topology(topology, areal)

        assert len(room.bedienelemente) == 1
        be = room.bedienelemente[0]
        assert be.element_type == "Wassermelder"
        assert be.channels == 1

    def test_existing_bedienelement_moved_when_device_room_changes(self):
        """Regression Chalet Franziska 2005, Taster 1.1.30: ein Re-Import kann
        link_rooms_to_lines() dazu bringen, einem Geraet einen anderen Raum
        zuzuweisen als beim ersten Import -- das bereits angelegte
        Bedienelement muss mitziehen, statt verwaist im alten Raum zu bleiben
        (bei gleichzeitig KEINEM zweiten Bedienelement im neuen Raum)."""
        from knix_arranger.models.topology import Topology, Area, Line, Device
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room, Bedienelement

        old_room = Room(number="00", name="Haupteingang")
        new_room = Room(number="01", name="Eingang / Studio")
        apartment = Apartment(name="EG")
        apartment.rooms.extend([old_room, new_room])
        floor = Floor(name="Erdgeschoss", short_code="EG")
        floor.apartments.append(apartment)
        wing = Wing(name="Hauptgebäude")
        wing.floors.append(floor)
        building = Building(name="Gebäude")
        building.wings.append(wing)
        areal = Areal(name="Test")
        areal.buildings.append(building)

        # Bedienelement existiert bereits im ALTEN Raum (Stand vor Re-Import).
        stale_be = Bedienelement(element_type="Tastereinheit", channels=4,
                                  participant_number="1.1.30")
        old_room.bedienelemente.append(stale_be)

        # Das Geraet zeigt nach dem Re-Import (link_rooms_to_lines) auf den NEUEN Raum.
        device = Device(
            physical_address="1.1.30", device_type="sensor", product="Taster EDIZIOdue 1-8fach",
            room_id=new_room.id,
        )
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        KnxprojImportService._create_bedienelemente_from_topology(topology, areal)

        assert old_room.bedienelemente == []
        assert len(new_room.bedienelemente) == 1
        assert new_room.bedienelemente[0] is stale_be  # dasselbe Objekt, nur verschoben

    def test_no_move_when_device_room_unchanged(self):
        """Kein Verschieben/keine Nebenwirkung, wenn Geraet und Bedienelement
        bereits im selben Raum sind (Normalfall bei jedem erneuten Aufruf,
        z.B. via BelegungsplanService.generate())."""
        from knix_arranger.models.topology import Topology, Area, Line, Device
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room, Bedienelement

        room = Room(number="00", name="Haupteingang")
        apartment = Apartment(name="EG")
        apartment.rooms.append(room)
        floor = Floor(name="Erdgeschoss", short_code="EG")
        floor.apartments.append(apartment)
        wing = Wing(name="Hauptgebäude")
        wing.floors.append(floor)
        building = Building(name="Gebäude")
        building.wings.append(wing)
        areal = Areal(name="Test")
        areal.buildings.append(building)

        be = Bedienelement(element_type="Tastereinheit", channels=4, participant_number="1.1.30")
        room.bedienelemente.append(be)

        device = Device(
            physical_address="1.1.30", device_type="sensor", product="Taster EDIZIOdue 1-8fach",
            room_id=room.id,
        )
        line = Line(line_number=1, name="L1")
        line.devices.append(device)
        area = Area(area_number=1, name="Bereich 1")
        area.lines.append(line)
        topology = Topology(areas=[area])

        KnxprojImportService._create_bedienelemente_from_topology(topology, areal)

        assert room.bedienelemente == [be]


# ------------------------------------------------------------------
# _infer_device_type -- Gateway-Klassifizierung (FA-1307/1308-analog fuer
# importierte Geraete): device_type="gateway" wurde bisher fuer keinen
# importierten Pfad vergeben (weder XLSX- noch knxproj-Import), Gateway-
# Produkte fielen auf "other"/die Adress-Heuristik zurueck. Zusaetzlich
# verfehlte "knx gateway" Produktnamen mit Bindestrich statt Leerzeichen
# (z.B. "KNX-Gateway").
# ------------------------------------------------------------------

class TestInferDeviceTypeGateway:
    def test_hyphenated_knx_gateway_is_gateway(self):
        assert KnxprojImportService._infer_device_type("KNX-Gateway", []) == "gateway"

    def test_knx_gateway_with_space_is_gateway(self):
        assert KnxprojImportService._infer_device_type("KNX Gateway", []) == "gateway"

    def test_ip_interface_is_gateway(self):
        assert KnxprojImportService._infer_device_type("IP-Interface 300", []) == "gateway"

    def test_power_supply_keyword_still_other(self):
        assert KnxprojImportService._infer_device_type("Speisegerät 640mA", []) == "other"

    def test_taster_still_sensor(self):
        assert KnxprojImportService._infer_device_type("Taster EDIZIOdue 1-8fach", []) == "sensor"


# ------------------------------------------------------------------
# extract_product_libraries -- im KNXPROJ eingebettete Hersteller-
# Produktdaten (M-XXXX/Hardware.xml, Catalog.xml, App-Programme) als
# eigenstaendige .knxprod-Dateien in die "Produkte KNX"-Bibliothek des
# Integrators extrahieren, statt sie manuell von Herstellerseiten
# nachzupflegen.
# ------------------------------------------------------------------

class TestExtractProductLibraries:
    def test_writes_one_knxprod_per_manufacturer(self, tmp_path):
        svc = KnxprojImportService()
        written = svc.extract_product_libraries(CHALET, str(tmp_path))

        assert len(written) > 0
        assert all(p.endswith(".knxprod") for p in written)
        assert all(os.path.exists(p) for p in written)

    def test_extracted_files_are_readable_by_catalog_service(self, tmp_path):
        from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService

        svc = KnxprojImportService()
        written = svc.extract_product_libraries(CHALET, str(tmp_path))
        assert written

        cat = KnxprodCatalogService()
        total_products = 0
        for path in written:
            total_products += len(cat.import_file(path))
        assert total_products > 0

    def test_manufacturer_name_resolves_after_reimport(self, tmp_path):
        """Regression: die extrahierte Datei muss knx_master.xml (Hersteller-
        ID -> Klartextname) mitbringen. Ohne sie loest KnxprodCatalogService
        beim spaeteren Wieder-Einlesen manche Hersteller (die ihren Namen
        nicht redundant in der eigenen Catalog.xml fuehren) nur auf die rohe
        M-XXXX-ID auf statt auf den Klarnamen, den die extrahierte Datei im
        Dateinamen bereits korrekt zeigt (z.B. "Siemens (M-0001).knxprod")."""
        from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService

        svc = KnxprojImportService()
        written = svc.extract_product_libraries(CHALET, str(tmp_path))
        siemens_file = next(p for p in written if p.startswith(
            os.path.join(str(tmp_path), "Siemens")
        ))

        products = KnxprodCatalogService().import_file(siemens_file)
        assert products
        assert all(p.manufacturer == "Siemens" for p in products)

    def test_extracted_products_persist_via_product_search_service(self, tmp_path):
        """End-to-End der Auto-Katalogisierung: extrahierte Dateien -> geparste
        Produkte -> ProductSearchService.add_products() -> ueberleben eine
        neue Service-Instanz (== persistiert in der nutzereigenen Katalog-
        Erweiterung, nicht nur im Prozessspeicher). isolate_appdata (conftest)
        sorgt dafuer, dass dabei NICHT die echte %APPDATA% beschrieben wird."""
        from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService
        from knix_arranger.services.product_search_service import ProductSearchService

        svc = KnxprojImportService()
        written = svc.extract_product_libraries(CHALET, str(tmp_path))
        cat = KnxprodCatalogService()
        all_products = []
        for path in written:
            all_products.extend(cat.import_file(path))
        assert all_products

        ProductSearchService().add_products([p.to_catalog_dict() for p in all_products])

        # Frische Instanz laedt den persistierten nutzereigenen Katalog neu.
        reloaded = ProductSearchService()
        siemens_products = [
            p for p in reloaded._catalog if p.get("manufacturer") == "Siemens"
        ]
        assert siemens_products
        assert any(p["product_name"] == "Load Switch UP 511" for p in siemens_products)

    def test_manufacturer_folder_copied_complete_with_signature(self, tmp_path):
        """Die extrahierten Dateien dienen als Quelle fuer den Export mit
        Produktreferenz: Herstellerordner vollstaendig (inkl. Baggages) und
        mit M-XXXX.signature, byte-gleich zum Projekt."""
        svc = KnxprojImportService()
        written = svc.extract_product_libraries(CHALET, str(tmp_path))
        with zipfile.ZipFile(CHALET) as src:
            for path in written:
                with zipfile.ZipFile(path) as lib:
                    mfr = next(n.split("/")[0] for n in lib.namelist() if "/" in n)
                    expected = {
                        n for n in src.namelist()
                        if (n.startswith(f"{mfr}/") and not n.endswith("/"))
                        or n == f"{mfr}.signature"
                    }
                    names = set(lib.namelist()) - {"knx_master.xml"}
                    assert names == expected
                    assert all(lib.read(n) == src.read(n) for n in names)

    def test_missing_dest_folder_returns_empty(self, tmp_path):
        svc = KnxprojImportService()
        missing = str(tmp_path / "does_not_exist")
        assert svc.extract_product_libraries(CHALET, missing) == []

    def test_empty_dest_folder_arg_returns_empty(self):
        svc = KnxprojImportService()
        assert svc.extract_product_libraries(CHALET, "") == []

    def test_invalid_knxproj_returns_empty_not_raises(self, tmp_path):
        bad = tmp_path / "bad.knxproj"
        bad.write_bytes(b"not a zip")
        dest = tmp_path / "dest"
        dest.mkdir()
        svc = KnxprojImportService()
        assert svc.extract_product_libraries(str(bad), str(dest)) == []

    def test_reimport_overwrites_not_duplicates(self, tmp_path):
        """Erneuter Import desselben (oder eines aehnlichen) Projekts soll die
        Herstellerdatei auffrischen, nicht Dubletten anhaeufen (analog zum
        Ueberschreiben-Verhalten des manuellen KNXPROD-Ordner-Imports)."""
        svc = KnxprojImportService()
        first = svc.extract_product_libraries(CHALET, str(tmp_path))
        second = svc.extract_product_libraries(CHALET, str(tmp_path))
        assert sorted(first) == sorted(second)
