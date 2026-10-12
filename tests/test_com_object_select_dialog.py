"""
Tests fuer ComObjectSelectDialog (GA-Vorauswahl bei Produktverknuepfung).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from knix_arranger.ui.dialogs.com_object_select_dialog import ComObjectSelectDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _com_objects() -> list[dict]:
    return [
        {
            "number": 1, "name": "Helligkeit Ost", "function_text": "Helligkeit Ost",
            "datapoint_type": "DPST-9-4",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 2, "name": "Wind Geschwindigkeit", "function_text": "Wind Geschwindigkeit",
            "datapoint_type": "DPST-9-5",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 3, "name": "Regen", "function_text": "Regen",
            "datapoint_type": "DPST-1-2",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 4, "name": "Sperren Wind", "function_text": "Sperren Wind",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": True, "transmit_flag": False, "update_flag": False,
        },
        {
            # Kein needs_ga (kein Flag gesetzt) - darf nicht gelistet werden
            "number": 5, "name": "Reserve", "function_text": "Reserve",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": False, "update_flag": False,
        },
    ]


class TestComObjectSelectDialog:
    def test_only_needs_ga_objects_are_listed(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg._table.rowCount() == 4  # Nr. 5 (kein needs_ga) fehlt

    def test_default_all_selected_no_exclusions(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg.excluded_numbers() == set()

    def test_preexisting_exclusions_respected(self):
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), excluded_numbers={2, 4},
        )
        assert dlg.excluded_numbers() == {2, 4}

    def test_unchecking_a_row_adds_it_to_excluded(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._checkboxes[1].setChecked(False)  # Nr. 2
        assert dlg.excluded_numbers() == {2}

    def test_select_none_then_select_all(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._set_visible(False)
        assert dlg.excluded_numbers() == {1, 2, 3, 4}
        dlg._set_visible(True)
        assert dlg.excluded_numbers() == set()

    def test_search_filter_hides_non_matching_rows(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._search_edit.setText("wind")
        hidden = [dlg._table.isRowHidden(r) for r in range(dlg._table.rowCount())]
        # "Wind Geschwindigkeit" (Nr. 2) und "Sperren Wind" (Nr. 4) bleiben sichtbar
        visible_numbers = {
            dlg._relevant[r].number for r in range(dlg._table.rowCount())
            if not dlg._table.isRowHidden(r)
        }
        assert visible_numbers == {2, 4}

    def test_choose_different_product_rejects_with_flag(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg.wants_different_product() is False
        dlg._choose_different_product()
        assert dlg.wants_different_product() is True
        assert dlg.result() == QDialog.Rejected

    def test_default_all_selected_false_starts_with_none_checked(self):
        """Opt-in-Modus (Taster-Zusatzsensorik): ohne explizite excluded_numbers
        startet nichts ausgewählt, statt wie im Standardfall alles."""
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), default_all_selected=False,
        )
        assert dlg.excluded_numbers() == {1, 2, 3, 4}

    def test_explicit_excluded_numbers_overrides_default_all_selected(self):
        """Beim Wiederöffnen mit einer gespeicherten Auswahl gewinnt die
        explizite excluded_numbers-Angabe gegenüber default_all_selected."""
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(),
            excluded_numbers={1, 3, 4}, default_all_selected=False,
        )
        assert dlg.excluded_numbers() == {1, 3, 4}

    def test_header_note_override(self):
        from PySide6.QtWidgets import QLabel
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), header_note="Eigener Hinweistext",
        )
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        assert any("Eigener Hinweistext" in t for t in labels)


def _leak_objects() -> list[dict]:
    """Elsner Leak KNX 2.0 (Projekt_23): KO 2 in zwei Parametervarianten,
    Texte mit ETS-Platzhalter."""
    def co(number, text, dpt):
        return {"number": number, "name": text, "function_text": text,
                "datapoint_type": dpt, "communication_flag": True, "read_flag": False,
                "write_flag": False, "transmit_flag": True, "update_flag": False}
    return [co(2, "Leckage Alarm", "DPST-1-1"),
            co(3, "{{0}}Leckage Alarm Text", "DPST-16-0"),
            co(2, "Leckage Alarm", "DPST-1-1")]


class TestDoppelteKoNummern:
    def test_eine_zeile_je_nummer_und_auswahl_bleibt(self):
        dlg = ComObjectSelectDialog("Elsner Leak", _leak_objects(),
                                    default_all_selected=False)
        assert dlg._table.rowCount() == 2
        dlg._checkboxes[0].setChecked(True)           # nur «Leckage Alarm»
        assert dlg.excluded_numbers() == {3}

    def test_platzhalter_nicht_angezeigt(self):
        dlg = ComObjectSelectDialog("Elsner Leak", _leak_objects())
        texts = [dlg._table.item(r, 2).text() for r in range(dlg._table.rowCount())]
        assert texts == ["Leckage Alarm", "Leckage Alarm Text"]

    def test_produkt_schema_ohne_doppel_und_platzhalter(self):
        from knix_arranger.models.gewerk import Gewerk
        from knix_arranger.services.address_generator import AddressGenerator
        from knix_arranger.services.knxprod_catalog_service import clean_co_text
        gewerk = Gewerk(code="A", name="Alarm", ga_count=5, block_size=5, middle_group=3)
        schema = AddressGenerator.__new__(AddressGenerator)._build_product_schema(
            gewerk, {"com_objects": _leak_objects(), "excluded_co_numbers": []})
        assert [e.function for e in schema.entries] == ["Leckage Alarm", "Leckage Alarm Text"]
        assert clean_co_text("{{0:Room 1}}: Room Status") == "Room 1: Room Status"
        assert clean_co_text("{{1}}: Mute") == "Mute"
        from knix_arranger.services.address_generator import _com_object_function_name
        assert _com_object_function_name(
            {"function_text": "Leckage Alarm (0 = Aus | 1 = An)"}) == "Leckage Alarm"
