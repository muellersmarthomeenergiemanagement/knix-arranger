"""
DaliService – DALI-Konfigurationsverwaltung (FA-2801 bis FA-2806).

Verantwortlich für:
- Ermittlung von DALI-Gateways aus der Topologie
- Anlegen/Abrufen von DaliGateway-Konfigurationen
- Verknüpfung von KNX-GAs mit dem DALI-Gateway (FA-2803)
- Generierung der DALI-Geräteliste für Dokumentation (FA-2805)
- Checklisten-Punkte für Notbeleuchtung (FA-2804)
"""
from __future__ import annotations
import re
import logging
from ..models.dali_config import DaliGateway, DaliDevice, DaliGroup, DaliScene, EMERGENCY_MODES

logger = logging.getLogger("knix_arranger.dali_service")

# GA-Adress-Pattern für Validierung
_GA_RE = re.compile(r"^\d+/\d+/\d+$")

# LDA-GA-Bezeichnung: "LDA_001_01 E/A" → (room_nr="001", elem_nr="01", func="E/A")
# KNiX-eigene NamingEngine-Konvention ("KNX Swiss Bezeichnungskonzept"),
# vergeben von der App selbst beim Neu-Generieren von Adressen (Schritt 7).
_LDA_PREFIX_RE = re.compile(r"^LDA_(\w+)_(\d{2})\s+(.+)$", re.IGNORECASE)

# LDA-GA-Bezeichnung nach ETS6-XLSX-Importkonvention (siehe
# xlsx_import_service._GA_FLOOR_ROOM_RE): "LDA.OG.00.02_ea" bzw. mehrere per
# "+" verknüpfte Raum-Codes für eine Broadcast-GA, z.B.
# "LDA.OG.00.02+LDA.OG.00.01_ea". Das ist die Bezeichnung, die der
# Installateur selbst in ETS vergeben hat -- bei importierten (nicht in
# KNiX Arranger neu generierten) Projekten die tatsächlich vorkommende Form,
# im Gegensatz zur obigen NamingEngine-Konvention mit Leerzeichen.
_LDA_DOT_RE = re.compile(r"^LDA\.[A-Z0-9]{2,5}\.\d{2}\.\d{1,3}", re.IGNORECASE)
_LDA_DOT_ROOM_RE = re.compile(r"\.([A-Z0-9]{2,5})\.(\d{2})\.\d{1,3}", re.IGNORECASE)
# War frueher mit \s*$ ans Stringende verankert -- Installateure haengen in ETS
# oft noch einen Freitext-Kommentar HINTER dem Funktions-Suffix an, bevor die
# Klammer-Bezeichnung kommt (z.B. "LDA.EG.00.01_ea von pir  ( Spots
# Haupteingang )"). Mit der Endanker-Verankerung schlug das Parsen dieser GA
# komplett fehl -- sie wurde nie einer DALI-Gruppe zugeordnet und tauchte in
# der DALI-Konfiguration nirgends auf, obwohl sie uebers CO-Verknuepfungs-
# Formular sichtbar an DALI-COs haengt. Da es pro Bezeichnung nur ein "_"
# vor dem Funktions-Suffix gibt (Raum-Codes enthalten keine Unterstriche,
# siehe _LDA_DOT_ROOM_RE), findet ein unverankertes search() weiterhin genau
# die richtige Stelle, auch mit nachfolgendem Freitext.
_LDA_DOT_SUFFIX_RE = re.compile(r"_([a-zA-Z]+)")
# Suffix (Kleinschreibung) → kanonische Funktionsbezeichnung, wie sie
# find_lda_ga() für die NamingEngine-Konvention erwartet (siehe
# create_dali_block_schema in models/address_block.py für die vollständige
# Liste; "wert" fehlt hier bewusst -- das ist der Sollwert-Kanal [Schreiben],
# keine der fünf DaliGateway-Zielgrößen unten).
_LDA_DOT_SUFFIX_TO_FUNC = {
    "ea": "e/a",
    "dim": "dim",
    "szene": "szene",
    "scene": "szene",
    "stoerung": "stoerung",
    "rm": "rm",
    "rmwert": "rm wert",
}


def _lda_dot_convention_func(desig: str) -> str:
    """Extrahiert die kanonische Funktionsbezeichnung aus einer LDA-GA im
    XLSX-Importformat (siehe `_LDA_DOT_RE`). Leerstring, wenn die
    Bezeichnung nicht dieser Konvention folgt oder das Suffix unbekannt ist.
    """
    if not _LDA_DOT_RE.match(desig):
        return ""
    base = desig.split("(", 1)[0].strip()  # Klartext-Kommentar abtrennen
    m = _LDA_DOT_SUFFIX_RE.search(base)
    if not m:
        return ""
    return _LDA_DOT_SUFFIX_TO_FUNC.get(m.group(1).lower(), "")


def _lda_dot_room_numbers(desig: str) -> set[str]:
    """Alle Raumnummern aus einer (ggf. per '+' mehrfachen) LDA-GA im
    XLSX-Importformat, z.B. "LDA.OG.00.02+LDA.OG.00.01_ea" -> {"00"}."""
    return {m.group(2) for m in _LDA_DOT_ROOM_RE.finditer(desig)}


def _lda_dot_room_numbers_ordered(desig: str) -> list[str]:
    """Wie `_lda_dot_room_numbers`, aber als Liste in Vorkommensreihenfolge
    (ohne Duplikate) -- für die Gruppen-Namensbildung, bei der die
    Reihenfolge der '+'-verknüpften Raum-Codes erhalten bleiben soll."""
    seen: list[str] = []
    for m in _LDA_DOT_ROOM_RE.finditer(desig):
        nr = m.group(2)
        if nr not in seen:
            seen.append(nr)
    return seen


# Funktions-Suffix (Kleinschreibung) → GROSSGESCHRIEBENE Funktionsbezeichnung,
# wie sie _derive_groups_from_import()/_derive_evgs_from_import() für die
# NamingEngine-Konvention erwarten. Enthält bewusst auch "wert"/"rmwert"
# (anders als _LDA_DOT_SUFFIX_TO_FUNC oben) -- hier wird der Sollwert-/
# Rückmelde-Kanal einer DALI-Gruppe zugeordnet, keine der fünf
# DaliGateway-Zielgrößen aus find_lda_ga().
_LDA_DOT_SUFFIX_TO_GROUP_FUNC = {
    "ea": "E/A",
    "dim": "DIM",
    "wert": "WERT",
    "rmwert": "RM WERT",
    "helligkeitswert": "HELLIGKEITSWERT",
}


def _parse_lda_designation_for_grouping(desig: str) -> tuple[str, str] | None:
    """Liefert (Gruppen-Schlüssel, FUNKTION) aus einer LDA-GA-Bezeichnung,
    für beide bekannten Namenskonventionen (siehe `_LDA_PREFIX_RE` und
    `_LDA_DOT_RE`/`_lda_dot_key` oben). Der Schlüssel ist für beide
    Konventionen ein String (bei der NamingEngine-Konvention "{room_nr}_
    {elem_nr}"), damit `sorted()` auf der gemischten Gruppenliste nicht mit
    einem TypeError (Tupel vs. String) abbricht. None, wenn `desig` keiner
    der beiden Konventionen folgt.
    """
    m = _LDA_PREFIX_RE.match(desig)
    if m:
        return f"{m.group(1)}_{m.group(2)}", m.group(3).strip().upper()

    key = _lda_dot_key(desig)
    if not key:
        return None
    base = desig.split("(", 1)[0].strip()
    m2 = _LDA_DOT_SUFFIX_RE.search(base)
    if not m2:
        return None
    func = _LDA_DOT_SUFFIX_TO_GROUP_FUNC.get(m2.group(1).lower())
    return (key, func) if func else None


def _designation_comment(desig: str) -> str:
    """Extrahiert den Klartext-Kommentar in Klammern einer GA-Bezeichnung,
    z.B. "LDA.EG.00.01_ea von pir  ( Spots Haupteingang )" -> "Spots
    Haupteingang". Leerstring, wenn keine Klammer vorhanden ist."""
    if "(" not in desig or ")" not in desig:
        return ""
    return desig.split("(", 1)[1].rsplit(")", 1)[0].strip()


def _group_name_for_key(key: str, room_index: dict[str, str], comment: str = "") -> str:
    """Menschenlesbarer Gruppenname aus dem Schlüssel von
    `_parse_lda_designation_for_grouping()`, für beide Konventionen.

    `comment`: bei einer disambiguierten Kollisions-Gruppe (siehe
    `_assign_lda_slot`) der Klartext-Kommentar der jeweiligen GA -- aussage-
    kräftiger als der (identische) Raumname beider kollidierenden Gruppen."""
    if comment:
        return comment
    if _LDA_DOT_RE.match(key):
        names: list[str] = []
        for room_nr in _lda_dot_room_numbers_ordered(key):
            name = room_index.get(room_nr, f"Raum {room_nr}")
            if name not in names:
                names.append(name)
        return " + ".join(names) if names else key
    if "_" in key:
        room_nr, elem_nr = key.rsplit("_", 1)
        room_name = room_index.get(room_nr, f"Raum {room_nr}")
        return room_name if elem_nr == "01" else f"{room_name} {elem_nr}"
    return key


_LDA_FUNC_TO_SLOT = {
    "E/A": "switch", "SCHALTEN": "switch", "SWITCH": "switch",
    "DIM": "dim", "DIMMEN": "dim",
    "WERT": "value", "RM WERT": "value", "HELLIGKEITSWERT": "value", "VALUE": "value",
}


def _same_mirrored_target(addr_a: str, addr_b: str) -> bool:
    """True, wenn zwei GA-Adressen sich NUR in der Mittelgruppe unterscheiden
    (z.B. "2/0/5" vs "2/7/5"): das übliche Muster für eine Status-/Spiegel-
    Adresse derselben physischen Gruppe (Mittelgruppe 0 = Befehl, 7 = Status
    -- projektübliche Konvention), selbst wenn beide GAs identisch oder
    ähnlich benannt wurden. Unterscheiden sie sich zusätzlich in Haupt- oder
    Untergruppe, ist es eine andere physische Adresse, kein blosser Spiegel
    -- der Freitext-Kommentar allein ist dafür kein verlässliches Kriterium
    (siehe _assign_lda_slot)."""
    pa, pb = addr_a.split("/"), addr_b.split("/")
    if len(pa) != 3 or len(pb) != 3:
        return False
    return pa[0] == pb[0] and pa[2] == pb[2] and pa[1] != pb[1]


def _assign_lda_slot(lda_groups: dict[str, dict], key: str, func: str, ga_addr: str) -> None:
    """Trägt `ga_addr` in das zu `func` passende Funktions-Feld (switch/dim/
    value) der LDA-Gruppe `key` in `lda_groups` ein (baut den Eintrag bei
    Bedarf neu auf).

    Trägt derselbe Schlüssel für dasselbe Feld bereits eine ANDERE Adresse,
    wird anhand der Adressstruktur unterschieden (siehe `_same_mirrored_
    target`), NICHT anhand des Freitext-Kommentars -- der reicht nicht: im
    Chalet-Projekt tragen sowohl die reine Status-Spiegeladresse EINER
    Gruppe ("2/7/0") als auch eine per Bewegungsmelder ausgelöste, aber
    physisch ANDERE Schalt-GA ("2/0/3") denselben Kommentartext "Spots
    Haupteingang" wie die Haupt-GA ("2/0/0") -- Kommentargleichheit hätte
    "2/0/3" also fälschlich ebenfalls verworfen.

    - Nur unterschiedliche Mittelgruppe (z.B. "2/0/5"/"2/7/5"): sehr
      wahrscheinlich dieselbe physische Gruppe, nur doppelt/inkonsistent
      benannt (realer Befund: praktisch jede DALI-Gruppe im Chalet-Projekt
      hatte neben ihrer MG-0-Steuer-GA eine MG-7-"Status"-GA mit identischem
      Freitext, nur die Suffix-Funktion "_ea" wurde beim Kopieren nicht
      angepasst). Die zuerst gefundene Adresse (durch sortierte Verarbeitung
      die MG-0/Steuer-Adresse) wird behalten, die weitere ignoriert --
      sonst würde praktisch jede Gruppe unnötig verdoppelt.
    - Abweichende Haupt- oder Untergruppe: eine ETS-seitige Bezeichnungs-
      Kollision, keine echte Duplizierung. Sie früher stillschweigend zu
      verlieren (letzter Schreibzugriff gewinnt) war der Grund, warum eine
      importierte GA (Chalet Franziska 2005: "2/0/3") in der DALI-
      Konfiguration nirgends auftauchte, obwohl sie laut CO-Verknüpfung
      sichtbar an DALI-Kommunikationsobjekten hängt. Die zusätzliche GA
      bekommt stattdessen einen eigenen, disambiguierten Schlüssel und wird
      als eigene Gruppe angelegt.
    """
    slot = _LDA_FUNC_TO_SLOT.get(func)
    if slot is None:
        return
    target_key = key
    if key in lda_groups and lda_groups[key][slot] and lda_groups[key][slot] != ga_addr:
        existing_addr = lda_groups[key][slot]
        if _same_mirrored_target(existing_addr, ga_addr):
            logger.debug(
                f"DALI _derive_groups: '{ga_addr}' vermutlich Status-/"
                f"Spiegeladresse von '{existing_addr}' (Schlüssel '{key}', "
                f"Feld '{slot}') -- ignoriert."
            )
            return
        target_key = f"{key}†{ga_addr}"
        logger.warning(
            f"DALI _derive_groups: LDA-Schlüssel '{key}' ist für '{slot}' "
            f"mehrfach vergeben ({existing_addr!r} und {ga_addr!r}, "
            f"unterschiedliche Haupt-/Untergruppe) -- '{ga_addr}' als eigene "
            f"Gruppe angelegt, ETS-Bezeichnung prüfen."
        )
    if target_key not in lda_groups:
        lda_groups[target_key] = {
            "switch": "", "dim": "", "value": "", "name": "", "_base_key": key,
        }
    lda_groups[target_key][slot] = ga_addr


def _lda_primary_room_and_elem(desig: str) -> tuple[str, str]:
    """Liefert (room_nr, elem_nr) einer LDA-GA für beide Namenskonventionen
    -- für Anzeige-/Zuordnungszwecke (EVG-Name, Raumzuordnung in
    `_derive_evgs_from_import`). Bei der Importkonvention mit mehreren
    '+'-verknüpften Raum-Codes wird der erste genommen (ein EVG sitzt
    physisch in genau einem Raum, auch wenn seine Broadcast-GA mehrere
    Räume gemeinsam schaltet); elem_nr bleibt dort leer, da es dort keine
    projektweit eindeutige Elementnummer über mehrere Räume hinweg gibt.
    ("", "") wenn `desig` keiner der beiden Konventionen folgt.
    """
    m = _LDA_PREFIX_RE.match(desig)
    if m:
        return m.group(1), m.group(2)
    if _LDA_DOT_RE.match(desig):
        room_nrs = _lda_dot_room_numbers_ordered(desig)
        if room_nrs:
            return room_nrs[0], ""
    return "", ""


def _lda_dot_key(desig: str) -> str:
    """Gibt den Bezeichnungs-Präfix vor dem Funktions-Suffix zurück, z.B.
    "LDA.OG.00.02+LDA.OG.00.01_ea" -> "LDA.OG.00.02+LDA.OG.00.01". Eindeutig
    pro Broadcast-Ziel (Kombination von Raum-Codes), unabhängig von der
    jeweiligen Funktions-GA -- Pendant zum (room_nr, elem_nr)-Schlüssel der
    NamingEngine-Konvention, nur als String statt als Tupel (muss mit dessen
    Schlüsseln sortierbar bleiben, siehe `_derive_groups_from_import`).
    Leerstring, wenn `desig` nicht der Importkonvention folgt.
    """
    if not _LDA_DOT_RE.match(desig):
        return ""
    base = desig.split("(", 1)[0].strip()
    m = _LDA_DOT_SUFFIX_RE.search(base)
    if not m:
        return ""
    return base[: m.start()]

# KO-Name-Pattern für Gruppen/Kanäle:
#   Deutsch: "Gruppe 3 Schalten", "Kanal 2 Dimmen relativ"
#   Englisch: "Group 1, Switching", "Group 2, Dimming", "Group 3, Set Value"
_KO_GROUP_RE = re.compile(
    r"(?:gruppe|group|kanal|channel|ausgang|output)\s+(\d+)[\s,]+"
    r"(schalten|switching|switch|on[./]?off|dimmen|dimming|dim"
    r"|helligkeitswert|set\s+value|value|wert)",
    re.IGNORECASE,
)

# Kurzform mancher Hersteller (z.B. Chalet-Projekt-Gateway): "G2, Schalten,",
# "G5, Status," -- ohne das ausgeschriebene "Gruppe"/"Group". Muss am
# Stringanfang stehen, sonst matcht es faelschlich Text mitten im Namen.
_KO_GROUP_SHORT_RE = re.compile(r"^G\s*(\d+)\s*,", re.IGNORECASE)


def _ko_group_number(co_name: str) -> int | None:
    """Extrahiert die physische DALI-Gruppennummer (1-basiert, wie sie der
    Hersteller im KO-Namen vergibt) aus einem Kommunikationsobjekt-Namen,
    oder None wenn keines der bekannten Namensmuster passt."""
    name = co_name or ""
    m = _KO_GROUP_RE.search(name)
    if m:
        return int(m.group(1))
    m = _KO_GROUP_SHORT_RE.match(name)
    if m:
        return int(m.group(1))
    return None

# KO-Name-Pattern für Einzelgeräte/EVGs (Herstellervarianten):
#   "EVG 5 Schalten", "Betriebsgerät 3 Dimmen", "Einzelgerät 1 - Schalten",
#   "Individual 2 On/Off", "Ballast 4 Dim", "Leuchte 7 Schalten", "Gear 1 Switch"
_KO_EVG_RE = re.compile(
    r"(?:evg|betriebsger[äa]t|einzelger[äa]t|ballast|individual|leuchte|gear)\s*[-–]?\s*(\d+)"
    r"(?:\s*[-–]\s*|\s+)"
    r"(schalten|switch|on[./]?off|dimmen|dim|relativ|helligkeitswert|value|wert)",
    re.IGNORECASE,
)


class DaliService:
    """Verwaltung der DALI-Konfigurationen eines Projekts."""

    # ── Gateway-Ermittlung ────────────────────────────────────────────────────

    def get_dali_gateways_from_topology(self, project) -> list:
        """Gibt alle Topology-Devices zurück, die DALI-Gateways sind.

        Bedingung: device_type in {"gateway"} und gewerk_code == "LDA"
        oder actor_type enthält "DALI".
        """
        gateways = []
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if self._is_dali_gateway(device):
                        gateways.append(device)
        return gateways

    @staticmethod
    def _is_dali_gateway(device) -> bool:
        """Prüft ob ein Topology-Device ein DALI-Gateway ist.

        Primärkriterium: Produktname enthält "dali" (herstellerunabhängig).
        Sekundärkriterium: device_type ist kein reines Infrastrukturgerät.

        Hintergrund: Der XLSX-Topologie-Import klassifiziert Geräte anhand
        der physikalischen Adresse (1–100 = actor, 101–199 = sensor). Ein
        DALI-Gateway mit hoher Teilnehmernummer würde sonst als "sensor"
        eingestuft und nicht erkannt.
        """
        product_lower = (device.product or "").lower()
        if "dali" not in product_lower:
            return False
        # Koppler und Speisegeräte ausschliessen
        return device.device_type not in ("coupler", "power_supply")

    # ── Konfiguration anlegen/abrufen ─────────────────────────────────────────

    def get_or_create(self, project, gateway_device_id: str, name: str = "") -> DaliGateway:
        """Gibt die DaliGateway-Konfiguration für ein Device zurück; legt sie an falls nötig."""
        if gateway_device_id not in project.dali_configs:
            config = DaliGateway(
                gateway_device_id=gateway_device_id,
                name=name or f"DALI-Gateway {gateway_device_id[:8]}",
            )
            project.dali_configs[gateway_device_id] = config
        return project.dali_configs[gateway_device_id]

    # ── GA-Verknüpfung (FA-2803) ──────────────────────────────────────────────

    def link_gas_from_structure(self, dali_gw: DaliGateway, project) -> int:
        """Sucht passende KNX-GAs in der GA-Struktur und verknüpft sie.

        Strategie (FA-2803):
        1. Findet das Gateway-Device in der Topologie über gateway_device_id,
           ermittelt dessen Linie und die zugehörigen Räume.
        2. Sucht GAs mit LDA_-Prefix nach KNX-Arranger-Namenskonvention:
           E/A → switch_broadcast, DIM → dim_broadcast,
           RM WERT → status_value, RM → (Rückmeldung, kein Fault)
        3. Fallback: Keyword-Suche in allen GAs.

        Gibt die Anzahl verknüpfter GAs zurück.
        """
        all_gas = project.group_addresses.all_addresses()
        linked = 0

        # ── Schritt 1: Räume auf der Gateway-Linie ermitteln ─────────────────
        room_numbers: set[str] = set()
        if dali_gw.gateway_device_id:
            for area in project.topology.areas:
                for line in area.lines:
                    if any(d.id == dali_gw.gateway_device_id for d in line.devices):
                        room_index = {r.id: r for r in project.all_rooms}
                        for rid in line.assigned_room_ids:
                            room = room_index.get(rid)
                            if room and room.number:
                                room_numbers.add(room.number)
                        break

        # ── Schritt 2: LDA-GAs nach Namenskonvention suchen ──────────────────
        # Filtert optional auf Räume der Gateway-Linie (wenn bekannt)
        def find_lda_ga(suffix: str, exclude_suffix: str = "") -> str:
            # Sucht LDA-GAs nach beiden bekannten Namenskonventionen (siehe
            # _LDA_PREFIX_RE / _LDA_DOT_RE oben):
            #   NamingEngine: "LDA_xxx_xx <suffix> [optionaler Kommentar]"
            #   XLSX-Import:  "LDA.xxx.xx.yy[+...]_<suffix> [(Kommentar)]"
            # suffix z.B. " E/A", " DIM", " RM WERT", " RM"
            suffix_lc = suffix.strip().lower()
            excl_lc = exclude_suffix.strip().lower()
            candidates = []
            for ga in all_gas:
                desig = (ga.designation or "").strip()
                if not _GA_RE.match(ga.address or ""):
                    continue

                func_lc = ""
                room_nrs: set[str] = set()
                if desig.upper().startswith("LDA_"):
                    # Funktions-Teil: alles nach "LDA_xxx_xx "
                    parts = desig.split(" ", 1)
                    if len(parts) < 2:
                        continue
                    func_lc = parts[1].lower()
                    room_nr = desig.split("_")[1] if "_" in desig else ""
                    if room_nr:
                        room_nrs = {room_nr}
                else:
                    func_lc = _lda_dot_convention_func(desig)
                    if not func_lc:
                        continue
                    room_nrs = _lda_dot_room_numbers(desig)

                # func_lc ist z.B. "e/a (garage)" oder "dim" oder "rm wert"
                if not (func_lc == suffix_lc or func_lc.startswith(suffix_lc + " ")):
                    continue
                if excl_lc and (func_lc == excl_lc or func_lc.startswith(excl_lc + " ")):
                    continue
                priority = 0 if room_nrs & room_numbers else 1
                candidates.append((priority, ga.address))
            if candidates:
                return sorted(candidates)[0][1]
            return ""

        # ── Schritt 3: Keyword-Fallback für nicht-LDA-GAs ────────────────────
        def find_ga_keyword(keywords: list[str], exclude: list[str] = None) -> str:
            exclude = exclude or []
            for ga in all_gas:
                text = (ga.designation or "").lower()
                if any(kw in text for kw in keywords) and \
                   not any(ex in text for ex in exclude):
                    if _GA_RE.match(ga.address or ""):
                        return ga.address
            return ""

        # switch_broadcast: E/A
        if not dali_gw.ga_switch_broadcast:
            addr = find_lda_ga(" e/a") or find_ga_keyword(
                ["schalten", "switch", "on_off", "broadcast"], ["dim", "szene", "status"])
            if addr:
                dali_gw.ga_switch_broadcast = addr
                linked += 1

        # dim_broadcast: DIM (aber nicht RM WERT)
        if not dali_gw.ga_dim_broadcast:
            addr = find_lda_ga(" dim") or find_ga_keyword(
                ["dimmen", "dim", "helligkeit", "brightness"], ["szene", "status", "rm"])
            if addr:
                dali_gw.ga_dim_broadcast = addr
                linked += 1

        # scene: SZENE aus LDA-GA (neuer 10er-Block), Fallback Keyword
        if not dali_gw.ga_scene:
            addr = find_lda_ga("szene") or find_ga_keyword(["szene", "scene"])
            if addr:
                dali_gw.ga_scene = addr
                linked += 1

        # status_value: RM WERT (bevorzugt vor RM)
        if not dali_gw.ga_status_value:
            addr = find_lda_ga("rm wert") or find_lda_ga("rm") or find_ga_keyword(
                ["istwert", "rueckmeldung", "feedback", "rm wert"], ["stoerung", "fault"])
            if addr:
                dali_gw.ga_status_value = addr
                linked += 1

        # status_fault: nur aus LDA-STOERUNG-GA, kein Keyword-Fallback
        if not dali_gw.ga_status_fault:
            addr = find_lda_ga("stoerung")
            if addr:
                dali_gw.ga_status_fault = addr
                linked += 1

        logger.info(f"DaliService: {linked} GAs für Gateway '{dali_gw.name}' verknüpft.")
        return linked

    # ── Geräteliste für Dokumentation (FA-2805) ───────────────────────────────

    def generate_device_list(self, dali_gw: DaliGateway, project) -> list[dict]:
        """Generiert eine strukturierte DALI-Geräteliste für Revisionsunterlagen.

        Rückgabe: Liste von Dicts mit keys:
            short_address, name, evg_type, room, groups, is_emergency, emergency_mode,
            ga_switch, ga_dim, ga_scene
        """
        room_map = {r.id: r.name for r in project.all_rooms}

        rows = []
        for dev in sorted(dali_gw.devices, key=lambda d: d.short_address):
            group_names = []
            for g_nr in sorted(dev.group_memberships):
                grp = next((g for g in dali_gw.groups if g.number == g_nr), None)
                group_names.append(grp.name if grp and grp.name else f"Gruppe {g_nr}")

            rows.append({
                "short_address": dev.short_address,
                "name": dev.name or f"EVG {dev.short_address}",
                "evg_type": dev.evg_type,
                "room": room_map.get(dev.room_id, ""),
                "groups": ", ".join(group_names),
                "is_emergency": dev.is_emergency,
                "emergency_mode": EMERGENCY_MODES.get(dev.emergency_mode, dev.emergency_mode),
                "ga_switch": dali_gw.ga_switch_broadcast,
                "ga_dim": dali_gw.ga_dim_broadcast,
                "ga_scene": dali_gw.ga_scene,
            })
        return rows

    # ── Notlicht-Checkliste (FA-2804) ─────────────────────────────────────────

    def generate_emergency_checklist_items(self, dali_gw: DaliGateway) -> list[dict]:
        """Generiert Checklisten-Punkte für DALI-Notlicht-EVGs.

        Rückgabe: Liste von Dicts mit keys: text, category, device_name, device_address
        """
        items = []
        for dev in dali_gw.devices:
            if not dev.is_emergency:
                continue
            name = dev.name or f"EVG {dev.short_address}"
            items += [
                {
                    "text": f"DALI Notlicht {name} (Adr. {dev.short_address}): "
                             "Funktionstest – 1 h Betrieb nach Netzausfall",
                    "category": "DALI Notbeleuchtung",
                    "device_name": name,
                    "device_address": dev.short_address,
                },
                {
                    "text": f"DALI Notlicht {name} (Adr. {dev.short_address}): "
                             "Dauerbetriebstest – Vollentladungstest (≥ 3 h)",
                    "category": "DALI Notbeleuchtung",
                    "device_name": name,
                    "device_address": dev.short_address,
                },
            ]
        return items

    # ── Gruppen-Synchronisation (Hilfsmethode) ────────────────────────────────

    def sync_groups_from_devices(self, dali_gw: DaliGateway) -> None:
        """Aktualisiert DaliGroup.device_addresses aus DaliDevice.group_memberships."""
        group_map: dict[int, list[int]] = {}
        for dev in dali_gw.devices:
            for g_nr in dev.group_memberships:
                group_map.setdefault(g_nr, []).append(dev.short_address)

        for grp in dali_gw.groups:
            grp.device_addresses = sorted(group_map.get(grp.number, []))

    def resync_group_numbers(self, dali_gw: DaliGateway, device) -> int:
        """
        Gleicht bestehende DaliGroup.number-Werte mit der physischen
        DALI-Gruppennummer ab, die im ETS-KO-Namen des Gateways steht
        (z.B. "G5, Schalten," -> Nummer 4, 0-basiert). Behebt das
        "Auseinanderlaufen" zwischen der in der App angezeigten Nummer
        (ursprünglich nur Sortierposition der Raum-Schlüssel, siehe
        _derive_groups_from_import) und der echten Gruppennummer im
        DALI-Gateway.

        Name, GA-Verknüpfungen und Geräte bleiben unverändert -- nur die
        Nummer wird korrigiert, und referenzierende
        DaliDevice.group_memberships werden entsprechend mitverschoben,
        damit EVG-Zuordnungen nicht auf die falsche (jetzt anders belegte)
        Nummer zeigen.

        Gruppen ohne eindeutig auflösbare physische Nummer (kein
        passendes KO gefunden, oder mehrdeutig -- dieselbe GA an mehrere
        physische Gruppen gebunden) behalten ihre bisherige Nummer, sofern
        die frei ist, sonst rücken sie auf die nächste freie Nummer.

        Gibt die Anzahl tatsächlich geänderter Gruppennummern zurück.
        """
        ga_to_real_nr: dict[str, int] = {}
        for co in device.communication_objects:
            nr = _ko_group_number(co.name)
            if nr is None:
                continue
            for ga_addr in co.connected_gas:
                ga_to_real_nr[ga_addr] = nr

        groups_sorted = sorted(dali_gw.groups, key=lambda g: g.number)

        # Phase A: Gruppen mit eindeutig auflösbarer physischer Nummer
        # beanspruchen ihren Zielplatz zuerst (deterministisch nach
        # aufsteigender aktueller Nummer verarbeitet).
        target: dict[int, int] = {}  # id(grp) -> neue Nummer
        used: set[int] = set()
        for grp in groups_sorted:
            real_nr = (
                ga_to_real_nr.get(grp.ga_switch)
                or ga_to_real_nr.get(grp.ga_dim)
                or ga_to_real_nr.get(grp.ga_value)
            )
            if real_nr is None:
                continue
            want = real_nr - 1
            if want < 0 or want in used:
                continue
            target[id(grp)] = want
            used.add(want)

        # Phase B: Rest behält die aktuelle Nummer, falls frei -- sonst
        # nächste freie Nummer (verhindert Kollision mit Phase-A-Zielen).
        next_seq = 0
        for grp in groups_sorted:
            if id(grp) in target:
                continue
            if grp.number not in used:
                target[id(grp)] = grp.number
                used.add(grp.number)
            else:
                while next_seq in used:
                    next_seq += 1
                target[id(grp)] = next_seq
                used.add(next_seq)

        remap = {grp.number: target[id(grp)] for grp in groups_sorted}
        changed = sum(1 for old, new in remap.items() if old != new)
        if changed:
            for grp in groups_sorted:
                grp.number = target[id(grp)]
            for dev in dali_gw.devices:
                dev.group_memberships = [remap.get(nr, nr) for nr in dev.group_memberships]
        return changed

    # ── Standard-Szenen anlegen ───────────────────────────────────────────────

    @staticmethod
    def ensure_default_scenes(dali_gw: DaliGateway) -> None:
        """Legt Szenen 0–3 an, falls noch keine Szenen vorhanden sind."""
        if dali_gw.scenes:
            return
        defaults = [
            (0, "Präsenz"),
            (1, "Putzen"),
            (2, "Nacht"),
            (3, "Aus"),
        ]
        for nr, name in defaults:
            dali_gw.scenes.append(DaliScene(number=nr, name=name))

    # ── Import-Automatisierung ────────────────────────────────────────────────

    def auto_configure_from_import(self, project) -> int:
        """
        Konfiguriert alle DALI-Gateways automatisch nach einem XLSX/knxproj-Import.

        Pro erkanntem Gateway:
        1. DaliGateway-Config anlegen (get_or_create)
        2. Broadcast-GAs verknüpfen (link_gas_from_structure)
        3. Gruppen aus LDA-GAs oder KO-Namen ableiten (_derive_groups_from_import)
        4. Standard-Szenen anlegen (ensure_default_scenes)

        Gibt die Gesamtzahl verknüpfter GAs zurück.
        """
        gateways = self.get_dali_gateways_from_topology(project)
        if not gateways:
            return 0

        # Veraltete Configs entfernen (gateway_device_id nicht mehr in Topologie)
        active_ids = {d.id for d in gateways}
        stale = [k for k in project.dali_configs if k not in active_ids]
        for k in stale:
            del project.dali_configs[k]
            logger.debug(f"DALI: veraltete Config '{k[:8]}' entfernt.")

        total_linked = 0
        for device in gateways:
            gw = self.get_or_create(
                project,
                device.id,
                name=device.product_name or device.product or "DALI-Gateway",
            )
            # Broadcast-GAs nur verknüpfen wenn noch leer
            if not (gw.ga_switch_broadcast or gw.ga_dim_broadcast):
                total_linked += self.link_gas_from_structure(gw, project)

            # Gruppen ableiten (nur wenn noch keine vorhanden)
            if not gw.groups:
                self._derive_groups_from_import(gw, device, project)

            # EVGs ableiten (nur wenn noch keine vorhanden)
            if not gw.devices:
                self._derive_evgs_from_import(gw, device, project)

            self.ensure_default_scenes(gw)

        logger.info(
            f"DALI auto_configure_from_import: {len(gateways)} Gateway(s), "
            f"{total_linked} GAs verknüpft."
        )
        return total_linked

    def _derive_groups_from_import(
        self, dali_gw: DaliGateway, device, project
    ) -> int:
        """
        Leitet DALI-Gruppen aus dem importierten Gerät ab.

        Strategie 1 – LDA-GAs (beide Namenskonventionen, siehe
          `_parse_lda_designation_for_grouping`): NamingEngine
          ('LDA_xxx_xx FUNKTION') oder ETS6-XLSX-Importkonvention
          ('LDA.Stockwerk.Raum.Elem[+...]_funktion'). Alle GAs werden nach
          ihrem Gruppen-Schlüssel gruppiert (Raum+Element bzw. die exakte
          Raum-Code-Kombination); jede eindeutige Kombination ergibt eine
          DALI-Gruppe mit ga_switch (E/A) und ga_dim (DIM).

        Strategie 2 – KO-Namen (ETS6-Import ohne LDA-Konvention):
          KO-Namen des Gateway-Devices werden auf
          'Gruppe/Kanal X Schalten/Dimmen' geparst.
          Die verbundene GA des KOs wird der Gruppe zugeordnet.

        Gibt die Anzahl angelegter Gruppen zurück.
        """
        ga_by_addr = {
            ga.address: ga
            for ga in project.group_addresses.all_addresses()
        }

        # ── Strategie 1: LDA-GAs ──────────────────────────────────────────────
        # Alle LDA-GAs die mit diesem Gateway verbunden sind
        # (über connected_gas der KOs oder alle LDA-GAs der Linie)
        connected_gas: set[str] = set()
        for co in device.communication_objects:
            connected_gas.update(co.connected_gas)

        # LDA-GAs aus connected_gas parsen. Sortiert iterieren (nicht direkt
        # über das set()): wenn zwei GAs auf denselben (key, func) zusammen-
        # fallen (z.B. zwei "_ea"-GAs derselben Gruppe), gewinnt die zuletzt
        # verarbeitete -- mit einem set() haengt das von der Python-Hash-
        # Reihenfolge ab und war bisher zwischen Prozessläufen nicht
        # reproduzierbar (unterschiedliches Ergebnis bei jedem Neustart der
        # App, ohne dass sich am Projekt etwas geändert hätte).
        lda_groups: dict[str, dict] = {}  # Gruppen-Schlüssel → {switch, dim, value, name}
        for ga_addr in sorted(connected_gas):
            ga = ga_by_addr.get(ga_addr)
            if not ga or not ga.designation:
                continue
            parsed = _parse_lda_designation_for_grouping(ga.designation.strip())
            if not parsed:
                continue
            key, func = parsed
            _assign_lda_slot(lda_groups, key, func, ga_addr)

        # Falls keine connected GAs bekannt: alle LDA-GAs der GA-Struktur prüfen
        if not lda_groups:
            for ga in project.group_addresses.all_addresses():
                if not ga.designation:
                    continue
                parsed = _parse_lda_designation_for_grouping(ga.designation.strip())
                if not parsed:
                    continue
                key, func = parsed
                _assign_lda_slot(lda_groups, key, func, ga.address)

        if lda_groups:
            # Räume für Namensgebung
            room_index = {r.number: r.name for r in project.all_rooms}

            # Physische DALI-Gruppennummer je GA ermitteln, falls die KOs des
            # Gateways sie im Namen tragen (z.B. "G2, Schalten,"). Ohne das
            # liefe die hier angezeigte Nummer rein nach Sortierreihenfolge
            # der Raum-Schlüssel, was von der echten DALI-Gruppennummer im
            # Gateway/ETS auseinanderlaufen kann (Chalet Franziska 2005:
            # "G2"/"G5" im DALI-Gateway vs. "Gruppe 1"/"Gruppe 5" in der App).
            # Bei einer GA, die (wie dort teils der Fall) an mehrere reale
            # Gruppen gebunden ist, bleibt die Zuordnung absichtlich
            # mehrdeutig -- last-write-wins beim Aufbau der Map, betroffene
            # Schlüssel fallen unten auf die naechste freie Nummer zurück.
            ga_to_real_nr: dict[str, int] = {}
            for co in device.communication_objects:
                nr = _ko_group_number(co.name)
                if nr is None:
                    continue
                for ga_addr in co.connected_gas:
                    ga_to_real_nr[ga_addr] = nr

            resolved: dict[str, int] = {}
            used_numbers: set[int] = set()
            for key, info in lda_groups.items():
                real_nr = (
                    ga_to_real_nr.get(info["switch"])
                    or ga_to_real_nr.get(info["dim"])
                    or ga_to_real_nr.get(info["value"])
                )
                if real_nr is None:
                    continue
                number = real_nr - 1  # "DALI-Gruppe 1" im Namen = Nummer 0
                if number < 0 or number in used_numbers:
                    continue
                resolved[key] = number
                used_numbers.add(number)

            next_seq = 0
            for key in sorted(lda_groups):
                if key in resolved:
                    continue
                while next_seq in used_numbers:
                    next_seq += 1
                resolved[key] = next_seq
                used_numbers.add(next_seq)

            for key, info in sorted(lda_groups.items()):
                base_key = info.get("_base_key", key)
                comment = ""
                if key != base_key:
                    # Disambiguierte Kollisions-Gruppe (siehe _assign_lda_slot):
                    # der (identische) Raumname beider Gruppen waere nicht
                    # unterscheidbar -- stattdessen den Klartext-Kommentar
                    # dieser spezifischen GA verwenden, falls vorhanden.
                    addr_for_comment = info["switch"] or info["dim"] or info["value"]
                    ga_obj = ga_by_addr.get(addr_for_comment)
                    if ga_obj:
                        comment = _designation_comment(ga_obj.designation)
                grp_name = _group_name_for_key(base_key, room_index, comment)
                grp = DaliGroup(
                    number=resolved[key],
                    name=grp_name,
                    ga_switch=info["switch"],
                    ga_dim=info["dim"],
                    ga_value=info["value"],
                )
                dali_gw.groups.append(grp)
            logger.info(
                f"DALI _derive_groups: {len(dali_gw.groups)} Gruppen aus LDA-GAs "
                f"für Gateway '{dali_gw.name}'."
            )
            return len(dali_gw.groups)

        # ── Strategie 2: KO-Namen parsen ─────────────────────────────────────
        ko_groups: dict[int, dict] = {}  # group_nr → {switch, dim, value}
        for co in device.communication_objects:
            m = _KO_GROUP_RE.search(co.name or "")
            if not m:
                continue
            grp_nr = int(m.group(1))
            func_raw = m.group(2).lower()
            if grp_nr not in ko_groups:
                ko_groups[grp_nr] = {"switch": "", "dim": "", "value": ""}
            # Erste verbundene GA verwenden
            ga_addr = co.connected_gas[0] if co.connected_gas else ""
            if not ga_addr:
                continue
            if any(k in func_raw for k in ("schalten", "switch", "on")):
                ko_groups[grp_nr]["switch"] = ga_addr
            elif any(k in func_raw for k in ("dimmen", "dim")):
                ko_groups[grp_nr]["dim"] = ga_addr
            elif any(k in func_raw for k in ("wert", "value", "helligkeit")):
                ko_groups[grp_nr]["value"] = ga_addr

        for grp_nr in sorted(ko_groups):
            info = ko_groups[grp_nr]
            dali_gw.groups.append(DaliGroup(
                number=grp_nr - 1,  # KNX-Gruppe 1 = DALI-Gruppe 0
                name=f"Gruppe {grp_nr}",
                ga_switch=info["switch"],
                ga_dim=info["dim"],
                ga_value=info["value"],
            ))

        if ko_groups:
            logger.info(
                f"DALI _derive_groups: {len(dali_gw.groups)} Gruppen aus KO-Namen "
                f"für Gateway '{dali_gw.name}'."
            )
        return len(dali_gw.groups)

    def _derive_evgs_from_import(
        self, dali_gw: DaliGateway, device, project
    ) -> int:
        """
        Leitet individuelle DALI-EVGs aus den KOs des importierten Gateway-Devices ab.

        Erkannte KO-Muster (herstellerübergreifend):
          "EVG 5 Schalten", "Betriebsgerät 3 Dimmen", "Einzelgerät 1 - Schalten",
          "Individual 2 On/Off", "Ballast 4 Dim", "Leuchte 7 Schalten", "Gear 1 Switch"

        Pro erkannter Nummer wird ein DaliDevice angelegt:
          - short_address: die Nummer direkt (0-basiert nach DALI-Standard)
          - name: Raumname + Element-Nr. aus GA-Bezeichnung (LDA_xxx_xx) oder
                  Fallback "EVG {addr}"
          - room_id: aus LDA-GA-Bezeichnung oder device.room_id

        Nur EVGs mit mind. einer verbundenen GA werden angelegt.
        EVGs mit identischer short_address werden dedupliziert.

        Gibt Anzahl angelegter EVGs zurück.
        """
        if not device.communication_objects:
            return 0

        # GA-Index für Bezeichnungs-Lookup
        ga_by_addr = {
            ga.address: ga
            for ga in project.group_addresses.all_addresses()
        }
        # Raum-Index: room_nr → room_id
        room_id_by_nr = {r.number: r.id for r in project.all_rooms}
        room_name_by_nr = {r.number: r.name for r in project.all_rooms}

        # EVG-Daten sammeln: short_addr → {switch, dim, value, room_id, name}
        evg_data: dict[int, dict] = {}

        for co in device.communication_objects:
            m = _KO_EVG_RE.search(co.name or "")
            if not m:
                continue
            # Keine GAs verbunden → EVG nicht anlegen (wahrscheinlich nicht programmiert)
            if not co.connected_gas:
                continue

            raw_nr = int(m.group(1))
            func_raw = m.group(2).lower()

            # DALI-Adressierung: Hersteller verwenden meist 1-basierte Labels
            # (EVG 1 = short_address 0). Wenn raw_nr == 0 → 0-basiert, direkt übernehmen.
            short_addr = raw_nr - 1 if raw_nr > 0 else 0

            if short_addr not in evg_data:
                evg_data[short_addr] = {
                    "switch": "", "dim": "", "value": "",
                    "room_id": device.room_id or "",
                    "name": "",
                }

            ga_addr = co.connected_gas[0]
            if any(k in func_raw for k in ("schalten", "switch", "on")):
                evg_data[short_addr]["switch"] = ga_addr
            elif any(k in func_raw for k in ("dimmen", "dim", "relativ")):
                evg_data[short_addr]["dim"] = ga_addr
            elif any(k in func_raw for k in ("wert", "value", "helligkeit")):
                evg_data[short_addr]["value"] = ga_addr

            # Raum aus GA-Bezeichnung ableiten (beide Namenskonventionen,
            # siehe _lda_primary_room_and_elem)
            if not evg_data[short_addr]["room_id"]:
                ga_obj = ga_by_addr.get(ga_addr)
                if ga_obj and ga_obj.designation:
                    room_nr, _elem_nr = _lda_primary_room_and_elem(ga_obj.designation.strip())
                    if room_nr:
                        evg_data[short_addr]["room_id"] = room_id_by_nr.get(room_nr, "")

            # Name aus Raumname + Element-Nr. ableiten
            if not evg_data[short_addr]["name"]:
                ga_obj = ga_by_addr.get(ga_addr)
                if ga_obj and ga_obj.designation:
                    room_nr, elem_nr = _lda_primary_room_and_elem(ga_obj.designation.strip())
                    if room_nr:
                        room_name = room_name_by_nr.get(room_nr, f"Raum {room_nr}")
                        evg_data[short_addr]["name"] = (
                            room_name if not elem_nr or elem_nr == "01"
                            else f"{room_name} {elem_nr}"
                        )

        # DaliDevice-Einträge anlegen
        existing_addrs = {d.short_address for d in dali_gw.devices}
        added = 0
        for short_addr in sorted(evg_data):
            if short_addr in existing_addrs:
                continue
            info = evg_data[short_addr]
            name = info["name"] or f"EVG {short_addr}"
            dali_gw.devices.append(DaliDevice(
                short_address=short_addr,
                name=name,
                room_id=info["room_id"],
            ))
            added += 1

        if added:
            logger.info(
                f"DALI _derive_evgs: {added} EVGs aus KO-Namen abgeleitet "
                f"für Gateway '{dali_gw.name}'."
            )
        return added
