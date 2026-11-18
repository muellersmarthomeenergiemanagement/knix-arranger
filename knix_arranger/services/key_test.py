"""
Tastentest (FA-3106): der Tester drückt im Raum die Tasten der Bedienelemente,
KNiX hört am Bus mit und prüft je Prüfpunkt der Checkliste (Taste + GA):

- kommt das Telegramm vom richtigen Taster (physikalische Adresse) auf der
  geplanten GA? Dann «gesendet»;
- meldet ein Aktorkanal, der auf diese GA hört, danach seinen Status? Dann OK,
  sonst entscheidet der Tester vor Ort (OK/Mangel);
- Telegramme eines Tasters des Raums auf einer nicht geplanten GA und
  geplante GAs von einem fremden Gerät sind Befunde.

Die Reihenfolge ist frei; ein Telegramm hakt alle Prüfpunkte mit derselben
Adresse und GA ab. Gesendet wird nichts -- der Test läuft auch über den
USB-Busmonitor. Ohne Qt; Dialog in ui/dialogs/key_test_dialog.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..models.documentation import ITEM_KIND_DEVICE, RESULT_DEFECT, RESULT_OK, RESULT_OPEN

# so lange wartet der Test nach dem Tastendruck auf den Status des Aktors,
# bevor er den Tester fragt
REACTION_TIMEOUT = 3.0
# ein späterer Status zählt noch (Storen melden die Position am Ende der Fahrt)
LATE_REACTION = 120.0

PRESS_SHORT, PRESS_LONG, PRESS_DOUBLE = "kurz", "lang", "doppelt"

# Geräte-Grundprüfungen, die ein Telegramm des Tasters auf einer geplanten GA
# belegt (Montage bleibt Sichtprüfung)
PROVEN_DEVICE_CHECKS = ("Physik. Adresse", "Applikation", "Kommunikation")

STATE_OPEN, STATE_SENT, STATE_CONFIRM, STATE_OK, STATE_DEFECT = (
    "", "sent", "confirm", "ok", "defect")


@dataclass
class KeyCheck:
    """Ein Prüfpunkt: Taste eines Bedienelements und eine Befehls-GA."""
    room_id: str
    be_number: str              # physikalische Adresse des Tasters
    be_type: str                # "Tastereinheit"
    be_title: str               # "1.1.40 · EDIZIOdue colore"
    channel: str                # "Taste 2, links (langer Tastendruck)"
    address: str                # "3/4/29"
    # Text der Zuordnung wie im Prüfpunkt: "3/4/29  Raum2_Licht Zentral"
    # (importiert) bzw. "L_EG_01_01 E/A (Wohnen)" (geplant)
    function_ga: str = ""
    designation: str = ""       # "Raum2_Licht Zentral"
    label: str = ""             # was die Taste tut: "Szene High"
    press: str = PRESS_SHORT
    # Status-GAs der Aktorkanäle, die auf die GA hören (leer: vor Ort prüfen)
    reactions: set[str] = field(default_factory=set)
    actuators: list[str] = field(default_factory=list)   # "1.1.5 Motor 3"

    @property
    def key(self) -> str:
        """Taste ohne Bedienart: "Taste 2, links"."""
        text = re.sub(r"\s*\(\s*langer?\s+Tastendruck\s*\)", "", self.channel, flags=re.I)
        return re.sub(r",\s*Doppelklick", "", text, flags=re.I).strip()

    def instruction(self) -> str:
        """"Taste 2, links lang drücken"."""
        how = {PRESS_LONG: "lang drücken", PRESS_DOUBLE: "doppelt drücken"}.get(
            self.press, "kurz drücken")
        return f"{self.key} {how}"

    def function(self) -> str:
        """Was reagieren muss: "Szene High · Raum2_Szene High"."""
        parts = [self.label, self.designation]
        return " · ".join(p for i, p in enumerate(parts) if p and p not in parts[:i])


def _press(channel: str, co_function: str, designation: str) -> str:
    text = f"{channel} {co_function} {designation}".lower()
    if "doppel" in text:
        return PRESS_DOUBLE
    if "lang" in channel.lower():
        return PRESS_LONG
    if re.search(r"schritt|stop|step|lamelle", text):
        return PRESS_SHORT
    if re.search(r"auf/ab|auf / ab|\bmove\b|_move|bewegen|fahren|dimmen|\bdim", text):
        return PRESS_LONG
    return PRESS_SHORT


def _status_listeners(project) -> dict[str, tuple[set[str], list[str]]]:
    """Befehls-GA -> (Status-GAs der Aktorkanäle, die auf sie hören,
    ["1.1.5 Motor 3", ...])."""
    from .actor_channels import _is_feedback, device_channels
    result: dict[str, tuple[set[str], list[str]]] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type not in ("actor", "gateway"):
                    continue
                channels = [(ch.label, ch.com_objects) for ch in device_channels(device)
                            if ch.com_objects]
                if not channels:
                    channels = [("", device.communication_objects)]
                for label, cos in channels:
                    status = {co.connected_gas[0] for co in cos
                              if co.connected_gas and _is_feedback(co)}
                    text = " ".join(p for p in (device.physical_address, label) if p)
                    for co in cos:
                        if _is_feedback(co):
                            continue
                        for address in co.connected_gas or []:
                            entry = result.setdefault(address, (set(), []))
                            entry[0].update(status - {address})
                            if text not in entry[1]:
                                entry[1].append(text)
    return result


_STATUS_FUNCTIONS = ("RM", "RM WERT", "STATUS POSITION HOEHE", "STATUS POSITION LAMELLEN")


def _element_status(project) -> dict[str, set[str]]:
    """Befehls-GA eines Elements -> seine Rückmelde-GAs (Gliederung: RM,
    RM WERT, STATUS POSITION ...), für Projekte ohne verknüpfte Aktor-KOs."""
    from .ets_function_plan import _element_gas
    result: dict[str, set[str]] = {}
    try:
        elements = _element_gas(project)
    except Exception:
        return result
    for functions in elements.values():
        status = {ga.address for f, ga in functions.items() if f in _STATUS_FUNCTIONS}
        if not status:
            continue
        for f, ga in functions.items():
            if f not in _STATUS_FUNCTIONS:
                result.setdefault(ga.address, set()).update(status)
    return result


def plan_key_checks(project, room_id: str) -> list[KeyCheck]:
    """Prüfpunkte der bedienbaren Elemente des Raums (Tasten mit
    Befehls-GA), in der Reihenfolge der Checkliste."""
    from .bedienelement_layout import parse_button
    from .sensor_service import project_for_export
    from .user_manual import UserManualBuilder

    export = project_for_export(project)
    room = next((r for r in export.all_rooms if r.id == room_id), None)
    if room is None:
        return []
    builder = UserManualBuilder(export, snapshot=False)
    listeners = _status_listeners(export)
    element_status = _element_status(export)
    imported = export.topology.is_imported
    checks: list[KeyCheck] = []
    for be in room.bedienelemente:
        if not be.is_shown(imported) or not be.is_operable or not be.participant_number:
            continue
        device = builder.device_by_addr.get(be.participant_number)
        co_function = {}
        if device is not None:
            for co in device.communication_objects:
                for address in co.connected_gas or []:
                    co_function.setdefault(address, co.object_function or "")
        try:
            labels = {(kl.key.number, kl.key.side, kl.key.variant): kl.label
                      for kl in builder.key_lines(be, room.name)}
        except Exception:
            labels = {}
        product = (device.product_name or device.product) if device else be.product_name
        title = " · ".join(p for p in (be.participant_number, product) if p)
        seen: set[tuple] = set()
        for fa in be.function_assignments:
            if fa.role != "befehl" or not fa.function_ga:
                continue
            # geplant steht der Name im Prüfpunkt ("L_EG_01_01 E/A (Wohnen)")
            ga = builder._resolve(fa.function_ga)
            if ga is None or not ga.address:
                continue
            address = ga.address
            if (fa.button_channel, address) in seen:
                continue
            seen.add((fa.button_channel, address))
            parsed = parse_button(fa.button_channel)
            if parsed is not None and parsed[1]:
                continue                      # LED
            designation = " ".join((ga.designation or "").split())
            # Beschriftung der Taste nur für den kurzen Druck (lang/doppelt
            # bedienen oft etwas anderes: «Licht Zentral»)
            label = labels.get((parsed[0].number, parsed[0].side, parsed[0].variant), "") \
                if parsed else ""
            reactions, actuators = listeners.get(address, (set(), []))
            if not reactions:
                # noch keine Aktor-KOs verknüpft (geplant): Status des Elements
                reactions = element_status.get(address, set())
            checks.append(KeyCheck(
                room_id=room.id, be_number=be.participant_number,
                be_type=be.element_type, be_title=title, channel=fa.button_channel,
                address=address, function_ga=fa.function_ga,
                designation=designation, label=label,
                press=_press(fa.button_channel, co_function.get(address, ""), designation),
                reactions=set(reactions), actuators=list(actuators)))
    return checks


@dataclass
class Event:
    """Was ein Telegramm bewirkt hat (für die Anzeige)."""
    rows: list[int] = field(default_factory=list)   # geänderte Prüfpunkte
    finding: str = ""                               # Befund


class KeySession:
    """Auswertung der mitgehörten Telegramme für die Prüfpunkte eines Raums."""

    def __init__(self, checks: list[KeyCheck], confirm: bool = False,
                 room_addresses: dict[str, set[str]] | None = None):
        self.checks = checks
        self.confirm = confirm        # Reaktion immer vor Ort bestätigen
        self.state = [STATE_OPEN] * len(checks)
        self.note = [""] * len(checks)
        self.value = [""] * len(checks)
        self._sent_at = [0.0] * len(checks)
        # nach der Wartezeit gefragt, ein später Status zählt noch
        self._late = [False] * len(checks)
        self._by_source: dict[str, set[str]] = {}
        for c in checks:
            self._by_source.setdefault(c.be_number, set()).add(c.address)
        # alle GAs der Taster des Raums (auch LED, Temperatur ...): nur
        # Telegramme auf anderen GAs sind ein Befund
        self._known = room_addresses or {}
        self._expected = {c.address for c in checks}
        self.findings: list[str] = []

    def next_open(self) -> int | None:
        return next((i for i, s in enumerate(self.state) if s == STATE_OPEN), None)

    def on_telegram(self, telegram, now: float, value: str = "") -> Event:
        event = Event()
        if telegram.sent or telegram.service != "Write":
            return event
        source, destination = telegram.source, telegram.destination
        # Status eines Aktors nach dem Tastendruck
        for i, check in enumerate(self.checks):
            waiting = self.state[i] == STATE_SENT or (
                self.state[i] == STATE_CONFIRM and self._late[i])
            if (waiting and destination in check.reactions
                    and source != check.be_number
                    and now - self._sent_at[i] <= LATE_REACTION):
                self._late[i] = False
                if self.confirm:
                    self.state[i] = STATE_CONFIRM
                    self.note[i] = (f"Tastentest: {check.address} von {check.be_number}, "
                                    f"Status {destination} = {value or 'Meldung'}")
                else:
                    self._done(i, True, f"Tastentest: {check.address} von {check.be_number}, "
                                        f"Status {destination} = {value or 'Meldung'}")
                event.rows.append(i)
        if source in self._by_source:
            rows = [i for i, c in enumerate(self.checks)
                    if c.be_number == source and c.address == destination]
            for i in rows:
                if self.state[i] in (STATE_OK, STATE_DEFECT):
                    continue                  # schon geprüft; nochmals drücken ändert nichts
                self.value[i] = value
                self._sent_at[i] = now
                if self.checks[i].reactions:
                    self.state[i] = STATE_SENT
                else:
                    self.state[i] = STATE_CONFIRM
                    self.note[i] = (f"Tastentest: {destination} von {source}, "
                                    "Reaktion vor Ort")
                event.rows.append(i)
            if not rows and destination not in self._known.get(source, set()) \
                    and destination not in self._by_source[source]:
                event.finding = (f"{source} sendet auf {destination}"
                                 f"{' = ' + value if value else ''} – nicht geplant")
        elif destination in self._expected:
            owners = sorted({c.be_number for c in self.checks if c.address == destination})
            event.finding = (f"{destination} kommt von {source}, geplant von "
                             f"{', '.join(owners)} – anderes Gerät")
        if event.finding:
            self.findings.append(event.finding)
        return event

    def tick(self, now: float) -> list[int]:
        """Kein Status innerhalb der Wartezeit: der Tester entscheidet."""
        changed = []
        for i, state in enumerate(self.state):
            if state == STATE_SENT and now - self._sent_at[i] > REACTION_TIMEOUT:
                check = self.checks[i]
                self.state[i] = STATE_CONFIRM
                self._late[i] = not self.confirm
                self.note[i] = (f"Tastentest: {check.address} von {check.be_number}, "
                                "kein Status vom Aktor")
                changed.append(i)
        return changed

    def decide(self, i: int, ok: bool) -> None:
        """Entscheid des Testers (vor Ort)."""
        check = self.checks[i]
        base = self.note[i] or f"Tastentest: {check.address}"
        if self.state[i] == STATE_OPEN:
            base = f"Tastentest: {check.address} nicht gesendet"
        self._done(i, ok, f"{base}, {'vor Ort bestätigt' if ok else 'Mangel vor Ort'}")

    def _done(self, i: int, ok: bool, note: str) -> None:
        self.state[i] = STATE_OK if ok else STATE_DEFECT
        self.note[i] = note


def room_addresses(project, room_id: str) -> dict[str, set[str]]:
    """Taster des Raums -> alle GAs ihrer KOs bzw. Zuordnungen (auch LED,
    Temperatur): Telegramme darauf sind kein Befund."""
    result: dict[str, set[str]] = {}
    room = next((r for r in project.all_rooms if r.id == room_id), None)
    if room is None:
        return result
    devices = {d.physical_address: d for a in project.topology.areas
               for line in a.lines for d in line.devices}
    for be in room.bedienelemente:
        if not be.participant_number:
            continue
        known = result.setdefault(be.participant_number, set())
        known.update(fa.function_ga.split()[0] for fa in be.function_assignments
                     if fa.function_ga)
        device = devices.get(be.participant_number)
        if device is not None:
            for co in device.communication_objects:
                known.update(co.connected_gas or [])
    return result


def record_key_result(project, check: KeyCheck, ok: bool, note: str, visum: str = "",
                      day: date | None = None) -> int:
    """Ergebnis auf die Prüfpunkte der Taste mit dieser GA (Checkliste des
    Raums); ein Telegramm auf geplanter GA belegt dazu Adresse, Applikation
    und Kommunikation des Tasters, solange diese offen sind. Gibt die Anzahl
    eingetragener Tasten-Prüfpunkte zurück."""
    checklist = next((c for c in project.checklists if c.room_id == check.room_id), None)
    if checklist is None:
        return 0
    count = 0
    for item in checklist.items:
        if (item.be_number == check.be_number and item.check_type == check.channel
                and (item.function_ga == check.function_ga
                     or item.function_ga.split()[:1] == [check.address])):
            item.set_result(RESULT_OK if ok else RESULT_DEFECT, visum, day)
            item.checked_date = (day or date.today()).isoformat()
            if visum:
                item.checked_by = visum
            item.notes = note
            count += 1
    return count


def record_device_proven(project, check: KeyCheck, visum: str = "",
                         day: date | None = None) -> int:
    """Taster hat auf geplanter GA gesendet: Physik. Adresse, Applikation,
    Kommunikation OK, wenn noch offen."""
    checklist = next((c for c in project.checklists if c.room_id == check.room_id), None)
    if checklist is None:
        return 0
    count = 0
    for item in checklist.items:
        if (item.item_kind == ITEM_KIND_DEVICE and item.be_number == check.be_number
                and item.check_type in PROVEN_DEVICE_CHECKS
                and item.result == RESULT_OPEN):
            item.set_result(RESULT_OK, visum, day)
            item.notes = f"Tastentest: Telegramm von {check.be_number} auf {check.address}"
            count += 1
    return count
