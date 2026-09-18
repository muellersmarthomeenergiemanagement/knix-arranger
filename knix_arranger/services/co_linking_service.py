"""
CO-Auto-Linking Service (FA-3000)

Generiert Vorschlaege fuer Kommunikationsobjekt-Gruppenadress-Verknuepfungen
basierend auf dem generierten Belegungsplan (Aktor-Rows) und schreibt
bestaetigte Verknuepfungen in Device.communication_objects[].connected_gas.

FA-3006: Ist am Geraet ein echtes (aus KNXPROD importiertes) Kommunikations-
objekt vorhanden, dessen Funktionsname exakt zur GA-Funktion passt, wird
dieses reale CO (mit seinem tatsaechlichen DPT/Flags) als Vorschlag
verwendet statt des generischen _FUNCTION_MAP-Eintrags. Das greift sowohl,
wenn die GAs bereits aus dem Produkt-Schema generiert wurden
(AddressGenerator._build_product_schema, ueber GewerkAssignment.linked_product),
als auch, wenn ein Produkt erst nachtraeglich am Geraet zugewiesen wurde
(MaterialListView._update_device_product) und dessen Funktionsnamen zufaellig
mit den generierten GA-Funktionsnamen uebereinstimmen.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("knix_arranger.co_linking")


@dataclass
class CoLinkingProposal:
    """Ein CO-GA-Verknuepfungsvorschlag fuer ein Aktor-Geraet."""
    device_id: str
    physical_address: str       # z.B. "1.1.3"
    co_name: str                # z.B. "Schalten", "Dimmen relativ"
    co_dpt: str                 # z.B. "DPST-1-1"
    co_flags: str               # z.B. "KSUA" (vereinfacht ohne Umlaute)
    direction: str              # "empfangen" | "senden"
    function_name: str          # z.B. "E/A", "DIM", "AUF/AB"
    gewerk_code: str            # z.B. "LD", "J"
    ga_address: str             # z.B. "2/0/0"
    ga_designation: str         # z.B. "LD_E01_01 E/A (Wohnzimmer)"
    ga_dpt: str = ""            # tatsaechlicher DPT der GA (aus Projekt)
    room_name: str = ""         # Ort/Raum des bedienten Stromkreises (leer bei Zentral-/Szenen-GAs)
    confidence: str = "sicher"  # "sicher" | "manuell pruefen"
    selected: bool = True
    already_linked: bool = False  # GA bereits in connected_gas vorhanden


# Mapping: GA-Funktion → Liste von (CO-Name, DPT, Flags, Richtung)
# Flags: K=Kommunikation, L=Lesen, S=Schreiben, U=Uebertragen, A=Aktualisieren
# Richtung: "empfangen" = Aktor empfaengt Befehl vom Bus (S-Flag)
#            "senden"    = Aktor sendet Rueckmeldung auf den Bus (U-Flag)
_FUNCTION_MAP: dict[str, list[tuple[str, str, str, str]]] = {
    # Licht / Schalten
    "E/A":                  [("Schalten",              "DPST-1-1",    "KSUA", "empfangen")],
    "RM":                   [("Status Schalten",        "DPST-1-1",    "KLU",  "senden")],
    # Dimmen
    "DIM":                  [("Dimmen relativ",         "DPST-3-7",    "KSU",  "empfangen")],
    "WERT":                 [("Helligkeitswert",        "DPST-5-1",    "KSUA", "empfangen")],
    "RM WERT":              [("Status Helligkeitswert", "DPST-5-1",    "KLU",  "senden")],
    # Jalousie / Rollladen
    "AUF/AB":               [("Auf/Ab",                "DPST-1-8",    "KSU",  "empfangen")],
    "STOPP":                [("Stopp/Lamellen",         "DPST-1-7",    "KSU",  "empfangen")],
    "POSITION HOEHE":       [("Position Hoehe",         "DPST-5-1",    "KSUA", "empfangen")],
    "POSITION LAMELLEN":    [("Position Lamellen",      "DPST-5-1",    "KSUA", "empfangen")],
    "STATUS POSITION HOEHE":    [("Status Pos. Hoehe",    "DPST-5-1",  "KLU",  "senden")],
    "STATUS POSITION LAMELLEN": [("Status Pos. Lamellen", "DPST-5-1",  "KLU",  "senden")],
    "BESCHATTUNG":          [("Beschattung",            "DPST-1-8",    "KSU",  "empfangen")],
    "SPERREN":              [("Sperren",                "DPST-1-1",    "KSUA", "empfangen")],
    # Heizung
    "STELLGROESSE":         [("Stellgroesse",           "DPST-5-1",    "KSUA", "empfangen")],
    "IST":                  [("Ist-Temperatur",         "DPST-9-1",    "KLU",  "senden")],
    "BASIS-SOLL":           [("Basis-Sollwert",         "DPST-9-1",    "KSUA", "empfangen")],
    "RM AKTUELLER SOLLWERT": [("Akt. Sollwert",         "DPST-9-1",    "KLU",  "senden")],
    "UMSCHALTEN BETRIEBSART": [("Betriebsart",          "DPST-20-102", "KSUA", "empfangen")],
    "STATUS BETRIEBSART":   [("Status Betriebsart",     "DPST-20-102", "KLU",  "senden")],
    "STOERUNG":             [("Stoerung",               "DPST-1-1",    "KLU",  "senden")],
    # Zentral-/Szenen-GAs (HG 0, siehe belegungsplan_service._collect_central_actor_rows).
    # Generischer Fallback ohne reales CO -- generate_proposals() setzt die
    # Konfidenz fuer diesen Fall bewusst auf "manuell pruefen", da nicht jeder
    # Aktor ein Szenen-Objekt besitzt (anders als bei Zentral-Licht/Jalousie).
    "SZENE":                [("Szene",                  "DPST-17-1",   "KSUA", "empfangen")],
    # Fremdsystem-Gateway "MM" (z.B. Multiroom-Audio wie Revox)
    "EIN/AUS":              [("Ein/Aus",                "DPST-1-1",    "KSUA", "empfangen")],
    "LAUTSTAERKE":          [("Lautstaerke",             "DPST-5-1",    "KSUA", "empfangen")],
    "QUELLE":               [("Quelle",                  "DPST-5-1",    "KSUA", "empfangen")],
    "PLAY/PAUSE":           [("Play/Pause",              "DPST-1-1",    "KSUA", "empfangen")],
    "STATUS":               [("Status",                  "DPST-1-1",    "KLU",  "senden")],
}


def _dpt_normalize(dpt: str) -> str:
    """Normalisiert DPT-Strings fuer Vergleich: 'DPST-1-1' und 'DPT-1-1' gelten als gleich."""
    return dpt.upper().replace("DPST-", "DPT-").strip()


def _dpt_compatible(co_dpt: str, ga_dpt: str) -> bool:
    """
    FA-3004: Prueft ob CO-DPT und GA-DPT kompatibel sind.

    Regeln:
    - Leerer Wert auf einer Seite → kompatibel (kein DPT bekannt)
    - Exakter Treffer nach Normalisierung → kompatibel
    - Gleicher Haupttyp (z.B. beide DPT-1-x) → kompatibel
    - Sonst → inkompatibel (Warnung)
    """
    if not co_dpt or not ga_dpt:
        return True
    co_n = _dpt_normalize(co_dpt)
    ga_n = _dpt_normalize(ga_dpt)
    if co_n == ga_n:
        return True
    # Gleicher Haupttyp: "DPT-5-1" und "DPT-5-100" → DPT-5 identisch
    co_parts = co_n.split("-")
    ga_parts = ga_n.split("-")
    if len(co_parts) >= 2 and len(ga_parts) >= 2 and co_parts[:2] == ga_parts[:2]:
        return True
    return False


class CoLinkingService:
    """
    Erstellt CO-GA-Verknuepfungsvorschlaege und schreibt sie ins Projekt.

    Arbeitsweise:
    1. generate_proposals(): Liest ActorRows aus BelegungsplanService,
       leitet daraus CO-Vorschlaege (Name, DPT, Flags) ab.
    2. apply_proposals(): Schreibt ausgewaehlte Vorschlaege als
       CommunicationObject-Eintraege mit connected_gas in die Topologie.
    """

    def generate_proposals(self, project) -> list[CoLinkingProposal]:
        """
        FA-3001/3002: Generiert CO-GA-Verknuepfungsvorschlaege.

        Nutzt BelegungsplanService.actor_rows als Datenquelle,
        da dieser bereits die GA-Gereat-Zuordnung nach Raum und
        Gewerk-Code berechnet hat.
        """
        from .belegungsplan_service import BelegungsplanService
        try:
            belegungsplan = BelegungsplanService().generate(project)
        except Exception as exc:
            logger.warning(f"BelegungsplanService Fehler: {exc}")
            return []

        device_map = self._build_device_map(project)
        # Bestehende Verknuepfungen aufbauen: phys_addr+function → [ga_address]
        existing = self._build_existing_links(device_map)

        proposals: list[CoLinkingProposal] = []
        for row in belegungsplan.actor_rows:
            if not row.function_name or not row.ga_address:
                continue
            device = device_map.get(row.physical_address)
            device_id = device.id if device else ""
            already = row.ga_address in existing.get(
                (row.physical_address, row.function_name), set()
            )

            real_co = self._match_real_co(device, row.function_name, row.co_function)
            if real_co is not None:
                co_specs = [(
                    real_co.name or row.function_name,
                    real_co.data_type,
                    real_co.flags or "K",
                    self._direction_from_flags(real_co.flags),
                )]
            else:
                co_specs = _FUNCTION_MAP.get(row.function_name)
                if not co_specs:
                    continue
            for co_name, co_dpt, co_flags, direction in co_specs:
                # FA-3004: DPT-Kompatibilitaetspruefung
                ga_dpt = row.dpt or ""
                if ga_dpt and not _dpt_compatible(co_dpt, ga_dpt):
                    confidence = "manuell pruefen"
                elif row.function_name == "SZENE" and real_co is None:
                    # Kein reales Szenen-CO gefunden -- anders als bei Zentral-
                    # Licht/Jalousie kann ohne Produktdaten nicht sicher davon
                    # ausgegangen werden, dass dieser Aktor ueberhaupt ein
                    # Szenen-Objekt besitzt (nicht jeder Aktortyp unterstuetzt
                    # Szenen). Der generische Vorschlag bleibt sichtbar, aber
                    # als pruefungsbeduerftig markiert.
                    confidence = "manuell pruefen"
                else:
                    confidence = "sicher"
                proposals.append(CoLinkingProposal(
                    device_id=device_id,
                    physical_address=row.physical_address,
                    co_name=co_name,
                    co_dpt=co_dpt,
                    co_flags=co_flags,
                    direction=direction,
                    function_name=row.function_name,
                    gewerk_code=row.gewerk_code,
                    ga_address=row.ga_address,
                    ga_designation=row.ga_designation,
                    ga_dpt=ga_dpt,
                    room_name=row.room_name,
                    confidence=confidence,
                    selected=not already,
                    already_linked=already,
                ))

        proposals = self._dedupe_proposals(proposals)

        logger.info(
            f"CO-Auto-Linking: {len(proposals)} Vorschlaege generiert "
            f"({sum(1 for p in proposals if p.already_linked)} bereits verknuepft)"
        )
        return proposals

    def _dedupe_proposals(
        self, proposals: list[CoLinkingProposal]
    ) -> list[CoLinkingProposal]:
        """
        Entfernt echte Doppeleintraege: identische (Geraeteadresse, GA-Adresse,
        CO-Name, Richtung)-Kombination mehrfach vorgeschlagen.

        Kann entstehen, wenn dasselbe Geraet (gleiche physikalische Adresse)
        aus mehreren Quellen dieselbe GA fuer dieselbe Funktion erhaelt, z.B.
        bei doppelten Geraete-Eintraegen in der Topologie (Import-Merge) oder
        bei sich ueberschneidenden Gewerk-/Zentral-GA-Zuordnungen fuer dieselbe
        Funktion. Eine identische Verknuepfung zweimal vorzuschlagen bringt
        keinen Mehrwert (apply_proposals wuerde ohnehin nur einmal schreiben)
        und verwirrt in der Tabelle -- daher hier bereits bereinigt, mit
        Logging, damit die Quelle bei Bedarf nachvollzogen werden kann.
        """
        seen: dict[tuple, CoLinkingProposal] = {}
        result: list[CoLinkingProposal] = []
        dropped: list[tuple] = []
        for p in proposals:
            key = (p.physical_address, p.ga_address, p.co_name, p.direction)
            if key in seen:
                dropped.append(key)
                continue
            seen[key] = p
            result.append(p)
        if dropped:
            logger.warning(
                f"CO-Auto-Linking: {len(dropped)} doppelte Vorschlags-Zeile(n) "
                f"entfernt (identische Geraeteadresse+GA+CO-Funktion): {dropped}"
            )
        return result

    def apply_proposals(self, project, proposals: list[CoLinkingProposal]) -> int:
        """
        FA-3003/3005: Schreibt ausgewaehlte Vorschlaege in die Topologie.

        Gibt die Anzahl neu angelegter/aktualisierter CO-Links zurueck.
        """
        from ..models.topology import CommunicationObject
        device_map = self._build_device_map(project)
        count = 0
        for p in proposals:
            if not p.selected or not p.ga_address or p.already_linked:
                continue
            device = device_map.get(p.physical_address)
            if device is None:
                logger.debug(f"Kein Geraet fuer Adresse {p.physical_address}")
                continue
            co = self._find_or_create_co(device, p, CommunicationObject)
            if p.ga_address not in co.connected_gas:
                co.connected_gas.append(p.ga_address)
                count += 1

        logger.info(f"CO-Auto-Linking: {count} neue GA-Verknuepfungen geschrieben")
        return count

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    def _build_device_map(self, project) -> dict[str, object]:
        """Gibt ein Dict physikalische_Adresse → Device zurueck."""
        result: dict[str, object] = {}
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.physical_address:
                        result[device.physical_address] = device
        return result

    def _build_existing_links(
        self, device_map: dict
    ) -> dict[tuple[str, str], set[str]]:
        """
        Gibt bestehende CO-GA-Verknuepfungen zurueck als
        {(phys_addr, function_name): {ga_address, ...}}.

        Der Funktionsname eines COs steckt in object_function: bei
        generisch angelegten COs ist das der _FUNCTION_MAP-Funktionsname
        (z.B. "E/A"), bei aus KNXPROD importierten COs der reale
        Funktionstext des Produkts -- beides ist direkt mit
        row.function_name vergleichbar, ohne Umweg ueber den CO-Namen.
        """
        result: dict[tuple[str, str], set[str]] = {}
        for phys_addr, device in device_map.items():
            for co in device.communication_objects:
                func = co.object_function or co.name
                if func:
                    key = (phys_addr, func)
                    result.setdefault(key, set()).update(co.connected_gas)
        return result

    def _match_real_co(self, device, function_name: str, co_function: str = ""):
        """
        FA-3006: Sucht ein reales (aus KNXPROD importiertes) Kommunikations-
        objekt des Geraets, dessen Funktionsname/Name exakt (ohne Gross-/
        Kleinschreibung) zur GA-Funktion passt.

        Nur ein exakter Treffer zaehlt -- eine unscharfe Zuordnung wuerde
        bei generischen Vorlagen-Funktionsnamen (z.B. "EIN/AUS") faelschlich
        auf voellig andere Produktfunktionen matchen.

        `co_function` (ActorRow.co_function, siehe belegungsplan_service):
        bei ETS6-CO-Fallback-Zeilen kann ein Geraet MEHRERE COs mit demselben
        `co.name` (physischer Kanal, z.B. "Ausgang A") aber unterschiedlicher
        `co.object_function` (Schalten/8-Bit-Szene/Telegr. Status ...) haben.
        Ohne dieses Zusatzkriterium liefert die Namenssuche unten den ERSTEN
        Treffer -- unabhaengig davon, ob das ueberhaupt das CO ist, aus dem
        diese Zeile stammt (Chalet Franziska 2005: 1.1.10, GA 0/4/1 -- die
        Zeile stammt vom "8-Bit-Szene"-CO, aber die reine Namenssuche traf
        zuerst das gleichnamige "Schalten"-CO, DPT "1 bit" statt "1 byte" --
        daher der scheinbare CO-DPT/GA-DPT-Widerspruch in der Tabelle). Ist
        `co_function` bekannt, muss sie zusaetzlich zum Namen exakt passen.

        Ausnahme "SZENE": Hersteller benennen das Szenen-Objekt selten
        woertlich "Szene", meist z.B. "8-Bit-Szene" oder "Szenensteuerung"
        (siehe gewerk_channel_matching._FUNCTION_KEYWORDS, dort fuer die
        Kanal-Zuordnung bereits genutzt). Ohne diesen Zusatz wuerde so gut
        wie nie ein reales Szenen-CO gefunden, und generate_proposals()
        koennte nie zwischen "Geraet hat nachweislich ein Szenen-Objekt"
        (Konfidenz "sicher") und "reine Vermutung" (Konfidenz "manuell
        pruefen") unterscheiden. Bewusst NUR fuer "SZENE" aktiviert, um das
        oben beschriebene Fehltreffer-Risiko fuer alle anderen, generischeren
        Funktionsnamen nicht wieder einzufuehren.
        """
        if device is None:
            return None
        target = function_name.strip().lower()
        if not target:
            return None
        role = co_function.strip().lower()
        if role:
            for co in device.communication_objects:
                if co.name.strip().lower() == target and co.object_function.strip().lower() == role:
                    return co
        for co in device.communication_objects:
            if co.object_function.strip().lower() == target:
                return co
            if co.name.strip().lower() == target:
                return co
        if target == "szene":
            from .gewerk_channel_matching import _FUNCTION_KEYWORDS
            keywords = _FUNCTION_KEYWORDS.get("SZENE", ())
            for co in device.communication_objects:
                text = f"{co.object_function} {co.name}".strip().lower()
                if text and any(kw in text for kw in keywords):
                    return co
        return None

    def _direction_from_flags(self, flags: str) -> str:
        """Leitet 'empfangen'/'senden' aus den ETS-Flags eines realen COs ab
        (Konvention aus knxprod_catalog_service: K,L,Ü=Schreiben,S=Senden,U)."""
        if "Ü" in flags:
            return "empfangen"
        if "S" in flags:
            return "senden"
        return "empfangen"

    def _find_or_create_co(
        self, device, proposal: CoLinkingProposal, co_class
    ):
        """Findet ein bestehendes CO oder legt ein neues an."""
        for co in device.communication_objects:
            if co.name == proposal.co_name and co.data_type == proposal.co_dpt:
                return co
        co = co_class(
            object_number=len(device.communication_objects),
            name=proposal.co_name,
            object_function=proposal.function_name,
            flags=proposal.co_flags,
            data_type=proposal.co_dpt,
        )
        device.communication_objects.append(co)
        return co
