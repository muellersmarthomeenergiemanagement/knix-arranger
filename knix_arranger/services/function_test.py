"""
Geführter Funktionstest (FA-3104): je Element eines Raums den Aktor über den
Bus auslösen und auf seine Rückmeldung warten; das Ergebnis kommt mit Datum
und Visum in die Inbetriebnahme-Checkliste.

Je Gewerk:
- Licht, Steckdosen, Schaltfunktionen, Ventilatoren: E/A Ein, Rückmeldung
  abwarten, Aus.
- Dimmbar (mit WERT): 50 %, Rückmeldung abwarten, 0 %.
- Storen (J, R, M, T, FG): Ab, 2 s, Stopp, Rückmeldung abwarten, dann Auf,
  2 s, Stopp -- der Behang steht danach ungefähr wie vorher.
- Nie automatisch: Alarm und Kontakte, Wetterstation, Tor, Türe, Fenster
  und Dachfenster (Einklemmgefahr, Alarm).

Befehls- und Rückmelde-GAs je Element wie bei den ETS-Funktionen
(ets_function_plan): geplant aus der Gliederung (E/A, RM, AUF/AB ...),
importiert aus den Aktor-KOs, die Rückmeldung über das Status-KO des Kanals.
Ohne Rückmelde-GA fragt der Test den Anwender, ob das Element reagiert hat.

Ohne Qt; ausgeführt wird der Plan in ui/dialogs/function_test_dialog.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..models.documentation import (
    ACTUATOR_GROUP, ITEM_KIND_FUNCTION, RESULT_DEFECT, RESULT_OK, ChecklistItem,
)

# Fahrzeit der Storen je Richtung
BLIND_TRAVEL = 2.0
# so lange wartet der Test auf die Rückmeldung
FEEDBACK_TIMEOUT = 3.0
# Pause zwischen zwei Elementen (Bus und Beobachter vor Ort)
STEP_PAUSE = 1.0

SWITCH_CODES = ("L", "LD", "LDA", "LC", "LCT", "LCW", "DMX", "S", "SD", "SF", "V")
BLIND_CODES = ("J", "R", "M", "T", "FG")
# nie automatisch auslösen (zusätzlich Kategorie "alarm")
EXCLUDED_CODES = ("W", "G", "TE", "F", "DF")

KIND_SWITCH, KIND_DIM, KIND_BLIND = "switch", "dim", "blind"


@dataclass
class Action:
    """Ein Schritt der Ausführung: Telegramm senden, warten, auf die
    Rückmeldung warten oder den Anwender fragen."""
    kind: str               # "send", "wait", "feedback", "ask"
    address: str = ""
    payload: str = ""
    size: int = 0
    seconds: float = 0.0
    text: str = ""          # Anzeige ("Ein", "Ab", "50 %")
    # Rückmeldung: was sie zeigen muss ("on" = Ein, "nonzero" = nicht 0,
    # "" = jede Meldung zählt)
    expect: str = ""


def feedback_matches(expect: str, telegram) -> bool:
    """Passt eine Rückmeldung (Schreiben oder Antwort eines Geräts) zum
    ausgelösten Befehl? Eigene Telegramme und Leseanfragen zählen nicht."""
    if telegram.sent or telegram.service not in ("Write", "Response"):
        return False
    data = (telegram.payload or "").strip("0")
    if expect == "on":
        return telegram.payload in ("01", "1") or (telegram.size == 0 and bool(data))
    if expect == "nonzero":
        return bool(data)
    return True


@dataclass
class TestStep:
    """Ein Element im Funktionstest."""
    room_id: str
    room: str                       # "E05 Küche"
    gewerk_code: str
    label: str                      # "L_EG_E05_01 (Decke)"
    kind: str = ""
    commands: dict[str, str] = field(default_factory=dict)   # Funktion -> GA
    designations: list[str] = field(default_factory=list)    # aller Element-GAs
    feedback: str = ""              # Rückmelde-GA ("" = Anwender fragt)
    skip: str = ""                  # Grund, warum nicht automatisch
    # Haupt-GA des Elements für die Checkliste: "3/0/35  L.OG.02.02_ea (Möbel)"
    ga_line: str = ""
    # was vor Ort reagieren muss: Klartext des Elements, sonst der Ort aus
    # der GA-Bezeichnung ("Balkon Bibliothek") -- erkennt vertauschte Kanäle
    place: str = ""
    # Aktorkanal, an dem der Befehl hängt: "1.1.5 Motor 3"
    actuator: str = ""

    @property
    def testable(self) -> bool:
        return not self.skip

    @property
    def code(self) -> str:
        """Elementcode ohne Raumnamen: "L_OG_02_01"."""
        return self.label.split(" (", 1)[0]

    def title(self) -> str:
        """"Balkon Bibliothek (J_OG_02_04)" -- Objekt zuerst."""
        return f"{self.place} ({self.code})" if self.place else self.code

    def description(self) -> str:
        """Text des Prüfpunkts: Objekt, Ablauf, Aktorkanal."""
        what = self.what() if self.testable else "vor Ort prüfen"
        text = f"{self.place} – {what}" if self.place else what
        return f"{text} · Aktor {self.actuator}" if self.actuator else text

    def what(self) -> str:
        """Kurz, was der Test tut."""
        if self.skip:
            return self.skip
        if self.kind == KIND_BLIND:
            return "Ab – 2 s – Stopp, Auf – 2 s – Stopp"
        if self.kind == KIND_DIM:
            return "50 %, dann 0 %"
        return "Ein, dann Aus"

    def actions(self) -> list[Action]:
        if self.skip:
            return []
        expect = {KIND_SWITCH: "on", KIND_DIM: "nonzero"}.get(self.kind, "")
        feedback = [Action("feedback", self.feedback, seconds=FEEDBACK_TIMEOUT,
                           expect=expect)] \
            if self.feedback else [Action("wait", seconds=FEEDBACK_TIMEOUT), Action("ask")]
        c = self.commands
        if self.kind == KIND_BLIND:
            move, stop = c["AUF/AB"], c["STOPP"]
            return [Action("send", move, "01", 0, text="Ab"),
                    Action("wait", seconds=BLIND_TRAVEL),
                    Action("send", stop, "01", 0, text="Stopp"),
                    *feedback,
                    Action("send", move, "00", 0, text="Auf"),
                    Action("wait", seconds=BLIND_TRAVEL),
                    Action("send", stop, "00", 0, text="Stopp")]
        if self.kind == KIND_DIM:
            value = c["WERT"]
            return [Action("send", value, "80", 1, text="50 %"), *feedback,
                    Action("send", value, "00", 1, text="0 %")]
        switch = c["E/A"]
        return [Action("send", switch, "01", 0, text="Ein"), *feedback,
                Action("send", switch, "00", 0, text="Aus")]


def plan_steps(project, room_ids: set[str] | None = None) -> list[TestStep]:
    """Elemente der Räume (alle, wenn room_ids None) in der Reihenfolge des
    Gebäudes; nicht automatisch prüfbare mit Grund (skip). Gewerke ohne
    sinnvollen Test (Heizung, Energie ...) fehlen."""
    from .ets_function_plan import (
        MemberElement, _assignments_by_id, _element_gas, _imported_status_gas,
    )
    by_id = _assignments_by_id(project)
    element_gas = _element_gas(project)
    _add_unassigned(project, by_id, element_gas)
    imported = (_imported_status_gas(project, element_gas)
                if project.topology.is_imported else {})
    catalog = project.gewerk_catalog
    numbers: dict[str, list[int]] = {}
    for assignment_id, number in element_gas:
        numbers.setdefault(assignment_id, []).append(number)

    steps = []
    channels = None
    for assignment_id, (room, assignment, floor_code) in by_id.items():
        if room_ids is not None and room.id not in room_ids:
            continue
        code = assignment.gewerk_code
        gewerk = catalog.get(code) if catalog else None
        category = getattr(gewerk, "category", "") if gewerk else ""
        excluded = category == "alarm" or code in EXCLUDED_CODES
        if not excluded and code not in SWITCH_CODES + BLIND_CODES:
            continue
        for number in sorted(numbers.get(assignment_id, [])):
            functions = element_gas[(assignment_id, number)]
            key = (assignment_id, number)
            step = TestStep(
                room_id=room.id,
                room=" ".join(p for p in (room.number, room.name) if p),
                gewerk_code=code,
                label=MemberElement(room, assignment, number, floor_code).label,
                designations=[ga.designation for ga in functions.values() if ga.designation])
            status = {**{f: ga for f, ga in functions.items()}, **imported.get(key, {})}
            for ga in imported.get(key, {}).values():
                if ga.designation:
                    step.designations.append(ga.designation)
            if excluded:
                step.skip = "nicht automatisch (Sicherheit) – vor Ort prüfen"
            elif code in BLIND_CODES:
                step.kind = KIND_BLIND
                _need(step, functions, ("AUF/AB", "STOPP"))
                step.feedback = _address(status.get("STATUS POSITION HOEHE"))
            elif "WERT" in functions and code not in ("L", "S", "SF", "V"):
                step.kind = KIND_DIM
                _need(step, functions, ("WERT",))
                step.feedback = _address(status.get("RM WERT") or status.get("RM"))
            else:
                step.kind = KIND_SWITCH
                _need(step, functions, ("E/A",))
                step.feedback = _address(status.get("RM"))
            main = next((functions[f] for f in ("E/A", "AUF/AB", "WERT") if f in functions),
                        next(iter(functions.values()), None))
            step.ga_line = _ga_text(main)
            step.place = assignment.element_label(number) or _place(main)
            if step.place in ("", room.name):
                # nur der Raumname: das Gewerk sagt mehr ("Steckdosen")
                step.place = getattr(gewerk, "name", "") or step.place or step.room
            if channels is None:
                channels = _actuator_channels(project)
            addresses = [*step.commands.values(), *(ga.address for ga in functions.values())]
            step.actuator = next((channels[a] for a in addresses if a in channels), "")
            steps.append(step)
    return steps


def _place(ga) -> str:
    """Ort/Objekt aus der GA-Bezeichnung: der Klartext in Klammern
    ("J.OG.02.04_move (Balkon Bibliothek)" -> "Balkon Bibliothek"), sonst
    die Bezeichnung ohne technischen Teil."""
    if ga is None or not ga.designation:
        return ""
    import re
    text = " ".join(ga.designation.split())
    found = re.search(r"\(([^()]+)\)\s*$", text)
    if found:
        return found.group(1).strip()
    # "Bibliothek Decke" bleibt, "L.OG.02.01_ea" allein sagt nichts
    return "" if re.fullmatch(r"[\w.\-]+", text) and ("_" in text or "." in text) else text


def _actuator_channels(project) -> dict[str, str]:
    """Befehls-GA -> "1.1.5 Motor 3" (Aktor/Gateway und Kanal, der auf die
    GA hört; Einbauort angehängt, wenn erfasst)."""
    from .actor_channels import _is_feedback, device_channels
    result: dict[str, str] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type not in ("actor", "gateway"):
                    continue
                where = f" ({device.installation_location})" \
                    if device.installation_location else ""
                channels = device_channels(device)
                listed = {id(co) for ch in channels for co in ch.com_objects}
                groups = [(ch.label, ch.com_objects) for ch in channels if ch.com_objects]
                rest = [co for co in device.communication_objects if id(co) not in listed]
                groups += [((co.name or "").split(",")[0].strip(), [co]) for co in rest]
                for label, cos in groups:
                    text = " ".join(p for p in (device.physical_address, label) if p) + where
                    for co in cos:
                        if _is_feedback(co):
                            continue
                        for address in co.connected_gas or []:
                            result.setdefault(address, text)
    return result


def _ga_text(ga) -> str:
    """'3/0/35  L.OG.02.02_ea (Möbel)' -- Schlüssel des Prüfpunkts, ohne DPT
    (der kann sich ändern)."""
    if ga is None:
        return ""
    import re
    text = f"{ga.address}  {' '.join((ga.designation or '').split())}".strip()
    return re.sub(r"\(\s*", "(", re.sub(r"\s*\)", ")", text))


def actuator_item(step: TestStep) -> ChecklistItem:
    """Prüfpunkt des Elements in der Gruppe «Aktorkanäle» der Raum-Checkliste."""
    return ChecklistItem(
        item_kind=ITEM_KIND_FUNCTION, check_type=step.code,
        description=step.description(),
        function_ga=step.ga_line, room_id=step.room_id,
        be_type=ACTUATOR_GROUP, be_number="", gewerk_code=step.gewerk_code)


def steps_by_room(project) -> dict[str, list[TestStep]]:
    """Alle Elemente je Raum (für die Checklisten)."""
    result: dict[str, list[TestStep]] = {}
    for step in plan_steps(project):
        result.setdefault(step.room_id, []).append(step)
    return result


def _add_unassigned(project, by_id: dict, element_gas: dict) -> None:
    """GAs ohne Zuweisung (Projekte, deren GAs vor der festen Zuordnung
    erzeugt wurden): über Raum, Gewerk und Elementnummer dem ersten
    passenden Gewerk des Raums zuordnen."""
    first: dict[tuple[str, str], str] = {}
    for assignment_id, (room, assignment, _floor) in by_id.items():
        first.setdefault((room.id, assignment.gewerk_code), assignment_id)
    for ga in project.group_addresses.all_addresses():
        if (ga.assignment_id or ga.is_placeholder or ga.function_id
                or not ga.element_number or not ga.planned_function):
            continue
        assignment_id = first.get((ga.room_id, ga.gewerk_code))
        if assignment_id:
            element_gas.setdefault((assignment_id, ga.element_number), {}) \
                .setdefault(ga.planned_function, ga)


def _need(step: TestStep, functions: dict, names: tuple[str, ...]) -> None:
    missing = [n for n in names if n not in functions]
    if missing:
        step.skip = f"keine GA {', '.join(missing)}"
        return
    step.commands = {n: functions[n].address for n in names}


def _address(ga) -> str:
    return ga.address if ga is not None else ""


def record_result(project, step: TestStep, ok: bool, note: str, visum: str = "",
                  day: date | None = None) -> int:
    """Ergebnis auf den Prüfpunkt des Elements in der Gruppe «Aktorkanäle»
    der Raum-Checkliste; fehlt er (Checkliste von früher), wird er angelegt.
    Die Prüfpunkte der Tasten bleiben unberührt: ein Telegramm vom PC zeigt,
    dass der Aktor schaltet, nicht dass die Taste es tut. Gibt 1 zurück, 0
    ohne Checkliste des Raums."""
    checklist = next((c for c in project.checklists if c.room_id == step.room_id), None)
    if checklist is None:
        return 0
    item = next((i for i in checklist.items if i.be_type == ACTUATOR_GROUP
                 and i.check_type == step.code), None)
    if item is None:
        item = actuator_item(step)
        checklist.items.append(item)
    item.description = step.description()
    item.set_result(RESULT_OK if ok else RESULT_DEFECT, visum, day)
    item.checked_date = (day or date.today()).isoformat()
    if visum:
        item.checked_by = visum
    item.notes = note
    return 1
