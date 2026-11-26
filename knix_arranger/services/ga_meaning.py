"""
Bedeutung ergänzen (FA-3105b): GAs, die aus den Geräten gelesen wurden
(Teilnehmer suchen, FA-3108b), bekommen Gewerk, Funktion, Element und einen
Namen nach dem Namensschema – abgeleitet aus den KOs, an denen sie hängen
(Herstellertexte, Produkt, DPT), wie bei importierten GAs (FA-531a).

Ohne Räume steht an der Stelle des Raums die physikalische Adresse des
Geräts: «J_1.1.4_03 AUF/AB (Motor C)». Sind die Räume bekannt (FA-3105c),
ersetzt der Raum die Adresse.

Nur GAs mit vorläufigem Namen aus «Ins Projekt übernehmen» («… (1.1.5)»)
oder ohne Namen werden benannt; Namen aus der ETS bleiben. Gespeichert wird
in der Korrekturschicht (Name, Gewerk), also jederzeit überschreibbar und
als Aufgabe in der ETS-Arbeitsliste.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .device_scan import clean_dpt

# Gewerk nach Stichworten in Produkt- und KO-Text, die erste passende Zeile
# gilt (Reihenfolge: speziell vor allgemein)
_GEWERK_KEYWORDS: list[tuple[str, str]] = [
    ("LDA", r"\bdali\b"),
    ("MM", r"revox|audio|multiroom|sonos|radio"),
    ("G", r"garage|\btor\b|hörmann|hoermann"),
    ("WP", r"wärmepumpe|waermepumpe|vitogate|viessmann|wärmeerzeuger|heat pump"),
    ("W", r"wetter|weather|\bwind\b|regen|\brain\b|dämmerung|daemmerung"),
    ("A", r"leck|leak|leckage|wasseralarm|rauch|smoke"),
    ("FK", r"fensterkontakt|window contact|fenster.*kontakt"),
    ("M", r"markise|awning"),
    ("R", r"rollladen|rolladen|roller shutter"),
    ("J", r"jalousie|storen|\bblind|shutter|lamell|behang|\bjax\b|sonnenschutz|beschattung|"
          r"griesser"),
    ("H", r"stellantrieb|thermal|heiz|heating|ventil|valve|stellwert|stellgr|\bpwm\b|"
          r"sollwert|setpoint|thermostat|\brth\b|raumtemperaturregler|kühlen|kuehlen|"
          r"temperatur|temperature"),
    ("TF", r"feuchte|humidity|\bco2\b|luftqualit"),
    ("LD", r"dimm|\bdim\b|helligkeitswert|dimming"),
    ("E", r"zähler|zaehler|energie|energy|leistung|\bpower\b|meter"),
    ("L", r"licht|light|lamp|leuchte|präsenz|praesenz|presence|bewegung|motion|"
          r"pirios|pixa|schalt|switch|ausgang|output"),
]

# Gewerke, die das Gerät selbst festlegt: das Produkt gilt vor dem KO-Text
# (DALI-Gateway «G1, Dimmen» ist LDA, nicht LD; Revox «Raum 1 Ein/Aus» MM)
_PRODUCT_GEWERKE = ("LDA", "MM", "G", "WP", "W", "A", "J", "H")

# Funktion aus dem KO, wenn ko_functions nichts festlegt
_FUNCTION_KEYWORDS: list[tuple[str, str]] = [
    ("SZENE", r"szene|scene"),
    ("STELLGROESSE", r"stellwert|stellgr|\bpwm\b"),
    ("SOLL", r"sollwert|setpoint"),
    ("IST", r"temperatur|temperature|istwert"),
    ("FEUCHTE", r"feuchte|humidity"),
    ("ALARM", r"alarm|leck|leak|störung|stoerung|fehler"),
    ("SPERREN", r"sperr|disable|lock"),
]

_PROVISIONAL = re.compile(r"^(.*) \((\d+\.\d+\.\d+)\)$")


@dataclass
class Meaning:
    address: str
    gewerk: str = ""
    function: str = ""
    element: int = 0
    channel: str = ""             # Klartext: Kanal des Geräts
    device_address: str = ""
    designation: str = ""
    dpt: str = ""


@dataclass
class MeaningResult:
    named: int = 0
    gewerke: Counter = field(default_factory=Counter)
    groups_named: int = 0
    scenes: int = 0
    without_gewerk: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"{self.named} GAs benannt."]
        if self.gewerke:
            lines.append("Gewerke: " + ", ".join(
                f"{code} {count}" for code, count in self.gewerke.most_common()))
        if self.groups_named:
            lines.append(f"{self.groups_named} Haupt- und Mittelgruppen benannt.")
        if self.scenes:
            lines.append(f"{self.scenes} Szenen erkannt.")
        if self.without_gewerk:
            lines.append(f"Ohne erkennbares Gewerk: {len(self.without_gewerk)} GAs "
                         "(Gewerk «SF», bitte prüfen).")
        lines.append("Namen und Gewerke stehen in der Korrekturschicht: jederzeit "
                     "änderbar, Rückgängig möglich.")
        return "\n".join(lines)


def is_provisional(ga) -> bool:
    """Name aus «Ins Projekt übernehmen» («Ausgang A Schalten (1.1.5)») oder leer."""
    return not (ga.designation or "").strip() or bool(_PROVISIONAL.match(ga.designation))


def _text(*parts) -> str:
    return " ".join(p for p in parts if p).lower()


def gewerk_of(device, co) -> str:
    """Gewerk aus KO-Text, dann Produkt; "" ohne Treffer."""
    # mit Hersteller: Hörmann «KNX-Gateway» ist ein Tor, Viessmann Wärme
    product = _text(getattr(device, "manufacturer", ""), getattr(device, "product", ""),
                    getattr(device, "product_name", ""),
                    getattr(device, "application_program", ""))
    for code, pattern in _GEWERK_KEYWORDS:
        if code in _PRODUCT_GEWERKE and re.search(pattern, product):
            return code
    for text in (_text(co.name, co.object_function), product):
        for code, pattern in _GEWERK_KEYWORDS:
            if re.search(pattern, text):
                return code
    return ""


def _dpt_main(dpt: str) -> int:
    match = re.match(r"DPS?T-(\d+)", dpt or "")
    return int(match.group(1)) if match else 0


# Funktion nach dem DPT-Haupttyp, wenn der Text nichts sagt (WERT/RM WERT
# erwartet das Schema als 1 Byte, Messwerte heissen anders)
_FUNCTION_BY_DPT = {3: "DIM", 7: "MESSWERT", 9: "MESSWERT", 12: "MESSWERT",
                    13: "MESSWERT", 14: "MESSWERT", 17: "SZENE", 18: "SZENE",
                    20: "BETRIEBSART"}


def _function_of(co, actor_function: str, dpt: str = "") -> str:
    text = _text(co.name, co.object_function)
    main = _dpt_main(dpt or co.data_type)
    if main == 9 and re.search(r"temperatur|temperature", text) and not re.search(
            r"soll|setpoint", text):
        return "IST"
    if main in _FUNCTION_BY_DPT and main not in (3,) and not actor_function:
        return _FUNCTION_BY_DPT[main]
    # Stellgrösse eines Heizaktors als 1-Byte-Wert; als 1 Bit (schaltend)
    # heisst sie nach Schema E/A
    one_bit_size = (co.object_size or "").strip().lower() == "1 bit" or main == 1
    if re.search(r"stellgr|stellwert|\bpwm\b", text) and not one_bit_size:
        return "STELLGROESSE"
    if actor_function:
        return actor_function
    for function, pattern in _FUNCTION_KEYWORDS:
        if re.search(pattern, text):
            return function
    from .ko_links import parse_flags
    flags = parse_flags(co.flags)
    size = (co.object_size or "").strip().lower()
    one_bit = size == "1 bit" or main == 1
    if main == 3:
        return "DIM"
    if not one_bit and size and not size.startswith("1 byte") and main not in (5,):
        return "MESSWERT"            # 2 Byte und mehr: kein 1-Byte-Wert
    feedback = bool(re.search(r"status|rückmeld|rueckmeld|feedback|zustand", text)) or (
        "Ü" in flags and "S" not in flags)
    if feedback:
        return "RM" if one_bit else "RM WERT"
    return "E/A" if one_bit else "WERT"


_CHANNEL = re.compile(
    r"(kanal|ausgang|output|channel|taste|wippe|motor|raum|gruppe|zone|eingang|input)"
    r"\s*[\w]+|\bg\d+\b|\(m\d+\)", re.IGNORECASE)


def _channel(co) -> str:
    """Kanal aus dem KO-Namen: der Teil mit der Kanalbezeichnung («Ausgang A»,
    «G9» aus «G9, Status», «Kanal 1» aus «Stellgröße, Kanal 1», «Bedienung
    Storen (M1)» aus «…, Endlage»); sonst der erste Teil; ohne Namen die
    KO-Nummer. Schalten, Dimmen und Status eines Kanals = ein Element."""
    name = (co.name or "").strip()
    parts = [p.strip() for p in re.split(r"[,:;]", name) if p.strip()]
    for part in parts:
        if _CHANNEL.search(part):
            return part
    return parts[0] if parts else f"KO {co.object_number}"


def _anchors(project) -> tuple[dict[str, tuple], dict[str, list]]:
    """GA -> (Gerät, KO, Rang) des KOs, das die Bedeutung trägt: empfangendes
    Aktor-/Gateway-KO vor sendendem Sensor-KO, KO mit Text vor «KO n»; dazu
    je GA die empfangenden Aktorkanäle [(Gerät, KO)]."""
    from .device_scan import project_devices
    best: dict[str, tuple] = {}
    receivers: dict[str, list] = {}
    for device in project_devices(project):
        receiver = device.device_type in ("actor", "gateway")
        for co in device.communication_objects:
            for address in co.connected_gas:
                if receiver:
                    receivers.setdefault(address, []).append((device, co))
                rank = (0 if receiver else 1) + (2 if re.fullmatch(r"KO \d+", co.name or "")
                                                 else 0)
                if address not in best or rank < best[address][2]:
                    best[address] = (device, co, rank)
    return best, receivers


# ab so vielen Aktorkanälen ist eine GA eine Zentral- bzw. Gruppen-GA
CENTRAL_CHANNELS = 3


def propose(project, refresh=()) -> list[Meaning]:
    """Bedeutung für alle GAs mit vorläufigem Namen; `refresh`: dazu diese
    GAs neu (Herstellerdatei nachgeführt, FA-3108f)."""
    from .ets_function_plan import ko_functions
    functions = ko_functions(project)
    anchors, receivers = _anchors(project)
    refresh = set(refresh)
    gas = [ga for ga in project.group_addresses.all_addresses()
           if is_provisional(ga) or ga.address in refresh]
    # Elemente: je Gerät und Gewerk die Kanäle in der Reihenfolge ihrer KOs
    proposals: list[Meaning] = []
    channels: dict[tuple[str, str], dict[str, int]] = {}
    centrals: dict[str, int] = {}
    channel_gewerke: dict[tuple[str, str], str] = {}
    ordered = sorted(gas, key=lambda g: (anchors[g.address][0].physical_address,
                                         anchors[g.address][1].object_number)
                     if g.address in anchors else ("~", 0))
    for ga in ordered:
        anchor = anchors.get(ga.address)
        if anchor is None:
            proposals.append(Meaning(ga.address))
            continue
        device, co, _rank = anchor
        dpt = clean_dpt(ga.datapoint_type) or clean_dpt(co.data_type)
        function = _function_of(co, functions.get(ga.address, ""), dpt)
        kanaele = {(d.physical_address, _channel(c)) for d, c in receivers.get(ga.address, [])}
        if len(kanaele) >= CENTRAL_CHANNELS:
            # Zentral-/Gruppen-GA (BZ-07): Gewerk der Mehrheit, «ZE» statt Raum
            votes = Counter(gewerk_of(d, c) for d, c in receivers[ga.address])
            votes.pop("", None)
            gewerk = votes.most_common(1)[0][0] if votes else ""
            element = centrals.setdefault(gewerk or "SF", 0) + 1
            centrals[gewerk or "SF"] = element
            proposals.append(Meaning(ga.address, gewerk, function, element,
                                     f"{len(kanaele)} Kanäle", "ZE", dpt=dpt))
            continue
        channel = _channel(co)
        # ein Gewerk je Kanal: Stellwert und Status von «Ausgang A» gehören
        # zusammen (das genaueste Gewerk seiner KOs)
        gewerk = _channel_gewerk(device, channel, channel_gewerke)
        # Gewerk der Partner, wenn das eigene KO nichts verrät
        if not gewerk:
            gewerk = _partner_gewerk(project, ga.address, device)
        numbers = channels.setdefault((device.physical_address, gewerk or "SF"), {})
        element = numbers.setdefault(channel, len(numbers) + 1)
        proposals.append(Meaning(ga.address, gewerk, function, element, channel,
                                 device.physical_address, dpt=dpt))
    for meaning in proposals:
        if meaning.device_address:
            meaning.designation = designation(meaning)
    _make_unique(proposals)
    return proposals


_SPECIFICITY = {code: index for index, (code, _pattern) in enumerate(_GEWERK_KEYWORDS)}


def _channel_gewerk(device, channel: str, cache: dict) -> str:
    """Gewerk eines Kanals: das genaueste (früheste in _GEWERK_KEYWORDS)
    unter den verknüpften KOs des Kanals."""
    key = (device.physical_address, channel)
    if key not in cache:
        codes = {gewerk_of(device, co) for co in device.communication_objects
                 if co.connected_gas and _channel(co) == channel}
        codes.discard("")
        cache[key] = min(codes, key=lambda c: _SPECIFICITY.get(c, 99)) if codes else ""
    return cache[key]


def _make_unique(proposals: list[Meaning]) -> None:
    """Gleiche Namen (ein KO an mehreren GAs, z.B. Schalten über zwei
    Wege) mit einer Nummer im Klartext unterscheiden: «(Ausgang A · 2)»."""
    seen: Counter = Counter()
    for meaning in proposals:
        if not meaning.designation:
            continue
        seen[meaning.designation] += 1
        if seen[meaning.designation] > 1:
            meaning.channel = f"{meaning.channel} · {seen[meaning.designation]}"
            meaning.designation = designation(meaning)


def _partner_gewerk(project, address: str, own_device) -> str:
    from .device_scan import project_devices
    votes = Counter()
    for device in project_devices(project):
        if device is own_device:
            continue
        for co in device.communication_objects:
            if address in co.connected_gas:
                code = gewerk_of(device, co)
                if code:
                    votes[code] += 1
    return votes.most_common(1)[0][0] if votes else ""


def designation(meaning: Meaning, room: str = "") -> str:
    """Name nach dem Namensschema; ohne Raum die Geräteadresse an seiner Stelle."""
    from .naming_engine import NamingEngine
    return NamingEngine.create_designation(
        meaning.gewerk or "SF", room or meaning.device_address, meaning.element,
        meaning.function, meaning.channel)


# ── Anwenden ──────────────────────────────────────────────────────────────

_AUTO_GROUP_NAME = re.compile(r"^(Hauptgruppe \d+|Mittelgruppe \d+/\d+)?$")


def apply(project, proposals: list[Meaning]) -> MeaningResult:
    """Namen, Gewerke, Funktion und Element setzen (Korrekturschicht), Haupt-
    und Mittelgruppen mit automatischem Namen nach ihrem Gewerk benennen,
    Szenen erkennen."""
    from .ets_corrections import set_ga_field, set_gewerk
    result = MeaningResult()
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    for meaning in proposals:
        ga = by_address.get(meaning.address)
        if ga is None or not meaning.designation:
            continue
        set_ga_field(project, ga, "designation", meaning.designation)
        if meaning.dpt and meaning.dpt != ga.datapoint_type:
            # leer oder mehrdeutig («DPT-1 DPST-1-3») aus «Ins Projekt übernehmen»
            set_ga_field(project, ga, "datapoint_type", meaning.dpt)
        code = meaning.gewerk or "SF"
        set_gewerk(project, [ga.address], code)
        ga.function_name = meaning.function
        ga.element_number = meaning.element
        result.named += 1
        result.gewerke[code] += 1
        if not meaning.gewerk:
            result.without_gewerk.append(ga.address)
    result.groups_named = _name_groups(project)
    result.scenes = _detect_scenes(project)
    return result


def _name_groups(project) -> int:
    """Haupt- und Mittelgruppen mit automatischem Namen nach dem häufigsten
    Gewerk ihrer GAs benennen («Jalousie», «Licht dimmbar DALI»)."""
    catalog = project.gewerk_catalog
    named = 0

    def label(gas, strict: bool = False) -> str:
        """Häufigstes Gewerk; «u.a.», wenn es nicht die Mehrheit hat. strict
        (Hauptgruppen, oft Stockwerke): nur bei klarer Mehrheit, sonst nichts."""
        codes = Counter(ga.gewerk_code for ga in gas if ga.gewerk_code)
        if not codes:
            return ""
        code, count = codes.most_common(1)[0]
        gewerk = catalog.get(code) if hasattr(catalog, "get") else None
        # kurz: «Alarm-Magnetkontakte» statt «… (Sammelalarme/Alarmanlage)»
        name = (getattr(gewerk, "name", "") or code).split(" (")[0]
        share = count / sum(codes.values())
        if strict:
            return name if share >= 0.8 else ""
        return name if share > 0.5 else f"{name} u.a."

    for hg in project.group_addresses.main_groups:
        all_gas = []
        for mg in hg.middle_groups:
            all_gas.extend(mg.group_addresses)
            if _AUTO_GROUP_NAME.match(mg.name or ""):
                text = label(mg.group_addresses)
                if text and text != mg.name:
                    mg.name = text
                    named += 1
        if _AUTO_GROUP_NAME.match(hg.name or ""):
            text = label(all_gas, strict=True)
            if text and text != hg.name:
                hg.name = text
                named += 1
    return named


def _detect_scenes(project) -> int:
    from .scene_detection_service import detect_scenes
    added = detect_scenes(project)
    project.scenes.extend(added)
    return len(added)
