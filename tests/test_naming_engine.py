"""
Tests fuer NamingEngine (FA-401, FA-402, FA-403)
Format: [Gewerk]_[Raum]_[Nr] [Funktion] ([Klartext])
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.naming_engine import NamingEngine


class TestCreateDesignation:
    """Tests fuer create_designation."""

    def test_basic_designation(self):
        """Grundlegende Bezeichnung ohne Klartext."""
        result = NamingEngine.create_designation("LD", "E05", 1, "E/A")
        assert result == "LD_E05_01 E/A"

    def test_designation_with_description(self):
        """Bezeichnung mit Klartext in Klammern."""
        result = NamingEngine.create_designation(
            "LD", "E05", 1, "E/A", "Eingang Decke"
        )
        assert result == "LD_E05_01 E/A (Eingang Decke)"

    def test_designation_jalousie(self):
        """Jalousie-Bezeichnung."""
        result = NamingEngine.create_designation("J", "E01", 2, "AUF/AB")
        assert result == "J_E01_02 AUF/AB"

    def test_designation_heizung(self):
        """Heizungs-Bezeichnung."""
        result = NamingEngine.create_designation("H", "O01", 1, "STELLGROESSE")
        assert result == "H_O01_01 STELLGROESSE"

    def test_designation_two_digit_number(self):
        """Element-Nummer wird immer zweistellig formatiert."""
        result = NamingEngine.create_designation("L", "E01", 5, "E/A")
        assert result == "L_E01_05 E/A"

        result = NamingEngine.create_designation("L", "E01", 12, "E/A")
        assert result == "L_E01_12 E/A"

    def test_designation_no_function(self):
        """Bezeichnung ohne Funktion (leer)."""
        result = NamingEngine.create_designation("L", "E01", 1, "")
        assert result == "L_E01_01"

    def test_placeholder(self):
        """Platzhalter-Bezeichnung (FA-434)."""
        result = NamingEngine.create_placeholder_designation()
        assert result == "--"


class TestParseDesignation:
    """Tests fuer parse_designation."""

    def test_parse_full_designation(self):
        """Parst vollstaendige Bezeichnung."""
        result = NamingEngine.parse_designation("LD_E05_01 E/A (Eingang Decke)")
        assert result["gewerk_code"] == "LD"
        assert result["room_number"] == "E05"
        assert result["element_number"] == 1
        assert result["function_name"] == "E/A"
        assert result["description"] == "Eingang Decke"

    def test_parse_without_description(self):
        """Parst Bezeichnung ohne Klartext."""
        result = NamingEngine.parse_designation("J_E01_02 AUF/AB")
        assert result["gewerk_code"] == "J"
        assert result["room_number"] == "E01"
        assert result["element_number"] == 2
        assert result["function_name"] == "AUF/AB"
        assert result["description"] == ""

    def test_parse_placeholder(self):
        """Parst Platzhalter."""
        result = NamingEngine.parse_designation("--")
        assert result["gewerk_code"] == ""
        assert result["element_number"] == 0

    def test_parse_empty(self):
        """Parst leeren String."""
        result = NamingEngine.parse_designation("")
        assert result["gewerk_code"] == ""

    def test_roundtrip(self):
        """Erstellen und Parsen liefert urspruengliche Werte."""
        original_code = "LD"
        original_room = "E05"
        original_nr = 1
        original_func = "DIM"
        original_desc = "Stehlampe"

        designation = NamingEngine.create_designation(
            original_code, original_room, original_nr,
            original_func, original_desc,
        )
        parsed = NamingEngine.parse_designation(designation)

        assert parsed["gewerk_code"] == original_code
        assert parsed["room_number"] == original_room
        assert parsed["element_number"] == original_nr
        assert parsed["function_name"] == original_func
        assert parsed["description"] == original_desc

    def test_parse_complex_function_name(self):
        """Parst Bezeichnung mit mehrteiligem Funktionsnamen."""
        result = NamingEngine.parse_designation("J_E01_01 STATUS POSITION HOEHE")
        assert result["gewerk_code"] == "J"
        assert result["function_name"] == "STATUS POSITION HOEHE"

    def test_parse_rm_wert(self):
        """Parst RM WERT Bezeichnung."""
        result = NamingEngine.parse_designation("LD_E01_01 RM WERT")
        assert result["gewerk_code"] == "LD"
        assert result["function_name"] == "RM WERT"
