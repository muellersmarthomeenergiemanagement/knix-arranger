"""Tests fuer i18n und Locale-Formatierung (NFA-151-156)."""
from datetime import datetime
from knix_arranger.utils.i18n import (
    load_language, tr, term, get_current_language, available_languages,
    format_date, format_number, format_currency,
)


class TestI18nTranslation:
    def test_load_german(self):
        load_language("de")
        assert get_current_language() == "de"
        assert tr("menu.file") == "Datei"

    def test_load_english(self):
        load_language("en")
        assert get_current_language() == "en"
        assert tr("menu.file") == "File"

    def test_load_french(self):
        load_language("fr")
        assert get_current_language() == "fr"
        assert tr("menu.file") == "Fichier"

    def test_all_sections_present_en(self):
        """EN muss alle Sektionen aus DE haben (NFA-154)."""
        load_language("de")
        de_file = tr("menu.file")
        load_language("en")
        en_file = tr("menu.file")
        assert de_file != en_file  # Unterschiedliche Uebersetzung

        # Stichproben
        assert tr("wizard.title") != ""
        assert tr("building.floor") != ""
        assert tr("topology.area") != ""
        assert tr("gewerk.title") != ""
        assert tr("address.main_group") != ""
        assert tr("validation.title") != ""
        assert tr("export.csv_export") != ""
        assert tr("common.ok") != ""
        assert tr("license.title") != ""

    def test_all_sections_present_fr(self):
        """FR muss alle Sektionen aus DE haben (NFA-154)."""
        load_language("fr")
        assert tr("wizard.title") != ""
        assert tr("building.floor") != ""
        assert tr("topology.area") != ""
        assert tr("gewerk.title") != ""
        assert tr("address.main_group") != ""
        assert tr("validation.title") != ""
        assert tr("export.csv_export") != ""
        assert tr("common.ok") != ""
        assert tr("license.title") != ""

    def test_tr_fallback(self):
        load_language("de")
        assert tr("nonexistent.key", "fallback") == "fallback"

    def test_available_languages(self):
        langs = available_languages()
        assert "de" in langs
        assert "en" in langs
        assert "fr" in langs


class TestI18nTerms:
    def test_german_terms(self):
        load_language("de")
        result = term("Gruppenadresse")
        assert "Logische Adresse" in result or "KNX" in result

    def test_english_terms(self):
        load_language("en")
        result = term("Gruppenadresse")
        assert "Logical address" in result or "KNX" in result

    def test_french_terms(self):
        load_language("fr")
        result = term("Gruppenadresse")
        assert "Adresse logique" in result or "KNX" in result


class TestLocaleFormatting:
    def test_format_date_de(self):
        load_language("de")
        dt = datetime(2026, 2, 18, 10, 30)
        assert format_date(dt) == "18.02.2026"

    def test_format_date_en(self):
        load_language("en")
        dt = datetime(2026, 2, 18, 10, 30)
        assert format_date(dt) == "02/18/2026"

    def test_format_date_fr(self):
        load_language("fr")
        dt = datetime(2026, 2, 18, 10, 30)
        assert format_date(dt) == "18/02/2026"

    def test_format_number_de(self):
        load_language("de")
        assert format_number(1234.50) == "1'234.50"

    def test_format_number_en(self):
        load_language("en")
        assert format_number(1234.50) == "1,234.50"

    def test_format_number_fr(self):
        load_language("fr")
        assert format_number(1234.50) == "1 234,50"

    def test_format_number_large(self):
        load_language("de")
        assert format_number(1234567.89) == "1'234'567.89"

    def test_format_number_small(self):
        load_language("de")
        assert format_number(42.10) == "42.10"

    def test_format_currency_de(self):
        load_language("de")
        assert format_currency(1234.50) == "CHF 1'234.50"

    def test_format_currency_en(self):
        load_language("en")
        assert format_currency(1234.50) == "CHF 1,234.50"

    def test_format_currency_fr(self):
        load_language("fr")
        assert format_currency(1234.50) == "CHF 1 234,50"

    def teardown_method(self):
        # Zurueck auf Deutsch setzen
        load_language("de")
