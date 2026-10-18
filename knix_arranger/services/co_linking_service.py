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
    # Nummer des realen KOs (-1 = generischer KO): gleichnamige KOs eines
    # Kanals (ABB RM/S4.1: alle "Ausgang A (6 A)") unterscheidet nur sie
    co_number: int = -1


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
    # Der Aktor (Regler im Aktor) empfängt die Ist-Temperatur, z.B. vom Taster
    "IST":                  [("Ist-Temperatur",         "DPST-9-1",    "KSA",  "empfangen")],
    "BASIS-SOLL":           [("Basis-Sollwert",         "DPST-9-1",    "KSUA", "empfangen")],
    "RM AKTUELLER SOLLWERT": [("Akt. Sollwert",         "DPST-9-1",    "KLU",  "senden")],
    "UMSCHALTEN BETRIEBSART": [("Betriebsart",          "DPST-20-102", "KSUA", "empfangen")],
    "STATUS BETRIEBSART":   [("Status Betriebsart",     "DPST-20-102", "KLU",  "senden")],
    "STOERUNG":             [("Stoerung",               "DPST-1-1",    "KLU",  "senden")],
    # Zentral-/Szenen-GAs (HG 0, siehe belegungsplan_service._collect_central_actor_rows).
    # Generischer Fallback ohne reales CO -- generate_proposals() setzt die
    # Konfidenz fuer diesen Fall bewusst auf "manuell pruefen", da nicht jeder
    # Aktor ein Szenen-Objekt besitzt (anders als bei Zentral-Licht/Jalousie).
    "SZENE":                [("Szene",                  "DPST-18-1",   "KSUA", "empfangen")],
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
    - Szenennummer (17.x) und Szenensteuerung (18.x) → kompatibel; 18.001
      enthält die Szenennummer, Abrufen funktioniert mit beiden
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
    scene_main = {"17", "18"}
    if len(co_parts) >= 2 and len(ga_parts) >= 2 and {co_parts[1], ga_parts[1]} <= scene_main:
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

            # Gewählter KO aus «Kanäle und KOs zuordnen…» (actor_channels)
            chosen = self._chosen_co(device, row)
            if chosen is False:
                continue                 # bewusst nicht verknüpfen
            real_co = chosen or self._match_real_co(device, row.function_name, row.co_function)
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
                # Bereits verknüpft: am selben KO, das apply_proposals
                # beschreiben würde (KO-Nummer bzw. Name+DPT) -- der
                # Funktionsname allein trifft Produkt-KOs nicht («GO0002»),
                # sonst stünden übernommene Verknüpfungen immer als neu da
                linked = already or self._ga_on_co(
                    device, real_co, co_name, co_dpt, row.ga_address)
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
                    selected=not linked,
                    already_linked=linked,
                    co_number=real_co.object_number if real_co is not None else -1,
                ))

        proposals += self._sensor_proposals(project, device_map)
        proposals = self._dedupe_proposals(proposals)

        logger.info(
            f"CO-Auto-Linking: {len(proposals)} Vorschlaege generiert "
            f"({sum(1 for p in proposals if p.already_linked)} bereits verknuepft)"
        )
        return proposals

    def _sensor_proposals(self, project, device_map: dict) -> list[CoLinkingProposal]:
        """Vorschläge aus der KO-Auswahl der Taster/Sensoren (sensor_channels):
        nur ausdrücklich gewählte KOs, ohne Auswahl schlägt die Verknüpfung
        für Sensoren nichts vor."""
        from .sensor_channels import sensor_co_map, sensor_links, sensor_plan
        sensors = [d for d in device_map.values()
                   if d.device_type == "sensor" and sensor_co_map(d)]
        if not sensors:
            return []
        plan = sensor_plan(project)
        proposals = []
        for device in sensors:
            selection = sensor_co_map(device)
            by_number = {}
            for co in device.communication_objects:
                by_number.setdefault(co.object_number, co)
            for link in sensor_links(project, device, plan):
                co = by_number.get(selection.get(link.key, -1))
                if co is None:
                    continue
                already = link.ga_address in co.connected_gas
                proposals.append(CoLinkingProposal(
                    device_id=device.id,
                    physical_address=device.physical_address,
                    co_name=co.name or co.object_function,
                    co_dpt=co.data_type,
                    co_flags=co.flags or "K",
                    direction="empfangen" if link.feedback else "senden",
                    function_name=link.ga_function,
                    gewerk_code="",
                    ga_address=link.ga_address,
                    ga_designation=link.ga_designation,
                    ga_dpt=link.dpt,
                    room_name="",
                    confidence=("sicher" if _dpt_compatible(co.data_type, link.dpt)
                                else "manuell pruefen"),
                    selected=not already,
                    already_linked=already,
                    co_number=co.object_number,
                ))
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
            key = (p.physical_address, p.ga_address, p.co_name, p.direction, p.co_number)
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

    @staticmethod
    def _chosen_co(device, row):
        """KO laut Device.co_map für diesen Stromkreis und diese Funktion:
        das CommunicationObject, False für «nicht verknüpfen», None ohne
        Vorgabe (dann die bisherige Suche)."""
        if device is None or not device.co_map or not row.room_id:
            return None
        from .actor_channels import circuit_key
        selection = device.co_map.get(
            circuit_key(row.room_id, row.gewerk_code, row.element_number))
        if not selection or row.function_name not in selection:
            return None
        number = selection[row.function_name]
        if number < 0:
            return False
        from .ko_links import co_by_number
        return co_by_number(device.communication_objects, number)

    def _direction_from_flags(self, flags: str) -> str:
        """Leitet 'empfangen'/'senden' aus den Flags eines realen COs ab
        (ETS oder Produktdaten, siehe ko_links.parse_flags)."""
        from .ko_links import TRANSMIT, WRITE, parse_flags
        parsed = parse_flags(flags)
        if WRITE in parsed:
            return "empfangen"
        if TRANSMIT in parsed:
            return "senden"
        return "empfangen"

    @staticmethod
    def _ga_on_co(device, real_co, co_name: str, co_dpt: str, ga_address: str) -> bool:
        """Liegt die GA schon an dem KO, das _find_or_create_co wählen würde?"""
        if device is None:
            return False
        if real_co is not None:
            # Gleiche Nummer kann mehrfach vorkommen (Varianten eines KOs in
            # den Produktdaten); apply_proposals schreibt in die erste
            return any(ga_address in co.connected_gas for co in device.communication_objects
                       if co.object_number == real_co.object_number)
        return any(ga_address in co.connected_gas for co in device.communication_objects
                   if co.name == co_name and co.data_type == co_dpt)

    def _find_or_create_co(
        self, device, proposal: CoLinkingProposal, co_class
    ):
        """Findet ein bestehendes CO oder legt ein neues an."""
        if proposal.co_number >= 0:
            from .ko_links import co_by_number
            co = co_by_number(device.communication_objects, proposal.co_number)
            if co is not None:
                return co
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
