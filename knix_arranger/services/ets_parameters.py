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


def _alternatives(variant: dict) -> list[list]:
    from .knxprod_catalog_service import condition_alternatives
    return condition_alternatives(variant.get("conditions") or [])


def _alt_settings(alternative: list, parameters: dict) -> dict[str, Setting]:
    """Sichtbare Einstellungen einer Alternative, je Parameter-Kennung (zwei
    Parameter können gleich heissen: MDT «Unterfunktion» für Schalten und
    für Werte senden)."""
    result = {}
    for param, test in alternative:
        info = parameters.get(param)
        if not info:
            continue
        block, label, values, visible = info
        if visible and label:
            result.setdefault(param, Setting(block, label, value_text(values, test)))
    return result


def _variant_choice(variant: dict, siblings: list[dict], parameters: dict,
                    prefer: dict | None = None) -> list[tuple[str, Setting]]:
    """Einstellungen der Variante, die sie von den übrigen Varianten derselben
    KO-Nummer unterscheiden. Bei mehreren Alternativen (dieselbe Variante in
    verschiedenen Zweigen) die, die zu den schon gewählten Einstellungen des
    Geräts passt (prefer: Parameter -> Wert), sonst die kürzeste."""
    alternatives = [_alt_settings(alt, parameters) for alt in (_alternatives(variant) or [[]])]
    others = [_alt_settings(alt, parameters)
              for sibling in siblings if sibling is not variant
              for alt in (_alternatives(sibling) or [[]])]
    if not others:
        return []
    prefer = prefer or {}

    def cost(settings: dict) -> tuple:
        conflicts = sum(1 for param, setting in settings.items()
                        if param in prefer and prefer[param] != setting.value)
        agreeing = sum(1 for param, setting in settings.items()
                       if prefer.get(param) == setting.value)
        return (conflicts, -agreeing, len(settings))
    chosen = min(alternatives, key=cost)
    return [(param, setting) for param, setting in chosen.items()
            if any(param not in other or other[param].value != setting.value
                   for other in others)]


def variant_settings(variant: dict, siblings: list[dict], parameters: dict) -> list[Setting]:
    """Einstellungen, die diese Variante von den übrigen Varianten derselben
    KO-Nummer unterscheiden (siblings: alle Varianten der Nummer)."""
    return [setting for _param, setting in _variant_choice(variant, siblings, parameters)]


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
    values: dict[str, list[str]] = {}         # Parameter -> verlangte Werte
    labels: dict[str, tuple[str, str]] = {}
    prefer: dict[str, str] = {}
    for co in chosen:
        variant, siblings = _catalog_variant(by_number, co)
        if variant is None:
            result.unknown += 1
            continue
        if len(siblings) > 1 and not variant.get("conditions"):
            result.unknown += 1
        for param, setting in _variant_choice(variant, siblings, parameters, prefer):
            prefer.setdefault(param, setting.value)
            labels[param] = (setting.block, setting.label)
            if setting.value not in values.setdefault(param, []):
                values[param].append(setting.value)
                if setting not in result.settings:
                    result.settings.append(setting)
    result.conflicts = {labels[param]: vals for param, vals in values.items() if len(vals) > 1}
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
    attach_families(device)
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


# ── Belegung je Variante (für die Variantenwahl) ──────────────────────────

# Wort im Parameterwert -> Belegung (sensor_channels.link_family)
_FAMILY_WORDS = (
    ("dimm", "dimmen"), ("jalousie", "jalousie"), ("rollladen", "jalousie"),
    ("rolladen", "jalousie"), ("storen", "jalousie"), ("shutter", "jalousie"),
    ("blind", "jalousie"), ("beschattung", "jalousie"), ("szene", "szene"),
    ("scene", "szene"), ("schalt", "schalten"), ("switch", "schalten"),
)
_DIGIT = re.compile(r"\d")
_FAMILY_CACHE: dict[tuple, dict] = {}
_FAMILY_CACHE_MAX = 64
# Steigt mit jedem Neueinlesen: Geräte berechnen ihre Belegungen dann neu
_generation = 0


def families_of(variant: dict, parameters: dict) -> frozenset:
    """Belegungen einer Katalogvariante aus ihren Bedingungen -- nur Parameter
    einer Taste bzw. eines Kanals (Nummer in Seite oder Name: «Taste 1, links
    › Funktion Taste = Dimmen»); allgemeine Seiten («Konfiguration Szenen ›
    Szenenfunktion = dezentrale Szenenspeicherung») zählen nicht."""
    found = set()
    for param, test in (pair for alt in _alternatives(variant) for pair in alt):
        info = parameters.get(param)
        if not info:
            continue
        block, label, values, visible = info
        if not visible or not (_DIGIT.search(block or "") or _DIGIT.search(label or "")):
            continue
        text = value_text(values, test).lower()
        for word, family in _FAMILY_WORDS:
            if word in text:
                found.add(family)
    return frozenset(found)


def attach_families(device, catalog=None) -> None:
    """Je KO des Geräts die Belegungen der passenden Katalogvariante als
    Attribut «families» (None = unbekannt, dann gilt der Textzusatz) --
    nur zur Laufzeit, nicht gespeichert."""
    cos = getattr(device, "communication_objects", None)
    if not cos or not (device.manufacturer and device.order_number):
        return
    if catalog is None:
        from .product_sync import shared_catalog
        catalog = shared_catalog()
    if catalog is None:
        return
    stamp = (id(catalog), _generation, id(cos), len(cos))
    if getattr(device, "_families_stamp", None) == stamp             and all(hasattr(co, "families") for co in cos):
        return
    product_key = (device.manufacturer, device.order_number, device.product_name)
    key = (id(catalog), *product_key)
    mapping = _FAMILY_CACHE.get(key)
    if mapping is None:
        product = catalog.find_product(*product_key)
        mapping = {}
        if product:
            parameters = catalog.parameters_of(product) if hasattr(catalog, "parameters_of") \
                else product.get("parameters") or {}
            if parameters:
                for variant in product.get("com_objects") or []:
                    if variant.get("conditions"):
                        mapping[(variant.get("number"), variant.get("name", ""),
                                 variant.get("function_text", ""),
                                 variant.get("object_size", ""))] = (
                            families_of(variant, parameters),
                            condition_views(variant, parameters))
        if len(_FAMILY_CACHE) >= _FAMILY_CACHE_MAX:
            _FAMILY_CACHE.clear()
        _FAMILY_CACHE[key] = mapping
    for co in cos:
        found = mapping.get((co.object_number, co.name, co.object_function, co.object_size))
        co.families, co.condition_views = found if found else (None, None)
    device._families_stamp = stamp


def condition_views(variant: dict, parameters: dict) -> list[dict]:
    """Bedingungen je Alternative, wie die ETS sie zeigt: {(Seite, Name):
    Wert} -- Feller führt «Funktion Taste» je Zweig als eigenen Parameter."""
    views = []
    for alt in _alternatives(variant):
        view = {}
        for param, test in alt:
            info = parameters.get(param)
            if info and info[1]:
                view.setdefault((info[0], info[1]), value_text(info[2], test))
        views.append(view)
    return views


def views_compatible(a, b) -> bool:
    """Können zwei KO-Varianten gleichzeitig aktiv sein? Ja, wenn je eine
    Alternative keinem Parameter einen anderen Wert gibt (unbekannt = ja).
    MDT F1: «Status für Anzeige» aus «Unterfunktion = Zustand senden» passt
    nicht zum Befehl «Schalten» aus «Unterfunktion = Schalten»."""
    va = getattr(a, "condition_views", None)
    vb = getattr(b, "condition_views", None)
    if not va or not vb:
        return True
    return any(all(x.get(key, value) == value for key, value in y.items())
               for x in va for y in vb)


def reset_family_cache() -> None:
    """Nach dem Neueinlesen der Herstellerdateien (Katalog geändert)."""
    global _generation
    _FAMILY_CACHE.clear()
    _generation += 1
