"""Tests fuer den Bericht "Aktoren und Gateways" (Einbauort -> Geraet -> Kanal)."""
import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.report_service import (
    ReportService, _report_channel_label, _co_object_text, _channel_total,
    _natural_key, _split_long_rows, _MAX_CHANNEL_LINES,
)


def test_kanal_aus_objektname():
    assert _report_channel_label("Ausgang A") == "Ausgang A"
    assert _report_channel_label("Stellgrösse, Kanal 1") == "Kanal 1"
    assert _report_channel_label("Group 1, Switching") == "Group 1"
    assert _report_channel_label("Output 1") == "Output 1"
    assert _report_channel_label("ON/OFF_3") == "Kanal 3"
    assert _report_channel_label("Status indication ON/OFF_3") == "Kanal 3"
    # Kein Kanal: Unterstrich-Namen mit mehreren Teilen, Platzhalter
    assert _report_channel_label("R_1_TEXT_OBJECT_1") == ""
    assert _report_channel_label("GO0002") == ""


def test_objekttext_ohne_kanalanteil():
    def co(name, function=""):
        return CommunicationObject(object_number=7, name=name, object_function=function)
    assert _co_object_text(co("Stellgrösse, Kanal 1", "continuously"), "Kanal 1") == "Stellgrösse"
    assert _co_object_text(co("Group 1, Switching", "On/Off"), "Group 1") == "Switching"
    assert _co_object_text(co("Ausgang A", "Switch"), "Ausgang A") == "Switch"
    assert _co_object_text(co("ON/OFF_1", "ON/OFF"), "Kanal 1") == "ON/OFF"
    assert _co_object_text(co("GO0002", "Up / Down"), "") == "Up / Down"
    assert _co_object_text(co("$Dummy", "Schalten"), "") == "Schalten"
    assert _co_object_text(co("", ""), "") == "KO 7"


def test_kanalzahl_nur_aus_produktname():
    assert _channel_total("AT/S8.16.5 Switch Actuator, 8-fold, 16A") == 8
    assert _channel_total("Schaltaktor 12-fach") == 12
    assert _channel_total("9x blind actuator JAX-9") == 9
    assert _channel_total("DALI-Gateway KNX plus") == 0


def test_kanaele_natuerlich_sortiert():
    assert sorted(["Kanal 10", "Kanal 2", "Kanal 1"], key=_natural_key) == [
        "Kanal 1", "Kanal 2", "Kanal 10"]


def test_lange_kanalzeile_wird_geteilt():
    gas = "\n".join(f"0/0/{i}" for i in range(_MAX_CHANNEL_LINES + 5))
    rows = _split_long_rows([["Zentral", ("Zentral", ""), gas]])
    assert [r[0] for r in rows] == ["Zentral", "Zentral (Forts.)"]
    assert rows[1][1] == ""
    assert rows[1][2].count("\n") == 4


def test_bericht_nach_einbauort_und_kanal(tmp_path):
    fitz = pytest.importorskip("fitz")
    project = KnxProject(name="Aktoren")
    schaltaktor = Device(
        physical_address="1.1.2", device_type="actor",
        product="Schaltaktor 8-fach", manufacturer="ABB", order_number="SA/S8",
        installation_location="UV1   ( Steigzone )",
        communication_objects=[
            CommunicationObject(object_number=1, name="Ausgang B", object_function="Schalten",
                                connected_gas=["1/0/2"]),
            CommunicationObject(object_number=0, name="Ausgang A", object_function="Schalten",
                                connected_gas=["1/0/1"]),
            CommunicationObject(object_number=20, name="Ausgang A", object_function="Status",
                                connected_gas=["1/7/1"]),
            CommunicationObject(object_number=30, name="Sperren",
                                connected_gas=["0/0/9"]),
        ])
    gateway = Device(physical_address="1.1.9", device_type="gateway",
                     product="Wetterstation-Gateway", installation_location="02 Garage")
    taster = Device(physical_address="1.1.20", device_type="sensor", product="Taster")
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=1, devices=[gateway, schaltaktor, taster])])]
    path = str(tmp_path / "aktoren.pdf")
    ReportService(project).generate_aktoren_gateway_report(path)

    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    toc = doc.get_toc()
    doc.close()
    assert "1 Aktor, 1 Gateway an 2 Einbauorten." in text
    assert "Taster" not in text                          # Sensoren gehoeren nicht dazu
    assert "UV1 (Steigzone)  (1 Gerät)" in text
    assert "1.1.2  ·  Aktor" in text
    assert "ABB · Schaltaktor 8-fach · SA/S8" in text
    assert "2 / 8" in text                               # belegte / vorhandene Kanaele
    assert "Keine Gruppenadressen verknüpft." in text    # Gateway ohne Objekte
    # Kanaele sortiert, Objekte ohne Kanal zuletzt
    assert text.index("Ausgang A") < text.index("Ausgang B") < text.index("Weitere")
    assert "20  Status" in text
    # Verteiler vor Raum, Geraetekarten eine Ebene unter dem Einbauort
    assert [(lvl, title) for lvl, title, _p in toc if lvl >= 2] == [
        (2, "Übersicht"),
        (2, "UV1 (Steigzone)  (1 Gerät)"), (3, "1.1.2  Schaltaktor 8-fach"),
        (2, "02 Garage  (1 Gerät)"), (3, "1.1.9  Wetterstation-Gateway"),
    ]


def test_bericht_ohne_aktoren(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = str(tmp_path / "leer.pdf")
    ReportService(KnxProject(name="Leer")).generate_aktoren_gateway_report(path)
    doc = fitz.open(path)
    assert "Keine Aktoren oder Gateways" in doc[0].get_text()
    doc.close()
