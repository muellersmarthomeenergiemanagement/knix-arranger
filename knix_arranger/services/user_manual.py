"""
Bedienungsanleitung für den Bauherrn (FA-2001 bis FA-2004).

Für Bewohner geschrieben, nicht für Integratoren: je Raum die Taster mit
Tastenplan und je Taste, WAS sie bewirkt ("Wandleuchten Zugang") und WIE man
sie bedient ("kurz: Ein · lang: heller") -- ohne Gruppenadressen und
ETS-Bezeichnungen. Die Bedienung stammt aus den ETS-Parametern des Tasters
(Device.button_configuration, z.B. Feller EDIZIOdue: "Funktion Dimmen:
EIN/heller (kurz/lang)"); fehlen sie, wird sie aus dem Datenpunkttyp der
Gruppenadressen abgeleitet.

Aufbau: Inhaltsübersicht, allgemeiner Teil (KNX in Kürze, so bedienen Sie die
Taster, zentrale Funktionen, bei Störungen, Kontakt), danach je Stockwerk und
Raum die Bedienstellen und Besonderheiten (Präsenz-, Rauch-, Wassermelder,
Heizung). Sensoren erscheinen nur als Satz, nie mit Objektliste.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .bedienelement_layout import ButtonKey, group_assignments, _PAREN_RE, _SCENE_RE
from .gewerk_service import GewerkService
from .report_sorting import sorted_rooms

logger = logging.getLogger("knix_arranger.user_manual")

_ADDR_RE = re.compile(r"^\s*(\d+/\d+/\d+)")
_CODE_TOKEN_RE = re.compile(r"\b[A-Z]{1,4}\.[A-Z]{2}\.[\w.+\-]*\b")


# ── ETS-Parameter des Tasters ──────────────────────────────────────────────

@dataclass
class KeyParams:
    """Parameter einer Taste (oder Wippe) aus dem ETS-Report."""
    function: str = ""                 # "Schalten", "Dimmen", "Jalousie", "Wert"
    values: dict = field(default_factory=dict)       # "Funktion Schalten" -> "Drücken: EIN"
    long_function: str = ""
    long_values: dict = field(default_factory=dict)
    led: str = ""
    led_mode: str = ""
    led_color: str = ""
    long_time: str = ""
    double_click: str = ""             # erweiterte Funktionen Jalousie (Doppelklick)
    value: str = ""                    # gesendeter Wert (Funktion Wert), z.B. "0"
    long_value: str = ""


@dataclass
class ButtonConfig:
    philosophy: dict = field(default_factory=dict)   # Tastennummer -> Bedienphilosophie
    keys: dict = field(default_factory=dict)         # (Nummer, Seite) -> KeyParams

    def params(self, key: ButtonKey) -> KeyParams | None:
        return (self.keys.get((key.number, key.side))
                or self.keys.get((key.number, "")))


_SECTION_RE = re.compile(r"^Taste\s*(\d+)(?:\s*,\s*(links|rechts))?\s*:\s*$", re.IGNORECASE)
_PHILO_RE = re.compile(r"^Bedienphilosophie Taste\s*(\d+)\s*:\s*(.+)$", re.IGNORECASE)


def parse_button_configuration(text: str) -> ButtonConfig:
    """Liest den ETS-Parametertext eines Tasters (siehe
    XlsxImportService.extract_button_configuration) in Tasten-Parameter."""
    cfg = ButtonConfig()
    current: KeyParams | None = None
    in_long = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _PHILO_RE.match(line)
        if m:
            cfg.philosophy[int(m.group(1))] = m.group(2).strip()
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = KeyParams()
            in_long = False
            cfg.keys[(int(m.group(1)), (m.group(2) or "").lower())] = current
            continue
        if current is None or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name, value = name.strip(), " ".join(value.split())
        low = name.lower()
        if low == "funktion taste":
            current.function = value
        elif low.startswith("langer tastendruck"):
            in_long = value.lower() == "aktiv"
        elif low == "funktion langer tastendruck":
            current.long_function = value
        elif low == "zeit für langen tastendruck":
            current.long_time = value
        elif low == "funktion led":
            current.led = value
        elif low == "led anzeigemodus":
            current.led_mode = value
        elif low == "led farbe":
            current.led_color = value
        elif low.startswith("erweiterte funktionen"):
            current.double_click = value
        elif low.startswith("funktion "):
            (current.long_values if in_long and current.long_function else current.values)[name] = value
        elif "wert" in low and value.isdigit():
            # "1Byte Wert (0..255): 2" -- bei Szenen die Szenennummer - 1
            if in_long and current.long_function:
                current.long_value = value
            else:
                current.value = value
    return cfg


# ── Bedienung in Alltagssprache ────────────────────────────────────────────

def _switch_text(value: str) -> str:
    v = value.upper().replace(" ", "")
    if "LOSLASSEN" in v or "LOSL" in v:
        return "gedrückt halten: Ein, loslassen: Aus"
    if "UM" in v.split(":")[-1]:
        return "Ein/Aus"
    if v.endswith("EIN"):
        return "Ein"
    if v.endswith("AUS"):
        return "Aus"
    return value


def _dim_text(value: str) -> tuple[str, str]:
    """(kurz, lang) für "EIN/heller (kurz/lang)" usw."""
    v = value.lower()
    if "um" in v and ("1 taste" in v or "um/dimmen" in v):
        return "Ein/Aus", "heller/dunkler (wechselnd)"
    if "heller" in v:
        return "Ein", "heller"
    if "dunkler" in v:
        return "Aus", "dunkler"
    return "Ein/Aus", "dimmen"


def _blind_side(value: str) -> str:
    v = value.upper()
    return "auf" if v.startswith("AUF") else "ab" if v.startswith("AB") else ""


def describe_from_params(p: KeyParams, side: str) -> tuple[str, list[str]]:
    """(Kurzform für den Tastenplan, Bedienzeilen) aus den ETS-Parametern."""
    func = p.function.lower()
    lines: list[str] = []
    short = ""
    if func == "dimmen":
        kurz, lang = _dim_text(next(iter(p.values.values()), ""))
        lines.append(f"kurz drücken: {kurz} · lang drücken: {lang}")
        short = "Ein/Aus · dimmen" if "wechselnd" in lang else f"{kurz} / {lang}"
    elif func == "jalousie":
        sides = {k.lower(): _blind_side(v) for k, v in p.values.items()}
        own = (sides.get(f"funktion jalousie {side}") or sides.get("funktion jalousie", "")) if side else ""
        if own:
            lines.append(f"lang drücken: {own}fahren · kurz drücken: Stopp / Lamellen")
            short = own.capitalize()
        elif sides:
            pair = " · ".join(f"{k.split()[-1]}: {v}" for k, v in sides.items()
                              if v and k.split()[-1] in ("links", "rechts"))
            lines.append(f"{pair}" if pair else "")
            lines.append("lang drücken: fahren · kurz drücken: Stopp / Lamellen")
            short = "Auf / Ab"
        else:
            lines.append("lang drücken: fahren · kurz drücken: Stopp / Lamellen")
            short = "Auf / Ab"
        if "doppelklick" in p.double_click.lower():
            lines.append("Doppelklick: in die Beschattungsposition fahren")
    elif func == "schalten":
        text = _switch_text(next(iter(p.values.values()), ""))
        lines.append(f"drücken: {text}" if not text.startswith("gedrückt") else text)
        short = "Ein/Aus" if text == "Ein/Aus" else text if text in ("Ein", "Aus") else ""
    elif func == "wert":
        lines.append("drücken")
    elif func:
        lines.append(f"drücken ({p.function})")
    if p.long_function:
        long_val = next(iter(p.long_values.values()), "")
        what = (_switch_text(long_val) if p.long_function.lower() == "schalten"
                else "andere Einstellung" if p.long_function.lower() == "wert"
                else p.long_function)
        time = f" ({p.long_time})" if p.long_time else ""
        lines.append(f"lang drücken{time}: {what}")
    return short, [ln for ln in lines if ln]


def led_text(p: KeyParams) -> str:
    led = p.led.lower()
    if not led or "nicht aktiv" in led:
        return ""
    color = f" {p.led_color}" if p.led_color else ""
    if "loslassen" in led or "losl" in led:
        return f"Leuchtanzeige{color}: leuchtet beim Drücken"
    if "invers" in p.led_mode.lower():
        return f"Leuchtanzeige{color}: leuchtet, wenn ausgeschaltet"
    return f"Leuchtanzeige{color}: leuchtet, wenn eingeschaltet"


def dpt_kind(ga) -> str:
    """Art einer GA aus dem DPT -- als Kennung ("DPST-3-7") oder, wie in
    manchen Importen, als Name ("Dimmer Schritt", "Schritt", "Auf/Ab")."""
    dpt = (getattr(ga, "datapoint_type", "") or "").strip()
    up = dpt.upper()
    low = dpt.lower()
    if up.startswith(("DPST-3-", "DPT-3")) or "dimmer" in low:
        return "dim"
    if up.startswith(("DPST-1-8",)) or low in ("auf/ab", "up/down"):
        return "updown"
    if up.startswith(("DPST-1-7",)) or low in ("schritt", "step"):
        return "step"
    if up.startswith(("DPST-17", "DPST-18")) or low.startswith("szene"):
        return "scene"
    if up.startswith("DPST-5") or "prozent" in low or "wert" in low and "bin" not in low:
        return "value"
    if up.startswith("DPST-1-") or low in ("schalten", "switch"):
        return "switch"
    return ""


def describe_from_dpt(gas: list) -> tuple[str, list[str]]:
    """Bedienung ohne ETS-Parameter, aus den Datenpunkttypen."""
    kinds = {dpt_kind(g) for g in gas}
    if "dim" in kinds:
        return "Ein/Aus / dimmen", ["kurz drücken: Ein/Aus · lang drücken: dimmen"]
    if "updown" in kinds:
        return "Auf / Ab", ["lang drücken: fahren · kurz drücken: Stopp / Lamellen"]
    if "scene" in kinds:
        return "Szene", ["drücken: Szene abrufen"]
    if "step" in kinds:
        return "vor/zurück", ["drücken: vor/zurück"]
    if "value" in kinds:
        return "", ["drücken: Wert einstellen"]
    return "Ein/Aus", ["drücken: Ein/Aus"]


_GATE_RE = re.compile(r"\b(garagen)?tor(e)?\b", re.IGNORECASE)
_PRESENCE_RE = re.compile(r"^(an|ab)wesen", re.IGNORECASE)


def is_gate(label: str) -> bool:
    return bool(_GATE_RE.search(label or ""))


def name_scene_values(p: KeyParams, ga, short: str, how: list[str]) -> tuple[str, list[str]]:
    """Wert-Taste auf einer Szenen-GA: gesendeter Wert -> Szenenname aus dem
    ETS-Kommentar ("#1: Anwesend"). Auf dem Bus ist Szene 1 der Wert 0."""
    from .scene_value_linking import scene_names_from_comment
    if dpt_kind(ga) != "scene" or not p.value:
        return short, how
    names = scene_names_from_comment(getattr(ga, "comment", "") or "")

    def scene(value: str) -> str:
        number = int(value) + 1
        return f"«{names[number]}»" if number in names else f"Szene {number}"

    how = [f"drücken: {scene(p.value)}"] + [
        (f"{h.split(':')[0]}: {scene(p.long_value)}"
         if h.startswith("lang drücken") and p.long_value else h)
        for h in how[1:]]
    return scene(p.value).strip("«»"), how


def _is_audio(label: str) -> bool:
    low = label.lower()
    return low.startswith("musik") or "lautstärke" in low or "musik" in low


def adapt_to_target(short: str, how: list[str], gas: list, label: str,
                    function: str = "") -> tuple[str, list[str]]:
    """Passt die allgemeine Tastenbedienung an das gesteuerte Ziel an:
    - Dimmen ohne Schalt-GA (z.B. nur Lautstärke) -> kein "kurz drücken"
    - Lautstärke -> lauter/leiser statt heller/dunkler
    - Schritt-Objekt (DPT 1.007, z.B. Titel Rückw/Vorw) -> vor/zurück."""
    kinds = {dpt_kind(g) for g in gas}
    if function.lower() == "dimmen" and "switch" not in kinds:
        how = [h.split(" · ", 1)[1] if h.startswith("kurz drücken") and " · " in h else h
               for h in how]
        short = short.split(" / ", 1)[-1]
    if _is_audio(label):
        swap = (("heller/dunkler", "lauter/leiser"), ("heller", "lauter"),
                ("dunkler", "leiser"), ("dimmen", "Lautstärke ändern"))
        for old, new in swap:
            how = [h.replace(old, new) for h in how]
            short = short.replace(old, new)
    if is_gate(label):
        how = [("drücken: Tor öffnen bzw. schliessen"
                if h.startswith("gedrückt halten") or h == "drücken: Ein/Aus" else h)
               .replace("Stopp / Lamellen", "Stopp")
               .replace("auffahren", "öffnen").replace("abfahren", "schliessen")
               for h in how]
        short = {"Auf": "öffnen", "Ab": "schliessen"}.get(short, short)
        if short in ("Ein/Aus", "Ein", ""):
            short = "öffnen / schliessen"
    elif _PRESENCE_RE.match(label or ""):
        how = [f"drücken: {label}" if h.startswith("gedrückt halten") or h == "drücken" else h
               for h in how]
        short = ""
    if "step" in kinds and kinds <= {"step", ""}:
        swap = (("Ein/Aus", "vor/zurück"), ("Ein", "vor"), ("Aus", "zurück"))
        for old, new in swap:
            how = [h.replace(f": {old}", f": {new}") for h in how]
            if short == old:
                short = new
    return short, how


# ── Was die Taste bewirkt ──────────────────────────────────────────────────

_CATEGORY_WORD = {
    "licht": "Licht", "licht_color": "Licht", "jalousie": "Storen",
    "heizung": "Heizung", "lueftung": "Lüftung", "alarm": "Alarm",
    "energie": "Energie",
}


#: Funktionssuffixe der ETS-Bezeichnung ohne Aussage für den Bauherrn
_TECH_SUFFIXES = {"ea", "dim", "move", "step", "wert", "status", "rm", "stop"}


def _code_suffix(match: re.Match) -> str:
    """"J.DG.04.02-04_beschattung" -> "Beschattung", "L.UG.01.1_ea" -> ""."""
    suffix = match.group(0).rsplit("_", 1)[-1] if "_" in match.group(0) else ""
    return "" if suffix.lower() in _TECH_SUFFIXES or len(suffix) < 3 else suffix.capitalize()


def _clean(text: str) -> str:
    text = _CODE_TOKEN_RE.sub(_code_suffix, text or "")
    text = re.sub(r"[-_\s]*\b1\s*(bit|byte)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"\bRaum\s?\d+\b", "", text)      # UniPro-Raumnummer "Raum2"
    return " ".join(text.split()).strip(" -·")


_ABBREVIATIONS = (("Rückw/Vorw", "Titel zurück/vor"), ("Rückw", "zurück"),
                  ("Vorw", "vor"), ("Lautst.", "Lautstärke"))


def _function_words(base: str, code: str) -> str:
    """Funktionsteil einer ETS-Bezeichnung ohne Kürzel:
    "MM.OG.02.01_dim Lautstärke" -> "Lautstärke",
    "MM_S1_MusikChalet_ea" -> "S1 Musik Chalet"."""
    text = _CODE_TOKEN_RE.sub("", base)
    words = [w for w in re.split(r"[_\s]+", text) if w]
    # Gewerk-Kürzel am Anfang ("MM_S1_…"), auch wenn kein Gewerk erkannt wurde
    if words and ((code and words[0].upper() == code.upper())
                  or (words[0].isalpha() and words[0].isupper() and len(words[0]) <= 4)):
        words = words[1:]
    words = [w for w in words if w.lower() not in _TECH_SUFFIXES]
    text = " ".join(words)
    text = re.sub(r"(?<=[a-zäöü])(?=[A-ZÄÖÜ])", " ", text)   # MusikChalet
    for old, new in _ABBREVIATIONS:
        text = text.replace(old, new)
    return text.strip(" -·")


def object_label(ga, catalog, room_name: str) -> str:
    """Was die Taste bewirkt, z.B. "Wandleuchten Zugang Chalet", "Szene High",
    "Licht" -- das gesteuerte Objekt aus der ETS-Bezeichnung (Klammertext)
    statt des Gewerk-Katalognamens (im Chalet steht "T." für Tor, nicht für
    Tagesvorhang)."""
    if ga is None:
        return ""
    designation = ga if isinstance(ga, str) else (ga.designation or "")
    designation = _ADDR_RE.sub("", designation)
    paren = _PAREN_RE.search(designation)
    detail = _clean(paren.group(1)) if paren else ""
    base = _PAREN_RE.sub("", designation).strip()
    scene = _SCENE_RE.search(base)
    if scene and (isinstance(ga, str) or not ga.gewerk_code):
        return f"Szene {_clean(scene.group(1))}".strip()
    code = "" if isinstance(ga, str) else (ga.gewerk_code or "")
    if not code:
        matched = GewerkService._match_ga_designation(base)
        code = matched[0] if matched else ""
    if code.upper() == "MM" or "musik" in base.lower():
        # Multimedia: Ort UND Funktion ("Musik Wohnen – Lautstärke")
        func = _function_words(base, code)
        place = detail if detail and detail.lower() != (room_name or "").lower() else ""
        words = func.split()
        idx = next((i for i, w in enumerate(words) if w.lower().startswith("musik")), None)
        if idx:   # "S1 Musik Chalet" -> "Musik Chalet – S1"
            return f"{' '.join(words[idx:])} – {' '.join(words[:idx])}"
        head = f"Musik {place}".strip() if "musik" not in func.lower() else place
        return " – ".join(p for p in (head, func) if p) or "Musik"
    gewerk = catalog.get(code) if (code and catalog) else None
    if detail and not (room_name and detail.lower() == room_name.lower()):
        # Storen nur mit Ort ("Mitte", "Berg") -> "Storen Mitte"
        if (gewerk and gewerk.category == "jalousie" and not is_gate(detail)
                and not re.search(r"storen|jalousie|rollladen|markise|vorhang", detail, re.I)):
            return f"Storen {detail}"
        return detail
    if gewerk:
        word = _CATEGORY_WORD.get(gewerk.category, gewerk.name)
        # "J.EG.06.1-03_move", "J.OG.03.01+J.OG.04.01_move": mehrere Elemente
        token = _CODE_TOKEN_RE.search(base)
        if token and ("+" in token.group(0) or re.search(r"\d-\d", token.group(0))):
            return f"{word} gemeinsam"
        return word
    return _clean(base) or "Funktion"


# ── Raumbezogene Texte ─────────────────────────────────────────────────────

_SENSOR_TEXT = (
    (("präsenz", "bewegung", "pir"),
     "Präsenzmelder: schaltet das Licht automatisch, wenn jemand im Raum ist, "
     "und nach einer Weile ohne Bewegung wieder aus."),
    (("rauch",), "Rauchmelder: warnt mit einem lauten Ton bei Rauch."),
    (("wasser", "leck"), "Wassermelder: meldet austretendes Wasser."),
    (("fenster", "kontakt"), "Fensterkontakt: meldet, ob das Fenster offen ist."),
    (("wetter",), "Wetterstation: steuert Storen bei Wind, Regen und Sonne automatisch."),
    (("temperatur", "fühler", "fuehler"), "Temperaturfühler: misst die Raumtemperatur."),
)


def sensor_sentence(element_type: str, product: str = "") -> str:
    text = f"{element_type} {product}".lower()
    for words, sentence in _SENSOR_TEXT:
        if any(w in text for w in words):
            return sentence
    return f"{element_type}: arbeitet automatisch."


def _friendly_type(be) -> str:
    t = be.element_type or "Bedienelement"
    return {"Tastereinheit": "Taster"}.get(t, t)


# ── Dokument ───────────────────────────────────────────────────────────────

@dataclass
class _KeyLine:
    key: ButtonKey
    label: str
    short: str
    how: list[str]
    led: str
    scene_text: str = ""     # Was die Szene bewirkt (Kurzbeschreibung, FA-2002)


class UserManualBuilder:
    """Baut die Bedienungsanleitung in einen PdfGenerator."""

    def __init__(self, project, company_profile=None):
        from .sensor_service import project_for_export
        self.project = project_for_export(project)
        self.company = company_profile
        self.catalog = self.project.gewerk_catalog
        self.ga_by_address = {g.address: g for g in self.project.group_addresses.all_addresses()}
        # Geplante Projekte verweisen auf GAs per Bezeichnung ("LDA_M01_01 E/A")
        from .belegungsplan_service import build_ga_by_designation
        self.ga_by_designation = build_ga_by_designation(self.project.group_addresses)
        self.scenes = {sc.id: sc for sc in getattr(self.project, "scenes", [])}
        self.scene_names = {sid: sc.name for sid, sc in self.scenes.items()}
        self.device_by_addr = {
            d.physical_address: d
            for area in self.project.topology.areas for line in area.lines
            for d in line.devices if d.physical_address
        }

    def _resolve(self, function_ga: str):
        m = _ADDR_RE.match(function_ga or "")
        if m:
            return self.ga_by_address.get(m.group(1))
        from .belegungsplan_service import _lookup_ga_by_function_ga
        return _lookup_ga_by_function_ga(function_ga or "", self.ga_by_designation)

    def _scenes_by_key(self, be) -> dict[tuple, str]:
        """(Taste, Seite, Variante) -> Name der Szene, die die Taste aufruft
        (SensorFunktion.scene_id, geplante Projekte)."""
        from .bedienelement_layout import parse_button
        sf_scene = {sf.id: (self.scene_names.get(sf.scene_id, sf.label), sf.scene_id)
                    for sf in be.funktionen if sf.scene_id}
        result = {}
        for fa in be.function_assignments:
            name = sf_scene.get(fa.sf_id)
            parsed = parse_button(fa.button_channel) if name else None
            if parsed:
                key = parsed[0]
                result[(key.number, key.side, key.variant)] = name
        return result

    def scene_description(self, scene, call_ga, room_name: str) -> str:
        """Kurzbeschreibung einer Szene für den Bauherrn: die erfassten
        Aktionen mit Wert ("Licht 30 % · Storen zu"); sonst, worauf die
        Szene wirkt, aus dem Gewerk ihrer Szenen-GA ("stellt das Licht ein")."""
        own = {getattr(call_ga, "address", ""), _clean(getattr(call_ga, "designation", "") or "")}
        parts = []
        for action in (scene.actions if scene else []):
            if action.ga_address in own or _clean(action.group_address) in own:
                continue
            if not action.value or action.value.lower() == "status":
                continue
            ga = (self.ga_by_address.get(action.ga_address)
                  or self._resolve(action.group_address))
            what = object_label(ga or action.group_address, self.catalog, room_name)
            parts.append(f"{what} {action.value}".strip())
        if parts:
            return " · ".join(dict.fromkeys(parts))
        code = getattr(call_ga, "gewerk_code", "") if call_ga is not None else ""
        gewerk = self.catalog.get(code) if (code and self.catalog) else None
        word = {"licht": "das Licht", "licht_color": "das Licht", "jalousie": "die Storen",
                "heizung": "die Heizung"}.get(gewerk.category if gewerk else "", "")
        return f"stellt {word} im Raum ein" if word else ""

    @staticmethod
    def _status_leds(rows) -> set[int]:
        """Tasten mit Rückmeldung "Status N" (geplante Projekte)."""
        leds = set()
        for row in rows:
            m = re.match(r"^Status\s*(\d+)$", (row.name or "").strip()) if row.key is None else None
            if m:
                leds.add(int(m.group(1)))
        return leds

    # Tasten eines Bedienelements
    def key_lines(self, be, room_name: str) -> list[_KeyLine]:
        rows = group_assignments(be.function_assignments, self._resolve)
        device = self.device_by_addr.get(be.participant_number or "")
        cfg = parse_button_configuration(device.button_configuration if device else "")
        by_key: dict[tuple, _KeyLine] = {}
        extras: dict[tuple, list[str]] = defaultdict(list)
        scenes = self._scenes_by_key(be)
        status_leds = self._status_leds(rows)
        for row in rows:
            if row.key is None or not row.gas:
                continue
            label = object_label(row.gas[0], self.catalog, room_name)
            scene_name, scene_id = scenes.get((row.key.number, row.key.side, row.key.variant),
                                              ("", ""))
            scene_text = ""
            if scene_name:
                label = f"Szene «{scene_name}»"
                scene_text = self.scene_description(self.scenes.get(scene_id), row.gas[0],
                                                    room_name)
            base = (row.key.number, row.key.side)
            if row.key.variant:
                # langer Tastendruck / Doppelklick als eigene Funktion
                if row.key.variant == "lang":
                    extras[base].append(f"lang drücken: {label}")
                    extras[(base, "label")].append(label)
                else:
                    extras[base].append(f"Doppelklick: {label}")
                continue
            params = cfg.params(row.key)
            if params and params.function:
                short, how = describe_from_params(params, row.key.side)
                led = led_text(params)
            else:
                short, how = describe_from_dpt(row.gas)
                led = ("Leuchtanzeige: zeigt den Zustand"
                       if row.led_gas or row.key.number in status_leds else "")
            short, how = adapt_to_target(short, how, row.gas, label,
                                         params.function if params else "")
            if params and params.function.lower() == "wert":
                short, how = name_scene_values(params, row.gas[0], short, how)
            if label.startswith("Szene"):
                # "Ein" sagt bei einer Szene nichts
                how = ["drücken: Szene abrufen"] + [h for h in how if h.startswith("lang")]
                short = ""
            by_key[base] = _KeyLine(row.key, label, short, how, led,
                                    scene_text if scene_name else "")
        for base, more in extras.items():
            line = by_key.get(base)
            if line is None or len(base) == 2 and base[1] == "label":
                continue
            for text in more:
                if text.endswith(f": {line.label}"):
                    kind = text.split(":")[0]
                    if any(h.startswith(kind) for h in line.how):
                        continue   # aus den Parametern schon besser beschrieben
                    text = text.replace(f": {line.label}", ": ebenfalls " + line.label)
                kind = text.split(":")[0]
                # aus den Parametern schon beschrieben -> nur Ziel ergänzen
                line.how = [h for h in line.how if not h.startswith(kind)] + [text]
        return sorted(by_key.values(), key=lambda kl: kl.key.sort_key())

    @staticmethod
    def plan(lines: list[_KeyLine]) -> list[dict]:
        by_number: dict[int, dict[str, tuple[str, str]]] = {}
        for kl in lines:
            title, _, rest = kl.label.partition(" – ")
            # "Musik Wohnen – Lautstärke": Ort oben, Funktion + Bedienung darunter
            detail = " · ".join(p for p in (rest, kl.short) if p)
            by_number.setdefault(kl.key.number, {})[kl.key.side] = (title, detail)
        plan = []
        for number in sorted(by_number):
            sides = by_number[number]
            if set(sides) <= {""}:
                cells = [sides.get("", ("", ""))]
            else:
                cells = [sides.get("links", ("", "")), sides.get("rechts", ("", ""))]
            plan.append({"number": number, "cells": cells})
        return plan

    # ── Aufbau ──
    def build(self, pdf, custom_intro: str = "") -> None:
        project = self.project
        imported = project.topology.is_imported
        floor_by_room, zone_by_room = {}, {}
        for building in project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name
                            # Zone nur, wenn sie mehr sagt als das Stockwerk
                            if apt.name not in (floor.name, floor.short_code):
                                zone_by_room[room.id] = apt.name

        from .channel_count_service import count_controlled_elements
        try:
            counts = count_controlled_elements(project).by_room
        except Exception:
            logger.exception("Gewerke je Raum nicht ermittelbar")
            counts = {}

        # Sensoren aus der Topologie ohne Bedienelement (z.B. nach Import)
        known = {be.participant_number for r in project.all_rooms
                 for be in r.bedienelemente if be.participant_number}
        extra_sensors: dict[str, list] = defaultdict(list)
        for d in self.device_by_addr.values():
            if d.device_type == "sensor" and d.room_id and d.physical_address not in known:
                extra_sensors[d.room_id].append(d)

        entries = []
        central: list[tuple[str, str, str]] = []
        uses = defaultdict(bool)
        for room in sorted_rooms(project.areal):
            shown = [be for be in room.bedienelemente if be.is_shown(imported)]
            operable = [be for be in shown if be.is_operable and be.function_assignments]
            sensors = [be for be in shown if not be.is_operable]
            heating = any(
                (self.catalog.get(code).category if self.catalog.get(code) else "") in ("heizung", "lueftung")
                for code in (counts.get(room.id) or {})
            ) if self.catalog else False
            cards = []
            for be in operable:
                lines = self.key_lines(be, room.name)
                if not lines:
                    continue
                cards.append((be, lines))
                for kl in lines:
                    text = " ".join(kl.how).lower()
                    uses["lang"] |= "lang drücken" in text
                    uses["jalousie"] |= "stopp / lamellen" in text
                    uses["dimmen"] |= "heller" in text or "dimmen" in text
                    uses["doppel"] |= "doppelklick" in text
                    uses["led"] |= bool(kl.led)
                    first = self._first_ga(be, kl.key)
                    if first is not None and first.main_group == 0:
                        central.append((kl.label, room.name, f"{_friendly_type(be)}, Taste {kl.key.label()}"))
            device = [self.device_by_addr.get(be.participant_number or "") for be, _ in cards]
            uses["nacht"] |= any(d and "nachtabsenkung" in d.button_configuration.lower()
                                 or (d and any("nachtabsenkung" in (c.name or "").lower()
                                               for c in d.communication_objects))
                                 for d in device)
            specials = [sensor_sentence(be.element_type, be.product_name) for be in sensors]
            specials += [sensor_sentence(d.product or "", d.product_name) for d in extra_sensors.get(room.id, [])]
            if heating and not any("thermostat" in (be.element_type or "").lower() for be, _ in cards):
                specials.append("Heizung: Die Raumtemperatur wird automatisch geregelt.")
            specials = list(dict.fromkeys(specials))
            if cards or specials:
                entries.append((room, cards, specials))

        self._intro(pdf, entries, floor_by_room, zone_by_room, custom_intro)
        self._general(pdf, uses, central)

        current_floor = None
        for room, cards, specials in entries:
            floor = floor_by_room.get(room.id, "") or "Ohne Stockwerk"
            if floor != current_floor:
                pdf.add_page_break()
                pdf.add_heading(floor, level=2)
                current_floor = floor
            else:
                # Raumtitel nie allein am Seitenende: Platz für den ersten Taster
                first = len(cards[0][1]) if cards else 0
                pdf.add_conditional_break(min_height=min(170 + 34 * first, 560) if cards else 120)
            pdf.add_anchor(f"room:{room.id}")
            pdf.add_heading(self._room_label(room, zone_by_room), level=3)
            for i, (be, lines) in enumerate(cards):
                device = self.device_by_addr.get(be.participant_number or "")
                location = (device.installation_location or "").strip() if device else ""
                title = _friendly_type(be)
                if location and room.name.lower() not in location.lower():
                    title += f" – {location}"
                if i:
                    pdf.add_conditional_break(min_height=min(120 + 34 * len(lines), 520))
                pdf.add_card_header(
                    title,
                    f"Gerätenummer {be.participant_number}" if be.participant_number else "",
                    bookmark=f"{room.name}: {title}",
                )
                pdf.add_button_plan(self.plan(lines))
                # Gleiche Leuchtanzeige bei allen Tasten: einmal unter der Tabelle
                leds = {kl.led for kl in lines}
                common_led = leds.pop() if len(leds) == 1 else ""
                pdf.add_table(
                    ["Taste", "Funktion", "Bedienung"],
                    [[kl.key.label(), kl.label,
                      ("\n".join(kl.how), "" if common_led else kl.led)] for kl in lines],
                    col_widths=[0.13, 0.32, 0.55],
                )
                if common_led:
                    label, _, text = common_led.partition(": ")
                    pdf.add_note(f"{label}:", f"{text} (alle Tasten)")
                scene_lines = [f"{kl.label.removeprefix('Szene ')}: {kl.scene_text}"
                               for kl in lines if kl.scene_text]
                if scene_lines:
                    pdf.add_heading("Szenen", level=4)
                    pdf.add_paragraph("\n".join(f"• {line}" for line in scene_lines))
                thermostat = sorted(n for n, philo in parse_button_configuration(
                    device.button_configuration if device else "").philosophy.items()
                    if "thermostat" in philo.lower())
                if thermostat:
                    keys = " und ".join(str(n) for n in thermostat)
                    pdf.add_note("Raumthermostat:",
                                 f"Taste {keys}: gewünschte Raumtemperatur höher oder "
                                 "tiefer einstellen.")
            if specials:
                pdf.add_conditional_break(min_height=40 + 14 * len(specials))
                pdf.add_heading("Automatisch", level=4)
                pdf.add_paragraph("\n".join(f"• {sp}" for sp in specials))
            pdf.add_separator()

    def _first_ga(self, be, key: ButtonKey):
        for fa in be.function_assignments:
            parsed = group_assignments([fa], self._resolve)
            if parsed and parsed[0].key and (parsed[0].key.number, parsed[0].key.side,
                                             parsed[0].key.variant) == (key.number, key.side, ""):
                ga = parsed[0].gas[0] if parsed[0].gas else None
                return ga if hasattr(ga, "main_group") else None
        return None

    @staticmethod
    def _room_label(room, zone_by_room) -> str:
        zone = zone_by_room.get(room.id, "")
        name = f"{room.name}" if room.name else room.number
        return " · ".join(p for p in (zone, name) if p)

    def _intro(self, pdf, entries, floor_by_room, zone_by_room, custom_intro):
        from ..utils.pdf_generator import PageRef
        project = self.project
        client = getattr(project, "client_profile", None)
        pdf.add_heading("Bedienungsanleitung", level=1)
        who = client.name if client and client.name else ""
        obj = client.object_address if client and client.object_address else ""
        pdf.add_paragraph(" | ".join(p for p in (
            f"Für: {who}" if who else "", obj, f"Projekt: {project.name}",
            f"Stand: {datetime.now().strftime('%d.%m.%Y')}") if p))
        pdf.add_separator()
        pdf.add_paragraph(custom_intro or (
            "Diese Anleitung zeigt Ihnen Raum für Raum, was die Taster in Ihrem Haus "
            "bewirken und wie Sie sie bedienen. Jeder Taster ist so abgebildet, wie er "
            "an der Wand aussieht."))
        pdf.add_heading("Inhalt", level=2)
        rows = [["Allgemeines", "So bedienen Sie Ihre Taster, zentrale Funktionen, bei Störungen, Kontakt",
                 PageRef("general")]]
        for room, cards, _specials in entries:
            floor = floor_by_room.get(room.id, "")
            n = len(cards)
            what = f"{n} Taster" if n else "nur automatische Funktionen"
            rows.append([floor, self._room_label(room, zone_by_room) + f"  ({what})",
                         PageRef(f"room:{room.id}")])
        pdf.add_table(["Stockwerk", "Raum", "Seite"], rows,
                      col_widths=[0.22, 0.68, 0.10], align=["left", "left", "right"])

    def _general(self, pdf, uses, central):
        pdf.add_page_break()
        pdf.add_anchor("general")
        pdf.add_heading("Allgemeines", level=2)
        pdf.add_heading("Ihr Haus in Kürze", level=3)
        pdf.add_paragraph(
            "Ihr Haus ist mit KNX ausgestattet. Taster, Präsenzmelder und Sensoren "
            "geben ihre Befehle über eine eigene Steuerleitung an Schaltgeräte im "
            "Verteiler weiter, die Licht, Storen und Heizung steuern. Deshalb kann ein "
            "Taster auch Leuchten in einem anderen Raum schalten, und Funktionen lassen "
            "sich später ohne neue Leitungen ändern.")
        pdf.add_heading("So bedienen Sie Ihre Taster", level=3)
        tips = ["Kurz drücken: Antippen, z.B. Licht ein oder aus."]
        if uses["lang"] or uses["dimmen"] or uses["jalousie"]:
            tips.append("Lang drücken: Taste gedrückt halten (etwa eine Sekunde oder länger).")
        if uses["dimmen"]:
            tips.append("Dimmen: Taste gedrückt halten, bis die gewünschte Helligkeit "
                        "erreicht ist, dann loslassen.")
        if uses["jalousie"]:
            tips.append("Storen: lang drücken fährt ganz auf oder ab; kurz drücken stoppt "
                        "die Fahrt oder verstellt die Lamellen.")
        if uses["doppel"]:
            tips.append("Doppelklick: zweimal kurz hintereinander drücken.")
        if uses["led"]:
            tips.append("Leuchtanzeigen an den Tasten zeigen, ob die Funktion eingeschaltet ist.")
        if uses["nacht"]:
            tips.append("Nachts werden die Leuchtanzeigen automatisch gedimmt.")
        pdf.add_paragraph("\n".join(f"• {tip}" for tip in tips))
        if central:
            pdf.add_heading("Zentrale Funktionen", level=3)
            pdf.add_paragraph("Diese Tasten wirken auf mehrere Räume oder das ganze Haus:")
            seen = set()
            rows = []
            for label, room, where in central:
                if (label, room) in seen:
                    continue
                seen.add((label, room))
                rows.append([label, f"{room} – {where}"])
            pdf.add_table(["Funktion", "Wo"], rows, col_widths=[0.4, 0.6])
        pdf.add_heading("Wenn etwas nicht funktioniert", level=3)
        pdf.add_paragraph("\n".join(f"• {tip}" for tip in (
            "Eine Leuchte reagiert nicht: zuerst prüfen, ob das Leuchtmittel defekt ist "
            "und ob im Sicherungskasten eine Sicherung ausgelöst hat.",
            "Mehrere Taster reagieren nicht mehr: Bitte nichts selbst verändern und uns "
            "kontaktieren – vermutlich ist die Steuerung betroffen.",
            "Storen fahren nicht: Bei Wind oder Frost sind sie zum Schutz oft gesperrt "
            "und fahren erst wieder, wenn die Gefahr vorbei ist.",
        )))
        c = self.company
        if c and (c.company_name or c.user_name):
            pdf.add_heading("Ihr Ansprechpartner", level=3)
            person = ", ".join(p for p in (c.user_name, c.role) if p)
            lines = [c.company_name, person, c.address,
                     " | ".join(p for p in (c.phone, c.email, c.website) if p)]
            pdf.add_paragraph("\n".join(line for line in lines if line))
