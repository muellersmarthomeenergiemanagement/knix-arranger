"""
SceneDetectionService – automatische Szenen-Erkennung aus importierten
Gruppenadressen (FA-1808).

Erkennt drei unabhängige Muster in bereits importierten .knxproj-Projekten:

1. DPT-basiert: Gruppenadressen mit Datenpunkttyp DPST-17-x ("Szenennummer")
   oder DPST-18-x ("Szenensteuerung") -- beide sind laut KNX-Datenpunktliste
   ausschliesslich fuer Szenen reserviert und werden daher ordner-unabhaengig
   vertraut. Nutzt ein Integrator einen dieser DPTs fuer etwas anderes (z.B.
   einen generischen Modus-Selektor), taucht das als Szene auf -- das ist als
   Hinweis auf eine fragwuerdige ETS-Konfiguration gewollt, nicht als Fehler
   der Erkennung; die Szene kann in der Uebersicht einfach geloescht werden.
   GroupAddress.datapoint_type traegt je nach Importweg zwei verschiedene
   Darstellungen desselben DPT: den ETS-Rohcode ("DPST-17-1") bei einem
   .knxproj-Import (knxproj_import_service.py), oder ein menschenlesbares
   Label ("Szenen Nummer", "Szeneninformation") bei einem XLSX-/GA-Report-
   Import (xlsx_import_service.py uebernimmt die Report-Spalte woertlich).
   Regel 1 erkennt beide Formen (siehe _is_scene_dpt).
2. Ordner+Stichwort: Gruppenadressen in einer Mittelgruppe, deren ETS-Name
   "Szene" enthaelt, UND deren eigene Bezeichnung ebenfalls "Szene" enthaelt
   (faengt z.B. Speicher/Abruf-Kanaele mit generischem 1-Byte-DPT, ohne die
   uebrigen Zentral-GAs im selben Ordner mitzureissen).
3. Namensmuster: "RaumN_Szene <Preset>[ LED]"-Cluster (Taster-Lichtstimmungen
   High/Middle/Low/Off je mit optionaler LED-Rueckmeldung).

Bewusst ausgeschlossen: DPST-1-17 ("Scene A/B", von ETS als DPT-Name "Szene"
angezeigt). Anders als DPT 17/18 wird dieser 1-Bit-Typ in der Praxis haeufig
fuer beliebige binaere Umschaltungen zweckentfremdet (im Testprojekt z.B. fuer
die Beschattungs-Sperrbits der Jalousien) -- ordner-unabhaengiges Vertrauen
waere hier zu fehleranfaellig. Ausserhalb eines "Szenen"-Ordners wird er daher
gar nicht erfasst; innerhalb eines "Szenen"-Ordners faengt ihn Regel 2 ab.
"""
from __future__ import annotations
import re
import logging

from ..models.project import KnxProject
from ..models.group_address import GroupAddress
from ..models.scene import Scene, SceneAction
from .scene_addressing import group_named_scenes

logger = logging.getLogger("knix_arranger.scene_detection_service")

# DPST-17-x ("Szenennummer") und DPST-18-x ("Szenensteuerung") sind laut
# KNX-Datenpunktliste ausschliesslich fuer Szenen reserviert -- beide werden
# ordner-unabhaengig vertraut. Eine fehlerhafte Zweckentfremdung durch den
# Integrator (z.B. ein Modus-Selektor mit DPST-18) soll bewusst als Szene
# sichtbar werden statt stillschweigend uebergangen zu werden.
_SCENE_DPT_PREFIXES = ("DPST-17-", "DPST-18-")

# Menschenlesbare DPT-Labels (aus XLSX-/GA-Report-Importen, siehe
# xlsx_import_service.py:1454 -- dort landet die Report-Spalte woertlich,
# nie der Rohcode). Die deutsche Plural-/Genitivform "Szenen-" grenzt
# zuverlaessig von DPT 1.017 "Szene A/B" (Singular, siehe Modul-Docstring)
# ab, ohne eine Ausschlussliste zu brauchen.
_SCENE_DPT_LABEL_MARKERS = ("szenen", "scene number", "scene control")


def _is_scene_dpt(datapoint_type: str) -> bool:
    dt = (datapoint_type or "").strip()
    if not dt:
        return False
    if dt.startswith(_SCENE_DPT_PREFIXES):
        return True
    low = dt.lower()
    return any(marker in low for marker in _SCENE_DPT_LABEL_MARKERS)


_TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")

# "Raum1_Szene High   ( Carnozet )" / "Raum2_Szene Off LED"
_ROOM_SCENE_RE = re.compile(
    r"^Raum(\d+)_Szene\s+(.+?)(\s+LED)?\s*(?:\(.*\))?\s*$", re.IGNORECASE
)

# Namen, die zwar dem "RaumN_Szene <Wort>"-Muster entsprechen, aber keine
# abrufbaren Szenen-Presets sind, sondern stufenlose Steuerbefehle (z.B. die
# gemeinsame Dimm-Schritt-GA eines Raums, "Raum1_Szene Dimm").
_NON_PRESET_NAMES = {"dimm", "dimmen"}


def detect_scenes(project: KnxProject) -> list[Scene]:
    """Ermittelt neu zu uebernehmende Szenen aus project.group_addresses.

    Gibt nur Szenen zurueck, die noch nicht in project.scenes vorhanden sind
    (Dedup ueber Scene.source_ga_addresses -- die stabile "H/M/S"-Adresse,
    NICHT GroupAddress.id, da diese bei jedem Import neu vergeben wird) --
    die Funktion selbst haengt nichts an project.scenes an, das macht der
    Aufrufer. Wiederholtes Ausfuehren, auch nach einem Re-Import, liefert
    daher keine Duplikate.
    """
    already: set[str] = {
        addr for s in project.scenes for addr in s.source_ga_addresses
    }
    processed: set[str] = set(already)
    detected: list[Scene] = []

    all_gas = project.group_addresses.all_addresses()
    reserved = _reserved_designations(project)

    detected.extend(_detect_by_dpt(all_gas, processed, reserved))
    detected.extend(_detect_by_folder(project, processed, reserved))
    detected.extend(_detect_room_clusters(project, processed))

    return detected


def _reserved_designations(project: KnxProject) -> set[str]:
    """Bezeichnungen gemeinsamer Szenenaufruf-GAs, die address_generator aus
    bereits vorhandenen (manuell angelegten) Scenes erzeugen wuerde.

    Ohne diese Sperrliste wuerde ein Klick auf "Szenen erkennen" NACH dem
    Generieren der Adressen (Schritt 7) die gemeinsame Szenenaufruf-GA als
    neue, ueberfluessige Szene anlegen -- die generierte GA hat keine
    Rueckverknuepfung zu den Scenes, die sie teilen (siehe
    address_generator._create_central_main_group). Gruppierung/Benennung
    muss mit scene_addressing.group_named_scenes() uebereinstimmen.
    """
    groups = group_named_scenes(project.scenes, project.areal)
    return {designation for designation, _scenes in groups.values()}


def _make_number(designation: str) -> int:
    m = _TRAILING_NUMBER_RE.search(designation)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def _detect_by_dpt(all_gas: list[GroupAddress], processed: set[str],
                    reserved: set[str]) -> list[Scene]:
    result = []
    for ga in all_gas:
        if ga.address in processed:
            continue
        if not _is_scene_dpt(ga.datapoint_type):
            continue
        if ga.designation in reserved:
            continue
        processed.add(ga.address)
        result.append(Scene(
            name=(ga.designation or "Szene").strip(),
            scene_number=_make_number(ga.designation or ""),
            scope="central",
            trigger="",
            actions=[SceneAction(group_address=ga.designation, value="", ga_address=ga.address)],
            is_detected=True,
            detection_kind="dpt",
            source_ga_addresses=[ga.address],
        ))
    return result


def _detect_by_folder(project: KnxProject, processed: set[str],
                       reserved: set[str]) -> list[Scene]:
    result = []
    for mg_main in project.group_addresses.main_groups:
        for mg in mg_main.middle_groups:
            if "szene" not in (mg.name or "").lower():
                continue
            for ga in mg.group_addresses:
                if ga.address in processed:
                    continue
                if "szene" not in (ga.designation or "").lower():
                    continue
                if ga.designation in reserved:
                    continue
                processed.add(ga.address)
                result.append(Scene(
                    name=" ".join((ga.designation or "Szene").split()),
                    scene_number=_make_number(ga.designation or ""),
                    scope="central",
                    trigger="",
                    actions=[SceneAction(group_address=ga.designation, value="", ga_address=ga.address)],
                    is_detected=True,
                    detection_kind="folder",
                    source_ga_addresses=[ga.address],
                ))
    return result


def _detect_room_clusters(project: KnxProject, processed: set[str]) -> list[Scene]:
    result = []
    room_by_name = {
        (r.name or "").strip().lower(): r
        for r in project.areal.all_rooms
        if r.name
    }

    for mg_main in project.group_addresses.main_groups:
        for mg in mg_main.middle_groups:
            gas_sorted = sorted(mg.group_addresses, key=lambda g: g.sub_group)
            # clusters: (raum_nr, preset_name) -> {"trigger": ga, "led": ga, "room_name": str}
            clusters: dict[tuple[str, str], dict] = {}
            last_room_by_raum_nr: dict[str, str] = {}

            for ga in gas_sorted:
                desig = (ga.designation or "").strip()
                m = _ROOM_SCENE_RE.match(desig)
                if not m:
                    continue
                raum_nr, preset_raw, led_suffix = m.group(1), m.group(2), m.group(3)
                preset_name = preset_raw.strip()
                if preset_name.lower() in _NON_PRESET_NAMES:
                    continue
                if ga.room_number:
                    last_room_by_raum_nr[raum_nr] = ga.room_number

                key = (raum_nr, preset_name.lower())
                cluster = clusters.setdefault(key, {
                    "trigger": None, "led": None,
                    "preset_name": preset_name, "raum_nr": raum_nr,
                })
                if led_suffix:
                    cluster["led"] = ga
                else:
                    cluster["trigger"] = ga

            for (raum_nr, _preset_key), cluster in clusters.items():
                members = [g for g in (cluster["trigger"], cluster["led"]) if g]
                if not members:
                    continue
                if all(g.address in processed for g in members):
                    continue
                for g in members:
                    processed.add(g.address)

                room_name = last_room_by_raum_nr.get(raum_nr, "")
                room = room_by_name.get(room_name.strip().lower()) if room_name else None

                if room:
                    scope, scope_id = "room", room.id
                    label = f"{cluster['preset_name']} ({room.name})"
                else:
                    scope, scope_id = "central", ""
                    label = (
                        f"{cluster['preset_name']} ({room_name})"
                        if room_name else cluster["preset_name"]
                    )

                actions = []
                if cluster["trigger"]:
                    actions.append(SceneAction(
                        group_address=cluster["trigger"].designation, value="1",
                        ga_address=cluster["trigger"].address,
                    ))
                if cluster["led"]:
                    actions.append(SceneAction(
                        group_address=cluster["led"].designation, value="Status",
                        ga_address=cluster["led"].address,
                    ))

                result.append(Scene(
                    name=label,
                    scene_number=0,
                    scope=scope,
                    scope_id=scope_id,
                    trigger="",
                    actions=actions,
                    is_detected=True,
                    detection_kind="pattern",
                    source_ga_addresses=[g.address for g in members],
                ))
    return result
