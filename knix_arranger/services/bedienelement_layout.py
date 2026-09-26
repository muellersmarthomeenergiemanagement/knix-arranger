"""
Aufbereitung der Tastenbelegung für den Bedienelemente-Bericht.

Die Funktionszuordnungen eines Tasters heissen nach ETS-Kanal, z.B.
"Taste 3, links", "Taste 3, links, Signal-LED", "Taste 1, Doppelklick",
"Taste 2, rechts (langer Tastendruck)". Daraus entstehen
- eine Zeile je Taste und Bedienung (kurz, lang, Doppelklick) mit allen
  Gruppenadressen, die LED-Rückmeldung als Zusatz derselben Taste,
- der Tastenplan (Raster wie der Taster an der Wand) mit Gewerk oder
  Szene als Beschriftung.
Objekte ohne Tastenbezug ("Nachtabsenkung LED's", "Raumtemperatur")
stehen unter "Weitere".
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from .gewerk_service import GewerkService

_BUTTON_RE = re.compile(
    r"^Taste\s*(\d+)"
    r"(?:\s*,\s*(links|rechts))?"
    r"(?:\s*\((langer Tastendruck)\))?"
    r"(?:\s*,\s*(.+?))?\s*$",
    re.IGNORECASE,
)
_LED_RE = re.compile(r"signal[\s-]*led|\bled\b", re.IGNORECASE)
_PAREN_RE = re.compile(r"\(\s*([^()]*?)\s*\)")
_SCENE_RE = re.compile(r"szene[\s_]*(.*)", re.IGNORECASE)
_ADDR_PREFIX_RE = re.compile(r"^\d+/\d+/\d+\s+")

SIDE_ORDER = {"": 0, "links": 1, "rechts": 2}
VARIANT_ORDER = {"": 0, "lang": 1, "Doppelklick": 2}


@dataclass
class ButtonKey:
    number: int
    side: str = ""          # "", "links", "rechts"
    variant: str = ""       # "", "lang", "Doppelklick"

    def label(self) -> str:
        parts = [str(self.number)]
        if self.side:
            parts.append(self.side)
        if self.variant:
            parts.append(self.variant)
        return " ".join(parts)

    def sort_key(self) -> tuple:
        return (self.number, SIDE_ORDER[self.side], VARIANT_ORDER[self.variant])


@dataclass
class ButtonRow:
    key: ButtonKey | None           # None = "Weitere" (kein Tastenbezug)
    name: str = ""                  # Kanalname bei "Weitere"
    gas: list = field(default_factory=list)       # GroupAddress oder Text
    led_gas: list = field(default_factory=list)


def parse_button(channel: str) -> tuple[ButtonKey, bool] | None:
    """('Taste 3, links, Signal-LED') -> (ButtonKey(3, 'links'), is_led)."""
    m = _BUTTON_RE.match((channel or "").strip())
    if not m:
        return None
    number, side, long_press, extra = m.groups()
    extra = extra or ""
    is_led = bool(_LED_RE.search(extra))
    variant = "lang" if long_press else ""
    if "doppel" in extra.lower():
        variant = "Doppelklick"
    return ButtonKey(int(number), (side or "").lower(), variant), is_led


def group_assignments(assignments, resolve) -> list[ButtonRow]:
    """Fasst Funktionszuordnungen zu Tastenzeilen zusammen.

    resolve(function_ga) -> GroupAddress | None."""
    rows: dict[tuple, ButtonRow] = {}
    for fa in assignments:
        ga = resolve(fa.function_ga) if fa.function_ga else None
        item = ga if ga is not None else _ADDR_PREFIX_RE.sub("", fa.function_ga or "").strip()
        if not item:
            continue
        parsed = parse_button(fa.button_channel)
        if parsed is None:
            name = (fa.button_channel or fa.description or "").strip() or "Objekt"
            row = rows.setdefault(("~", name), ButtonRow(None, name))
            row.gas.append(item)
            continue
        key, is_led = parsed
        row = rows.setdefault((key.number, key.side, key.variant), ButtonRow(key))
        target = row.led_gas if is_led else row.gas
        if item not in target:
            target.append(item)
    return sorted(
        rows.values(),
        key=lambda r: (1, (), r.name) if r.key is None else (0, r.key.sort_key(), ""),
    )


def ga_function_label(ga, catalog, room_name: str = "") -> tuple[str, str]:
    """(Gewerk oder Szene, Zusatz) für die Beschriftung einer Taste.

    Zusatz ist der Klammertext der ETS-Bezeichnung ("( Fenster )"), sofern
    er nicht bloss den Raumnamen wiederholt."""
    if ga is None:
        return "", ""
    designation = ga if isinstance(ga, str) else (ga.designation or "")
    paren = _PAREN_RE.search(designation)
    detail = paren.group(1).strip() if paren else ""
    if detail and room_name and detail.lower() in room_name.lower():
        detail = ""
    base = _PAREN_RE.sub("", designation).strip()

    scene = _SCENE_RE.search(base)
    if scene and (isinstance(ga, str) or not ga.gewerk_code):
        rest = re.sub(r"[_\s]+", " ", scene.group(1)).strip()
        return "Szene", " ".join(p for p in (rest, detail) if p)

    code = "" if isinstance(ga, str) else (ga.gewerk_code or "")
    if not code:
        matched = GewerkService._match_ga_designation(base)
        code = matched[0] if matched else ""
    gewerk = catalog.get(code) if code else None
    if gewerk:
        return gewerk.name, detail
    return base, detail


def row_function_label(row: ButtonRow, catalog, room_name: str = "") -> tuple[str, str]:
    """Beschriftung einer Tastenzeile aus ihrer ersten Nicht-LED-GA."""
    for ga in row.gas:
        title, detail = ga_function_label(ga, catalog, room_name)
        if title:
            return title, detail
    return "", ""


def button_plan(rows: list[ButtonRow], catalog, room_name: str = "") -> list[dict]:
    """Rasterzeilen für PdfGenerator.add_button_plan (nur Kurzdruck)."""
    by_number: dict[int, dict[str, tuple[str, str]]] = {}
    for row in rows:
        if row.key is None or row.key.variant:
            continue
        label = row_function_label(row, catalog, room_name)
        by_number.setdefault(row.key.number, {})[row.key.side] = label
    plan = []
    for number in sorted(by_number):
        sides = by_number[number]
        if set(sides) <= {""}:
            cells = [sides.get("", ("", ""))]
        else:
            cells = [sides.get("links", ("", "")), sides.get("rechts", ("", ""))]
        plan.append({"number": number, "cells": cells})
    return plan
