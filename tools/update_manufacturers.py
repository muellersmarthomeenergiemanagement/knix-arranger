"""
KNiX Arranger – KNX-Herstellerliste aktualisieren

Liest das offizielle KNX-Herstellerregister (knx_master.xml) aus einem
ETS-Projekt (.knxproj) oder einer Produktdatenbank (.knxprod) und schreibt
knix_arranger/data/knx_manufacturers.json (Hersteller-ID -> Name).

    python tools/update_manufacturers.py <datei.knxproj|datei.knxprod>

Die Datei mit der hoechsten MasterData-Version verwenden (ETS6-Projekte
enthalten die aktuellste Liste). Kurze Anzeigenamen und Schreibvarianten
stehen nicht hier, sondern in knix_arranger/utils/manufacturers.py.
"""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_TARGET = Path(__file__).parent.parent / "knix_arranger" / "data" / "knx_manufacturers.json"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    with zipfile.ZipFile(sys.argv[1]) as zf:
        if "knx_master.xml" not in zf.namelist():
            print("Keine knx_master.xml in der Datei gefunden.")
            return 1
        root = ET.fromstring(zf.read("knx_master.xml"))

    master = next((e for e in root.iter() if e.tag.endswith("}MasterData")), None)
    version = master.get("Version", "") if master is not None else ""
    manufacturers = {
        e.get("Id"): {
            "name": e.get("Name", "").strip(),
            "active": e.get("MemberStatus", "Active") != "Inactive",
        }
        for e in root.iter()
        if e.tag.endswith("}Manufacturer") and e.get("Id", "").startswith("M-")
    }
    data = {
        "source": "knx_master.xml",
        "master_data_version": version,
        "manufacturers": dict(sorted(manufacturers.items())),
    }
    _TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(manufacturers)} Hersteller (MasterData-Version {version}) -> {_TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
