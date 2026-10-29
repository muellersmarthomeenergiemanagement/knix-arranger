"""
KNiX Arranger – KNX-Datenpunkttypen aktualisieren

Liest die Datenpunkttypen (DPT und Untertypen) mit ihren deutschen Namen aus
dem offiziellen KNX-Stamm (knx_master.xml) eines ETS-Projekts (.knxproj)
oder einer Produktdatenbank (.knxprod) und schreibt
knix_arranger/data/knx_dpt_names.json:

    {"DPST-1-8": {"main": "DPT-1", "bits": 1, "text": "Auf/Ab",
                  "main_text": "1-Bit"}, "DPT-1": {...}, ...}

    python tools/update_dpt_names.py <datei.knxproj|datei.knxprod>

Damit übersetzt KNiX die Anzeigenamen der ETS-Reports («Auf/Ab»,
«1-Bit, Freigeben») in DPT-Kennungen (utils/ets_dpt_names.py).
"""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_TARGET = Path(__file__).parent.parent / "knix_arranger" / "data" / "knx_dpt_names.json"
_GERMAN = ("de-CH", "de-DE", "de-AT")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _german_texts(root: ET.Element) -> dict[str, str]:
    by_language: dict[str, dict[str, str]] = {}
    for language in root.iter():
        if _local(language.tag) != "Language":
            continue
        identifier = language.get("Identifier", "")
        if identifier not in _GERMAN:
            continue
        texts = by_language.setdefault(identifier, {})
        for element in language.iter():
            if _local(element.tag) != "TranslationElement":
                continue
            ref_id = element.get("RefId", "")
            if not ref_id.startswith(("DPT-", "DPST-")):
                continue
            for translation in element:
                if translation.get("AttributeName") == "Text" and translation.get("Text"):
                    texts[ref_id] = translation.get("Text")
    for identifier in _GERMAN:
        if identifier in by_language:
            return by_language[identifier]
    return {}


def build(root: ET.Element) -> dict[str, dict]:
    german = _german_texts(root)
    result: dict[str, dict] = {}
    for dpt in root.iter():
        if _local(dpt.tag) != "DatapointType":
            continue
        main_id = dpt.get("Id", "")
        try:
            bits = int(dpt.get("SizeInBit", "0"))
        except ValueError:
            bits = 0
        main_text = german.get(main_id) or dpt.get("Text", "")
        result[main_id] = {"main": main_id, "bits": bits, "text": main_text,
                           "main_text": main_text}
        for sub in dpt.iter():
            if _local(sub.tag) == "DatapointSubtype":
                result[sub.get("Id", "")] = {
                    "main": main_id, "bits": bits,
                    "text": german.get(sub.get("Id", "")) or sub.get("Text", ""),
                    "main_text": main_text}
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    with zipfile.ZipFile(sys.argv[1]) as zf:
        if "knx_master.xml" not in zf.namelist():
            print("Keine knx_master.xml in der Datei gefunden.")
            return 1
        root = ET.fromstring(zf.read("knx_master.xml"))
    table = build(root)
    _TARGET.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
    print(f"{len(table)} Datenpunkttypen geschrieben: {_TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
