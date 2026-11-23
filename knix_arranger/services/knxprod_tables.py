"""
Lage der KO-Tabelle einer Applikation aus der Herstellerdatei (FA-3108d).

Die Herstellerdatei (.knxprod) beschreibt im Abschnitt Static der
Applikation, wo die ETS die Tabellen hinschreibt, z.B.
<ComObjectTable CodeSegment="M-0002_A-4701-11-952C_AS-01AE" Offset="0">
mit <AbsoluteSegment Id="…_AS-01AE" Address="430" …>. Damit liest
«Teilnehmer suchen» die Flags genau dort, statt die Tabelle im Speicher zu
suchen (BCU 2 und System 7 melden sie nicht als Objekt, und ihr Zeiger
0x0112 ist leer).

Gesucht wird im Produktordner (product_folder); Ergebnisse je Applikation
zwischengespeichert. Ohne Datei oder ohne absolute Lage (System B mit
relativen Segmenten): None.
"""
from __future__ import annotations

import logging
import re
import zipfile

logger = logging.getLogger("knix_arranger.knxprod_tables")

_CACHE: dict[tuple[str, str], int | None] = {}
_COM_TABLE = re.compile(r'<ComObjectTable\s+CodeSegment="([^"]+)"\s+Offset="(\d+)"')


def object_table_address(manufacturer_id: str, program: str,
                         files: list[str] | None = None) -> int | None:
    """Adresse der KO-Tabelle der Applikation program («4701-11») des
    Herstellers («M-0002»), None wenn unbekannt."""
    manufacturer_id = (manufacturer_id or "").upper()
    if not manufacturer_id or not program:
        return None
    key = (manufacturer_id, program.upper())
    if key in _CACHE:
        return _CACHE[key]
    if files is None:
        from .product_folder import folder_files
        files = folder_files()
    prefix = f"{manufacturer_id}_A-{program.upper()}-"
    address = None
    # Dateien des Herstellers zuerst («… (M-0002).knxprod»)
    ordered = sorted(files, key=lambda f: manufacturer_id not in f.upper())
    for path in ordered:
        try:
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist()
                         if n.rsplit("/", 1)[-1].upper().startswith(prefix)
                         and n.lower().endswith(".xml")]
                for name in names:
                    address = table_address(archive.read(name).decode("utf-8", "ignore"))
                    if address is not None:
                        break
        except (OSError, zipfile.BadZipFile, KeyError):
            logger.debug("Herstellerdatei nicht lesbar: %s", path, exc_info=True)
            continue
        if address is not None or names:
            break
    _CACHE[key] = address
    return address


def table_address(xml: str) -> int | None:
    """Adresse der KO-Tabelle aus dem Text einer Applikation."""
    match = _COM_TABLE.search(xml)
    if not match:
        return None
    segment, offset = match.group(1), int(match.group(2))
    found = re.search(r'<AbsoluteSegment[^>]*\bId="' + re.escape(segment)
                      + r'"[^>]*\bAddress="(\d+)"', xml)
    if found is None:
        found = re.search(r'<AbsoluteSegment[^>]*\bAddress="(\d+)"[^>]*\bId="'
                          + re.escape(segment) + '"', xml)
    if found is not None:
        return int(found.group(1)) + offset
    # Rückfall: die Segment-Kennung trägt die Adresse («…_AS-01AE»)
    tail = re.search(r"_AS-([0-9A-Fa-f]{4})$", segment)
    return int(tail.group(1), 16) + offset if tail else None
