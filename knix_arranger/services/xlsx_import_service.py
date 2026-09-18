"""
ETS6 XLSX Topologie-Report Import (FA-511 bis FA-520)
Liest ETS6-Topologie-Reports mit Zusatzwahl "Objekte" ein.

Spaltenstruktur (0-basiert) der ETS6-XLSX-Datei, Referenzlayout:
  Spalte  6: Schlüssel (Adresse / KO-Nummer / Topologie-ID)
  Spalte 11: Medium (TP/IP) bei Topologie-Zeilen; Hersteller bei Geräten
  Spalte 13: Name bei Topologie-Zeilen (Bereich/Linie/Backbone)
  Spalte 18: Einbauort (Geräte-Subzeile "Raum")
  Spalte 19: Bestellnummer bei Geräten
  Spalte 23: Produkt bei Geräten
  Spalte 37: Applikationsprogramm bei Geräten
  Spalte  9: KO-Name
  Spalte 17: KO-Objektfunktion
  Spalte 25: KO-Prioritaet
  Spalte 30: KO-Flags
  Spalte 33: KO-Datentyp
  Spalte 38: KO verbundene Gruppenadresse(n) / Fortsetzungszeilen

ETS6 verschiebt diese Indizes je nach gewählten Export-Zusatzspalten
(z.B. mehr Metadatenfelder) -- die Deltas zwischen den Spalten sind dabei
nicht einheitlich. Die obigen Werte dienen daher nur noch als Fallback;
die tatsächlichen Spalten werden pro Datei anhand der Kopfzeilen-Texte
ermittelt (siehe `_resolve_topology_columns`). Metadaten (Projekt/Datum)
werden nicht über feste Spalten gelesen, sondern als Label:Wert-Paar
in derselben Zeile gesucht (siehe `_extract_metadata`).
"""
from __future__ import annotations
import logging
import os
import re
from typing import Optional

from ..models.topology import (
    Topology, Area, Line, Device, CommunicationObject,
)
from ..models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Verteiler,
    SensorFunktion, SensorFunktionGa, FunctionAssignment,
    STANDARD_FLOOR_NAMES, FLOOR_TO_MAIN_GROUP,
)
from ..models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)

logger = logging.getLogger("knix_arranger.xlsx_import")

_valid_gewerk_codes_cache: set[str] | None = None


def _valid_gewerk_codes() -> set[str]:
    """Lädt einmalig (und cached) die Menge gültiger Standard-Gewerk-Kürzel
    aus dem Default-Katalog (config/gewerke_catalog.json), zur Validierung
    in `_parse_xlsx_designation()`. Projektspezifische Custom-Gewerke sind
    beim Import naturgemäss noch nicht bekannt (werden erst im Wizard
    angelegt) -- die Prüfung gegen den Standardkatalog reicht aber, um
    Nicht-Gewerk-Präfixe zuverlässig zu erkennen."""
    global _valid_gewerk_codes_cache
    if _valid_gewerk_codes_cache is None:
        from ..models.gewerk import GewerkCatalog
        catalog = GewerkCatalog()
        catalog.load_defaults()
        _valid_gewerk_codes_cache = set(catalog.all_codes())
    return _valid_gewerk_codes_cache

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# Spaltenindizes Topologie-Report (0-basiert)
COL_KEY = 6          # Adresse / KO-Nummer / Topologie-ID
COL_MEDIUM = 11      # TP / IP  (Topologie) oder Hersteller (Gerät)
COL_TOPO_NAME = 13   # Bereich/Linien-Name
COL_LOCATION = 18    # Einbauort (Geräte-Subzeile)
COL_ORDER_NR = 19    # Bestellnummer Gerät
COL_PRODUCT = 23     # Produkt-Bezeichnung Gerät
COL_APP_PROG = 37    # Applikationsprogramm Gerät
COL_KO_NAME = 9      # KO-Name
COL_KO_FUNC = 17     # KO-Funktion
COL_KO_PRIO = 25     # KO-Prioritaet
COL_KO_FLAGS = 30    # KO-Flags
COL_KO_DT = 33       # KO-Datentyp
COL_GA = 38          # Verbundene Gruppenadresse(n)

# Kopfzeilen-Text -> (Delta Werte-Spalte minus Kopfzeilen-Spalte).
# Kalibriert am Referenzlayout oben; das Delta entsteht durch Merged-Cell-
# Header (die Beschriftung sitzt nicht immer exakt über der Werte-Spalte)
# und ist projektübergreifend stabil, auch wenn ETS6 zusätzliche Spalten
# einfügt und damit alle Indizes nach rechts verschiebt.
_TOPOLOGY_HEADER_ANCHORS: dict[str, tuple[str, int]] = {
    "KEY": ("Adresse", 0),
    "MEDIUM": ("Hersteller", 1),
    "ORDER_NR": ("Bestellnummer", 0),
    "PRODUCT": ("Produkt", -2),
    "APP_PROG": ("Applikation", 0),
    "LOCATION": ("Raum", 3),
    "KO_NAME": ("Name", 0),
    "KO_FUNC": ("Objektfunktion", 0),
    "KO_PRIO": ("Priorität", 1),
    "KO_FLAGS": ("Flags", 0),
    "KO_DT": ("Datentyp", 0),
    "GA": ("Verbunden mit", 0),
}

# Spaltenindizes GA-Report (0-basiert), Referenzlayout -- nur noch Fallback.
# ETS6 verschiebt diese Indizes je nach gewählten Export-Zusatzspalten (z.B.
# ein Projekt mit mehr/weniger Metadatenfeldern); die tatsächlichen Spalten
# werden pro Datei anhand der Kopfzeilen-Texte ermittelt, siehe
# `_resolve_ga_report_columns` (analog zu `_resolve_topology_columns`).
COL_GAR_ADDR = 4        # HG-Nr / MG-Adresse / GA-Adresse / Geräteadresse / KO
COL_GAR_NAME = 8        # Name bei HG, MG und GA-Zeilen
COL_GAR_DTYPE = 22      # Datentyp bei GA-Zeilen
COL_GAR_META_LABEL = 7  # Metadaten-Label
COL_GAR_META_VALUE = 18 # Metadaten-Wert
COL_GAR_PRODUCT = 6     # Produktname bei Geräte-Zeilen
COL_GAR_LOCATION = 19   # Einbauort bei Geräte-Zeilen ("04 Schlafen" / "UV2 (Steigzone)")
COL_GAR_KO_DTYPE = 20   # Datentyp bei KO-Zeilen
COL_GAR_KO_PRIO = 23    # Priorität bei KO-Zeilen
COL_GAR_KO_FLAGS = 25   # Flags bei KO-Zeilen
COL_GAR_KO_GAS = 28     # Vollständige verbundene GAs bei KO-Zeilen (alle, nicht nur aktuelle)
# Relative Verschiebung Meta-Wert-Spalte gegenüber Meta-Label-Spalte -- bleibt
# stabil, auch wenn die absolute Position (s.o.) sich verschiebt.
_GAR_META_VALUE_OFFSET = COL_GAR_META_VALUE - COL_GAR_META_LABEL

# Kopfzeilen-Text -> (Delta Werte-Spalte minus Kopfzeilen-Spalte), analog zu
# `_TOPOLOGY_HEADER_ANCHORS`.
_GAR_HEADER_ANCHORS: dict[str, tuple[str, int]] = {
    "ADDR": ("Adresse", 0),
    "NAME": ("Name", 0),
    "DTYPE": ("Typ", 0),
    "PRODUCT": ("Produkt", 0),
    "LOCATION": ("Gebäude", 0),
    "KO_DTYPE": ("Datentyp", 0),
    "KO_PRIO": ("Priorität", 0),
    "KO_FLAGS": ("Flags", 0),
    "KO_GAS": ("Gruppenadressen", -1),
}

# Spaltenindex ETS6 'Gebäude'-Report (0-basiert), Referenzlayout -- nur noch
# Fallback. Anders als Topologie-/GA-Report gibt es hier nur eine relevante
# Spalte: sie trägt abwechselnd das Hierarchie-Label (Stockwerk/Raum/
# Verteiler, per Einrückung unterscheidbar) und die physikalische
# Geräteadresse (unverschachtelt).
COL_BR_ADDR = 7
_BR_HEADER_ANCHORS: dict[str, tuple[str, int]] = {
    "ADDR": ("Adresse", 0),
}

# Sortierreihenfolge für Stockwerk-Kurzcodes (UG < EG < OG < ... < DG) --
# gemeinsam genutzt von derive_building_structure() und
# derive_building_structure_from_building_report().
_FLOOR_SORT_ORDER = (
    "UG", "EG", "OG", "1OG", "1.OG", "2OG", "2.OG", "3OG", "3.OG", "DG",
)

# Regex
_PHYS_ADDR_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,3})$")
_POWER_SUPPLY_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.-$")
_LINE_ADDR_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
_GA_RE = re.compile(r"\d+/\d+/\d+")
# GA-Report Zeilenerkennung
_GAR_HG_RE = re.compile(r"^\d{1,2}$")                     # Hauptgruppe: '0', '1', '12'
_GAR_MG_RE = re.compile(r"^\d{1,2}/\d{1,2}$")            # Mittelgruppe: '0/0', '1/3'
_GAR_GA_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{1,3}$")    # Gruppenadresse: '0/0/100'
_GAR_KO_RE = re.compile(r"^\d+:")                          # KO-Zeile: '1: Ausgang B', '32: G1,...'
# Einbauort-Raum-Format: "04  Schlafen" → (room_nr, room_name)
_EINBAUORT_ROOM_RE = re.compile(r"^(\d{2})\s+(.+)$")
# Einbauort-Verteiler-Format: "HV", "UV1", "UV2 (Steigzone)" -- der Klammerzusatz
# ist optional, da viele ETS6-Exporte (z.B. Secure-Projekte, wo nur der XLSX-Weg
# funktioniert) den Verteiler ohne benannten Zusatz eintragen.
# Zusätzlicher Zusatz ohne Klammern wird ebenfalls akzeptiert (z.B. 'HV  HV',
# wenn der Installateur den Verteiler redundant mit seinem Typkürzel statt
# einer Steigzonen-Bezeichnung benannt hat) -- sonst würde dieser häufige Fall
# nicht als Verteiler erkannt und das Gerät bliebe ganz ohne Raumzuordnung.
# Gruppe 2 (Nummer) wird separat erfasst, damit z.B. 'UV1' und 'UV2' als
# unterschiedliche Verteiler unterschieden werden koennen (canonical key
# Typ+Nummer, siehe `_vt_key`).
_VT_RE = re.compile(
    r"^(HV|UV|NV|TV|HZV)\s*(\d*)\s*(?:\(\s*(.+?)\s*\)|\s+(.+))?$", re.IGNORECASE
)


def _vt_key(vt_type: str, vt_number: str = "") -> str:
    """Kanonischer Verteiler-Schlüssel (Typ+Nummer, z.B. 'UV2', 'HV') --
    identifiziert denselben physischen Verteiler unabhängig von Freitext-
    Zusätzen ('UV2 (Steigzone)' vs. 'UV2 Technik')."""
    return f"{vt_type.strip().upper()}{(vt_number or '').strip()}"
# GA-Name-Muster für Gebäudestruktur-Ableitung: z.B. "S.OG.04.01_ea ( Beschreibung )"
# Element-Nr. ist 1- oder 2-stellig (\d{1,2}) -- Installateure zaehlen Elemente
# nicht immer zweistellig durch (z.B. "L.UG.02.1_ea" statt "L.UG.02.01_ea"),
# waehrend die Raumnummer selbst durchgehend zweistellig ist.
_GA_FLOOR_ROOM_RE = re.compile(
    r"[A-Z]{1,2}\.([A-Z0-9]{2,5})\.(\d{2})\.\d{1,2}[_a-z]*\s*\(\s*([^)]{2,40})\)"
)
# Einfacheres Muster für Stockwerk/Raum-Extraktion (ohne Klammerpflicht)
_GA_FLOOR_ROOM_SIMPLE_RE = re.compile(
    r"^[A-Z]{1,4}\.([A-Z0-9]{2,5})\.(\d{2})\.\d{1,2}"
)
# Worte, die KEIN Raumname sind (technische/direktionale Bezeichnungen sowie
# Leuchten-/Verbraucher-Bezeichnungen, die eine GA-Beschreibung statt eines
# Raumnamens verraten, z.B. "Wandleuchten Balkon" für einen Raum "Balkon").
_NON_ROOM_WORDS = frozenset({
    "spots", "spot", "indirekt", "berg", "rotten", "mitte", "wand", "ost", "west",
    "nord", "sued", "sued", "links", "rechts", "oben", "unten", "seite",
    "status", "schalten", "dimmen", "jalousie", "heizung", "lueftung",
    "szene", "nacht", "tag", "abwesend", "anwesend", "abwesenheit",
    "wandleuchten", "wandleuchte", "deckenspots", "deckenleuchte",
    "deckenleuchten", "stehleuchte", "steckdose", "steckdosen", "fenster",
})

# 3-stellige Raumnummer ohne Stockwerk-Buchstaben (EFH-Konvention
# "{Stockwerk}{nn}", z.B. "L.004.1_ea" -> Stockwerk 0, Raum 04).
# Eine optionale Klammer-Beschreibung wird mitgenommen, falls vorhanden.
# Kein '^'-Anker: wird per finditer() auf Zellentext "Adresse Bezeichnung..."
# angewendet, die Bezeichnung beginnt also nicht am Stringanfang.
_GA_DIGIT_ROOM_RE = re.compile(
    r"\b[A-Z]{1,4}\.(\d)(\d{2})\.\d{1,2}[_a-z]*\s*(?:\(\s*([^)]{2,40})\))?"
)
_GA_DIGIT_ROOM_SIMPLE_RE = re.compile(r"^[A-Z]{1,4}\.(\d)(\d{2})\.")
# Seriennummern im Format "XXXX:XXXXXXXX" (Hex) -- kein GA-Hinweis
_SERIAL_NUMBER_RE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]+$")

# Produktname-Schluesselwoerter zur Geraete-Klassifizierung (analog
# knxproj_import_service._infer_device_type), als Ergaenzung zur reinen
# Adress-Heuristik, die bei Tastern/Sensoren mit niedriger Adresse irrt.
# Geprüft wird gegen den NORMALISIERTEN Produktnamen (siehe
# `_normalize_product_name`): Binde-/Unterstriche werden zu Leerzeichen,
# damit z.B. "KNX-Gateway" das Schlüsselwort "knx gateway" trifft (sonst
# verfehlt der reine Substring-Vergleich jede Schreibweise mit Trennzeichen
# statt Leerzeichen).
_GATEWAY_KEYWORDS = (
    "gateway", "ip interface", "usb interface", "knxnet", "remote access",
)
_INFRA_KEYWORDS = (
    "ip router", "knx router", "knx interface",
    "line coupler", "area coupler", "backbone coupler",
    "power supply", "speisegerät", "netzteil",
    "touch panel", "raumcontroller", "room controller", "thepixa",
)
_SENSOR_KEYWORDS = (
    "sensor", "button", "taster", "push", "presence", "präsenz",
    "temperature", "temperatur", "weather", "wetter", "detector",
    "bewegungsmelder", "raumthermostat", "thermostat",
    "leak", "leckage", "melder", "multisensor", "salva",
)
_ACTOR_KEYWORDS = (
    "actuator", "aktor", "switch act", "schaltakt", "dimm",
    "jalousie", "shutter", "blind", "hvac", "heating ctrl",
    "dali", "rgb led", "led driver",
)


def _normalize_product_name(name: str) -> str:
    """Normalisiert einen Produktnamen für die Schlüsselwort-Klassifizierung:
    Klein schreiben, Binde-/Unterstriche/Schrägstriche als Leerzeichen
    behandeln, mehrfache Leerzeichen kürzen. Ohne das verfehlt z.B.
    "KNX-Gateway" das Schlüsselwort "knx gateway", weil der Bindestrich statt
    eines Leerzeichens zwischen den Wörtern steht."""
    normalized = re.sub(r"[-_/]+", " ", (name or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _ga_sort_key(addr: str) -> tuple[int, int, int]:
    """Sortierschluessel für GA-Adressen (H/M/S)."""
    parts = addr.split("/")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return (999, 999, 999)


def _cell(row: tuple, idx: int) -> str:
    """Gibt den Zellenwert als bereinigten String zurück."""
    if idx < len(row) and row[idx] is not None:
        return str(row[idx]).strip()
    return ""


class XlsxImportService:
    """Importiert ETS6-Topologie-Reports (XLSX) (FA-511)."""

    def __init__(self):
        self._rows_cache: dict[str, list] = {}

    def _load_rows(self, filepath: str) -> list:
        """Lädt alle Zeilen einer XLSX-Datei, gecacht pro Dateipfad und
        Service-Instanz.

        Ein einzelner Import-Vorgang (siehe main_window._import_xlsx /
        _import_ga_report_xlsx / _import_building_report_xlsx) ruft auf
        DERSELBEN XlsxImportService-Instanz viele verschiedene Extraktions-
        methoden nacheinander auf derselben Datei auf (z.B. import_xlsx,
        extract_group_addresses, derive_building_structure,
        extract_device_notes, extract_button_configuration, ...). Ohne
        Cache öffnet jede Methode die Datei erneut und parst alle Zeilen
        neu -- bei den großen ETS6-Reports dieses Projekts (Topologie
        >23'000, Gebäude >38'000 Zeilen) je Aufruf mehrere Sekunden, macht
        bei rund zehn Aufrufen pro Import einen spürbaren, teils minuten-
        langen "Hänger" (FA-511d). Der Cache reduziert das auf einen
        Lesevorgang pro Datei und Instanz -- eine neue Instanz (jeder
        Import-Klick erzeugt eine frische XlsxImportService()) liest bei
        erneutem Import also wie bisher den aktuellen Dateiinhalt.
        """
        if filepath not in self._rows_cache:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"XLSX-Datei nicht gefunden: {filepath}")
            if not HAS_OPENPYXL:
                raise ImportError("openpyxl wird für XLSX-Import benoetigt.")
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            self._rows_cache[filepath] = list(ws.iter_rows(values_only=True))
            wb.close()
        return self._rows_cache[filepath]

    # Kopfzeilen dieser ETS6-Reports haben durchweg >= 5 nicht-leere Zellen
    # (verteilt über viele Spalten). Titel-/Abschnittslabel-Zeilen ("Gruppen-
    # adressen", Projektname, Datum, ...) haben dagegen nur 1-2. Ein Wert
    # von 3 trennt beide Faelle sicher, ohne synthetische Test-Fixtures mit
    # wenigen Spalten zu treffen.
    _MIN_HEADER_ROW_CELLS = 3

    @classmethod
    def _scan_header_texts(cls, rows: list) -> dict[str, int]:
        """Baut {Zellentext -> erste Spalte} über alle Zeilen auf, die wie
        eine echte tabellarische Kopfzeile aussehen (mindestens
        `_MIN_HEADER_ROW_CELLS` nicht-leere Textzellen).

        Zeilen mit weniger Zellen werden übersprungen, statt sie als
        Kopfzeile zu werten -- sonst kann ein Report-Titel/Abschnittslabel
        weiter oben im Blatt fälschlich als Spaltenanker durchgehen, wenn
        sein Text zufällig mit einer gesuchten Spaltenüberschrift
        übereinstimmt. Beobachtet am Chalet-Projekt: der GA-Report-Titel
        "Gruppenadressen" (Zeile 4, nur 1 nicht-leere Zelle) liegt vor der
        echten KO-Unter-Kopfzeile "Gruppenadressen" (Zeile 45, 6 nicht-leere
        Zellen) und wurde bislang als KO_GAS-Spaltenanker fehlinterpretiert
        -- die KO-Anreicherung (`enrich_device_ko_connections`) fand dadurch
        projektweit nie echte Daten. GA-Reports haben zudem zwei getrennte
        Kopfzeilen-Ebenen (Zeile 22 für Adresse/Name/Typ, Zeile 45 für die
        KO-Unter-Spalten Datentyp/Priorität/Flags/Gruppenadressen) -- eine
        Beschränkung auf nur eine einzelne Zeile würde die zweite Ebene
        verfehlen, daher werden alle qualifizierenden Zeilen zusammengeführt
        (erste Zeile gewinnt bei Mehrfachtreffern)."""
        header_idx: dict[str, int] = {}
        for row in rows:
            if not row:
                continue
            non_empty = [
                (idx, cell.strip()) for idx, cell in enumerate(row)
                if isinstance(cell, str) and cell.strip()
            ]
            if len(non_empty) < cls._MIN_HEADER_ROW_CELLS:
                continue
            for idx, text in non_empty:
                if text not in header_idx:
                    header_idx[text] = idx
        return header_idx

    def _resolve_topology_columns(self, rows: list) -> dict[str, int]:
        """
        Ermittelt die tatsächlichen Spaltenindizes des Topologie-Reports
        anhand der Kopfzeilen-Texte ("Adresse", "Hersteller", "Produkt", ...).

        ETS6 exportiert je nach gewählten Zusatzspalten unterschiedlich
        breite Reports (z.B. mit mehr Metadatenfeldern) -- feste Indizes
        brechen dann, da die Verschiebung zwischen den Spaltengruppen
        nicht einheitlich ist. Die Kopfzeilen-Texte bleiben stabil; ihr
        Versatz zur Werte-Spalte ist über `_TOPOLOGY_HEADER_ANCHORS`
        kalibriert. Wird ein Header nicht gefunden (z.B. abweichendes
        Exportformat), greift der Referenz-Index als Fallback.
        """
        cols: dict[str, int] = {
            "KEY": COL_KEY, "MEDIUM": COL_MEDIUM, "TOPO_NAME": COL_TOPO_NAME,
            "LOCATION": COL_LOCATION, "ORDER_NR": COL_ORDER_NR,
            "PRODUCT": COL_PRODUCT, "APP_PROG": COL_APP_PROG,
            "KO_NAME": COL_KO_NAME, "KO_FUNC": COL_KO_FUNC,
            "KO_PRIO": COL_KO_PRIO, "KO_FLAGS": COL_KO_FLAGS,
            "KO_DT": COL_KO_DT, "GA": COL_GA,
        }

        header_idx = self._scan_header_texts(rows[:80])

        for key, (text, delta) in _TOPOLOGY_HEADER_ANCHORS.items():
            if text in header_idx:
                cols[key] = header_idx[text] + delta
        # Bereich/Linien-Name liegt relativ zur Medium-Spalte (kein eigener
        # Header in der Bereichs-/Linien-Tabelle vorhanden).
        cols["TOPO_NAME"] = cols["MEDIUM"] + 2

        if any(cols[k] != v for k, v in (
            ("KEY", COL_KEY), ("MEDIUM", COL_MEDIUM), ("PRODUCT", COL_PRODUCT),
        )):
            logger.info(f"XLSX-Spalten abweichend vom Referenzlayout erkannt: {cols}")
        return cols

    def _resolve_ga_report_columns(self, rows: list) -> dict[str, int]:
        """
        Ermittelt die tatsächlichen Spaltenindizes des GA-Reports anhand der
        Kopfzeilen-Texte ("Adresse", "Name", "Typ", ...), analog zu
        `_resolve_topology_columns`.

        ETS6 verschiebt diese Indizes je nach gewählten Export-Zusatzspalten
        -- feste Indizes führen dann zu leeren GA-Bezeichnungen nach dem
        Import, obwohl die Daten in der Datei vorhanden sind. Wird ein
        Header nicht gefunden (z.B. abweichendes Exportformat), greift der
        Referenz-Index als Fallback.
        """
        cols: dict[str, int] = {
            "ADDR": COL_GAR_ADDR, "NAME": COL_GAR_NAME, "DTYPE": COL_GAR_DTYPE,
            "PRODUCT": COL_GAR_PRODUCT, "LOCATION": COL_GAR_LOCATION,
            "KO_DTYPE": COL_GAR_KO_DTYPE, "KO_PRIO": COL_GAR_KO_PRIO,
            "KO_FLAGS": COL_GAR_KO_FLAGS, "KO_GAS": COL_GAR_KO_GAS,
        }

        header_idx = self._scan_header_texts(rows[:120])

        for key, (text, delta) in _GAR_HEADER_ANCHORS.items():
            if text in header_idx:
                cols[key] = header_idx[text] + delta

        if cols["NAME"] != COL_GAR_NAME:
            logger.info(f"GA-Report-Spalten abweichend vom Referenzlayout erkannt: {cols}")
        return cols

    def _resolve_ga_report_meta_columns(self, rows: list) -> tuple[Optional[int], int]:
        """
        Sucht die Metadaten-Label-Spalte ("Projekt:", "Startdatum:", ...) in
        den ersten 20 Zeilen -- ihre Position verschiebt sich zusammen mit
        den übrigen GA-Report-Spalten. Der Versatz zur Wert-Spalte bleibt
        dabei stabil (`_GAR_META_VALUE_OFFSET`).

        Gibt (label_spalte, wert_spalte_delta) zurück; label_spalte ist
        None, wenn keine Metadaten-Zeile gefunden wurde (Fallback auf die
        Referenz-Indizes bleibt dann aktiv).
        """
        labels = {"projekt", "project", "startdatum", "importdatum", "druckdatum"}
        for row in rows[:20]:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if isinstance(cell, str) and cell.strip().lower().rstrip(":") in labels:
                    return idx, _GAR_META_VALUE_OFFSET
        return None, _GAR_META_VALUE_OFFSET

    def detect_report_type(self, filepath: str) -> str:
        """
        Erkennt den Typ eines ETS6-XLSX-Reports anhand der Kopfzeilen.

        Gibt 'topology', 'ga_report' oder 'building_report' zurück.
        Prüft die ersten 10 Zeilen auf den Report-Titel in Spalte 1.
        """
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für XLSX-Import benoetigt.")
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.active
        report_type = "topology"
        for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
            if not row:
                continue
            title = row[1] if len(row) > 1 and row[1] is not None else ""
            title_lower = str(title).lower()
            if "gruppenadressen" in title_lower:
                report_type = "ga_report"
                break
            if "gebäude" in title_lower:
                report_type = "building_report"
                break
        wb.close()
        return report_type

    def import_xlsx(self, filepath: str) -> Topology:
        """
        Importiert einen ETS6-Topologie-Report (FA-511).

        Zeilen-Typen werden anhand von Spalte 6 unterschieden:
          - '0'                 → IP-Backbone
          - einzelne Zahl      → Bereich (FA-513)
          - 'B.L'              → Linie  (FA-513)
          - 'B.L.-'            → Spannungsversorgung (FA-516)
          - 'B.L.T'            → Busteilnehmer/Gerät (FA-514)
          - Python-int         → Kommunikationsobjekt (FA-515)
          - Spalte 18 gesetzt  → Geräte-Subzeile (Einbauort)
          - Spalte 38 gesetzt  → KO-Fortsetzungszeile (weitere GAs)
        """
        topology = Topology()
        rows = self._load_rows(filepath)

        if not rows:
            logger.warning(f"Leere XLSX-Datei: {filepath}")
            return topology

        cols = self._resolve_topology_columns(rows)

        # Metadaten aus Kopfzeilen extrahieren (FA-512)
        meta = self._extract_metadata(rows)
        if meta:
            logger.info(
                f"Projektname: {meta.get('project_name', '?')} | "
                f"Druckdatum: {meta.get('print_date', '?')}"
            )
        topology.metadata = meta  # type: ignore[attr-defined]

        current_area: Optional[Area] = None
        current_line: Optional[Line] = None
        current_device: Optional[Device] = None

        for row in rows:
            if not row:
                continue

            key_raw = row[cols["KEY"]] if cols["KEY"] < len(row) else None

            # --- Backbone (Spalte 6 = String '0', nicht Integer 0 = KO-Nr.) ---
            if key_raw == "0":
                medium = _cell(row, cols["MEDIUM"])
                if "IP" in medium.upper():
                    topology.backbone_type = "IP"
                continue

            # --- Bereich erkennen (Spalte 6 = einstellige/-zweistellige Ganzzahl als String) ---
            if isinstance(key_raw, str) and re.match(r"^\d{1,2}$", key_raw.strip()):
                area = self._parse_area_row(row, cols)
                if area:
                    current_area = area
                    topology.areas.append(current_area)
                    current_line = None
                    current_device = None
                continue

            # --- Linie erkennen (Spalte 6 = 'B.L') ---
            if isinstance(key_raw, str) and _LINE_ADDR_RE.match(key_raw.strip()):
                if current_area:
                    line = self._parse_line_row(row, current_area, cols)
                    if line:
                        current_line = line
                        current_area.lines.append(current_line)
                        current_device = None
                continue

            # --- Spannungsversorgung erkennen (Spalte 6 = 'B.L.-') ---
            if isinstance(key_raw, str) and _POWER_SUPPLY_RE.match(key_raw.strip()):
                if current_line:
                    dev = Device(
                        physical_address=key_raw.strip(),
                        manufacturer=_cell(row, cols["MEDIUM"]),
                        order_number=_cell(row, cols["ORDER_NR"]),
                        product=_cell(row, cols["PRODUCT"]),
                        application_program=_cell(row, cols["APP_PROG"]),
                        device_type="power_supply",
                    )
                    current_line.devices.append(dev)
                    current_device = dev
                continue

            # --- Busteilnehmer erkennen (Spalte 6 = 'B.L.T') ---
            if isinstance(key_raw, str) and _PHYS_ADDR_RE.match(key_raw.strip()):
                if current_line:
                    device = self._parse_device_row(row, cols)
                    current_line.devices.append(device)
                    current_device = device
                continue

            # --- Kommunikationsobjekt (Spalte 6 = Python-int) ---
            if isinstance(key_raw, int):
                ko = self._parse_ko_row(row, key_raw, cols)
                if ko and current_device:
                    current_device.communication_objects.append(ko)
                continue

            # --- Geräte-Subzeile: Seriennummer (Spalte 6 = "XXXX:XXXXXXXX") ---
            # Kein continue: ETS6 legt die Einbauort-Subzeile manchmal auf
            # dieselbe Zeile wie die Seriennummer (Spalte 6 dann nicht leer).
            if (isinstance(key_raw, str)
                    and _SERIAL_NUMBER_RE.match(key_raw.strip())
                    and current_device):
                current_device.serial_number = key_raw.strip()

            # --- Geräte-Subzeile: Einbauort (Spalte 18 gesetzt) ---
            loc = _cell(row, cols["LOCATION"])
            if loc and not isinstance(key_raw, int) and current_device:
                current_device.installation_location = loc
                continue

            # --- KO-Fortsetzungszeile: weitere verbundene GAs (Spalte 38 gesetzt) ---
            ga_cont = _cell(row, cols["GA"])
            if (ga_cont and key_raw is None
                    and current_device
                    and current_device.communication_objects):
                last_ko = current_device.communication_objects[-1]
                for ga in self._extract_gas(ga_cont):
                    if ga not in last_ko.connected_gas:
                        last_ko.connected_gas.append(ga)

        # Geräteanzahl berechnen und Grenzwerte prüfen (FA-518)
        for area in topology.areas:
            for line in area.lines:
                line.update_device_count()
                if line.device_count > 100:
                    logger.error(
                        f"Linie {line.coupler_address}: "
                        f"{line.device_count} Geräte (max. empfohlen: 100)"
                    )
                elif line.device_count > 85:
                    logger.warning(
                        f"Linie {line.coupler_address}: "
                        f"{line.device_count} Geräte (Empfehlung: max. 85)"
                    )

        total_lines = sum(len(a.lines) for a in topology.areas)
        total_devices = sum(
            len(l.devices)
            for a in topology.areas
            for l in a.lines
        )
        logger.info(
            f"XLSX importiert: {len(topology.areas)} Bereiche, "
            f"{total_lines} Linien, {total_devices} Geräte  [{filepath}]"
        )
        return topology

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _extract_metadata(self, rows: list) -> dict:
        """
        Extrahiert Projektmetadaten aus den Kopfzeilen (FA-512).

        Sucht das Label (z.B. "Projekt:") an beliebiger Spaltenposition in
        der Zeile und nimmt die erste nicht-leere Zelle danach als Wert --
        feste Spaltenindizes sind nicht zuverlässig, da ETS6 je nach
        Exportkonfiguration unterschiedlich viele Spalten einfügt.
        """
        meta: dict = {}
        label_map = {
            "projekt":     "project_name",
            "project":     "project_name",
            "startdatum":  "start_date",
            "importdatum": "import_date",
            "druckdatum":  "print_date",
            "druckzeit":   "print_time",
        }
        for row in rows[:20]:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if not isinstance(cell, str):
                    continue
                label = cell.strip().lower().rstrip(":")
                if label not in label_map or label_map[label] in meta:
                    continue
                for val in row[idx + 1:]:
                    if val is not None and str(val).strip():
                        meta[label_map[label]] = str(val).strip()
                        break
        return meta

    def _parse_area_row(self, row: tuple, cols: dict[str, int]) -> Optional[Area]:
        """Erkennt und liest eine Bereich-Zeile (FA-513)."""
        key = _cell(row, cols["KEY"])
        try:
            area_num = int(key)
        except ValueError:
            return None
        if area_num == 0:
            return None  # Backbone, kein Bereich
        medium = _cell(row, cols["MEDIUM"])
        name = _cell(row, cols["TOPO_NAME"]) or f"Bereich {area_num}"
        return Area(
            area_number=area_num,
            name=name,
            coupler_address=f"{area_num}.0.0",
            backbone_type="IP" if "IP" in medium.upper() else "TP",
        )

    def _parse_line_row(self, row: tuple, area: Area, cols: dict[str, int]) -> Optional[Line]:
        """Erkennt und liest eine Linien-Zeile (FA-513)."""
        key = _cell(row, cols["KEY"])
        m = _LINE_ADDR_RE.match(key)
        if not m:
            return None
        line_num = int(m.group(2))
        name = _cell(row, cols["TOPO_NAME"]) or f"Linie {line_num}"
        return Line(
            line_number=line_num,
            name=name,
            coupler_address=f"{area.area_number}.{line_num}.0",
        )

    def _parse_device_row(self, row: tuple, cols: dict[str, int]) -> Device:
        """Liest eine Busteilnehmer-Zeile (FA-514)."""
        addr = _cell(row, cols["KEY"])
        m = _PHYS_ADDR_RE.match(addr)
        participant = int(m.group(3)) if m else -1

        product = _cell(row, cols["PRODUCT"])

        # Koppler: Teilnehmer-Adresse == 0 (FA-517)
        if participant == 0:
            dev_type = "coupler"
        elif participant < 0:
            dev_type = "unknown"
        else:
            dev_type = self._classify_device(addr, product)

        return Device(
            physical_address=addr,
            manufacturer=_cell(row, cols["MEDIUM"]),
            order_number=_cell(row, cols["ORDER_NR"]),
            product=product,
            application_program=_cell(row, cols["APP_PROG"]),
            device_type=dev_type,
        )

    def _parse_ko_row(
        self, row: tuple, obj_num: int, cols: dict[str, int],
    ) -> Optional[CommunicationObject]:
        """Liest eine Kommunikationsobjekt-Zeile (FA-515)."""
        name = _cell(row, cols["KO_NAME"])
        # Kopfzeilen der KO-Tabelle (z.B. "Name", " #") uebergehen
        if name.lower() in ("name", "beschreibung", ""):
            return None

        ga_cell = _cell(row, cols["GA"])
        connected_gas = self._extract_gas(ga_cell) if ga_cell else []

        return CommunicationObject(
            object_number=obj_num,
            name=name,
            object_function=_cell(row, cols["KO_FUNC"]),
            priority=_cell(row, cols["KO_PRIO"]) or "Niedrig",
            flags=_cell(row, cols["KO_FLAGS"]),
            data_type=_cell(row, cols["KO_DT"]),
            connected_gas=connected_gas,
        )

    def _extract_gas(self, ga_text: str) -> list[str]:
        """
        Extrahiert alle GA-Adressen (Format H/M/S) aus einem Zellentext (FA-519).

        Beispiel: '3/0/65 L.OG.01.01_ea   ( Licht )  0/0/100 3/4/9'
        → ['3/0/65', '0/0/100', '3/4/9']
        """
        return _GA_RE.findall(ga_text)

    def _classify_device(self, address: str, product: str = "") -> str:
        """Klassifiziert ein Gerät anhand Produktname (bevorzugt) und Adresse.

        Reine Adress-Heuristik (Teilnehmer <=100 -> Aktor, <=199 -> Sensor)
        liegt oft falsch, z.B. bei Tastern mit niedriger Adresse. Der
        Produktname liefert ein zuverlässigeres Signal (analog
        knxproj_import_service._infer_device_type) und wird deshalb zuerst
        geprüft; die Adress-Heuristik bleibt Fallback, wenn keine
        Schlüsselwörter zutreffen oder kein Produktname vorliegt.
        """
        m = _PHYS_ADDR_RE.match(address)
        if not m:
            return "unknown"
        participant = int(m.group(3))
        if participant == 0:
            return "coupler"

        name_norm = _normalize_product_name(product)
        if any(kw in name_norm for kw in _GATEWAY_KEYWORDS):
            return "gateway"
        if any(kw in name_norm for kw in _INFRA_KEYWORDS):
            return "other"
        if any(kw in name_norm for kw in _SENSOR_KEYWORDS):
            return "sensor"
        if any(kw in name_norm for kw in _ACTOR_KEYWORDS):
            return "actor"

        if participant <= 100:
            return "actor"
        if participant <= 199:
            return "sensor"
        return "unknown"

    def derive_building_structure(
        self, filepath: str, ga_structure: "GroupAddressStructure | None" = None,
    ) -> Areal:
        """
        Leitet Gebäudestruktur aus den GA-Namen im XLSX-Topologie-Report ab.

        Scannt alle GA-Zellen nach dem Muster '{Gewerk}.{Stockwerk}.{RaumNr}...'
        und erstellt daraus Stockwerke und Räume (FA-506 analog für XLSX).

        Zusätzlich wird der Einbauort (Spalte S / COL_LOCATION) jedes Geräts
        ausgelesen. Da der Einbauort das Format 'NN  Raumname' hat und in den
        KO-Zeilen desselben Geräts der Stockwerk-Code vorkommt, kann die
        Zuordnung (Stockwerk, RaumNr) → echter Raumname aus Spalte S hergestellt
        werden. Dieser Name hat Vorrang vor dem aus GA-Beschreibungen abgeleiteten.

        Manche Projekte benennen GAs ohne Stockwerk-Buchstaben, nach der
        EFH-Konvention '{Gewerk}.{Stockwerk}{RaumNr}.{Element}' (z.B.
        'L.004.1_ea' = Stockwerk 0, Raum 04). Liefert das Buchstaben-Muster
        keine Treffer, wird auf dieses Ziffern-Muster zurückgegriffen; der
        Stockwerksname wird dabei aus der passenden Hauptgruppe von
        `ga_structure` übernommen (Hauptgruppe = Stockwerk-Ziffer + 1), falls
        übergeben, sonst generisch als "Stockwerk N" benannt.

        Gibt ein Areal mit Gebäude > Flügel > Stockwerke > Wohnungen > Räume zurück.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"XLSX-Datei nicht gefunden: {filepath}")
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für XLSX-Import benoetigt.")

        # floor_rooms: {floor_code -> {room_nr -> [ga-beschreibungen]}}
        floor_rooms: dict[str, dict[str, list[str]]] = {}
        # col_s_names: {(floor_code, room_nr) -> echter Raumname aus Spalte S}
        col_s_names: dict[tuple[str, str], str] = {}
        # digit_floor_rooms: {stockwerk_ziffer -> {room_nr -> [ga-beschreibungen]}}
        digit_floor_rooms: dict[str, dict[str, list[str]]] = {}

        _LOC_RE = re.compile(r"^(\d{2})\s+(.+)$")

        rows = self._load_rows(filepath)

        cols = self._resolve_topology_columns(rows)
        # Raumnummer + Name aus Spalte S des aktuellen Geräts. Ein Gerät kann
        # über seine Kanäle GAs mehrerer RÄUME ansteuern (z.B. ein Mehrfach-
        # Taster im Flur, der Licht in drei anderen Zimmern schaltet) -- sein
        # eigener Einbauort beschreibt aber nur, WO ES MONTIERT ist. Der Name
        # darf daher nur für die GA übernommen werden, deren Raumnummer mit
        # der Einbauort-Raumnummer übereinstimmt, sonst "erbt" z.B. der
        # Konikeller fälschlich den Namen "Waschraum" vom dort montierten Taster.
        current_location_nr: str = ""
        current_location_name: str = ""

        for row in rows:
            if not row:
                continue
            key_raw = row[cols["KEY"]] if cols["KEY"] < len(row) else None

            # Neue Gerätezeile → Einbauort zurücksetzen
            if isinstance(key_raw, str) and (
                _PHYS_ADDR_RE.match(key_raw.strip())
                or _POWER_SUPPLY_RE.match(key_raw.strip())
            ):
                current_location_nr = ""
                current_location_name = ""
                continue

            # Geräte-Subzeile: Einbauort aus Spalte S lesen. Nicht auf
            # key_raw is None beschränkt -- ETS6 legt die Einbauort-Subzeile
            # manchmal auf dieselbe Zeile wie die Seriennummer-Subzeile
            # (Spalte 6 dann z.B. "001E:0100412C" statt leer).
            loc_raw = row[cols["LOCATION"]] if cols["LOCATION"] < len(row) else None
            if loc_raw is not None:
                loc_m = _LOC_RE.match(str(loc_raw).strip())
                if loc_m:
                    current_location_nr = loc_m.group(1)
                    current_location_name = loc_m.group(2).strip()

            # KO-Zeile: GA-Namen auswerten und Stockwerk/Raum-Mapping aufbauen
            if isinstance(key_raw, int):
                if cols["GA"] < len(row) and row[cols["GA"]] is not None:
                    text = str(row[cols["GA"]])
                    for m in _GA_FLOOR_ROOM_RE.finditer(text):
                        floor_code = m.group(1).upper()
                        room_nr = m.group(2)
                        desc = m.group(3).strip()

                        if floor_code not in floor_rooms:
                            floor_rooms[floor_code] = {}
                        if room_nr not in floor_rooms[floor_code]:
                            floor_rooms[floor_code][room_nr] = []
                        if desc and desc not in floor_rooms[floor_code][room_nr]:
                            floor_rooms[floor_code][room_nr].append(desc)

                        # Spalte-S-Namen mit (Stockwerk, RaumNr) verknüpfen --
                        # nur wenn die Einbauort-Raumnummer zur GA-Raumnummer passt.
                        fk = (floor_code, room_nr)
                        if (current_location_name and room_nr == current_location_nr
                                and fk not in col_s_names):
                            col_s_names[fk] = current_location_name

                    for m in _GA_DIGIT_ROOM_RE.finditer(text):
                        digit = m.group(1)
                        room_nr = m.group(2)
                        desc = (m.group(3) or "").strip()

                        if digit not in digit_floor_rooms:
                            digit_floor_rooms[digit] = {}
                        if room_nr not in digit_floor_rooms[digit]:
                            digit_floor_rooms[digit][room_nr] = []
                        if desc and desc not in digit_floor_rooms[digit][room_nr]:
                            digit_floor_rooms[digit][room_nr].append(desc)

        if not floor_rooms and digit_floor_rooms:
            return self._build_areal_from_digit_floors(digit_floor_rooms, ga_structure)

        if not floor_rooms:
            logger.warning("Keine Gebäudestruktur aus XLSX ableitbar (keine GA-Namen gefunden).")
            areal = Areal(name="Importiertes Projekt")
            building = Building(name="Gebäude")
            wing = Wing(name="Hauptgebäude")
            building.wings.append(wing)
            areal.buildings.append(building)
            return areal

        logger.info(
            f"Raumname aus Spalte S zugeordnet für {len(col_s_names)} Stockwerk/Raum-Kombinationen"
        )

        # Gebäude-Hierarchie aufbauen
        areal = Areal(name="")
        building = Building(name="Gebäude")
        wing = Wing(name="Hauptgebäude")

        # Stockwerke sortieren: UG < EG < OG < 1.OG < 2.OG < 3.OG < DG
        sort_order = {code: i for i, code in enumerate(_FLOOR_SORT_ORDER)}
        sorted_floors = sorted(
            floor_rooms.keys(),
            key=lambda c: sort_order.get(c, 99),
        )

        for floor_code in sorted_floors:
            rooms_dict = floor_rooms[floor_code]
            full_name = STANDARD_FLOOR_NAMES.get(floor_code, floor_code)
            hg_number = FLOOR_TO_MAIN_GROUP.get(floor_code, -1)
            floor = Floor(
                name=full_name,
                short_code=floor_code,
                main_group_number=hg_number,
            )
            apartment = Apartment(name=floor_code)
            floor.apartments.append(apartment)

            for room_nr in sorted(rooms_dict.keys()):
                fk = (floor_code, room_nr)
                if fk in col_s_names:
                    room_name = col_s_names[fk]
                else:
                    room_name = self._best_room_name(rooms_dict[room_nr], room_nr)
                room = Room(number=room_nr, name=room_name)
                apartment.rooms.append(room)

            wing.floors.append(floor)
            logger.info(
                f"Stockwerk {floor_code} ({full_name}): {len(rooms_dict)} Räume"
            )

        building.wings.append(wing)
        areal.buildings.append(building)

        total_rooms = sum(len(r) for r in floor_rooms.values())
        logger.info(
            f"Gebäudestruktur abgeleitet: {len(floor_rooms)} Stockwerke, "
            f"{total_rooms} Räume  [{filepath}]"
        )
        return areal

    def _build_areal_from_digit_floors(
        self,
        digit_floor_rooms: dict[str, dict[str, list[str]]],
        ga_structure: "GroupAddressStructure | None",
    ) -> Areal:
        """
        Baut ein Areal aus der Ziffern-Stockwerk-Konvention ('{Gewerk}.{D}{nn}.{Elem}').

        Stockwerksname wird, falls verfügbar, aus der ETS-Hauptgruppe
        übernommen (Hauptgruppe = Stockwerk-Ziffer + 1) -- diese trägt im
        GA-Report meist den echten Stockwerksnamen (z.B. "Erdgeschoss").
        Ohne GA-Struktur wird generisch "Stockwerk N" verwendet.
        """
        hg_names: dict[int, str] = {}
        if ga_structure is not None:
            for hg in ga_structure.main_groups:
                if hg.name and not hg.name.lower().startswith("hauptgruppe"):
                    hg_names[hg.number] = hg.name

        areal = Areal(name="")
        building = Building(name="Gebäude")
        wing = Wing(name="Hauptgebäude")

        for digit in sorted(digit_floor_rooms.keys(), key=int):
            rooms_dict = digit_floor_rooms[digit]
            hg_number = int(digit) + 1
            full_name = hg_names.get(hg_number, f"Stockwerk {digit}")
            short_code = f"D{digit}"
            floor = Floor(
                name=full_name,
                short_code=short_code,
                main_group_number=hg_number,
            )
            apartment = Apartment(name=short_code)
            floor.apartments.append(apartment)

            for room_nr in sorted(rooms_dict.keys()):
                room_name = self._best_room_name(rooms_dict[room_nr], room_nr)
                room = Room(number=room_nr, name=room_name)
                apartment.rooms.append(room)

            wing.floors.append(floor)
            logger.info(f"Stockwerk {short_code} ({full_name}): {len(rooms_dict)} Räume")

        building.wings.append(wing)
        areal.buildings.append(building)

        total_rooms = sum(len(r) for r in digit_floor_rooms.values())
        logger.info(
            f"Gebäudestruktur (Ziffern-Konvention) abgeleitet: "
            f"{len(digit_floor_rooms)} Stockwerke, {total_rooms} Räume"
        )
        return areal

    def _best_room_name(self, descriptions: list[str], fallback_nr: str) -> str:
        """Waehlt den besten Raumnamen aus einer Liste von GA-Beschreibungen.

        GA-Beschreibungen sind Freitext des Installateurs und beschreiben oft
        eine Leuchte/einen Verbraucher statt des Raums selbst (z.B.
        "Wandleuchten Balkon", "Spots Essen") -- ein Wort daraus reicht, um
        die ganze Beschreibung als Raumname zu verwerfen. Bleibt danach kein
        Kandidat übrig, wird bewusst der generische Name "Raum {nr}"
        zurückgegeben statt einer der verworfenen Beschreibungen: eine falsche
        aber plausibel klingende Beschreibung (z.B. eine Leuchten-Bezeichnung)
        als Raumname ist irreführender als ein erkennbarer Platzhalter, den
        der Nutzer manuell korrigiert (siehe Schritt 3 im Wizard).
        """
        if not descriptions:
            return f"Raum {fallback_nr}"
        candidates = [
            d for d in descriptions
            if len(d) >= 4
            and not any(w in _NON_ROOM_WORDS for w in d.lower().split())
        ]
        if not candidates:
            return f"Raum {fallback_nr}"
        # Kuerzeste sinnvolle Beschreibung nehmen (oft der eigentliche Raumname)
        best = min(candidates, key=len)
        # Auf 30 Zeichen begrenzen
        return best[:30] if len(best) <= 30 else best[:27] + "..."

    def _resolve_building_report_columns(self, rows: list) -> dict[str, int]:
        """Ermittelt die 'Adresse'-Spalte des Gebäude-Reports anhand des
        Kopfzeilen-Texts, analog zu `_resolve_topology_columns`."""
        cols: dict[str, int] = {"ADDR": COL_BR_ADDR}
        header_idx: dict[str, int] = {}
        for row in rows[:40]:
            if not row:
                continue
            for idx, cell in enumerate(row):
                if isinstance(cell, str):
                    text = cell.strip()
                    if text and text not in header_idx:
                        header_idx[text] = idx
        for key, (text, delta) in _BR_HEADER_ANCHORS.items():
            if text in header_idx:
                cols[key] = header_idx[text] + delta
        return cols

    def _parse_building_report_tree(
        self, filepath: str,
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict], list[dict]]:
        """
        Liest die Gebäude-Hierarchie aus einem ETS6 'Gebäude'-Report (XLSX).

        Diese Report-Art bildet die tatsächliche ETS6-Gebäudestruktur ab
        (wie im ETS6-Fenster "Gebäude" per Drag&Drop gepflegt), nicht eine
        aus GA-Namen/Freitext abgeleitete Vermutung. Die 'Adresse'-Spalte
        trägt abwechselnd ein Hierarchie-Label -- Einrückung zeigt die Ebene
        (Gebäude=0, Stockwerk=4, Raum/Verteiler=8, im Raum verschachtelter
        Verteiler=12, z.B. ein Heizungsverteiler-Schrank im Raum) -- oder
        eine physikalische Geräteadresse (unverschachtelt, z.B. '1.1.53'),
        die an die zuletzt gesehene Raum-/Verteiler-Zuordnung angehängt wird.
        Sonstige Zeilen unterhalb eines Geräts (Parameterblöcke wie "Taste 1",
        "Kanal 1", Kommunikationsobjekt-Nummern) ändern die aktuelle
        Zuordnung nicht -- sie matchen weder das Raum- noch das
        Verteiler-Muster.

        Gibt zurück:
          floor_room_names: {floor_code -> {room_nr -> room_name}}
          device_locations: {phys_addr -> {"type": "room"/"verteiler", ...}}
          (device_locations hat dasselbe Format wie extract_device_locations)
          verteiler_entries: [{"floor_code", "loc_text", "room_nr"}, ...] --
          ein Eintrag je im Report erkanntem Verteiler (HV/UV/NV/TV/HZV).
          "room_nr" ist gesetzt, wenn der Verteiler in Einrückung 12 direkt
          in einem Raum verschachtelt war (z.B. Heizungsverteiler-Schrank in
          einem Zimmer), sonst None (eigenständiger Verteiler-Raum auf
          Stockwerksebene, z.B. "UV2 (Steigzone)").
        """
        rows = self._load_rows(filepath)

        cols = self._resolve_building_report_columns(rows)
        col = cols["ADDR"]

        floor_room_names: dict[str, dict[str, str]] = {}
        device_locations: dict[str, dict] = {}
        verteiler_entries: list[dict] = []
        seen_verteiler: set[tuple[str, str]] = set()

        current_floor = ""
        current_room_nr: Optional[str] = None
        current_location: Optional[dict] = None

        for row in rows:
            if col >= len(row) or row[col] is None:
                continue
            raw = str(row[col])
            if raw.strip() == "":
                continue
            stripped_left = raw.lstrip(" ")
            indent = len(raw) - len(stripped_left)
            text = stripped_left.strip()

            if _PHYS_ADDR_RE.match(text):
                if current_location is not None and text not in device_locations:
                    device_locations[text] = current_location
                continue

            if indent == 4:
                current_floor = text
                current_room_nr = None
                current_location = None
                continue

            if indent in (8, 12):
                m_room = _EINBAUORT_ROOM_RE.match(text)
                if m_room:
                    room_nr, room_name = m_room.group(1), m_room.group(2).strip()
                    floor_room_names.setdefault(current_floor, {})[room_nr] = room_name
                    current_location = {
                        "type": "room", "room_nr": room_nr, "room_name": room_name,
                    }
                    if indent == 8:
                        current_room_nr = room_nr
                    continue
                m_vt = _VT_RE.match(text)
                if m_vt:
                    current_location = {
                        "type": "verteiler",
                        "vt_type": m_vt.group(1).upper(),
                        "vt_number": m_vt.group(2) or "",
                        "vt_name": (m_vt.group(3) or m_vt.group(4) or "").strip(),
                    }
                    nested_room_nr = current_room_nr if indent == 12 else None
                    dedupe_key = (current_floor, text)
                    if dedupe_key not in seen_verteiler:
                        seen_verteiler.add(dedupe_key)
                        verteiler_entries.append({
                            "floor_code": current_floor,
                            "loc_text": text,
                            "room_nr": nested_room_nr,
                        })
                    if indent == 8:
                        current_room_nr = None
                    continue
                # Sonstiges Label auf Raum-/Verteiler-Ebene (z.B. 'Taste 3',
                # 'Kanal 1') -- ändert die aktuelle Zuordnung nicht.

        return floor_room_names, device_locations, verteiler_entries

    def derive_building_structure_from_building_report(self, filepath: str) -> Areal:
        """
        Leitet die Gebäudestruktur direkt aus einem ETS6 'Gebäude'-Report ab
        (Pendant zu `derive_building_structure`, das die Struktur nur aus
        GA-Namen errät).

        Zuverlässiger als die GA-Namens-Heuristik, da hier die tatsächliche
        ETS6-Raumzuordnung gelesen wird -- unabhängig davon, ob der
        Installateur die GAs konsistent nach einer Namenskonvention
        benannt hat.

        Erzeugt zusätzlich Elektroverteilungen (HV/UV/NV/TV/HZV), die der
        Report als Verteiler-Knoten enthält -- unabhängig von einer
        Topologie-Datei, im Gegensatz zu `create_verteiler_rooms()`, das nur
        aus Geräte-Einbauorten der Topologie ableitet. Ein im Raum
        verschachtelter Verteiler (Einrückung 12, z.B. ein Heizungsverteiler-
        Schrank im Zimmer) wird direkt an den bestehenden Raum gehängt statt
        einen eigenen Pseudo-Raum zu erzeugen -- der Report kennt hier (anders
        als ein XLSX-Einbauort-Freitext) die echte Verschachtelung.
        """
        floor_room_names, _, verteiler_entries = self._parse_building_report_tree(filepath)

        areal = Areal(name="")
        building = Building(name="Gebäude")
        wing = Wing(name="Hauptgebäude")

        if not floor_room_names:
            logger.warning(
                f"Keine Gebäudestruktur aus Gebäude-Report ableitbar  [{filepath}]"
            )
            building.wings.append(wing)
            areal.buildings.append(building)
            return areal

        floor_by_code: dict[str, Floor] = {}
        room_by_floor_nr: dict[tuple[str, str], Room] = {}

        sort_order = {code: i for i, code in enumerate(_FLOOR_SORT_ORDER)}
        for floor_code in sorted(floor_room_names.keys(), key=lambda c: sort_order.get(c, 99)):
            rooms = floor_room_names[floor_code]
            full_name = STANDARD_FLOOR_NAMES.get(floor_code, floor_code)
            hg_number = FLOOR_TO_MAIN_GROUP.get(floor_code, -1)
            floor = Floor(name=full_name, short_code=floor_code, main_group_number=hg_number)
            apartment = Apartment(name=floor_code)
            floor.apartments.append(apartment)

            for room_nr in sorted(rooms.keys()):
                room = Room(number=room_nr, name=rooms[room_nr])
                apartment.rooms.append(room)
                room_by_floor_nr[(floor_code, room_nr)] = room

            wing.floors.append(floor)
            floor_by_code[floor_code] = floor
            logger.info(f"Stockwerk {floor_code} ({full_name}): {len(rooms)} Räume")

        verteiler_count = 0
        for entry in verteiler_entries:
            vt = Verteiler(
                name=entry["loc_text"],
                verteiler_type=self._detect_hv_uv_type(entry["loc_text"]),
            )
            room_nr = entry["room_nr"]
            target_room = (
                room_by_floor_nr.get((entry["floor_code"], room_nr)) if room_nr else None
            )
            if target_room is not None:
                target_room.verteiler.append(vt)
            else:
                floor = floor_by_code.get(entry["floor_code"])
                if floor is None:
                    continue
                pseudo_room = Room(number="", name=entry["loc_text"])
                pseudo_room.verteiler.append(vt)
                floor.apartments[0].rooms.append(pseudo_room)
            verteiler_count += 1

        building.wings.append(wing)
        areal.buildings.append(building)

        total_rooms = sum(len(r) for r in floor_room_names.values())
        logger.info(
            f"Gebäudestruktur aus Gebäude-Report abgeleitet: "
            f"{len(floor_room_names)} Stockwerke, {total_rooms} Räume, "
            f"{verteiler_count} Verteiler  [{filepath}]"
        )
        return areal

    def extract_device_locations_from_building_report(self, filepath: str) -> dict[str, dict]:
        """
        Liest Einbauort-Informationen direkt aus einem ETS6 'Gebäude'-Report
        (Pendant zu `extract_device_locations`, das die GA-Report-Spalte
        'Gebäude' liest). Gleiches Rückgabeformat -- beide Quellen werden in
        `link_rooms_to_lines` kombiniert (siehe MainWindow._collect_device_locations).
        """
        _, device_locations, _ = self._parse_building_report_tree(filepath)
        logger.info(
            f"extract_device_locations_from_building_report: "
            f"{sum(1 for v in device_locations.values() if v['type'] == 'room')} "
            f"Raum-Zuordnungen, "
            f"{sum(1 for v in device_locations.values() if v['type'] == 'verteiler')} "
            f"Verteiler-Zuordnungen  [{filepath}]"
        )
        return device_locations

    def extract_group_addresses(self, filepath: str) -> GroupAddressStructure:
        """
        Extrahiert Gruppenadressen aus dem ETS6-Topologie-Report (XLSX) (FA-519).

        Scannt alle GA-Zellen (Spalte 38) und baut daraus eine
        GroupAddressStructure auf, geordnet nach Haupt- und Mittelgruppe.
        Bereits bekannte Adressen werden nicht doppelt eingefügt.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"XLSX-Datei nicht gefunden: {filepath}")
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für XLSX-Import benoetigt.")

        # Eindeutige GA-Eintraege sammeln: addr_str -> designation-Text
        ga_map: dict[str, str] = {}

        rows = self._load_rows(filepath)

        cols = self._resolve_topology_columns(rows)
        ga_col = cols["GA"]
        for row in rows:
            if not row or len(row) <= ga_col or row[ga_col] is None:
                continue
            text = str(row[ga_col]).strip()
            if not text:
                continue
            for addr, designation in self._parse_ga_entries(text):
                if addr not in ga_map:
                    ga_map[addr] = designation

        if not ga_map:
            logger.warning("Keine Gruppenadressen aus XLSX extrahierbar.")
            return GroupAddressStructure()

        structure = GroupAddressStructure()
        hg_index: dict[int, MainGroup] = {}
        mg_index: dict[tuple[int, int], MiddleGroup] = {}

        for addr_str, designation in sorted(ga_map.items(), key=lambda x: _ga_sort_key(x[0])):
            parts = addr_str.split("/")
            if len(parts) != 3:
                continue
            try:
                hg_num = int(parts[0])
                mg_num = int(parts[1])
                sub_num = int(parts[2])
            except ValueError:
                continue

            if hg_num not in hg_index:
                hg = MainGroup(number=hg_num, name=f"Hauptgruppe {hg_num}")
                hg_index[hg_num] = hg
                structure.main_groups.append(hg)

            mg_key = (hg_num, mg_num)
            if mg_key not in mg_index:
                mg = MiddleGroup(number=mg_num, name=f"Mittelgruppe {mg_num}")
                mg_index[mg_key] = mg
                hg_index[hg_num].middle_groups.append(mg)

            ga = GroupAddress(
                main_group=hg_num,
                middle_group=mg_num,
                sub_group=sub_num,
                designation=designation,
            )
            self._parse_xlsx_designation(ga, designation)
            mg_index[mg_key].group_addresses.append(ga)

        structure.source = "topology"
        logger.info(
            f"XLSX GA-Extraktion: {len(ga_map)} Gruppenadressen, "
            f"{len(hg_index)} Hauptgruppen, {len(mg_index)} Mittelgruppen"
            f"  [{filepath}]"
        )
        return structure

    def _parse_ga_entries(self, text: str) -> list[tuple[str, str]]:
        """
        Extrahiert (Adresse, Bezeichnung)-Paare aus einem GA-Zellentext.

        Beispiel: '3/0/65 LD.EG.05.01_ea ( Licht )  0/0/100'
        -> [('3/0/65', 'LD.EG.05.01_ea ( Licht )'), ('0/0/100', '')]
        """
        matches = list(_GA_RE.finditer(text))
        entries: list[tuple[str, str]] = []
        for i, m in enumerate(matches):
            addr = m.group()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            designation = text[start:end].strip()
            entries.append((addr, designation))
        return entries

    def _parse_xlsx_designation(self, ga: GroupAddress, designation: str):
        """
        Extrahiert Gewerk-Code und Beschreibung aus einer XLSX-GA-Bezeichnung.

        Erwartet das Muster 'GEWERK.ETAGE.RAUM.ELEM_suffix ( Beschreibung )',
        z.B. 'LD.EG.05.01_ea ( Licht )'.
        """
        if not designation:
            return
        # Beschreibung aus Klammern: 'LD.EG.05.01_ea ( Licht )' -> 'Licht'
        paren_m = re.search(r'\(\s*([^)]+)\)', designation)
        if paren_m:
            ga.description = paren_m.group(1).strip()
            base = designation[:paren_m.start()].strip()
        else:
            base = designation.strip()
        # Gewerk-Code: erstes Segment vor '.' oder '_'.
        # Nur uebernehmen, wenn es tatsaechlich ein bekanntes Gewerk-Kuerzel
        # ist -- andere Bezeichnungskonventionen (z.B. Szenen-Controller-GAs
        # wie "Raum1_Szene High", "AK_...", "Tag/Nacht_...") folgen demselben
        # PRAEFIX_Funktion-Muster, sind aber kein Gewerk. Ungeprueft uebernommen
        # tauchten deren Praefixe bisher als scheinbare, aber ungueltige
        # Gewerk-Spalten in der Verknuepfungsmatrix auf (Chalet Franziska
        # 2005: "RAUM1"/"RAUM5"/"AK"/"TAG/NACHT" statt "Sonstige").
        if '.' in base:
            candidate = base.split('.')[0].upper()
        elif '_' in base:
            candidate = base.split('_')[0].upper()
        else:
            candidate = ""
        if candidate in _valid_gewerk_codes():
            ga.gewerk_code = candidate

    def import_ga_report(self, filepath: str) -> GroupAddressStructure:
        """
        Importiert einen ETS6 Gruppenadress-Report (XLSX) (FA-519b).

        Zeilentypen werden anhand der Adress-Spalte unterschieden:
          - Einstellige/-zweistellige Ganzzahl  → Hauptgruppe (Name-Spalte)
          - 'H/M'                               → Mittelgruppe (Name-Spalte)
          - 'H/M/S'                             → Gruppenadresse (Name-Spalte, Datentyp-Spalte)
          - Physikalische Adresse / KO / Header → wird übersprungen

        Die Spaltenindizes werden pro Datei anhand der Kopfzeilen-Texte
        ermittelt (`_resolve_ga_report_columns`), da ETS6 sie je nach
        gewählten Export-Zusatzspalten verschiebt -- feste Indizes führten
        sonst zu leeren GA-Bezeichnungen nach dem Import.
        """
        rows = self._load_rows(filepath)

        cols = self._resolve_ga_report_columns(rows)
        col_addr, col_name, col_dtype = cols["ADDR"], cols["NAME"], cols["DTYPE"]
        meta_label_col, meta_value_delta = self._resolve_ga_report_meta_columns(rows)

        structure = GroupAddressStructure()
        hg_index: dict[int, MainGroup] = {}
        mg_index: dict[tuple[int, int], MiddleGroup] = {}

        current_hg: Optional[MainGroup] = None
        current_mg: Optional[MiddleGroup] = None

        meta: dict = {}
        row_count = 0

        for row in rows:
            if not row:
                continue

            # Metadaten aus Kopfzeilen (erste 20 Zeilen)
            if row_count < 20 and meta_label_col is not None:
                label_raw = row[meta_label_col] if meta_label_col < len(row) else None
                if label_raw is not None:
                    label = str(label_raw).strip().lower().rstrip(":")
                    label_map = {
                        "projekt": "project_name", "project": "project_name",
                        "startdatum": "start_date", "importdatum": "import_date",
                        "druckdatum": "print_date", "druckzeit": "print_time",
                    }
                    if label in label_map:
                        value_col = meta_label_col + meta_value_delta
                        val_raw = row[value_col] if value_col < len(row) else None
                        if val_raw is not None:
                            meta[label_map[label]] = str(val_raw).strip()
            row_count += 1

            addr_raw = row[col_addr] if col_addr < len(row) else None
            if addr_raw is None:
                continue
            addr = str(addr_raw).strip()

            # Hauptgruppe
            if _GAR_HG_RE.match(addr):
                try:
                    hg_num = int(addr)
                except ValueError:
                    continue
                name_raw = row[col_name] if col_name < len(row) else None
                name = str(name_raw).strip() if name_raw else f"Hauptgruppe {hg_num}"
                if hg_num not in hg_index:
                    hg = MainGroup(number=hg_num, name=name)
                    hg_index[hg_num] = hg
                    structure.main_groups.append(hg)
                current_hg = hg_index[hg_num]
                current_mg = None
                continue

            # Mittelgruppe
            if _GAR_MG_RE.match(addr):
                parts = addr.split("/")
                try:
                    hg_num, mg_num = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                name_raw = row[col_name] if col_name < len(row) else None
                name = str(name_raw).strip() if name_raw else f"Mittelgruppe {mg_num}"
                mg_key = (hg_num, mg_num)
                if mg_key not in mg_index:
                    # Hauptgruppe sicherstellen (defensiv)
                    if hg_num not in hg_index:
                        hg = MainGroup(number=hg_num, name=f"Hauptgruppe {hg_num}")
                        hg_index[hg_num] = hg
                        structure.main_groups.append(hg)
                    mg = MiddleGroup(number=mg_num, name=name)
                    mg_index[mg_key] = mg
                    hg_index[hg_num].middle_groups.append(mg)
                current_mg = mg_index[mg_key]
                continue

            # Gruppenadresse
            if _GAR_GA_RE.match(addr):
                parts = addr.split("/")
                try:
                    hg_num, mg_num, sub_num = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    continue
                name_raw = row[col_name] if col_name < len(row) else None
                designation = str(name_raw).strip() if name_raw else ""
                dtype_raw = row[col_dtype] if col_dtype < len(row) else None
                data_type = str(dtype_raw).strip() if dtype_raw else ""

                # Mittelgruppe sicherstellen (defensiv)
                mg_key = (hg_num, mg_num)
                if mg_key not in mg_index:
                    if hg_num not in hg_index:
                        hg = MainGroup(number=hg_num, name=f"Hauptgruppe {hg_num}")
                        hg_index[hg_num] = hg
                        structure.main_groups.append(hg)
                    mg = MiddleGroup(number=mg_num, name=f"Mittelgruppe {mg_num}")
                    mg_index[mg_key] = mg
                    hg_index[hg_num].middle_groups.append(mg)

                ga = GroupAddress(
                    main_group=hg_num,
                    middle_group=mg_num,
                    sub_group=sub_num,
                    designation=designation,
                    datapoint_type=data_type,
                )
                self._parse_xlsx_designation(ga, designation)
                mg_index[mg_key].group_addresses.append(ga)
                continue

        if meta:
            logger.info(
                f"GA-Report Projektname: {meta.get('project_name', '?')} | "
                f"Druckdatum: {meta.get('print_date', '?')}"
            )

        total_gas = sum(
            len(mg.group_addresses)
            for hg in structure.main_groups
            for mg in hg.middle_groups
        )
        structure.source = "ga_report"
        logger.info(
            f"GA-Report importiert: {len(hg_index)} Hauptgruppen, "
            f"{len(mg_index)} Mittelgruppen, {total_gas} Gruppenadressen  [{filepath}]"
        )
        return structure

    def merge_with_csv(self, topology: Topology, ga_structure) -> int:
        """
        Fuehrt Topologie-Report und CSV-GA-Struktur zusammen (FA-520).

        Verknuepft Kommunikationsobjekte mit Gruppenadressen anhand
        der GA-Adresse und gibt die Anzahl der Verknuepfungen zurück.
        """
        ga_index: dict[str, object] = {}
        for ga in ga_structure.all_addresses():
            ga_index[ga.address] = ga

        linked = 0
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    for ko in device.communication_objects:
                        for ga_addr in ko.connected_gas:
                            if ga_addr in ga_index:
                                linked += 1

        logger.info(f"Zusammenfuehrung: {linked} GA-Verknuepfungen hergestellt")
        return linked

    def extract_device_locations(self, filepath: str) -> dict[str, dict]:
        """
        Liest Einbauort-Informationen aus einem ETS6 GA-Report (XLSX).

        Gibt ein Dict zurück: {physikalische_adresse → info}

        'info' hat zwei Formen:
          {"type": "room",      "room_nr": "04", "room_name": "Schlafen"}
          {"type": "verteiler", "vt_type": "UV", "vt_number": "2", "vt_name": "Steigzone"}
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"XLSX-Datei nicht gefunden: {filepath}")
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für XLSX-Import benoetigt.")

        result: dict[str, dict] = {}
        rows = self._load_rows(filepath)

        cols = self._resolve_ga_report_columns(rows)
        col_addr, col_location = cols["ADDR"], cols["LOCATION"]

        for row in rows:
            if not row or col_addr >= len(row) or row[col_addr] is None:
                continue
            addr = str(row[col_addr]).strip()
            if not _PHYS_ADDR_RE.match(addr):
                continue
            loc_raw = row[col_location] if col_location < len(row) else None
            if loc_raw is None:
                continue
            loc = str(loc_raw).strip()

            m_room = _EINBAUORT_ROOM_RE.match(loc)
            if m_room:
                result[addr] = {
                    "type": "room",
                    "room_nr": m_room.group(1),
                    "room_name": m_room.group(2).strip(),
                }
                continue

            m_vt = _VT_RE.match(loc)
            if m_vt:
                result[addr] = {
                    "type": "verteiler",
                    "vt_type": m_vt.group(1).upper(),
                    "vt_number": m_vt.group(2) or "",
                    "vt_name": (m_vt.group(3) or m_vt.group(4) or "").strip(),
                }

        logger.info(
            f"extract_device_locations: {sum(1 for v in result.values() if v['type'] == 'room')} "
            f"Raum-Zuordnungen, "
            f"{sum(1 for v in result.values() if v['type'] == 'verteiler')} "
            f"Verteiler-Zuordnungen  [{filepath}]"
        )
        return result

    def extract_device_notes(self, filepath: str) -> dict[str, str]:
        """
        Liest das Feld 'Installations-Hinweise' pro Gerät aus dem ETS6-
        Topologie-Report (XLSX).

        ETS6 stapelt unterhalb jeder Geräte-Hauptzeile bis zu vier Subzeilen
        (Beschreibung / Seriennummer / Kommentar / Installations-Hinweise),
        alle in Spalte 6 -- derselben Spalte wie die physikalische Adresse.
        Leere Felder erzeugen keine eigene Zeile, daher liegt der Hinweistext
        je Gerät auf unterschiedlicher Zeilenposition; gesucht wird die erste
        Subzeile mit Text in Spalte 6, die nicht wie eine Seriennummer aussieht.

        Installateure tragen hier oft die GA-Kurzbezeichnung ein, die das
        Gerät bedient (z.B. 'L.100.1' oder 'S.203.1_LD.203.1'). Das ist bei
        Aktoren im Verteiler eine zuverlässigere Quelle für den funktional
        bedienten Raum als der physische Einbauort.

        Gibt {physikalische_adresse -> Hinweistext} zurück (nur nicht-leere,
        nicht Seriennummer-artige Werte).
        """
        rows = self._load_rows(filepath)

        cols = self._resolve_topology_columns(rows)
        key_col = cols["KEY"]
        notes: dict[str, str] = {}
        current_addr: Optional[str] = None

        for row in rows:
            key_raw = row[key_col] if key_col < len(row) else None

            if key_raw == "0":
                current_addr = None  # Backbone
                continue
            if isinstance(key_raw, str) and re.match(r"^\d{1,2}$", key_raw.strip()):
                current_addr = None  # Bereich
                continue
            if isinstance(key_raw, str) and _LINE_ADDR_RE.match(key_raw.strip()):
                current_addr = None  # Linie
                continue
            if isinstance(key_raw, str) and _POWER_SUPPLY_RE.match(key_raw.strip()):
                current_addr = None  # Spannungsversorgung
                continue
            if isinstance(key_raw, str) and _PHYS_ADDR_RE.match(key_raw.strip()):
                current_addr = key_raw.strip()
                continue
            if isinstance(key_raw, int):
                continue  # KO-Zeile

            if current_addr and isinstance(key_raw, str):
                text = key_raw.strip()
                if (
                    text
                    and not _SERIAL_NUMBER_RE.match(text)
                    and current_addr not in notes
                ):
                    notes[current_addr] = text

        logger.info(
            f"extract_device_notes: {len(notes)} Installations-Hinweise gefunden  [{filepath}]"
        )
        return notes

    @staticmethod
    def _label_value_pairs_in_row(row: tuple) -> list[tuple[str, str]]:
        """Findet alle 'Label: Wert'-Paare in einer Zeile: jede Zelle, deren
        Text mit ':' endet, gilt als Label; ihr Wert ist die nächste
        nicht-leere Zelle rechts davon in derselben Zeile. Generischer
        Mechanismus, den ETS für beliebige Parameter-Dialoge verwendet
        (unabhängig vom Hersteller/Anwendungsprogramm) -- bis zu zwei Paare
        pro Zeile (linke/rechte Spaltengruppe) werden so gefunden, ohne auf
        feste Spaltenindizes angewiesen zu sein."""
        pairs: list[tuple[str, str]] = []
        for idx, cell in enumerate(row):
            if not isinstance(cell, str) or not cell.strip().endswith(":"):
                continue
            label = re.sub(r"\s+", " ", cell.strip()).rstrip(":").strip()
            if not label:
                continue
            for j in range(idx + 1, len(row)):
                if row[j] is not None:
                    pairs.append((label, str(row[j]).strip()))
                    break
        return pairs

    _BUTTON_CONFIG_SECTION_MARKER = "Konfiguration Tasten"
    _BUTTON_SUBSECTION_RE = re.compile(r"^Taste\b", re.IGNORECASE)

    def extract_button_configuration(self, filepath: str) -> dict[str, str]:
        """
        Liest die Tastenbelegung pro Gerät aus einem ETS6-Report (Topologie-
        ODER Gebäude-Report, jeweils mit Zusatzwahl 'Objekte'/Parameter
        exportiert) -- rein informativ, OHNE automatische Gewerk- oder
        Funktionsableitung daraus.

        ETS exportiert für viele Taster/Sensoren einen Abschnitt
        "Konfiguration Tasten" mit einer Unterüberschrift je physischer
        Taste (z.B. "Taste 1, links") und darunter Label:Wert-Zeilen (z.B.
        "Funktion Taste: Jalousie", "Funktion Jalousie links: AUF ...").
        Diese Label:Wert-Paare sind reiner Anwendungsprogramm-UI-Text -- je
        Hersteller/Produkt völlig unterschiedlich benannt und strukturiert
        (hier z.B. Feller EDIZIOdue). Es gibt daher KEINE generische
        Bedeutung, aus der sich z.B. ein Gewerk zuverlässig ableiten ließe;
        anders benannte Abschnitte anderer Hersteller werden schlicht nicht
        erkannt (Gerät bleibt unerwähnt im Ergebnis-Dict) statt falsch
        interpretiert. Das Ergebnis dient ausschließlich als lesbare
        Referenz (z.B. Tooltip), damit die tatsächliche Tastenfunktion ohne
        Blick in ETS nachvollziehbar ist.

        Gibt {physikalische_adresse -> mehrzeiliger Text} zurück (nur
        Geräte mit erkanntem "Konfiguration Tasten"-Abschnitt).
        """
        rows = self._load_rows(filepath)

        key_col = self._resolve_building_report_columns(rows)["ADDR"]

        # Die Hierarchie-Spalte der Geräte-Parameterausschnitte (Kurzanleitung,
        # Konfiguration Tasten, ...) liegt NICHT zwingend in derselben Spalte
        # wie die physikalische Adresse: im Gebäude-Report ist es dieselbe
        # Spalte, im Topologie-Report eine eigene (dort z.B. Spalte 9 statt 6
        # beobachtet) -- ETS exportiert diesen Abschnitt offenbar mit eigenem
        # Einrückungs-Offset. Statt eine feste Spalte anzunehmen, wird sie
        # anhand des ersten Vorkommens von "Konfiguration Tasten" ermittelt.
        param_col: Optional[int] = None
        for row in rows:
            for idx, cell in enumerate(row):
                if isinstance(cell, str) and cell.strip() == self._BUTTON_CONFIG_SECTION_MARKER:
                    param_col = idx
                    break
            if param_col is not None:
                break

        if param_col is None:
            logger.info(
                f"extract_button_configuration: kein 'Konfiguration Tasten'-"
                f"Abschnitt gefunden  [{filepath}]"
            )
            return {}

        lines_by_addr: dict[str, list[str]] = {}
        current_addr: Optional[str] = None
        in_button_section = False
        current_button: Optional[str] = None

        for row in rows:
            key_raw = row[key_col] if key_col < len(row) else None

            if isinstance(key_raw, str) and _PHYS_ADDR_RE.match(key_raw.strip()):
                current_addr = key_raw.strip()
                in_button_section = False
                current_button = None
            elif key_raw == "0" or (
                isinstance(key_raw, str) and (
                    re.match(r"^\d{1,2}$", key_raw.strip())
                    or _LINE_ADDR_RE.match(key_raw.strip())
                    or _POWER_SUPPLY_RE.match(key_raw.strip())
                )
            ):
                current_addr = None  # Backbone/Bereich/Linie/Spannungsversorgung
                in_button_section = False
                current_button = None

            param_raw = row[param_col] if param_col < len(row) else None
            if isinstance(param_raw, str) and param_raw.strip():
                text = param_raw.strip()
                if in_button_section and self._BUTTON_SUBSECTION_RE.match(text):
                    current_button = text
                    if current_addr:
                        dev_lines = lines_by_addr.setdefault(current_addr, [])
                        if dev_lines:
                            dev_lines.append("")
                        dev_lines.append(f"{text}:")
                    continue
                if text == self._BUTTON_CONFIG_SECTION_MARKER:
                    in_button_section = True
                    current_button = None
                    continue
                # Jeder andere Abschnitts-/Raum-/Stockwerk-Header (z.B.
                # 'Sequenzbaustein', 'Kurzanleitung', bei Gebäude-Report auch
                # Raum-/Stockwerk-Zeilen) beendet die Tastenkonfiguration.
                in_button_section = False
                current_button = None
                continue

            if current_addr and in_button_section:
                for label, value in self._label_value_pairs_in_row(row):
                    prefix = "  " if current_button else ""
                    lines_by_addr.setdefault(current_addr, []).append(
                        f"{prefix}{label}: {value}"
                    )

        button_texts = {
            addr: "\n".join(dev_lines).strip()
            for addr, dev_lines in lines_by_addr.items()
            if any(l.strip() for l in dev_lines)
        }
        logger.info(
            f"extract_button_configuration: {len(button_texts)} Geräte mit "
            f"Tastenbelegung gefunden  [{filepath}]"
        )
        return button_texts

    # -- Szenen-Schaltwerte aus dem Geräteparameter-Abschnitt (FA-1809) -------
    #
    # ETS exportiert bei Schalt-/Dimmaktoren (im Gegensatz zu DALI-Gateways,
    # deren Szenenwerte nur ueber die herstellereigene ETS-DCA-App
    # konfiguriert werden) die konfigurierten Szenen-Schaltwerte je Kanal als
    # lesbaren Text im "Geräteparameter"-Abschnitt -- Format ist je
    # Hersteller/Anwendungsprogramm unterschiedlich (reiner UI-Text, siehe
    # extract_button_configuration). Aktuell erkannt: ABB (Kanal-Subsection
    # "<Kanal>: Szene" mit "Ausgang zu(geo)rdnet zu(Szene 1...64)" +
    # "Standardwert"-Zeilenpaaren) und Hager (je "Ausgang N"-Subsection ein
    # "Szene"-Flag + bedingte "Ausgangszustand für Szene N"-Zeilen). Andere
    # Formate werden schlicht nicht erkannt statt falsch interpretiert.

    _DEVICE_PARAM_SECTION_MARKER = "Geräteparameter"
    _ABB_SCENE_CHANNEL_RE = re.compile(r"^([A-Za-z0-9]+):\s*Szene$")
    _ABB_SCENE_SUBSECTION_RE = re.compile(r"^[A-Za-z0-9]+:\s*\S")
    _ABB_SCENE_ASSIGN_RE = re.compile(r"^Ausgang \S+ zu\(Szene 1\.\.\.64\)$", re.IGNORECASE)
    _ABB_SCENE_NUMBER_RE = re.compile(r"^Szene\s+(\d+)$", re.IGNORECASE)
    _ABB_STANDARDWERT_RE = re.compile(r"^Standardwert$", re.IGNORECASE)
    _HAGER_CHANNEL_HEADER_RE = re.compile(r"^(Ausgang\s+\d+)\s*>", re.IGNORECASE)
    _HAGER_SCENE_STATE_RE = re.compile(
        r"^Ausgangszustand f[üu]r Szene\s+(\d+)$", re.IGNORECASE
    )

    @staticmethod
    def _alternating_pairs_in_row(row: tuple) -> list[tuple[str, str]]:
        """Bildet Label:Wert-Paare aus abwechselnd gefüllten Zellen einer
        Zeile (Label, Wert, Label, Wert, ...), ohne auf ein Doppelpunkt-
        Suffix am Label angewiesen zu sein (anders als
        `_label_value_pairs_in_row` -- die Szenen-Parameterzeilen tragen
        keinen Doppelpunkt am Label, z.B. 'Ausgang zuordnen zu(Szene
        1...64)' gefolgt von 'Szene 2' in der naechsten belegten Zelle)."""
        cells = [str(c).strip() for c in row if c not in (None, "")]
        return [(cells[i], cells[i + 1]) for i in range(0, len(cells) - 1, 2)]

    def extract_scene_values(self, filepath: str) -> dict[str, list["SceneValueEntry"]]:
        """
        Liest konfigurierte Szenen-Schaltwerte pro Gerät/Kanal aus einem
        ETS6-Topologie-Report (XLSX) (FA-1809).

        Gibt {physikalische_adresse -> [SceneValueEntry, ...]} zurück (nur
        Geräte mit erkanntem Muster -- siehe Modulkommentar oben).
        """
        from ..models.topology import SceneValueEntry

        rows = self._load_rows(filepath)
        key_col = self._resolve_building_report_columns(rows)["ADDR"]

        entries_by_addr: dict[str, list[SceneValueEntry]] = {}
        current_addr: Optional[str] = None
        in_params_section = False
        abb_channel: Optional[str] = None
        abb_pending_scene: Optional[int] = None
        hager_channel: Optional[str] = None

        for row in rows:
            key_raw = row[key_col] if key_col < len(row) else None

            if isinstance(key_raw, str) and _PHYS_ADDR_RE.match(key_raw.strip()):
                current_addr = key_raw.strip()
                in_params_section = False
                abb_channel = None
                hager_channel = None
                continue
            if key_raw == "0" or (
                isinstance(key_raw, str) and (
                    re.match(r"^\d{1,2}$", key_raw.strip())
                    or _LINE_ADDR_RE.match(key_raw.strip())
                    or _POWER_SUPPLY_RE.match(key_raw.strip())
                )
            ):
                current_addr = None
                in_params_section = False
                abb_channel = None
                hager_channel = None
                continue

            if not current_addr:
                continue

            cells = [str(c).strip() for c in row if c not in (None, "")]
            if len(cells) == 1:
                text = cells[0]
                if text == self._DEVICE_PARAM_SECTION_MARKER:
                    in_params_section = True
                    continue
                if not in_params_section:
                    continue
                m = self._ABB_SCENE_CHANNEL_RE.match(text)
                if m:
                    abb_channel = m.group(1)
                    abb_pending_scene = None
                    continue
                if self._ABB_SCENE_SUBSECTION_RE.match(text):
                    abb_channel = None
                m = self._HAGER_CHANNEL_HEADER_RE.match(text)
                if m:
                    hager_channel = m.group(1)
                continue

            if not in_params_section:
                continue

            for label, value in self._alternating_pairs_in_row(row):
                if abb_channel:
                    if self._ABB_SCENE_ASSIGN_RE.match(label):
                        m = self._ABB_SCENE_NUMBER_RE.match(value)
                        abb_pending_scene = int(m.group(1)) if m else None
                        continue
                    if self._ABB_STANDARDWERT_RE.match(label) and abb_pending_scene:
                        entries_by_addr.setdefault(current_addr, []).append(
                            SceneValueEntry(
                                channel=abb_channel,
                                scene_number=abb_pending_scene,
                                value=value,
                            )
                        )
                        abb_pending_scene = None
                        continue
                if hager_channel:
                    m = self._HAGER_SCENE_STATE_RE.match(label)
                    if m:
                        entries_by_addr.setdefault(current_addr, []).append(
                            SceneValueEntry(
                                channel=hager_channel,
                                scene_number=int(m.group(1)),
                                value=value,
                            )
                        )

        logger.info(
            f"extract_scene_values: {len(entries_by_addr)} Geräte mit "
            f"Szenen-Schaltwerten gefunden  [{filepath}]"
        )
        return entries_by_addr

    # -- Szenen-Ausloeser aus der Tastenkonfiguration (FA-1810) ---------------
    #
    # Sensor-Gegenstueck zu extract_scene_values: welche Taste sendet welche
    # Szenennummer. Nutzt denselben "Konfiguration Tasten"-Abschnitt wie
    # extract_button_configuration (_BUTTON_CONFIG_SECTION_MARKER,
    # _BUTTON_SUBSECTION_RE), sucht darin aber gezielt nach dem Parameter
    # "1Byte Wert (0..255)" unter "Funktion Wert: 1Byte Wert senden" -- das
    # ist der konfigurierte Szenen-Byte-Wert (0-63 -> Szene 1-64). Ein
    # "Langer Tastendruck ...: aktiv"-Feld schaltet den nachfolgenden Wert auf
    # die Lang-Druck-Variante der Taste um (eigenes ComObject, eigene Szene).
    # Aktuell verifiziert an Feller EDIZIOdue; andere Hersteller/Taster-Serien
    # werden schlicht nicht erkannt statt falsch interpretiert.

    _BYTE_VALUE_LABEL_RE = re.compile(r"^1Byte Wert \(0\.\.255\)$", re.IGNORECASE)
    _LANGER_TASTENDRUCK_RE = re.compile(r"^Langer Tastendruck", re.IGNORECASE)

    def extract_scene_triggers(self, filepath: str) -> dict[str, list["SceneTriggerEntry"]]:
        """
        Liest konfigurierte Szenen-Ausloeser (Taste -> Szenennummer) pro
        Gerät aus einem ETS6-Topologie-Report (XLSX) (FA-1810).

        Gibt {physikalische_adresse -> [SceneTriggerEntry, ...]} zurück (nur
        Geräte mit erkanntem Muster -- siehe Methoden-Kommentar oben).
        """
        from ..models.topology import SceneTriggerEntry

        rows = self._load_rows(filepath)
        key_col = self._resolve_building_report_columns(rows)["ADDR"]

        param_col: Optional[int] = None
        for row in rows:
            for idx, cell in enumerate(row):
                if isinstance(cell, str) and cell.strip() == self._BUTTON_CONFIG_SECTION_MARKER:
                    param_col = idx
                    break
            if param_col is not None:
                break
        if param_col is None:
            return {}

        entries_by_addr: dict[str, list[SceneTriggerEntry]] = {}
        current_addr: Optional[str] = None
        in_button_section = False
        current_button: Optional[str] = None
        in_long_press = False

        for row in rows:
            key_raw = row[key_col] if key_col < len(row) else None

            if isinstance(key_raw, str) and _PHYS_ADDR_RE.match(key_raw.strip()):
                current_addr = key_raw.strip()
                in_button_section = False
                current_button = None
                in_long_press = False
            elif key_raw == "0" or (
                isinstance(key_raw, str) and (
                    re.match(r"^\d{1,2}$", key_raw.strip())
                    or _LINE_ADDR_RE.match(key_raw.strip())
                    or _POWER_SUPPLY_RE.match(key_raw.strip())
                )
            ):
                current_addr = None
                in_button_section = False
                current_button = None
                in_long_press = False

            param_raw = row[param_col] if param_col < len(row) else None
            if isinstance(param_raw, str) and param_raw.strip():
                text = param_raw.strip()
                if in_button_section and self._BUTTON_SUBSECTION_RE.match(text):
                    current_button = text
                    in_long_press = False
                    continue
                if text == self._BUTTON_CONFIG_SECTION_MARKER:
                    in_button_section = True
                    current_button = None
                    in_long_press = False
                    continue
                in_button_section = False
                current_button = None
                in_long_press = False
                continue

            if not (current_addr and in_button_section and current_button):
                continue

            for label, value in self._label_value_pairs_in_row(row):
                if self._LANGER_TASTENDRUCK_RE.match(label):
                    in_long_press = value.strip().lower() == "aktiv"
                    continue
                if not self._BYTE_VALUE_LABEL_RE.match(label):
                    continue
                try:
                    byte_value = int(value.strip())
                except ValueError:
                    continue
                button = (
                    f"{current_button} (langer Tastendruck)" if in_long_press
                    else current_button
                )
                entries_by_addr.setdefault(current_addr, []).append(
                    SceneTriggerEntry(button=button, scene_number=byte_value + 1)
                )

        logger.info(
            f"extract_scene_triggers: {len(entries_by_addr)} Geräte mit "
            f"Szenen-Ausloesern gefunden  [{filepath}]"
        )
        return entries_by_addr

    @staticmethod
    def _room_id_for_designation(
        designation: str, room_id_by_floor_nr: dict[tuple[str, str], str],
    ) -> Optional[str]:
        """Löst eine GA-Bezeichnung (oder einen Installations-Hinweis-Token)
        über die Buchstaben- oder Ziffern-Stockwerkskonvention in eine
        Room-ID auf (gemeinsame Logik für mehrere Raum-Zuordnungsquellen)."""
        m = _GA_FLOOR_ROOM_SIMPLE_RE.match(designation)
        if m:
            rid = room_id_by_floor_nr.get((m.group(1).upper(), m.group(2)))
            if rid:
                return rid
        m_digit = _GA_DIGIT_ROOM_SIMPLE_RE.match(designation)
        if m_digit:
            return room_id_by_floor_nr.get((f"D{m_digit.group(1)}", m_digit.group(2)))
        return None

    def link_rooms_to_lines(
        self,
        topology: Topology,
        ga_structure,
        areal,
        device_locations: dict[str, dict] | None = None,
        device_notes: dict[str, str] | None = None,
    ) -> int:
        """
        Verknüpft Topologie-Linien mit Räumen aus der Gebäudestruktur.

        Ein KNX-Gerät mit physikalischer Adresse ist an genau einem Ort
        montiert -- Aktoren nicht nur in Elektroverteilungen, sondern auch
        direkt in Räumen; Bedienelemente nicht nur in Räumen, sondern auch
        in Elektroverteilungen. `device.room_id` bildet daher primär diesen
        physischen Montageort ab, nicht den funktional bedienten Raum.

        Drei Quellen werden kombiniert, in dieser Priorität:

        1. Installations-Hinweise (device_notes aus extract_device_notes):
           Explizite Freitext-Notiz des Installateurs, z.B. 'L.100.1'.
           Bewusste Annotation -- höchste Priorität, unabhängig von den
           automatisch abgeleiteten Quellen darunter.

        2. Physischer Einbauort (Raum ODER Verteiler): kombiniert
           `device.installation_location` (Topologie-Report, für jedes
           Gerät vorhanden) und device_locations aus extract_device_locations
           (GA-Report, oft mit saubererem Raumnamen). "04 Schlafen" →
           room_nr + room_name → Room-ID; "UV2 (Steigzone)" → Verteiler-
           Room-ID (siehe create_verteiler_rooms, muss vor diesem Aufruf
           bereits gelaufen sein). Das ist die automatische Standardquelle,
           da sie den tatsächlichen Montageort widerspiegelt.

        3. GA-Bezeichnungen der Kommunikationsobjekte (funktionaler Raum):
           'LDA.OG.00.01_ea' bzw. 'L.004.1_ea' → Stockwerk + Raum-Nr → Room-ID.
           Nur als Fallback, wenn Quelle 2 keinen Ort liefert (z.B. Einbauort-
           Text nicht auswertbar). Wird zusätzlich nur akzeptiert, wenn ein
           Raum eine echte absolute Mehrheit der Kanäle stellt (mehr als alle
           anderen Räume zusammen) -- sonst bedient das Gerät klar mehrere
           Räume gleichwertig (z.B. ein 8fach-Schaltaktor mit je einem Kanal
           pro Stockwerk), und "häufigste Raum-ID" wäre bei Gleichstand
           praktisch zufällig.

        Pro Linie werden alle gefundenen Room-IDs in assigned_room_ids eingetragen.
        Pro Gerät wird die ermittelte Room-ID als device.room_id gesetzt.

        Gibt die Anzahl der verknüpften (Linie, Raum)-Paare zurück.
        """
        # GA-Adress-Bezeichnungs-Index aufbauen
        ga_designation: dict[str, str] = {}
        for ga in ga_structure.all_addresses():
            if ga.designation:
                ga_designation[ga.address] = ga.designation

        # Raum-Index 1: (floor_code, room_nr) → room_id  (für GA-Bezeichnungs-Fallback)
        room_id_by_floor_nr: dict[tuple[str, str], str] = {}
        # Raum-Index 2: (room_nr, room_name_lower) → room_id  (für Einbauort)
        room_id_by_nr_name: dict[tuple[str, str], str] = {}
        # Raum-Index 3: Verteiler-Kanonicalkey (Typ+Nummer) → Liste von Räumen
        # (für Einbauort-Verteiler; setzt voraus, dass create_verteiler_rooms()
        # bereits gelaufen ist und die Verteiler-Räume angelegt hat).
        # Meist genau 1 Raum je Key -- eine Liste, weil ein Projekt mehrere
        # gleichartige, unnummerierte Verteiler desselben Typs haben kann
        # (z.B. zwei separate Heizungsverteiler "HzV Garage" und "HzV
        # Galerie", beide Typ HZV ohne Nummer); _resolve_verteiler_room()
        # löst das dann über den Freitext-Namen auf.
        verteiler_rooms_by_key: dict[str, list[Room]] = {}

        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        for room in apartment.rooms:
                            room_id_by_floor_nr[(floor.short_code, room.number)] = room.id
                            room_id_by_nr_name[
                                (room.number, room.name.lower().strip())
                            ] = room.id
                            # Key aus dem Verteiler-Objekt selbst (nicht room.name)
                            # ableiten: nach apply_verteiler_room_overrides() kann
                            # ein Verteiler in einem echten, normal benannten Raum
                            # stecken (z.B. "HV" in "Technikraum") -- room.name
                            # matcht dann nicht mehr das HV/UV/NV/TV-Muster, wohl
                            # aber vt.name/vt.verteiler_type.
                            for vt in room.verteiler:
                                m_vt = _VT_RE.match((vt.name or vt.verteiler_type).strip())
                                if m_vt:
                                    key = _vt_key(m_vt.group(1), m_vt.group(2))
                                    verteiler_rooms_by_key.setdefault(key, []).append(room)

        if not room_id_by_floor_nr:
            logger.warning("link_rooms_to_lines: Keine Räume in Gebäudestruktur.")
            return 0

        linked_pairs = 0
        via_location = 0
        via_ga = 0
        via_note = 0

        for area in topology.areas:
            for line in area.lines:
                line_room_ids: list[str] = []

                for device in line.devices:
                    room_id = None

                    # ── Quelle 1: Installations-Hinweis (expliziter Installateur-Hinweis) ──
                    note = (device_notes or {}).get(device.physical_address, "")
                    if note:
                        note_room_counts: dict[str, int] = {}
                        for token in re.split(r"[_\s]+", note.strip()):
                            if not token:
                                continue
                            rid = self._room_id_for_designation(token, room_id_by_floor_nr)
                            if rid:
                                note_room_counts[rid] = note_room_counts.get(rid, 0) + 1
                        if note_room_counts:
                            room_id = max(
                                note_room_counts, key=note_room_counts.__getitem__
                            )
                            via_note += 1

                    # ── Quelle 2: physischer Einbauort (Raum ODER Verteiler) ──
                    if not room_id:
                        # Kandidaten aus GA-Report (device_locations, meist sauberer
                        # Raumname) und Topologie-Report (device.installation_location,
                        # für jedes Gerät vorhanden) -- beide beschreiben denselben
                        # physischen Montageort, ggf. mit leicht anderem Freitext.
                        candidates: list[dict] = []
                        loc = (device_locations or {}).get(device.physical_address)
                        if loc:
                            candidates.append(loc)
                        raw_topo_loc = (device.installation_location or "").strip()
                        if raw_topo_loc:
                            m_room = _EINBAUORT_ROOM_RE.match(raw_topo_loc)
                            if m_room:
                                candidates.append({
                                    "type": "room",
                                    "room_nr": m_room.group(1),
                                    "room_name": m_room.group(2).strip(),
                                })
                            else:
                                m_vt = _VT_RE.match(raw_topo_loc)
                                if m_vt:
                                    candidates.append({
                                        "type": "verteiler",
                                        "vt_type": m_vt.group(1).upper(),
                                        "vt_number": m_vt.group(2) or "",
                                        "vt_name": (m_vt.group(3) or m_vt.group(4) or "").strip(),
                                    })

                        for cand in candidates:
                            if cand["type"] == "room":
                                nr = cand["room_nr"]
                                raw_name = cand["room_name"].lower().strip()
                                # Normalisierung: '/' entfernen, mehrfache Leerzeichen kürzen
                                norm_name = re.sub(r"\s*/\s*", " ", raw_name)
                                norm_name = re.sub(r"\s+", " ", norm_name).strip()
                                rid = room_id_by_nr_name.get(
                                    (nr, raw_name)
                                ) or room_id_by_nr_name.get((nr, norm_name))
                                # Teilwort-Fallback: alle Wörter des Einbauorts
                                # müssen im Areal-Raumnamen vorkommen (gleiche Nr.)
                                if not rid:
                                    words = [w for w in norm_name.split() if len(w) > 2]
                                    if words:
                                        for (rnr, rname_lc), cand_rid in room_id_by_nr_name.items():
                                            if rnr == nr and all(
                                                w in rname_lc for w in words
                                            ):
                                                rid = cand_rid
                                                break
                            else:  # "verteiler"
                                key = _vt_key(cand["vt_type"], cand.get("vt_number", ""))
                                rid = self._resolve_verteiler_room(
                                    verteiler_rooms_by_key.get(key) or [],
                                    cand.get("vt_name", ""),
                                )

                            if rid:
                                room_id = rid
                                via_location += 1
                                break

                    # ── Quelle 3: GA-Bezeichnungen der KOs (funktionaler Raum,
                    #    Fallback nur ohne auswertbaren physischen Einbauort) ──
                    if not room_id:
                        device_room_counts: dict[str, int] = {}
                        for ko in device.communication_objects:
                            for ga_addr in ko.connected_gas:
                                designation = ga_designation.get(ga_addr, "")
                                if not designation:
                                    continue
                                rid = self._room_id_for_designation(
                                    designation, room_id_by_floor_nr
                                )
                                if rid:
                                    device_room_counts[rid] = (
                                        device_room_counts.get(rid, 0) + 1
                                    )
                        if device_room_counts:
                            best_rid, best_count = max(
                                device_room_counts.items(), key=lambda kv: kv[1]
                            )
                            total = sum(device_room_counts.values())
                            # Nur bei echter absoluter Mehrheit übernehmen -- sonst
                            # bedient das Gerät mehrere Räume gleichwertig (z.B. ein
                            # Schaltaktor im Verteiler mit je einem Kanal pro
                            # Stockwerk) und "häufigste Raum-ID" wäre bei Gleichstand
                            # zufällig.
                            if best_count > total - best_count:
                                room_id = best_rid
                                via_ga += 1

                    if room_id:
                        device.room_id = room_id
                        if room_id not in line_room_ids:
                            line_room_ids.append(room_id)

                for room_id in line_room_ids:
                    if room_id not in line.assigned_room_ids:
                        line.assigned_room_ids.append(room_id)
                        linked_pairs += 1

        logger.info(
            f"link_rooms_to_lines: {linked_pairs} Paare — "
            f"{via_note} via Installations-Hinweis, {via_ga} via GA-Bezeichnung, "
            f"{via_location} via Einbauort."
        )
        return linked_pairs

    @staticmethod
    def verteiler_key(text: str) -> Optional[str]:
        """Kanonischer Verteiler-Key (siehe `_vt_key`) aus einem Einbauort-
        oder Verteiler-Namenstext, z.B. "UV2 (Steigzone)" -> "UV2". None,
        wenn der Text kein HV/UV/NV/TV/HZV-Muster erkennen lässt. Öffentliche
        Fassade für UI-Code (z.B. Step03bVerteiler), das keine privaten
        Modul-Helfer dieses Services importieren soll."""
        m = _VT_RE.match((text or "").strip())
        if not m:
            return None
        return _vt_key(m.group(1), m.group(2))

    @staticmethod
    def _resolve_verteiler_room(rooms: list[Room], vt_name: str) -> Optional[str]:
        """Löst einen Verteiler-Kanonicalkey (Typ+Nummer) zu genau einer
        Room-ID auf, auch wenn mehrere Räume denselben Key tragen.

        Der Kanonicalkey (siehe `_vt_key`) berücksichtigt nur Typ+Nummer,
        nicht den Freitext -- zwei unnummerierte, gleichartige Verteiler
        (z.B. zwei separate Heizungsverteiler "HzV Garage" und "HzV
        Galerie", beide Typ HZV ohne Nummer) kollabieren sonst auf denselben
        Key, wodurch Geräte des einen Verteilers dem jeweils anderen
        zugeordnet würden (sie "verschwinden" optisch aus ihrem echten
        Verteiler). Bei mehreren Kandidaten wird daher zusätzlich der
        Freitext-Name (vt_name, z.B. "Galerie") gegen den Verteiler-/Raum-
        namen abgeglichen. Bleibt die Mehrdeutigkeit trotzdem bestehen (kein
        Freitext verfügbar, oder er passt auf keinen Kandidaten), wird --
        wie im bisherigen Single-Room-Verhalten -- deterministisch der
        erste Kandidat gewählt, statt das Gerät ganz ohne Zuordnung zu
        lassen.
        """
        if not rooms:
            return None
        if len(rooms) == 1:
            return rooms[0].id
        vt_name_lc = vt_name.lower().strip()
        if vt_name_lc:
            for room in rooms:
                for vt in room.verteiler:
                    name_lc = (vt.name or "").lower()
                    if vt_name_lc in name_lc or (name_lc and name_lc in vt_name_lc):
                        return room.id
            for room in rooms:
                if vt_name_lc in room.name.lower():
                    return room.id
        return rooms[0].id

    @staticmethod
    def _detect_hv_uv_type(name: str) -> str:
        """Erkennt den Verteiler-Typ aus dem Einbauort-Text (analog zum
        .knxproj-Import, siehe KnxprojImportService._detect_hv_uv_type)."""
        upper = name.upper()
        if "HV" in upper or "HAUPTVERTEIL" in upper:
            return "HV"
        if "NV" in upper:
            return "NV"
        if "TV" in upper:
            return "TV"
        return "UV"

    def create_verteiler_rooms(self, topology: Topology, areal: Areal) -> int:
        """Erzeugt Räume mit Verteiler-Objekt aus den Einbauort-Texten der
        Topologie-Geräte (z.B. 'HV', 'UV2 (Steigzone)') (FA-521b).

        Der .knxproj-Import erkennt Verteiler strukturell über
        DistributionBoard-Space-Elemente (siehe KnxprojImportService).
        Der XLSX-Export kennt diese Struktur nicht -- hier ist der Einbauort
        nur freier Text pro Gerät. Diese Methode gruppiert Geräte mit
        gleichem, als HV/UV/NV/TV erkanntem Einbauort zu einem gemeinsamen
        Verteiler-Raum. Wird v.a. für KNX-Secure-Projekte benötigt, bei denen
        der .knxproj-Import mangels Entschlüsselung ausfällt und XLSX der
        einzige Importweg ist.

        Der Verteiler-Raum wird immer angelegt, sobald der Einbauort-Text auf
        HV/UV/NV/TV erkannt wird (für Dokumentation/Materialliste/Schritt 3b).
        Muss VOR link_rooms_to_lines() laufen: dessen physische Einbauort-
        Zuordnung (Quelle 2) löst Verteiler-Einbauorte über die hier
        angelegten Räume auf (Index über `_vt_key`) und würde sie sonst
        nicht finden. device.room_id wird hier vorsorglich schon gesetzt
        (falls noch leer) -- link_rooms_to_lines() überschreibt ihn danach
        i.d.R. mit demselben Ergebnis, da es den gleichen physischen
        Einbauort auswertet.

        Enthält `areal` bereits einen Verteiler mit demselben Kanonical-Key
        (z.B. weil derive_building_structure_from_building_report() ihn schon
        direkt aus einem Gebäude-Report angelegt hat -- ggf. sogar korrekt in
        einem echten Raum statt einem Pseudo-Raum verschachtelt), wird dafür
        KEIN zusätzlicher Pseudo-Raum erzeugt; die Geräte werden stattdessen
        dem bestehenden Raum zugeordnet, um Dubletten in der Gebäudestruktur
        zu vermeiden.

        Gibt die Anzahl neu angelegter Verteiler-Räume zurück.
        """
        groups: dict[str, list[Device]] = {}
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    loc = (device.installation_location or "").strip()
                    if not loc or not _VT_RE.match(loc):
                        continue
                    groups.setdefault(loc, []).append(device)

        if not groups:
            return 0

        existing_rooms_by_key: dict[str, list[Room]] = {}
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        for room in apartment.rooms:
                            for vt in room.verteiler:
                                m_vt = _VT_RE.match((vt.name or vt.verteiler_type).strip())
                                if m_vt:
                                    existing_rooms_by_key.setdefault(
                                        _vt_key(m_vt.group(1), m_vt.group(2)), []
                                    ).append(room)

        new_groups: dict[str, list[Device]] = {}
        for loc, devices in groups.items():
            m_vt = _VT_RE.match(loc)
            key = _vt_key(m_vt.group(1), m_vt.group(2)) if m_vt else None
            vt_name = (m_vt.group(3) or m_vt.group(4) or "").strip() if m_vt else ""
            existing_room_id = self._resolve_verteiler_room(
                existing_rooms_by_key.get(key) or [], vt_name
            ) if key else None
            if existing_room_id is not None:
                for device in devices:
                    if not device.room_id:
                        device.room_id = existing_room_id
                continue
            new_groups[loc] = devices

        if not new_groups:
            return 0

        if not areal.buildings:
            areal.buildings.append(Building(name="Gebäude"))
        building = areal.buildings[0]
        if not building.wings:
            building.wings.append(Wing(name="Hauptgebäude"))
        wing = building.wings[0]

        floor = Floor(name="Verteiler", short_code="VT")
        apartment = Apartment(name="VT")
        floor.apartments.append(apartment)

        for loc, devices in new_groups.items():
            room = Room(number="", name=loc)
            room.verteiler.append(
                Verteiler(name=loc, verteiler_type=self._detect_hv_uv_type(loc))
            )
            apartment.rooms.append(room)
            for device in devices:
                if not device.room_id:
                    device.room_id = room.id

        wing.floors.append(floor)
        logger.info(
            f"Verteiler-Räume aus Einbauort erkannt: {len(new_groups)} "
            f"({', '.join(sorted(new_groups))})"
        )
        return len(new_groups)

    def apply_verteiler_room_overrides(
        self, topology: Topology, areal: Areal, overrides: dict[str, list],
    ) -> int:
        """Verschiebt Verteiler-Pseudo-Räume in den vom Nutzer festgelegten
        echten Raum (siehe Step03bVerteiler._move_verteiler_to_room).

        create_verteiler_rooms() legt bei JEDEM Import einen neuen, unnum-
        merierten Pseudo-Raum je erkanntem Verteiler an (z.B. "HV  HV"), auch
        wenn der Nutzer diesen Verteiler zuvor bereits manuell dem Raum
        zugeordnet hat, in dem er tatsächlich physisch montiert ist (z.B.
        "Technikraum") -- ein XLSX-Export kennt diese Schachtelung nicht,
        anders als die DistributionBoard-Struktur eines .knxproj-Imports.
        Diese Methode wendet eine einmal vorgenommene Zuordnung automatisch
        wieder an, damit sie Re-Importe übersteht.

        `overrides`: kanonischer Verteiler-Key (siehe `_vt_key`, z.B. "HV",
        "UV2") -> [floor_short_code, room_number] des Zielraums. Muss NACH
        create_verteiler_rooms() und VOR link_rooms_to_lines() aufgerufen
        werden, damit Geräte direkt dem Zielraum zugeordnet werden statt
        zunächst dem (gleich wieder verschwindenden) Pseudo-Raum.

        Gibt die Anzahl zusammengeführter Verteiler zurück.
        """
        if not overrides:
            return 0

        room_by_floor_nr: dict[tuple[str, str], Room] = {}
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        for room in apartment.rooms:
                            room_by_floor_nr[(floor.short_code, room.number)] = room

        merged = 0
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        for pseudo_room in list(apartment.rooms):
                            if pseudo_room.number or not pseudo_room.verteiler:
                                continue  # nur unnummerierte Verteiler-Pseudo-Räume
                            m_vt = _VT_RE.match(pseudo_room.name.strip())
                            if not m_vt:
                                continue
                            key = _vt_key(m_vt.group(1), m_vt.group(2))
                            target_ref = overrides.get(key)
                            if not target_ref or len(target_ref) != 2:
                                continue
                            target = room_by_floor_nr.get(tuple(target_ref))
                            if not target or target is pseudo_room:
                                continue

                            target.verteiler.extend(pseudo_room.verteiler)
                            for area in topology.areas:
                                for line in area.lines:
                                    if pseudo_room.id in line.assigned_room_ids:
                                        remapped = [
                                            target.id if rid == pseudo_room.id else rid
                                            for rid in line.assigned_room_ids
                                        ]
                                        # Duplikate entfernen (falls Zielraum die
                                        # Linie bereits kannte), Reihenfolge egal.
                                        line.assigned_room_ids = list(dict.fromkeys(remapped))
                                    for device in line.devices:
                                        if device.room_id == pseudo_room.id:
                                            device.room_id = target.id
                            apartment.rooms.remove(pseudo_room)
                            merged += 1

        if merged:
            logger.info(f"Verteiler-Raum-Zuordnungen angewendet: {merged}")
        return merged

    _FEEDBACK_KO_HINTS = ("led", "signal", "status", "rückmeldung", "rueckmeldung", " rm ", "_rm")

    # Erkennt KO-Namen wie "Taste 1, links" -- identisch zu
    # KnxprojImportService._TASTE_KO_RE. Dient hier dazu, bei Tasterkombi-
    # nationen geräteinterne Neben-KOs ohne physische Taste (z.B. "Nachtab-
    # senkung LED's") von den echten Tasten-KOs zu unterscheiden.
    _TASTE_KO_RE = re.compile(r"\btaste\s*\d+", re.IGNORECASE)

    def _button_key(self, label: str) -> str:
        """Normalisiert einen KO-Namen auf die physische Taste, der er angehört.

        ETS modelliert eine physische Taste teils als MEHRERE separate KOs mit
        gemeinsamem Basis-Namen, die sich nur durch einen Rückmelde-Zusatz
        unterscheiden -- z.B. "Taste 4, links" (Schalten), "Taste 4, links"
        (Dimmen) und "Taste 4, links, Signal-LED" (Status) sind drei KOs
        derselben Taste. Schneidet daher alle kommagetrennten Segmente ab
        Segment 1 ab, sobald eines einen Rückmelde-Hinweis enthält -- das
        erste Segment ("Taste N") bleibt immer erhalten.
        """
        segments = [s.strip() for s in label.split(",")]
        key_segments = segments[:1]
        for seg in segments[1:]:
            if any(hint in seg.lower() for hint in self._FEEDBACK_KO_HINTS):
                break
            key_segments.append(seg)
        return ", ".join(key_segments)

    def backfill_function_assignments(
        self,
        topology: Topology,
        areal: Areal,
        group_addresses: "GroupAddressStructure",
    ) -> int:
        """Ergänzt function_assignments direkt aus den KO-GA-Verknüpfungen
        importierter Geräte (FA-521c).

        SensorService.auto_assign_functions() leitet Funktionszuordnungen aus
        room.gewerk_assignments her und schlägt dafür (gewerk_code, room,
        element_number, GroupAddress.function_name) in der GA-Struktur nach.
        element_number/function_name werden aber nur von KNiX' eigener
        Adress-Generierung (Schritt 7) gesetzt -- nie von einem Import (weder
        .knxproj noch XLSX). Für importierte Projekte bleiben Bedienelemente
        dadurch ohne jede Funktionszuordnung, obwohl die echten Kanal→GA-
        Zuordnungen bereits an Device.communication_objects[].connected_gas
        vorhanden sind (siehe enrich_device_ko_connections).

        Übernimmt diese KO→GA-Paare direkt als SensorFunktion (Direkte-GA-
        Variante, siehe SensorFunktion-Docstring) statt über die Gewerk-
        Funktionsnamen-Tabelle zu suchen. Greift NUR bei Bedienelementen ohne
        vorhandene function_assignments -- nicht-invasiv gegenüber der
        Wizard-Gewerkeplanung (auto_assign_functions bleibt für neu geplante
        Projekte unverändert die massgebliche Quelle).

        Eine physische Taste kann mehrere GAs tragen (eigene Schalt-GA +
        zusätzlich verknüpfte Status-GA, damit die Taste den von anderen
        Sensoren beeinflussten Gewerkzustand kennt) -- und ETS verteilt diese
        teils auf mehrere KOs mit gemeinsamem Basis-Namen statt auf ein
        einziges KO mit mehreren GAs (z.B. "Taste 4, links" für Schalten UND
        für Dimmen als zwei KOs, plus "Taste 4, links, Signal-LED" als
        drittes). Bei erkannten Tastereinheiten werden daher alle KOs mit
        gleichem Basis-Namen (siehe `_button_key`) zu EINER SensorFunktion
        gebündelt; innerhalb eines KOs gilt die erste GA als Befehl, alle
        weiteren als Rückmeldung, zusätzlich markiert jeder KO-Name mit
        Rückmelde-Hinweis (siehe `_FEEDBACK_KO_HINTS`) seine GA(s) als
        Rückmeldung. Vorher wurde pro GA bzw. pro KO eine eigene SensorFunktion
        erzeugt, wodurch z.B. 4 physische Tasten mit je einer Rückmelde-GA als
        8 "Tasten", oder eine dimmbare Taste mit Schalten+Dimmen+Status-LED
        als 3 "Tasten" im Bauherr-Formular erschienen.

        Geräteinterne Neben-KOs ohne "Taste N" im Namen (z.B. "Nachtabsenkung
        LED's") sind bei Tastereinheiten keiner physischen Taste zugeordnet,
        beeinflussen aber dennoch das Gerät -- sie werden als eigene
        SensorFunktion mit role="fremdsteuerung" übernommen (nicht als Taste
        gezählt, be.channels zählt nur echte "Taste N"-Gruppen). Für andere
        Bedienelement-Typen (Fensterkontakt, Melder, Raumthermostat, ...),
        deren KOs nie "Taste N" heissen, greifen weder dieser Filter noch die
        Bündelung nach Basis-Namen (dort bleibt es bei einer SensorFunktion
        pro KO, role stets "befehl"/"rueckmeldung").

        Gibt die Anzahl neu erstellter FunctionAssignment-Einträge zurück.
        """
        from .sensor_service import SensorService

        device_by_addr: dict[str, Device] = {
            d.physical_address: d
            for area in topology.areas
            for line in area.lines
            for d in line.devices
            if d.physical_address
        }
        ga_designation: dict[str, str] = {
            ga.address: ga.designation
            for ga in group_addresses.all_addresses()
            if ga.designation
        }

        def ga_text(addr: str) -> str:
            designation = ga_designation.get(addr, "")
            return f"{addr}  {designation}".strip() if designation else addr

        def make_sf(label: str, gas: list[tuple[str, str, bool]],
                    default_role: str) -> SensorFunktion:
            """Baut eine SensorFunktion aus (ga_addr, description, is_feedback)-
            Tupeln: die erste GA wird primär (SensorFunktion.ga_designation/
            primary_role), alle weiteren landen in extra_gas (FA-1410d) -- so
            überlebt die volle Taste jede spätere Neuableitung von
            function_assignments aus funktionen (z.B. durch
            SensorService.auto_assign_functions, das BelegungsplanService.
            generate() bei jedem Öffnen von Topologie/Verknüpfungsmatrix
            aufruft)."""
            primary_addr, _, primary_is_fb = gas[0]
            sf = SensorFunktion(
                label=label, ga_designation=ga_text(primary_addr),
                primary_role="rueckmeldung" if primary_is_fb else default_role,
            )
            for ga_addr, desc, is_fb in gas[1:]:
                sf.extra_gas.append(SensorFunktionGa(
                    ga_designation=ga_text(ga_addr),
                    role="rueckmeldung" if is_fb else default_role,
                    description=desc,
                ))
            return sf

        added = 0
        for room in areal.all_rooms:
            for be in room.bedienelemente:
                if be.function_assignments or not be.participant_number:
                    continue
                device = device_by_addr.get(be.participant_number)
                if not device:
                    continue

                kos = [ko for ko in device.communication_objects if ko.connected_gas]
                is_taster = be.element_type == "Tastereinheit" and any(
                    self._TASTE_KO_RE.search(ko.name or "") for ko in kos
                )

                funktionen: list[SensorFunktion] = []
                assignments: list[FunctionAssignment] = []

                if is_taster:
                    taste_kos = [ko for ko in kos if self._TASTE_KO_RE.search(ko.name or "")]
                    other_kos = [ko for ko in kos if not self._TASTE_KO_RE.search(ko.name or "")]

                    groups: dict[str, list] = {}
                    for ko in taste_kos:
                        groups.setdefault(self._button_key(ko.name or ""), []).append(ko)

                    for key, group_kos in groups.items():
                        gas: list[tuple[str, str, bool]] = []
                        for ko in group_kos:
                            ko_is_feedback = any(
                                hint in (ko.name or "").lower() for hint in self._FEEDBACK_KO_HINTS
                            )
                            desc = ko.name or ko.object_function or key
                            for idx, ga_addr in enumerate(ko.connected_gas):
                                gas.append((ga_addr, desc, ko_is_feedback or idx > 0))
                        if not gas:
                            continue
                        sf = make_sf(key, gas, default_role="befehl")
                        funktionen.append(sf)
                        assignments.extend(SensorService._expand_direct_ga(sf, sf.label))
                    be.channels = len(groups)

                    # Geräteinterne Neben-KOs ohne "Taste N" im Namen (z.B.
                    # "Nachtabsenkung LED's") sind keine physische Taste, aber
                    # dennoch eine GA-Verknüpfung, die den Taster beeinflusst --
                    # als Fremdsteuerung erfassen statt zu verwerfen.
                    for ko in other_kos:
                        if not ko.connected_gas:
                            continue
                        label = ko.name or ko.object_function or ko.connected_gas[0]
                        gas = [(addr, label, False) for addr in ko.connected_gas]
                        sf = make_sf(label, gas, default_role="fremdsteuerung")
                        funktionen.append(sf)
                        assignments.extend(SensorService._expand_direct_ga(sf, sf.label))
                else:
                    for ko in kos:
                        label = ko.name or ko.object_function or ko.connected_gas[0]
                        ko_is_feedback = any(
                            hint in (label or "").lower() for hint in self._FEEDBACK_KO_HINTS
                        )
                        gas = [
                            (addr, label, ko_is_feedback or idx > 0)
                            for idx, addr in enumerate(ko.connected_gas)
                        ]
                        sf = make_sf(label, gas, default_role="befehl")
                        funktionen.append(sf)
                        assignments.extend(SensorService._expand_direct_ga(sf, sf.label or "GA"))
                if not funktionen:
                    continue

                be.funktionen = funktionen
                be.is_auto = False
                be.function_assignments = assignments
                added += len(assignments)

        logger.info(f"backfill_function_assignments: {added} Funktionszuordnungen aus KOs übernommen.")
        return added

    def enrich_device_ko_connections(
        self,
        topology: Topology,
        filepath: str,
    ) -> tuple[int, int]:
        """
        Ergänzt KO-Verbindungen in der Topologie aus einem ETS6 GA-Report (XLSX).

        Der GA-Report enthält pro Gerät alle Kanäle mit vollständiger GA-Liste
        (col 28 = alle verbundenen GAs, nicht nur die aktuelle).
        Diese Methode:
          - ERSETZT connected_gas bestehender KOs durch die (laut GA-Report
            vollständige) neu geparste Liste, statt nur fehlende Einträge zu
            ergänzen -- rein additives Mergen würde veraltete Bindungen über
            beliebig viele Re-Importe hinweg mitschleppen, wenn zwischen zwei
            GA-Report-Importen kein voller Topologie-Re-Import stattfand (der
            die Geräteliste ohnehin komplett neu aufbaut). Beobachtet am
            Chalet-Projekt: KO "Ausgang 1 Schalten" von Gerät 1.1.15 hatte
            nach mehreren GA-Report-Re-Importen drei GAs angesammelt, obwohl
            der aktuelle Export für dieses KO nur eine listet -- vermutlich
            weil sich ETS' KO-Nummerierung zwischen zwei Export-Generationen
            verschoben hatte und die additive Anreicherung dadurch einmalig
            eine fremde Adresse auf das heute an dieser Nummer sitzende KO
            übertragen hatte, die seither nie wieder entfernt wurde.
            Bleibt die neu geparste Liste für ein KO leer (keine GAs in
            dieser Report-Zeile gefunden), wird die bestehende Liste NICHT
            angetastet -- eine leere Zeile ist kein verlässliches Signal,
            dass die Bindung wirklich entfernt wurde.
          - fügt vollständig fehlende KOs hinzu

        Gibt (enriched_devices, added_cos) zurück.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"XLSX-Datei nicht gefunden: {filepath}")
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für XLSX-Import benoetigt.")

        # ── Schritt 1: GA-Report parsen → {phys_addr → {ko_num → CO}} ──
        parsed: dict[str, dict[int, CommunicationObject]] = {}
        # Gerätemetadaten aus GA-Report (Produkt, Hersteller) für neue Geräte
        parsed_device_meta: dict[str, dict] = {}

        rows = self._load_rows(filepath)

        cols = self._resolve_ga_report_columns(rows)
        col_addr, col_product, col_location = cols["ADDR"], cols["PRODUCT"], cols["LOCATION"]
        col_ko_dtype, col_ko_prio, col_ko_flags, col_ko_gas = (
            cols["KO_DTYPE"], cols["KO_PRIO"], cols["KO_FLAGS"], cols["KO_GAS"],
        )

        current_phys: Optional[str] = None

        for row in rows:
            if not row or col_addr >= len(row) or row[col_addr] is None:
                continue
            addr_raw = str(row[col_addr]).strip()

            # Gerätezeile
            if _PHYS_ADDR_RE.match(addr_raw):
                current_phys = addr_raw
                if current_phys not in parsed:
                    parsed[current_phys] = {}
                    parsed_device_meta[current_phys] = {
                        "product": _cell(row, col_product),
                        "location": _cell(row, col_location),
                    }
                continue

            # KO-Zeile
            if current_phys and _GAR_KO_RE.match(addr_raw):
                m_ko = re.match(r"^(\d+):\s*(.+)$", addr_raw)
                if not m_ko:
                    continue
                ko_num = int(m_ko.group(1))
                ko_desc = m_ko.group(2).strip()

                # KO-Name und Funktion trennen: "Ausgang B - Schalten" / "G1, Schalten, - An/Aus"
                parts = ko_desc.rsplit(" - ", 1)
                ko_name = parts[0].strip()
                ko_func = parts[1].strip() if len(parts) == 2 else ""

                gas_raw = row[col_ko_gas] if col_ko_gas < len(row) else None
                connected_gas = _GA_RE.findall(str(gas_raw)) if gas_raw else []

                if ko_num not in parsed[current_phys]:
                    parsed[current_phys][ko_num] = CommunicationObject(
                        object_number=ko_num,
                        name=ko_name,
                        object_function=ko_func,
                        data_type=_cell(row, col_ko_dtype),
                        priority=_cell(row, col_ko_prio) or "Niedrig",
                        flags=_cell(row, col_ko_flags),
                        connected_gas=connected_gas,
                    )
                else:
                    # KO bereits vorhanden: fehlende GAs ergänzen
                    existing = parsed[current_phys][ko_num]
                    for ga in connected_gas:
                        if ga not in existing.connected_gas:
                            existing.connected_gas.append(ga)

            # Neue GA-Zeile → nächste Gerätesektion beginnt beim nächsten Gerät
            elif _GAR_GA_RE.match(addr_raw):
                current_phys = None

        # ── Schritt 2: Topologie-Geräte anreichern ──
        enriched_devices = 0
        added_cos = 0
        added_devices = 0

        # Index: phys_addr → Device
        device_index: dict[str, Device] = {
            dev.physical_address: dev
            for area in topology.areas
            for line in area.lines
            for dev in line.devices
            if dev.physical_address
        }

        # Index: line_addr (z.B. "1.1") → Line
        line_index: dict[str, Line] = {
            f"{area.area_number}.{line.line_number}": line
            for area in topology.areas
            for line in area.lines
        }

        for phys_addr, ko_map in parsed.items():
            device = device_index.get(phys_addr)
            if not device:
                # Gerät nur im GA-Report vorhanden (z.B. Taster ohne Topologie-Eintrag)
                # → anhand der physikalischen Adresse der richtigen Linie zuordnen
                m = _PHYS_ADDR_RE.match(phys_addr)
                if not m:
                    continue
                line_addr = f"{m.group(1)}.{m.group(2)}"
                target_line = line_index.get(line_addr)
                if not target_line:
                    continue
                meta = parsed_device_meta.get(phys_addr, {})
                device = Device(
                    physical_address=phys_addr,
                    product=meta.get("product", ""),
                    installation_location=meta.get("location", ""),
                    device_type=self._classify_device(phys_addr, meta.get("product", "")),
                )
                target_line.devices.append(device)
                device_index[phys_addr] = device
                added_devices += 1

            # Index bestehender KOs: ko_num → CO
            existing_kos: dict[int, CommunicationObject] = {
                co.object_number: co for co in device.communication_objects
            }

            changed = False
            for ko_num, new_co in ko_map.items():
                if ko_num in existing_kos:
                    # Verbundene GAs durch die (laut GA-Report vollstaendige)
                    # neu geparste Liste ERSETZEN statt nur zu ergaenzen --
                    # siehe Docstring-Begruendung oben. Leere neue Liste ->
                    # bestehende Daten unangetastet lassen.
                    existing = existing_kos[ko_num]
                    if new_co.connected_gas and set(new_co.connected_gas) != set(existing.connected_gas):
                        existing.connected_gas = list(new_co.connected_gas)
                        changed = True
                else:
                    # KO komplett neu hinzufügen
                    device.communication_objects.append(new_co)
                    added_cos += 1
                    changed = True

            if changed:
                enriched_devices += 1

        logger.info(
            f"enrich_device_ko_connections: {enriched_devices} Geräte angereichert, "
            f"{added_cos} neue KOs hinzugefügt, "
            f"{added_devices} fehlende Geräte (Taster/Sensor) ergänzt  [{filepath}]"
        )
        if added_devices:
            for area in topology.areas:
                for line in area.lines:
                    line.update_device_count()
        return enriched_devices, added_cos
