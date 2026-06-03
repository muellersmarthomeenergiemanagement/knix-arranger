"""
CO-Auto-Linking Service (FA-3000)

Generiert Vorschlaege fuer Kommunikationsobjekt-Gruppenadress-Verknuepfungen
basierend auf dem generierten Belegungsplan (Aktor-Rows) und schreibt
bestaetigte Verknuepfungen in Device.communication_objects[].connected_gas.
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
            co_specs = _FUNCTION_MAP.get(row.function_name)
            if not co_specs:
                continue
            device = device_map.get(row.physical_address)
            device_id = device.id if device else ""
            already = row.ga_address in existing.get(
                (row.physical_address, row.function_name), set()
            )
            for co_name, co_dpt, co_flags, direction in co_specs:
                # FA-3004: DPT-Kompatibilitaetspruefung
                ga_dpt = row.dpt or ""
                if ga_dpt and not _dpt_compatible(co_dpt, ga_dpt):
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
                    confidence=confidence,
                    selected=not already,
                    already_linked=already,
                ))

        logger.info(
            f"CO-Auto-Linking: {len(proposals)} Vorschlaege generiert "
            f"({sum(1 for p in proposals if p.already_linked)} bereits verknuepft)"
        )
        return proposals

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

        Benoetigt eine Heuristik: CO-Name → function_name Mapping.
        """
        # Umkehrtabelle: co_name → function_name
        _CO_TO_FUNC: dict[str, str] = {}
        for func, specs in _FUNCTION_MAP.items():
            for co_name, *_ in specs:
                _CO_TO_FUNC[co_name] = func

        result: dict[tuple[str, str], set[str]] = {}
        for phys_addr, device in device_map.items():
            for co in device.communication_objects:
                func = _CO_TO_FUNC.get(co.name, "")
                if func:
                    key = (phys_addr, func)
                    result.setdefault(key, set()).update(co.connected_gas)
        return result

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
