"""
ETS-Parameter zu einer KO-Zuordnung (Stufe 1 der Dynamic-Auswertung).

Welche KO-Variante in der ETS aktiv ist, entscheiden die Parameter des Geräts
(Feller EDIZIOdue KO 1: «heller/dunkler, Dimmen» bei «Funktion Taste =
Dimmen», «schritt/stopp, Jalousie» bei «= Jalousie»). Die Herstellerdatei
legt das im Dynamic-Abschnitt fest; knxprod_catalog_service liest je
Variante die Bedingungen und je Applikation die Parametertexte. Hier wird
daraus die Anleitung, was in der ETS einzustellen ist, damit die von KNiX
gewählten KOs existieren.

Gezeigt werden nur Parameter, die zwischen den Varianten derselben KO-Nummer
unterscheiden: eine Bedingung, die alle Varianten teilen (Theben DM 4 T
«Art des Grundmoduls», eine Applikation für mehrere Geräte), sagt nichts über
die Zuordnung und wäre für ein anderes Gerät der Applikation sogar falsch.
Unsichtbare Parameter (auf keiner Parameterseite) erscheinen nicht.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

_OPERATOR = re.compile(r"^\s*(!=|<=|>=|<|>|=)\s*(.+)$")
_OPERATOR_TEXT = {"!=": "nicht", "<=": "höchstens", ">=": "mindestens", "<": "kleiner als",
                  ">": "grösser als", "=": ""}


@dataclass(frozen=True)
class Setting:
    block: str          # Parameterseite in der ETS, z.B. «Taste 1, links»
    label: str          # Parameter, z.B. «Funktion Taste»
    value: str          # «Dimmen»

    def text(self) -> str:
        where = f"{self.block} › " if self.block else ""
        return f"{where}{self.label}: {self.value}"


@dataclass
class DeviceSettings:
    device: object
    settings: list[Setting] = field(default_factory=list)
    # (Block, Parameter) -> verschiedene Werte, die die gewählten KOs verlangen
    conflicts: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    # Gewählte KOs ohne Angaben (Produkt nicht neu eingelesen, Module)
    unknown: int = 0


def value_text(values: dict, test: str) -> str:
    """Wert einer Bedingung im Klartext: «3» -> «Dimmen», «1 2» -> «A oder
    B», «!=0» -> «nicht 0» (bzw. dessen Text)."""
    found = _OPERATOR.match(test or "")
    if found and found.group(1) != "=":
        operator, rest = found.groups()
        return f"{_OPERATOR_TEXT[operator]} {values.get(rest.strip(), rest.strip())}".strip()
    parts = (test or "").split()
    return " oder ".join(values.get(part, part) for part in parts) or test


def _settings_of(variant: dict, parameters: dict) -> dict[tuple[str, str], str]:
    result = {}
    for param, test in variant.get("conditions") or []:
        info = parameters.get(param)
        if not info:
            continue
        block, label, values, visible = info
        if visible and label:
            result.setdefault((block, label), value_text(values, test))
    return result


def variant_settings(variant: dict, siblings: list[dict], parameters: dict) -> list[Setting]:
    """Einstellungen, die diese Variante von den übrigen Varianten derselben
    KO-Nummer unterscheiden (siblings: alle Varianten der Nummer)."""
    own = _settings_of(variant, parameters)
    others = [_settings_of(v, parameters) for v in siblings if v is not variant]
    if not others:
        return []
    return [Setting(block, label, value) for (block, label), value in own.items()
            if any(other.get((block, label)) != value for other in others)]


def _catalog_variant(catalog_by_number: dict, co) -> tuple[dict | None, list]:
    """Katalogvariante zu einem KO des Geräts (gleiche Nummer, Name,
    Funktion, Grösse) und alle Varianten der Nummer."""
    siblings = catalog_by_number.get(co.object_number, [])
    for variant in siblings:
        if (variant.get("name", ""), variant.get("function_text", "")) == (
                co.name, co.object_function) and variant.get("object_size", "") == co.object_size:
            return variant, siblings
    return None, siblings


def settings_for(device, chosen: list, catalog) -> DeviceSettings:
    """ETS-Einstellungen für die gewählten KO-Varianten (CommunicationObjects
    des Geräts) -- gesammelt, doppelte zusammengefasst, Widersprüche (gleicher
    Parameter, verschiedene Werte) gemeldet."""
    result = DeviceSettings(device)
    if catalog is None or not chosen:
        return result
    product = catalog.find_product(device.manufacturer, device.order_number,
                                   device.product_name)
    if not product:
        result.unknown = len(chosen)
        return result
    parameters = catalog.parameters_of(product) if hasattr(catalog, "parameters_of") \
        else product.get("parameters") or {}
    by_number: dict[int, list] = {}
    for variant in product.get("com_objects") or []:
        by_number.setdefault(variant.get("number"), []).append(variant)
    values: dict[tuple[str, str], list[str]] = {}
    for co in chosen:
        variant, siblings = _catalog_variant(by_number, co)
        if variant is None:
            result.unknown += 1
            continue
        if len(siblings) > 1 and not variant.get("conditions"):
            result.unknown += 1
        for setting in variant_settings(variant, siblings, parameters):
            key = (setting.block, setting.label)
            if setting.value not in values.setdefault(key, []):
                values[key].append(setting.value)
                result.settings.append(setting)
    result.conflicts = {key: vals for key, vals in values.items() if len(vals) > 1}
    result.settings.sort(key=_setting_order)
    return result


_NUMBERS = re.compile(r"\d+")
_SIDES = {"links": 0, "left": 0, "rechts": 1, "right": 1}


def _setting_order(setting: Setting) -> tuple:
    """Wie man die ETS durchgeht: allgemeine Seiten zuerst, dann Taste/Kanal
    aufsteigend, links vor rechts."""
    block = setting.block.lower()
    numbers = tuple(int(n) for n in _NUMBERS.findall(block))
    side = next((v for k, v in _SIDES.items() if k in block), -1)
    return (bool(numbers), numbers, side, block, setting.label)


def chosen_for_sensor(device, links: list, selection: dict) -> list:
    """Varianten der gewählten KOs eines Tasters/Sensors (ga_key -> Nummer),
    je Zeile die passende wie im Dialog."""
    from .sensor_channels import display_variant, split_rocker
    by_number = _by_number(device)
    result = []
    for link in links:
        number = selection.get(link.key, -1)
        if number is not None and number >= 0 and number in by_number:
            result.append(display_variant(by_number[number], link, split_rocker(link, links)))
    return result


def chosen_for_actor(device, circuits: list, selection: dict) -> list:
    """Varianten der gewählten KOs eines Aktors ({Stromkreis: {Funktion: Nr}})."""
    from .sensor_channels import display_variant
    by_number = _by_number(device)
    result = []
    for circuit in circuits:
        chosen = selection.get(circuit.key) or {}
        for function, _ga in circuit.functions:
            number = chosen.get(function, -1)
            if number is not None and number >= 0 and number in by_number:
                link = _pseudo_link(function, circuit.gewerk_code,
                                    circuit.dpts.get(function, ""))
                result.append(display_variant(by_number[number], link))
    return result


def _by_number(device) -> dict[int, list]:
    by_number: dict[int, list] = {}
    for co in device.communication_objects:
        by_number.setdefault(co.object_number, []).append(co)
    return by_number


def _pseudo_link(function: str, gewerk_code: str, dpt: str):
    """Aktor-Funktion wie ein SensorLink, für display_variant."""
    from .ko_plausibility import is_feedback_function
    return SimpleNamespace(key=f"x|{gewerk_code}|1|{function}", channel="", function=function,
                           ga_function=function, dpt=dpt,
                           feedback=is_feedback_function(function))


def chosen_variants(project, device, actor_plan=None, sensor_rows=None) -> list:
    """Die Varianten der KOs, die die Zuordnung des Geräts (Device.co_map)
    verwendet -- je Zeile die passende Variante wie im Zuordnungsdialog."""
    from .sensor_channels import sensor_co_map, sensor_links
    if device.device_type == "sensor":
        selection = sensor_co_map(device)
        if not selection:
            return []
        return chosen_for_sensor(device, sensor_links(project, device, sensor_rows), selection)
    from .actor_channels import device_circuits
    return chosen_for_actor(device, device_circuits(project, device, actor_plan),
                            device.co_map or {})


def project_settings(project, catalog=None) -> list[DeviceSettings]:
    """ETS-Einstellungen aller Geräte mit KO-Zuordnung (für die ETS-
    Arbeitsliste); nur Geräte, für die es etwas einzustellen gibt."""
    from .product_sync import shared_catalog
    catalog = catalog if catalog is not None else shared_catalog()
    if catalog is None or project.topology.is_imported:
        return []
    result = []
    actor_plan = sensor_rows = None
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if not (device.co_map and device.communication_objects
                        and device.manufacturer and device.order_number):
                    continue
                if device.device_type == "sensor" and sensor_rows is None:
                    from .sensor_channels import sensor_plan
                    sensor_rows = sensor_plan(project)
                elif device.device_type != "sensor" and actor_plan is None:
                    from .belegungsplan_service import BelegungsplanService
                    actor_plan = BelegungsplanService().generate(project)
                found = settings_for(device, chosen_variants(project, device, actor_plan,
                                                             sensor_rows), catalog)
                if found.settings or found.conflicts:
                    result.append(found)
    return result
