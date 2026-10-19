"""Objektfunktion und Grösse der KOs für die automatische Zuordnung
(1.4.10): Theben DM 4 T aus Test 148 -- vorher hiessen alle KOs «Kanal C1 –
Channel C1», die Zuordnung legte RM auf «Soft schalten» (KO 3) und RM WERT
auf «Sperren» (KO 4)."""
from __future__ import annotations

from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.actor_channels import Circuit, DeviceChannel, suggested_co_map
from knix_arranger.services.com_object_store import pack_com_object, unpack_com_object
from knix_arranger.services.ko_plausibility import actor_ko_problem
from knix_arranger.services.ko_size import (
    co_bits, dpt_bits, dpt_from_size, ko_label, size_bits, size_text, sizes_compatible,
)
from knix_arranger.services.product_sync import communication_objects_of

# Kanal C1 des DM 4 T: Nummer, Objektfunktion, Grösse, Flags
_DM4T = [
    (0, "Schalten EIN/AUS", "1 Bit", "KLS-A-"),
    (1, "Heller / Dunkler", "4 Bit", "KLS-A-"),
    (2, "Dimmwert", "1 Byte", "K-S-A-"),
    (3, "Soft schalten", "1 Bit", "KLS-A-"),
    (4, "Sperren", "1 Bit", "KLS-A-"),
    (5, "Szenen abrufen/speichern", "1 Byte", "KLS-A-"),
    (8, "Dimmwertbegrenzung", "1 Byte", "KLS-A-"),
    (9, "Rückmeldung Ein/Aus", "1 Bit", "KL-ÜA-"),
    (10, "Rückmeldung in %", "1 Byte", "KL-ÜA-"),
]


def _cos():
    return [CommunicationObject(object_number=n, name="Kanal C1", object_function=f,
                                object_size=size, data_type=dpt_from_size(size), flags=flags)
            for n, f, size, flags in _DM4T]


def _circuit():
    functions = [("E/A", "DPST-1-1"), ("DIM", "DPST-3-7"), ("WERT", "DPST-5-1"),
                 ("RM", "DPST-1-1"), ("RM WERT", "DPST-5-1")]
    return Circuit(key="k", room_number="EG03", room_name="Schlafen", gewerk_code="LD",
                   element_number=1, channel=1,
                   functions=[(f, f"1/0/{i}") for i, (f, _d) in enumerate(functions)],
                   dpts=dict(functions))


class TestSizes:
    def test_size_text_and_bits(self):
        assert [size_bits(s) for s in ("1 Bit", "4 Bit", "1 Byte", "2 Bytes", "14 Bytes")] == [
            1, 4, 8, 16, 112]
        assert [size_text(b) for b in (1, 4, 8, 16)] == ["1 Bit", "4 Bit", "1 Byte", "2 Byte"]
        assert (dpt_bits("DPST-5-1"), dpt_bits("DPT-9"), dpt_bits("DPST-232-600")) == (8, 16, 24)

    def test_dpt_only_from_unique_sizes(self):
        assert [dpt_from_size(s) for s in ("1 Bit", "2 Bit", "4 Bit", "1 Byte", "2 Bytes")] == [
            "DPT-1", "DPT-2", "DPT-3", "", ""]

    def test_size_from_ets_import_data_type(self):
        """ETS-Importe tragen die Grösse in data_type («1 bit»)."""
        assert co_bits(CommunicationObject(data_type="1 bit")) == 1
        assert sizes_compatible(CommunicationObject(data_type="1 bit"), "DPST-5-1") is False
        assert sizes_compatible(CommunicationObject(), "DPST-5-1") is True   # unbekannt

    def test_label_shows_size_and_direction(self):
        rm = _cos()[7]
        assert ko_label(rm) == "9: Kanal C1 – Rückmeldung Ein/Aus (1 Bit, sendet)"
        assert ko_label(rm, number=False, details=False) == "Kanal C1 – Rückmeldung Ein/Aus"


class TestMatching:
    def test_dm4t_all_functions_on_the_right_ko(self):
        channel = DeviceChannel(1, "Kanal C1", _cos())
        assert suggested_co_map(channel, _circuit()) == {
            "E/A": 0, "DIM": 1, "WERT": 2, "RM": 9, "RM WERT": 10}

    def test_size_decides_without_texts(self):
        """Hager-artig: alle KOs gleich benannt, kein DPT -- die Grösse wählt."""
        cos = [CommunicationObject(object_number=n, name="Output 1", object_function="Output 1",
                                   object_size=size, flags=flags)
               for n, size, flags in ((0, "1 Bit", "K-S---"), (1, "1 Byte", "K-S---"),
                                      (2, "1 Bit", "KL-Ü--"), (3, "1 Byte", "KL-Ü--"))]
        circuit = Circuit(key="k", room_number="", room_name="", gewerk_code="LD",
                          element_number=1, channel=1,
                          functions=[("WERT", "a"), ("RM WERT", "b")],
                          dpts={"WERT": "DPST-5-1", "RM WERT": "DPST-5-1"})
        assert suggested_co_map(DeviceChannel(1, "Output 1", cos), circuit) == {
            "WERT": 1, "RM WERT": 3}

    def test_size_mismatch_is_a_problem(self):
        dimmwert = [_cos()[2]]      # 1 Byte, ohne DPT
        assert actor_ko_problem(dimmwert, "E/A", "DPST-1-1") == (
            "Grösse passt nicht (KO 1 Byte, GA 1 Bit)")
        assert actor_ko_problem(dimmwert, "WERT", "DPST-5-1") == ""
        # mit DPT (aus 1 Bit abgeleitet) meldet die DPT-Prüfung
        assert actor_ko_problem([_cos()[3]], "WERT", "DPST-5-1").startswith("DPT passt nicht")


class TestStorageAndDevices:
    def test_store_row_keeps_size_and_reads_old_rows(self):
        co = {"number": 2, "name": "Kanal C1", "function_text": "Dimmwert",
              "datapoint_type": "", "object_size": "1 Byte", "communication_flag": True,
              "read_flag": False, "write_flag": True, "transmit_flag": False,
              "update_flag": True}
        row = pack_com_object(co)
        assert isinstance(row, list) and unpack_com_object(row) == co
        old = unpack_com_object([2, "Kanal C1", "Channel C1", "", 5])
        assert "object_size" not in old and old["write_flag"]

    def test_device_kos_carry_size(self):
        cos = communication_objects_of([{"number": 2, "name": "Kanal C1",
                                         "function_text": "Dimmwert", "object_size": "1 Byte"}])
        assert cos[0].object_size == "1 Byte"
        assert CommunicationObject.from_dict(cos[0].to_dict()).object_size == "1 Byte"


class _Catalog:
    def __init__(self, cos):
        self._cos = cos

    def find_product(self, manufacturer, order_number, product_name=""):
        return {"com_objects": self._cos}


def test_refresh_device_texts_keeps_flags_and_links(test_project):
    from knix_arranger.models.topology import Area, Line
    from knix_arranger.services.product_sync import refresh_device_com_objects
    device = Device(device_type="actor", manufacturer="Theben", order_number="4940275",
                    communication_objects=[
                        CommunicationObject(object_number=9, name="Kanal C1",
                                            object_function="Channel C1", flags="KLSÜ--",
                                            connected_gas=["1/0/9"])])
    test_project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1,
                                                                   devices=[device])])]
    new = [{"number": 9, "name": "Kanal C1", "function_text": "Rückmeldung Ein/Aus",
            "datapoint_type": "DPT-1", "object_size": "1 Bit", "transmit_flag": True}]
    assert refresh_device_com_objects(test_project, catalog=_Catalog(new)) == [device]
    co = device.communication_objects[0]
    assert (co.object_function, co.object_size, co.data_type) == (
        "Rückmeldung Ein/Aus", "1 Bit", "DPT-1")
    assert (co.flags, co.connected_gas) == ("KLSÜ--", ["1/0/9"])     # bleiben
    # noch nicht neu eingelesener Katalog (ohne Grösse): nichts ändern
    old = [{"number": 9, "name": "x", "function_text": "y"}]
    assert refresh_device_com_objects(test_project, catalog=_Catalog(old)) == []
