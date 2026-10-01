"""
Mehrfach verknüpfte Sensorkanäle (FA-614, Doppelbelegung an einem sendenden KO).

Grundsatz (User, 2026-10-01): pro Sensorkanal darf nur EINE sendende GA
verknüpft sein. Rückmeldungen dürfen zusätzlich am Kanal hängen; eine weitere
sendende GA (Befehl einer anderen Bedienstelle) ist ein Fehler.

In der ETS sendet ein KO immer nur seine ERSTE Gruppenadresse; jede weitere
GA am selben KO hört es nur mit (der KO-Wert wird nachgeführt). Das ist
richtig für Rückmeldungen (Befehl 1/0/0 + Status 1/7/0), aber ein Fehler,
wenn die weitere GA der Befehl einer anderen Bedienstelle ist -- Praxisfall
Chalet 1.1.51 "Taste 2, links": 12/0/120 + 12/1/62 (Ein/Aus "S1 Wohnen").

Einordnung jeder weiteren GA (``classify_extra_ga``):

* GA-Variante B: Mittelgruppen 6 und 7 sind immer Rückmeldungen.
* Zusätzlich (auch bei Variante A, wo die Mittelgruppe nichts aussagt):
  wer sendet die GA? Ein Status-KO (Name "Status"/"Rückmeldung", oder KO
  überträgt nur, ohne Schreiben-Flag) -> Rückmeldung. Ein Befehls-KO eines
  anderen Tasters/Gateways (Schreiben + Übertragen) oder gar kein Sender
  -> "Mithören – prüfen".

Ergebnis je Fall: ``VERDICT_RUECKMELDUNG`` (in Ordnung),
``VERDICT_AUSSERHALB`` (Rückmeldung, aber bei Variante B ausserhalb MG 6/7 --
Hinweis) oder ``VERDICT_MITHOEREN`` (Warnung, in App und Berichten markiert).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VERDICT_RUECKMELDUNG = "rueckmeldung"
VERDICT_AUSSERHALB = "rueckmeldung_ausserhalb"
VERDICT_MITHOEREN = "mithoeren"

#: Rolle einer SensorFunktionGa/FunctionAssignment für eine mitgehörte GA
ROLE_MITHOEREN = "mithoeren"

VERDICT_LABELS = {
    VERDICT_RUECKMELDUNG: "Rückmeldung",
    VERDICT_AUSSERHALB: "Rückmeldung ausserhalb MG 6/7",
    VERDICT_MITHOEREN: "Mithören – prüfen",
}

_FEEDBACK_HINTS = ("led", "signal", "status", "rückmeldung", "rueckmeldung", "_rm", " rm ")
_TASTE_RE = re.compile(r"\btaste\s*\d+", re.IGNORECASE)


@dataclass
class KoSender:
    """Ein KO, das eine GA als erste (gesendete) Adresse führt."""
    physical_address: str
    co_number: int
    co_name: str
    is_status: bool

    @property
    def text(self) -> str:
        return f"{self.physical_address} KO {self.co_number} «{self.co_name}»"


@dataclass
class MultiGaFinding:
    """Eine weitere GA an einem sendenden Tasten-KO."""
    physical_address: str
    device_id: str
    room_id: str
    co_number: int
    co_name: str
    sent_ga: str                # die erste, tatsächlich gesendete GA
    extra_ga: str               # die zusätzlich verknüpfte GA
    extra_designation: str
    verdict: str
    reason: str
    senders: list[KoSender] = field(default_factory=list)

    @property
    def is_warning(self) -> bool:
        return self.verdict == VERDICT_MITHOEREN

    @property
    def is_error(self) -> bool:
        """Nachweislich zweite sendende GA: ein Befehls-KO eines anderen
        Geräts sendet sie (sonst nur Warnung -- Sender nicht gefunden)."""
        return self.is_warning and any(not s.is_status for s in self.senders)

    @property
    def level(self) -> str:
        """Stufe für Validierung und Berichte: error | warning | info | ok."""
        if self.is_error:
            return "error"
        if self.is_warning:
            return "warning"
        return "info" if self.verdict == VERDICT_AUSSERHALB else "ok"

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS.get(self.verdict, self.verdict)

    @property
    def ko_text(self) -> str:
        return f"{self.physical_address} KO {self.co_number} «{self.co_name}»"


def ga_address_of(designation: str) -> str:
    """'12/1/62  MM.OG… (Wohnen)' -> '12/1/62'."""
    head = (designation or "").strip().split(" ", 1)[0]
    return head if "/" in head else ""


def _transmits(flags: str) -> bool:
    # ETS-Report: "K-SÜA-", knxproj-Import: "KSUE-A" (U = Übertragen)
    return "Ü" in flags or "U" in flags


def _writes(flags: str) -> bool:
    return "S" in flags


def _has_feedback_hint(text: str) -> bool:
    low = f" {(text or '').lower()} "
    return any(h in low for h in _FEEDBACK_HINTS)


def is_sending_button_ko(co) -> bool:
    """Tasten-KO, das sendet (keine LED/Status-KOs). Ohne Flags (älterer
    Import) zählt jedes "Taste N"-KO."""
    name = co.name or ""
    if not _TASTE_RE.search(name) or _has_feedback_hint(name):
        return False
    return _transmits(co.flags) if co.flags else True


def _middle_group(addr: str) -> int | None:
    parts = addr.split("/")
    if len(parts) == 3 and parts[1].isdigit():
        return int(parts[1])
    return None


def _all_devices(project):
    for area in project.topology.areas:
        for line in area.lines:
            yield from line.devices


def build_sender_index(project) -> dict[str, list[KoSender]]:
    """GA -> KOs, die diese GA als erste Adresse führen und übertragen."""
    index: dict[str, list[KoSender]] = {}
    for device in _all_devices(project):
        for co in device.communication_objects:
            if not co.connected_gas:
                continue
            if co.flags and not _transmits(co.flags):
                continue
            label = f"{co.name} {co.object_function}"
            is_status = _has_feedback_hint(label) or (
                bool(co.flags) and not _writes(co.flags)
            )
            index.setdefault(co.connected_gas[0], []).append(KoSender(
                physical_address=device.physical_address,
                co_number=co.object_number,
                co_name=co.name or co.object_function,
                is_status=is_status,
            ))
    return index


def classify_extra_ga(addr: str, designation: str, variant: str,
                      senders: list[KoSender]) -> tuple[str, str]:
    """(Verdict, Begründung) für eine weitere GA an einem sendenden KO."""
    status_senders = [s for s in senders if s.is_status]
    command_senders = [s for s in senders if not s.is_status]
    status_by_sender = bool(status_senders) and not command_senders
    if variant == "B":
        mg = _middle_group(addr)
        if mg in (6, 7):
            return VERDICT_RUECKMELDUNG, f"Variante B: Mittelgruppe {mg} = Rückmeldung"
        if status_by_sender:
            return VERDICT_AUSSERHALB, (
                f"gesendet von Status-KO {status_senders[0].text}, "
                f"liegt aber in Mittelgruppe {mg} (Variante B: Rückmeldungen in MG 6/7)"
            )
    else:
        if status_by_sender:
            return VERDICT_RUECKMELDUNG, f"gesendet von Status-KO {status_senders[0].text}"
        if not senders and _has_feedback_hint(designation):
            return VERDICT_RUECKMELDUNG, "GA-Name weist auf Rückmeldung hin"
    if command_senders:
        reason = "Befehl von " + ", ".join(s.text for s in command_senders[:3])
    else:
        reason = "kein sendendes KO gefunden (nicht eindeutig)"
    return VERDICT_MITHOEREN, (
        f"{reason} – das KO hört nur mit, gesendet wird nur die erste GA"
    )


def find_multi_ga(project) -> list[MultiGaFinding]:
    """Alle weiteren GAs an sendenden Tasten-KOs, eingeordnet."""
    variant = getattr(project.config, "mg_variant", "A") or "A"
    designation = {
        ga.address: ga.designation for ga in project.group_addresses.all_addresses()
    }
    senders = build_sender_index(project)
    findings: list[MultiGaFinding] = []
    for device in _all_devices(project):
        for co in device.communication_objects:
            if len(co.connected_gas) < 2 or not is_sending_button_ko(co):
                continue
            for addr in co.connected_gas[1:]:
                own = [s for s in senders.get(addr, [])
                       if not (s.physical_address == device.physical_address
                               and s.co_number == co.object_number)]
                verdict, reason = classify_extra_ga(
                    addr, designation.get(addr, ""), variant, own)
                findings.append(MultiGaFinding(
                    physical_address=device.physical_address,
                    device_id=device.id,
                    room_id=device.room_id,
                    co_number=co.object_number,
                    co_name=co.name or co.object_function,
                    sent_ga=co.connected_gas[0],
                    extra_ga=addr,
                    extra_designation=designation.get(addr, ""),
                    verdict=verdict,
                    reason=reason,
                    senders=own,
                ))
    findings.sort(key=lambda f: (_pa_key(f.physical_address), f.co_number))
    return findings


def _pa_key(pa: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in pa.split("."))


def findings_by_ko(project) -> dict[tuple[str, str], MultiGaFinding]:
    """(physikalische Adresse, GA) -> Befund, für Anzeigen."""
    return {(f.physical_address, f.extra_ga): f for f in find_multi_ga(project)}


def apply_listen_roles(project) -> int:
    """Gleicht die Rolle importierter Zusatz-GAs (SensorFunktionGa) an die
    Einordnung an: "rueckmeldung" <-> "mithoeren". Andere Rollen (Befehl,
    Fremdsteuerung) bleiben unberührt. Gibt die Anzahl Änderungen zurück."""
    by_ko = findings_by_ko(project)
    changed = 0
    for room in project.all_rooms:
        for be in room.bedienelemente:
            pa = be.participant_number
            if not pa:
                continue
            for sf in be.funktionen:
                for extra in sf.extra_gas:
                    if extra.role not in ("rueckmeldung", ROLE_MITHOEREN):
                        continue
                    finding = by_ko.get((pa, ga_address_of(extra.ga_designation)))
                    if finding is None:
                        continue
                    role = ROLE_MITHOEREN if finding.is_warning else "rueckmeldung"
                    if extra.role != role:
                        extra.role = role
                        changed += 1
    return changed


def find_device(project, physical_address: str):
    return next((d for d in _all_devices(project)
                 if d.physical_address == physical_address), None)


def ko_for_ga(device, ga_addr: str, ko_name: str = ""):
    """KO eines Geräts, an dem die GA hängt; bei mehreren das mit passendem
    Namen (z.B. "Taste 2, links"), sonst das erste."""
    cos = [c for c in device.communication_objects if ga_addr in c.connected_gas]
    named = [c for c in cos if ko_name and (c.name or c.object_function) == ko_name]
    return (named or cos or [None])[0]


def unlink_ga(project,physical_address: str, co_number: int, ga_addr: str) -> bool:
    """Trennt eine GA von einem KO eines Geräts -- wie in der ETS. Entfernt
    sie aus ``connected_gas`` und aus der Tastenbelegung des zugehörigen
    Bedienelements (SensorFunktion bzw. deren Zusatz-GAs). Andere Geräte an
    derselben GA bleiben unverändert. Gibt False zurück, wenn nichts zu
    trennen war."""
    device = find_device(project, physical_address)
    if device is None:
        return False
    co = next((c for c in device.communication_objects
               if c.object_number == co_number), None)
    if co is None or ga_addr not in co.connected_gas:
        return False
    co.connected_gas.remove(ga_addr)
    still_on_device = any(ga_addr in c.connected_gas
                          for c in device.communication_objects)
    co_name = co.name or co.object_function
    for room in project.all_rooms:
        for be in room.bedienelemente:
            if be.participant_number != physical_address:
                continue
            for sf in be.funktionen:
                _unlink_from_sf(sf, ga_addr, co_name, still_on_device)
            be.is_auto = False
    return True


def _unlink_from_sf(sf, ga_addr: str, co_name: str, still_on_device: bool) -> None:
    extras = [e for e in sf.extra_gas if ga_address_of(e.ga_designation) == ga_addr]
    # Gleiche GA an mehreren KOs (z.B. Signal-LEDs): nur den Eintrag dieses KOs
    exact = [e for e in extras if e.description == co_name]
    if exact:
        sf.extra_gas.remove(exact[0])
        return
    if not still_on_device:
        for extra in extras:
            sf.extra_gas.remove(extra)
    if ga_address_of(sf.ga_designation) == ga_addr and not still_on_device:
        promote = next((e for e in sf.extra_gas if e.role == "befehl"), None)
        if promote is not None:
            sf.extra_gas.remove(promote)
            sf.ga_designation = promote.ga_designation
        else:
            sf.ga_designation = ""
