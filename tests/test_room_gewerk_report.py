"""Bericht "Raumbuch KNX" (früher "Räume nach Gewerken"): Zuordnung der
Gruppenadressen zu Räumen und Raumblatt."""
import pytest
from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.report_service import ReportService


def _ga(main, middle, sub, designation, **kw):
    return GroupAddress(main_group=main, middle_group=middle, sub_group=sub,
                        designation=designation, **kw)


def _project():
    bibliothek = Room(number="02", name="Bibliothek")
    garage = Room(number="02", name="Garage")          # gleiche Nummer, anderes Stockwerk
    uv = Room(number="99", name="UV2")
    project = KnxProject(name="Räume")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="OG", short_code="OG", apartments=[Apartment(rooms=[bibliothek, uv])]),
        Floor(name="EG", short_code="EG", apartments=[Apartment(rooms=[garage])]),
    ])])])
    gas = [
        _ga(3, 1, 10, "J.OG.02.01_move"),                # Bibliothek, Jalousie 1
        _ga(3, 1, 15, "J.OG.02.02_move"),                # Bibliothek, Jalousie 2
        _ga(3, 0, 1, "L.EG.02.01_ea"),                   # Garage (EG), nicht Bibliothek
        _ga(3, 4, 20, "Raum2_Szene High"),               # nur ueber Taster im Raum
        _ga(0, 0, 250, "Tag/Nacht_Chalet"),              # HG 0 -> Zentral
        _ga(3, 0, 60, "LDA.OG.04.01_ea"),                # OG 04 fehlt in der Struktur
        _ga(3, 0, 99, "Aktor-only"),                     # nur am Aktor im UV-Raum
    ]
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=n, middle_groups=[MiddleGroup(number=m, group_addresses=[
            g for g in gas if (g.main_group, g.middle_group) == (n, m)])
            for m in range(8)])
        for n in (0, 3)])
    taster = Device(physical_address="1.1.39", device_type="sensor", room_id=bibliothek.id,
                    communication_objects=[CommunicationObject(
                        object_number=1, connected_gas=["3/4/20", "0/0/250", "3/1/10"])])
    aktor = Device(physical_address="1.1.2", device_type="actor", room_id=uv.id,
                   communication_objects=[CommunicationObject(
                       object_number=0, connected_gas=["3/0/99", "3/0/1"])])
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1,
                                                               devices=[taster, aktor])])]
    return project, bibliothek, garage, uv


def test_zuordnung():
    project, bibliothek, garage, uv = _project()
    groups, missing = ReportService(project)._room_gewerk_groups()

    def addresses(room):
        result = {}
        for (_c, label, _e, _s), gas in groups[room.id].items():
            result.setdefault(label, []).extend(g.address for g in gas)
        return {label: sorted(a) for label, a in result.items()}

    bib = addresses(bibliothek)
    assert "3/1/10" in str(bib) and "3/1/15" in str(bib)
    assert "3/0/1" not in str(bib) and addresses(garage)          # Stockwerk entscheidet
    assert bib["Zentral (HG 0)"] == ["0/0/250"]
    assert "3/4/20" in str(bib)                                    # ueber Taster
    assert uv.id not in groups                                     # Aktoren ordnen nicht zu
    assert [g.address for g in missing["OG 04"]] == ["3/0/60"]
    # Jalousie 1 und 2 bleiben getrennte Elemente
    assert len([k for k in groups[bibliothek.id] if k[3] == "J"]) == 2


def test_bericht(tmp_path):
    fitz = pytest.importorskip("fitz")
    project, *_ = _project()
    path = str(tmp_path / "raeume.pdf")
    ReportService(project).generate_room_gewerk_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    toc = [(lvl, title) for lvl, title, _p in doc.get_toc()]
    landscape = all(p.rect.width > p.rect.height for p in doc)
    doc.close()
    assert landscape                                     # Querformat
    # Raumblatt: Gewerk mit Elementnummern, Kopf der Tabellen, Gerät im Raum
    assert "Jalousie" in text and "\n01\n" in text and "\n02\n" in text
    for header in ("Bedient von", "Ausgang", "Gruppenadressen", "KNX-Gerät im Raum"):
        assert header in text
    assert "1.1.39" in text
    assert "Total" in text                               # Übersicht als Matrix
    assert "Räume nicht in der Gebäudestruktur" in text and "OG 04" in text
    assert (2, "OG") in toc and (2, "EG") in toc
    assert any(lvl == 3 and title.startswith("02 Bibliothek") for lvl, title in toc)


def test_raumblatt_bereiche_und_kanaele():
    from knix_arranger.services.room_sheet import _channel_text, ga_ranges
    # kleine Lücken (Reserven) gehören zum Bereich, weite Abstände nicht
    assert ga_ranges(["1/0/20", "1/0/21", "1/0/22", "1/0/25", "1/0/29",
                      "1/6/20", "1/6/22", "1/0/60"]) == "1/0/20–29 · 1/0/60 · 1/6/20–22"
    assert ga_ranges([]) == ""
    assert _channel_text("Jalousieaktor 8-fach", ["1", "2", "3", "7"]) == "K1–3, K7"
    assert _channel_text("DALI-Gateway 32-fach", ["3", "4"]) == "Gr. 3–4"


def test_raumblatt_klartext_aus_ga_namen():
    from knix_arranger.services.room_sheet import klartext_from_gas
    room = Room(number="E01", name="Schlafzimmer")
    assert klartext_from_gas(
        [_ga(1, 0, 0, "L_E01_01 E/A (Wohnung / Schlafzimmer Leseleuchte Berg)")],
        room) == "Leseleuchte Berg"
    assert klartext_from_gas([_ga(1, 0, 0, "L.EG.01.01_ea ( Decke )")], room) == "Decke"
    assert klartext_from_gas(
        [_ga(1, 0, 0, "Licht", description="Treppe UG")], room) == "Treppe UG"


def test_raumblatt_geplant_mit_taste_und_ausgang(gewerk_catalog):
    """Geplantes Projekt: Bezeichnung aus der Planung, Taste und Aktorkanal
    über den Belegungsplan, Taster als Gerät im Raum."""
    from knix_arranger.models.building import GewerkAssignment
    from knix_arranger.services.belegungsplan_service import BelegungsplanService
    from knix_arranger.services.recalc_service import RecalcService
    from knix_arranger.services.room_sheet import build_room_sheets
    from knix_arranger.services.sensor_service import project_for_export
    from knix_arranger.services.topology_engine import TopologyEngine
    room = Room(number="E01", name="Schlafzimmer")
    room.gewerk_assignments = [
        GewerkAssignment(gewerk_code="L", count=2, element_labels=["Berg", "Rotten"]),
        GewerkAssignment(gewerk_code="J", count=1, element_labels=["Fenster"]),
    ]
    project = KnxProject(name="Plan")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="EG", short_code="EG", main_group_number=1,
              apartments=[Apartment(name="Wohnung", rooms=[room])])])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    RecalcService().recalc_actors_and_addresses(project)
    project = project_for_export(project)
    groups, _missing = ReportService(project)._room_gewerk_groups()
    sheets = build_room_sheets(project, groups, project.gewerk_catalog,
                               BelegungsplanService().generate(project))
    sheet = next(s for s in sheets if s.room.number == "E01")
    by_key = {(e.gewerk_code, e.number): e for e in sheet.elements}
    assert by_key[("L", 1)].label == "Berg" and by_key[("L", 2)].label == "Rotten"
    assert by_key[("J", 1)].label == "Fenster"
    assert all(e.outputs for e in by_key.values())          # Aktorkanal je Element
    assert any("Taste" in t for e in by_key.values() for t in e.operated_by)
    assert sheet.devices and sheet.devices[0].product == "kein Produkt zugewiesen"
    assert sheet.element_count == 3
