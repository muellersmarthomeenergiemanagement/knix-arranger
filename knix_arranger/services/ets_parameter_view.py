"""
Parameter eines Geräts aus der .knxproj, wie die ETS sie zeigt.

Die ETS speichert je Gerät nur die geänderten Parameterwerte
(ParameterInstanceRef). Was sichtbar ist, welche Kommunikationsobjekte
aktiv sind und welchen Text ein Wert hat, ergibt erst der Dynamic-Abschnitt
der Applikation (KNX-Standard): choose/when über Parameterwerte, Assign
(setzt Parameter), Parameterseiten (ParameterBlock), Trenner, Module mit
Instanzen und Repeat. Dieser Durchlauf rechnet das für ein konkretes Gerät
nach -- dieselben Seiten und Werte wie unter «Geräteparameter» im
ETS-Topologie-Report.

Nicht ausgewertet: ParameterCalculation (Skripte), Rename, DCA-Daten der
Hersteller-Apps.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable

from .knxprod_catalog_service import (
    argument_substitution, fill_text_parameter, when_matches,
)

# Höchstens so viele Durchläufe, bis die Assign-Werte feststehen
_MAX_PASSES = 4

# Parameterwert eines Moduls im Projekt: «…_MD-2_M-3_MI-1_P-2_R-2»
_MODULE_PARAMETER_RE = re.compile(r"^(?P<ap>.+?)_(?P<md>MD-\d+)_(?P<use>M-\d+)_MI-(?P<index>\d+)_(?P<rest>P-.+)$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass
class ParameterPage:
    """Eine Parameterseite («Konfiguration Tasten», «Taste 1, links»,
    «A: Szene») mit ihren sichtbaren Einträgen (Bezeichnung, Wert); ein
    Trenner hat den Wert None."""
    title: str              # Texte roh wie in der Applikation (mit Zeilenumbrüchen)
    entries: list[tuple[str, str | None]] = field(default_factory=list)
    # Reihenfolge wie in der ETS (DisplayOrder des Titelparameters bzw. der
    # Parameter); None = hinter dem Vorgänger
    order: int | None = None
    entry_orders: list[int | None] = field(default_factory=list)

    def add(self, label: str, value: str | None, order: int | None) -> None:
        self.entries.append((label, value))
        self.entry_orders.append(order)


def _display_sorted(items: list, orders: list[int | None]) -> list:
    """Stabil nach DisplayOrder; ohne Angabe gilt die des Vorgängers."""
    keyed, last = [], -1
    for i, (item, order) in enumerate(zip(items, orders)):
        if order is not None:
            last = order
        keyed.append((last, i, item))
    return [item for _o, _i, item in sorted(keyed, key=lambda k: (k[0], k[1]))]


@dataclass
class DeviceParameters:
    pages: list[ParameterPage] = field(default_factory=list)
    # Aktive KOs: (Modul-Instanz «MD-2_M-3_MI-1» oder "", ComObjectRef-Id)
    active_cos: set[tuple[str, str]] = field(default_factory=set)
    # Parameterwerte {(Instanz, ParameterRef-Id): Wert}, auch die gesetzten
    values: dict[tuple[str, str], str] = field(default_factory=dict)


class ApplicationParameters:
    """Was eine Applikation für die Auswertung je Gerät braucht. Hält nur den
    Dynamic-Abschnitt und kleine Tabellen, nicht die ganze XML."""

    def __init__(self, program: ET.Element, texts: dict[str, dict[str, str]]):
        self.ap_id = program.get("Id", "")
        self.texts = texts
        self.params: dict[str, dict] = {}
        self.param_refs: dict[str, dict] = {}
        self.enums: dict[str, dict[str, str]] = {}
        self.module_defs: dict[str, tuple[ET.Element | None, dict[str, str]]] = {}
        self.dynamic: ET.Element | None = None
        for el in program.iter():
            tag = _local(el.tag)
            if tag == "Parameter":
                self.params[el.get("Id", "")] = dict(el.attrib)
            elif tag == "ParameterRef":
                self.param_refs[el.get("Id", "")] = dict(el.attrib)
            elif tag == "ParameterType":
                values = {item.get("Value", ""): self.text(item)
                          for item in el.iter() if _local(item.tag) == "Enumeration"}
                if values:
                    self.enums[el.get("Id", "")] = values
            elif tag == "ModuleDef":
                args = {a.get("Id", ""): a.get("Name", "") for a in el.iter()
                        if _local(a.tag) == "Argument"}
                own = next((c for c in el if _local(c.tag) == "Dynamic"), None)
                self.module_defs[el.get("Id", "")] = (own, args)
        self.dynamic = next((c for c in program if _local(c.tag) == "Dynamic"), None)

    # -- Texte und Werte -----------------------------------------------------

    def text(self, el, attr: str = "Text") -> str:
        attrs = el if isinstance(el, dict) else el.attrib
        return (self.texts.get(attrs.get("Id", ""), {}).get(attr)
                or attrs.get(attr) or "")

    def parameter_id(self, ref_id: str) -> str:
        return self.param_refs.get(ref_id, {}).get("RefId", ref_id)

    def default(self, ref_id: str) -> str:
        ref = self.param_refs.get(ref_id, {})
        if ref.get("Value") is not None:
            return ref["Value"]
        return self.params.get(ref.get("RefId", ""), {}).get("Value", "")

    def label(self, ref_id: str) -> str:
        ref = self.param_refs.get(ref_id, {})
        return self.text(ref) or self.text(self.params.get(ref.get("RefId", ""), {}))

    def display_order(self, ref_id: str) -> int | None:
        try:
            return int(self.param_refs.get(ref_id, {}).get("DisplayOrder", ""))
        except ValueError:
            return None

    def hidden(self, ref_id: str) -> bool:
        ref = self.param_refs.get(ref_id, {})
        access = ref.get("Access") or self.params.get(ref.get("RefId", ""), {}).get("Access")
        return access == "None"

    def display(self, ref_id: str, value: str) -> str:
        """Wert wie in der ETS: Text des Aufzählungswerts, sonst die Zahl
        bzw. der Text, mit Einheit (SuffixText)."""
        ref = self.param_refs.get(ref_id, {})
        param = self.params.get(ref.get("RefId", ""), {})
        enum = self.enums.get(param.get("ParameterType", ""))
        if enum and value in enum:
            return enum[value]
        suffix = self.text(ref, "SuffixText") or self.text(param, "SuffixText")
        return f"{value} {suffix}" if suffix else value

    # -- Gerät ---------------------------------------------------------------

    def stored_values(self, instance_refs: dict[str, str]) -> dict[tuple[str, str], str]:
        """ParameterInstanceRef {RefId: Wert} -> {(Instanz, ParameterRef-Id): Wert}.
        Die ETS führt den Wert je ParameterRef: Feller «Bedienphilosophie
        Taste 1» hat je Tastenanzahl eine eigene Ref, gezeigt wird die der
        aktuellen Anzahl (mit ihrem eigenen Wert, sonst der Vorgabe)."""
        values = {}
        for ref_id, value in instance_refs.items():
            module = _MODULE_PARAMETER_RE.match(ref_id)
            if module:
                instance = f"{module['md']}_{module['use']}_MI-{module['index']}"
                ref_id = f"{module['ap']}_{module['md']}_{module['rest']}"
            else:
                instance = ""
            values[(instance, ref_id)] = value
        return values

    def evaluate(self, instance_refs: dict[str, str],
                 module_arguments: Callable[[str, str, int], dict[str, str]] | None = None,
                 ) -> DeviceParameters:
        """Seiten, aktive KOs und Werte eines Geräts. module_arguments(md,
        Verwendung, Instanz) liefert die Argumentwerte {Argument-Id: Wert}."""
        stored = self.stored_values(instance_refs)
        assigned: dict[tuple[str, str], str] = {}
        result = DeviceParameters()
        for _ in range(_MAX_PASSES):
            before = dict(assigned)
            result = _Walk(self, stored, assigned, module_arguments).run()
            if assigned == before:
                break
        return result


class _Walk:
    def __init__(self, app: ApplicationParameters, stored: dict, assigned: dict,
                 module_arguments):
        self.app = app
        self.stored = stored
        self.assigned = assigned
        self.module_arguments = module_arguments
        self.result = DeviceParameters()
        self.instance_count: dict[str, int] = {}

    def value(self, scope: str, ref_id: str) -> str:
        if "_MD-" not in ref_id:
            scope = ""          # Parameter der Applikation, auch im Modul
        key = (scope, ref_id)
        if key in self.assigned:
            return self.assigned[key]
        if key in self.stored:
            return self.stored[key]
        # Assign auf eine andere Ref desselben Parameters
        parameter = (scope, self.app.parameter_id(ref_id))
        if parameter in self.assigned:
            return self.assigned[parameter]
        return self.app.default(ref_id)

    def run(self) -> DeviceParameters:
        if self.app.dynamic is not None:
            self.walk(self.app.dynamic, "", None, None, "", False)
        pages = self.result.pages
        for page in pages:
            page.entries = _display_sorted(page.entries, page.entry_orders)
        self.result.pages = _display_sorted(pages, [p.order for p in pages])
        values = dict(self.stored)
        values.update(self.assigned)
        self.result.values = values
        return self.result

    def _title(self, el: ET.Element, scope: str, subst) -> str:
        text = ""
        if el.get("ParamRefId"):
            text = self.app.label(el.get("ParamRefId"))
        text = text or self.app.text(el)
        if subst:
            text = subst(text)
        if el.get("TextParameterRefId"):
            text = fill_text_parameter(text, self.value(scope, el.get("TextParameterRefId")))
        return text.strip()

    def walk(self, el: ET.Element, scope: str, subst, page: ParameterPage | None,
             channel: str, hidden: bool) -> None:
        tag = _local(el.tag)
        if tag == "ParameterBlock":
            block_hidden = hidden or el.get("Access") == "None" or (
                bool(el.get("ParamRefId")) and self.app.hidden(el.get("ParamRefId")))
            title = self._title(el, scope, subst)
            if channel and title:
                # wie im Report: «Ausgang 1 > Ausgang 1: Funktionsfreigabe»
                title = f"{channel} > {title}"
            if (el.get("Inline") == "true" or not title) and page is not None:
                new_page = page         # ohne Titel («Leerseite») keine eigene Seite
            else:
                new_page = ParameterPage(title, order=self.app.display_order(
                    el.get("ParamRefId", "")))
                if not block_hidden and title:
                    self.result.pages.append(new_page)
            for child in el:
                self.walk(child, scope, subst, new_page, channel, block_hidden)
            return
        if tag == "Channel":
            text = self._title(el, scope, subst)
            for child in el:
                self.walk(child, scope, subst, page, text, hidden)
            return
        if tag == "ParameterSeparator":
            if page is not None and not hidden and el.get("Access") != "None":
                text = self._title(el, scope, subst)
                if text:
                    page.add(text, None, None)
            return
        if tag == "ParameterRefRef":
            ref_id = el.get("RefId", "")
            if page is not None and not hidden and not self.app.hidden(ref_id):
                label = self.app.label(ref_id)
                if subst:
                    label = subst(label)
                page.add(label.strip(),
                         self.app.display(ref_id, self.value(scope, ref_id)),
                         self.app.display_order(ref_id))
            return
        if tag == "ComObjectRefRef":
            self.result.active_cos.add((scope, el.get("RefId", "")))
            return
        if tag == "choose":
            value = self.value(scope, el.get("ParamRefId", ""))
            whens = [c for c in el if _local(c.tag) == "when"]
            active = [w for w in whens if w.get("test") is not None
                      and when_matches(w.get("test"), value)]
            if not active:
                active = [w for w in whens if w.get("default") == "true"]
            for branch in active:
                for child in branch:
                    self.walk(child, scope, subst, page, channel, hidden)
            return
        if tag == "Assign":
            target_ref = el.get("TargetParamRefRef", "")
            if "_MD-" not in target_ref:
                scope = ""
            if el.get("SourceParamRefRef"):
                value = self.value(scope, el.get("SourceParamRefRef"))
            elif el.get("Value") is not None:
                value = el.get("Value")
            else:
                return
            self.assigned[(scope, target_ref)] = value
            self.assigned[(scope, self.app.parameter_id(target_ref))] = value
            return
        if tag == "Module":
            self._module(el, page, channel, hidden)
            return
        if tag == "Repeat":
            try:
                count = int(el.get("Count") or self.value(scope, el.get("ParameterRefId", "")) or 0)
            except ValueError:
                count = 0
            for _ in range(count):
                for child in el:
                    self.walk(child, scope, subst, page, channel, hidden)
            return
        if tag == "Rename":
            return
        for child in el:
            self.walk(child, scope, subst, page, channel, hidden)

    def _module(self, el: ET.Element, page, channel: str, hidden: bool) -> None:
        own, args = self.app.module_defs.get(el.get("RefId", ""), (None, {}))
        module_id = el.get("Id", "")
        index = self.instance_count.get(module_id, 0) + 1
        self.instance_count[module_id] = index
        md = el.get("RefId", "").rsplit("_", 1)[-1]          # «MD-2»
        use = module_id.rsplit("_", 1)[-1]                     # «M-3»
        values = self.module_arguments(md, use, index) if self.module_arguments else {}
        names = {args.get(arg_id, ""): value for arg_id, value in values.items()}
        if own is not None:
            self.walk(own, f"{md}_{use}_MI-{index}", argument_substitution(names),
                      page, channel, hidden)


# -- Auswertungen wie aus dem ETS-Report (XlsxImportService) ----------------

def _clean(text: str) -> str:
    # Zeilenumbrüche im ETS-Text fallen weg wie im Report
    # («zu\n(Szene 1...64)» -> «zu(Szene 1...64)»)
    return " ".join((text or "").replace("\r", "").replace("\n", "").split())


def button_configuration(pages: list[ParameterPage]) -> str:
    """Tastenbelegung als Text wie XlsxImportService.extract_button_configuration:
    Seite «Konfiguration Tasten» und die folgenden Seiten «Taste …»."""
    from .xlsx_import_service import XlsxImportService as X
    lines: list[str] = []
    in_section = False
    for page in pages:
        title = _clean(page.title)
        if title == X._BUTTON_CONFIG_SECTION_MARKER:
            in_section, prefix = True, ""
        elif in_section and X._BUTTON_SUBSECTION_RE.match(title):
            if lines:
                lines.append("")
            lines.append(f"{title}:")
            prefix = "  "
        else:
            in_section = False
            continue
        for label, value in page.entries:
            if value is not None and _clean(label).rstrip(":").strip():
                # Werte wie im Report: innere Leerzeichen bleiben
                lines.append(f"{prefix}{_clean(label).rstrip(':').strip()}: {value.strip()}")
    return "\n".join(lines).strip()


def scene_values(pages: list[ParameterPage]) -> list:
    """Szenen-Schaltwerte je Kanal wie XlsxImportService.extract_scene_values
    (ABB «A: Szene», Hager «Ausgang N > …»)."""
    from ..models.topology import SceneValueEntry
    from .xlsx_import_service import XlsxImportService as X
    entries = []
    hager_channel = None
    for page in pages:
        title = _clean(page.title)
        abb = X._ABB_SCENE_CHANNEL_RE.match(title)
        hager = X._HAGER_CHANNEL_HEADER_RE.match(title)
        if hager:
            hager_channel = hager.group(1)
        pending = None
        for label, value in page.entries:
            label, value = _clean(label), _clean(value or "")
            if abb:
                if X._ABB_SCENE_ASSIGN_RE.match(label):
                    number = X._ABB_SCENE_NUMBER_RE.match(value)
                    pending = int(number.group(1)) if number else None
                    continue
                if X._ABB_STANDARDWERT_RE.match(label) and pending:
                    entries.append(SceneValueEntry(channel=abb.group(1), scene_number=pending,
                                                   value=value))
                    pending = None
                    continue
            if hager_channel:
                state = X._HAGER_SCENE_STATE_RE.match(label)
                if state:
                    entries.append(SceneValueEntry(channel=hager_channel,
                                                   scene_number=int(state.group(1)), value=value))
    return entries


def scene_triggers(pages: list[ParameterPage]) -> list:
    """Szenen-Auslöser (Taste -> Szene) wie XlsxImportService.extract_scene_triggers
    (Feller: «1Byte Wert (0..255)», «Langer Tastendruck …: aktiv»)."""
    from ..models.topology import SceneTriggerEntry
    from .xlsx_import_service import XlsxImportService as X
    entries = []
    in_section = False
    for page in pages:
        title = _clean(page.title)
        if title == X._BUTTON_CONFIG_SECTION_MARKER:
            in_section = True
            continue
        if not (in_section and X._BUTTON_SUBSECTION_RE.match(title)):
            in_section = False
            continue
        long_press = False
        for label, value in page.entries:
            label = _clean(label).rstrip(":").strip()
            if value is None:
                continue
            if X._LANGER_TASTENDRUCK_RE.match(label):
                long_press = _clean(value).lower() == "aktiv"
                continue
            if not X._BYTE_VALUE_LABEL_RE.match(label):
                continue
            try:
                byte_value = int(_clean(value))
            except ValueError:
                continue
            button = f"{title} (langer Tastendruck)" if long_press else title
            entries.append(SceneTriggerEntry(button=button, scene_number=byte_value + 1))
    return entries
