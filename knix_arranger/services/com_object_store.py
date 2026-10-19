"""
Kommunikationsobjekte des eigenen Produktkatalogs in einer SQLite-Datei
(%APPDATA%/KNiX Arranger/product_com_objects.sqlite).

Die KOs der KNXPROD-Importe machen fast den ganzen Katalog aus (über
500'000 KOs bei ~800 Produkten). Im Speicher gehalten kosteten sie beim
Start Sekunden und Hunderte MB. Hier liegen sie je Produkt komprimiert und
werden erst gelesen, wenn ein Produkt gewählt wird; product_catalog_user.json
enthält nur die Stammdaten mit der Anzahl KOs ("co_count").
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import zlib
from collections import OrderedDict

logger = logging.getLogger("knix_arranger.com_object_store")

# KO als Zeile [Nummer, Name, Funktionstext, Datenpunkttyp, Flags-Bits,
# Grösse]; die Grösse ("1 Bit") fehlt in Zeilen bis Version 1.4.9
_CO_FIELDS = ("number", "name", "function_text", "datapoint_type")
_CO_FLAGS = ("communication_flag", "read_flag", "write_flag", "transmit_flag",
             "update_flag")
_CO_KEYS = frozenset(_CO_FIELDS + _CO_FLAGS)
# Optional: Grösse (ab 1.4.10), Parameterbedingungen (READER_VERSION 3)
_CO_OPTIONAL = frozenset({"object_size", "conditions"})


def pack_com_object(co):
    """KO als Zeile, wenn es die Standardfelder hat (jeder KNXPROD-Import);
    sonst bleibt es unverändert ein Dict (verlustfrei). Zeile: [Nummer, Name,
    Funktion, DPT, Flags-Bits, Grösse, Bedingungen]."""
    if not isinstance(co, dict) or not (_CO_KEYS <= co.keys() <= _CO_KEYS | _CO_OPTIONAL):
        return co
    bits = 0
    for i, flag in enumerate(_CO_FLAGS):
        if co[flag]:
            bits |= 1 << i
    row = [co.get("number", 0), co.get("name", ""), co.get("function_text", ""),
           co.get("datapoint_type", ""), bits]
    if "object_size" in co or co.get("conditions"):
        row.append(co.get("object_size", ""))
    if co.get("conditions"):
        row.append(co["conditions"])
    return row


def unpack_com_object(row):
    if not isinstance(row, list):
        return row
    co = dict(zip(_CO_FIELDS, row))
    bits = row[4] if len(row) > 4 else 1
    for i, flag in enumerate(_CO_FLAGS):
        co[flag] = bool(bits >> i & 1)
    if len(row) > 5:
        co["object_size"] = row[5]
    if len(row) > 6:
        co["conditions"] = row[6]
    return co


def _encode(com_objects: list) -> bytes:
    rows = [pack_com_object(co) for co in com_objects]
    return zlib.compress(json.dumps(rows, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"))


def _decode(blob: bytes) -> list[dict]:
    return [unpack_com_object(r) for r in json.loads(zlib.decompress(blob))]


def store_key(key: tuple[str, str]) -> str:
    """Produktschlüssel (product_key) als Text."""
    return "\x1f".join(key)


class ComObjectStore:
    """KOs je Produktschlüssel. Kleiner Zwischenspeicher für zuletzt
    gelesene Produkte (Validierung fragt dieselben Geräte wiederholt ab)."""

    _CACHE_SIZE = 32

    def __init__(self, path: str):
        self._path = path
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()

    @property
    def path(self) -> str:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path)
        con.execute("CREATE TABLE IF NOT EXISTS com_objects "
                    "(key TEXT PRIMARY KEY, data BLOB NOT NULL)")
        # Parametertexte je Applikation (ETS-Parametrier-Anleitung)
        con.execute("CREATE TABLE IF NOT EXISTS app_parameters "
                    "(key TEXT PRIMARY KEY, data BLOB NOT NULL)")
        return con

    def get_parameters(self, app_id: str) -> dict:
        """Parametertabelle einer Applikation, {} wenn keine gespeichert."""
        if not app_id or not os.path.exists(self._path):
            return {}
        cache_key = "\x1eapp\x1e" + app_id
        if cache_key in self._cache:
            return self._cache[cache_key]
        try:
            con = self._connect()
            try:
                row = con.execute("SELECT data FROM app_parameters WHERE key = ?",
                                  (app_id,)).fetchone()
            finally:
                con.close()
            data = json.loads(zlib.decompress(row[0])) if row else {}
        except (sqlite3.Error, zlib.error, ValueError) as e:
            logger.warning(f"Parameter von {app_id!r} konnten nicht gelesen werden: {e}")
            return {}
        self._cache[cache_key] = data
        if len(self._cache) > self._CACHE_SIZE:
            self._cache.popitem(last=False)
        return data

    def put_parameters(self, items: dict[str, dict]) -> None:
        """Parametertabellen je Applikation speichern (ersetzt vorhandene)."""
        if not items:
            return
        con = self._connect()
        try:
            with con:
                for app_id, table in items.items():
                    self._cache.pop("\x1eapp\x1e" + app_id, None)
                    con.execute("INSERT OR REPLACE INTO app_parameters VALUES (?, ?)",
                                (app_id, zlib.compress(json.dumps(
                                    table, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"))))
        finally:
            con.close()

    def get(self, key: tuple[str, str]) -> list[dict]:
        """KOs des Produkts (Kopie der Liste), [] wenn keine gespeichert."""
        skey = store_key(key)
        if skey in self._cache:
            self._cache.move_to_end(skey)
            return list(self._cache[skey])
        if not os.path.exists(self._path):
            return []
        try:
            con = self._connect()
            try:
                row = con.execute("SELECT data FROM com_objects WHERE key = ?",
                                  (skey,)).fetchone()
            finally:
                con.close()
            com_objects = _decode(row[0]) if row else []
        except (sqlite3.Error, zlib.error, ValueError) as e:
            logger.warning(f"KOs von {skey!r} konnten nicht gelesen werden: {e}")
            return []
        self._cache[skey] = com_objects
        if len(self._cache) > self._CACHE_SIZE:
            self._cache.popitem(last=False)
        return list(com_objects)

    def put_many(self, items: dict[tuple[str, str], list]) -> None:
        """Speichert KOs je Produkt in einer Transaktion (ersetzt vorhandene;
        eine leere Liste entfernt den Eintrag)."""
        if not items:
            return
        con = self._connect()
        try:
            with con:
                for key, com_objects in items.items():
                    skey = store_key(key)
                    self._cache.pop(skey, None)
                    if com_objects:
                        con.execute("INSERT OR REPLACE INTO com_objects VALUES (?, ?)",
                                    (skey, _encode(com_objects)))
                    else:
                        con.execute("DELETE FROM com_objects WHERE key = ?", (skey,))
        finally:
            con.close()

    def delete(self, keys) -> None:
        self.put_many({key: [] for key in keys})
