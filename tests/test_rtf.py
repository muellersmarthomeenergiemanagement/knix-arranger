"""Tests fuer die RTF-Umwandlung von ETS-Freitextfeldern (Einbauort)."""
from knix_arranger.models.topology import Device
from knix_arranger.utils.rtf import is_rtf, rtf_to_text

# Wie in ETS6-Projekten gespeichert (Chalet Franziska 1.1.21 / Chalet 64 1.1.39)
_HEADER = (
    r"{\rtf1\ansi\ansicpg1252\uc1\htmautsp\deff2{\fonttbl{\f0\fcharset0 Times New Roman;}"
    r"{\f2\fcharset0 Segoe UI;}}{\colortbl\red0\green0\blue0;\red255\green255\blue255;}"
    r"\loch\hich\dbch\pard\plain\ltrpar\itap0"
)
WITH_TEXT = (
    _HEADER + r"{\lang1033\fs18\f2\cf0 \cf0\ql{\f2 {\lang2055\ltrch F\'fcr Liftsteuerung}"
    r"\li0\ri0\sa0\sb0\fi0\ql\par}" + "\r\n}\r\n}"
)
EMPTY = _HEADER + r"{\lang1031\fs18\f2\cf0 \cf0\ql{\f2 \li0\ri0\sa0\sb0\fi0\ql\par}" + "\r\n}\r\n}"


def test_text_with_umlaut():
    assert rtf_to_text(WITH_TEXT) == "Für Liftsteuerung"


def test_empty_rtf_gives_empty_text():
    assert rtf_to_text(EMPTY) == ""


def test_plain_text_unchanged():
    assert not is_rtf("UV2   ( Steigzone )")
    assert rtf_to_text("UV2   ( Steigzone )") == "UV2   ( Steigzone )"


def test_unicode_escape_paragraphs_and_literals():
    rtf = r"{\rtf1\ansi\uc1 Stra\u223?e\par 2. Stock \{Nord\}\par}"
    assert rtf_to_text(rtf) == "Straße\n2. Stock {Nord}"


def test_skipped_destinations():
    rtf = r"{\rtf1{\*\generator Riched20;}{\fonttbl{\f0 Arial;}}Keller}"
    assert rtf_to_text(rtf) == "Keller"


def test_device_from_older_import_is_cleaned_on_load():
    device = Device.from_dict({"installation_location": WITH_TEXT})
    assert device.installation_location == "Für Liftsteuerung"
