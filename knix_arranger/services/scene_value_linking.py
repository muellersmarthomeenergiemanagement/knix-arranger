"""
SceneValueLinkingService – verknüpft erkannte Szenen (FA-1808) mit den aus
Geräteparametern extrahierten Szenen-Schaltwerten (FA-1809, Aktor-Seite)
und Szenen-Ausloesern (FA-1810, Sensor-Seite: welche Taste sendet welche
Szenennummer).

Ablauf pro erkannter (is_detected) Szene mit bekannter Quell-GA
(source_ga_addresses, z.B. der zentrale Szenen-Recall-Kanal "0/4/1"):

1. Alle Geräte-Kanaele finden, deren eigenes Szenen-Trigger-ComObject
   (Funktion/Name enthaelt "Szene", z.B. "8-Bit-Szene"/"Szenensteuerung")
   an genau diese Quell-GA angeschlossen ist -- das sind die Kanaele, die
   auf diesen Recall-Kanal reagieren.
2. Ein zentraler Szenen-Recall-Kanal traegt oft nicht nur EINE Szene,
   sondern per Byte-Wert bis zu 64 (KNX-Konvention DPT 17/18, siehe
   scene_addressing.py) -- daher hat die von der Erkennung angelegte
   "Kanal-Szene" oft scene_number=0 (kein bestimmbarer Name/Nummer).
   Hier wird pro tatsaechlich in den Geraeteparametern konfigurierter
   Szenennummer eine EIGENE, numerierte Scene angelegt/wiederverwendet
   (sonst wuerden mehrere unabhaengige Szenen faelschlich in einer
   einzigen Aktionsliste vermischt).
3. Deren geparste Device.scene_values (siehe
   XlsxImportService.extract_scene_values) nach der passenden
   scene_number filtern; den Kanal-Namen gegen die eigenen
   communication_objects des Geraets auflösen (die tatsaechlich
   schaltende ComObject, nicht Status/Trigger) -> deren Ziel-GA ergibt
   eine SceneAction.

Nicht auflösbare Kanaele (kein passendes ComObject, keine verbundene GA)
werden übersprungen -- best effort, kein Fehler.
"""
from __future__ import annotations
import logging

from ..models.project import KnxProject

logger = logging.getLogger("knix_arranger.scene_value_linking")

# Funktions-/Namensfragmente, die ein Szenen-Trigger-ComObject ausmachen
# (Eingang, der die Szenennummer empfaengt), z.B. "8-Bit-Szene",
# "Szenensteuerung", "Szenen Nummer".
_TRIGGER_FUNCTION_KEYWORDS = ("szene",)

# Funktionen, die eine tatsaechlich schaltende (nicht Status/Trigger)
# ComObject ausmachen.
_OUTPUT_FUNCTIONS = {"schalten", "wert", "dimmen", "heller/dunkler"}


def link_scene_values(project: KnxProject) -> int:
    """Befuellt Scene.actions detektierter Szenen mit echten Aktor-
    Schaltwerten aus den Geräteparametern (legt bei Bedarf zusaetzliche
    numerierte Szenen fuer geteilte Recall-Kanaele an, siehe Modul-
    Docstring). Gibt die Anzahl neu hinzugefügter SceneActions zurück;
    idempotent (dedupe per (group_address, value), keine doppelten
    numerierten Szenen bei wiederholtem Aufruf)."""
    ga_by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    all_devices = [
        device
        for area in project.topology.areas
        for line in area.lines
        for device in line.devices
    ]

    added = 0
    for scene in list(project.scenes):
        if not scene.is_detected or not scene.source_ga_addresses:
            continue
        source_addresses = set(scene.source_ga_addresses) & set(ga_by_address.keys())
        if not source_addresses:
            continue

        listening = [
            (device, channel)
            for device in all_devices
            for channel in _listening_channels(device, source_addresses)
        ]
        if not listening:
            continue

        if scene.scene_number > 0:
            numbers = {scene.scene_number}
        else:
            numbers = {
                entry.scene_number
                for device, channel in listening
                for entry in device.scene_values
                if entry.channel == channel
            }

        for number in sorted(numbers):
            target_scene = (
                scene if number == scene.scene_number
                else _find_or_create_numbered_scene(project, scene, number)
            )
            existing_keys = {(a.group_address, a.value) for a in target_scene.actions}

            for device, channel in listening:
                for entry in device.scene_values:
                    if entry.scene_number != number or entry.channel != channel:
                        continue
                    target_co = _resolve_output_object(device, channel)
                    if not target_co or not target_co.connected_gas:
                        continue
                    ga = ga_by_address.get(target_co.connected_gas[0])
                    if not ga:
                        continue
                    key = (ga.designation, entry.value)
                    if key in existing_keys:
                        continue
                    _append_action(target_scene, ga, entry.value)
                    existing_keys.add(key)
                    added += 1

    if added:
        logger.info(f"link_scene_values: {added} Aktion(en) aus Gerätedaten ergänzt.")
    return added


def _find_or_create_numbered_scene(project: KnxProject, channel_scene, number: int):
    """Findet eine bereits angelegte numerierte Szene fuer denselben
    Recall-Kanal wieder (Idempotenz), sonst wird eine neue erstellt."""
    from ..models.scene import Scene

    source_addrs = set(channel_scene.source_ga_addresses)
    for s in project.scenes:
        if (
            s.is_detected and s.scene_number == number
            and set(s.source_ga_addresses) == source_addrs
        ):
            return s

    new_scene = Scene(
        name=f"{channel_scene.name} – Szene {number}",
        scene_number=number,
        scope=channel_scene.scope,
        scope_id=channel_scene.scope_id,
        is_detected=True,
        detection_kind=channel_scene.detection_kind,
        source_ga_addresses=list(channel_scene.source_ga_addresses),
    )
    project.scenes.append(new_scene)
    return new_scene


def _append_action(scene, ga, value: str) -> None:
    from ..models.scene import SceneAction
    scene.actions.append(SceneAction(
        group_address=ga.designation, value=value, ga_address=ga.address,
    ))


def _listening_channels(device, source_addresses: set[str]) -> set[str]:
    """Kanal-Namen (z.B. 'A', 'Ausgang 1') dieses Geräts, deren eigenes
    Szenen-Trigger-ComObject an eine der Quell-GAs angeschlossen ist."""
    channels = set()
    for co in device.communication_objects:
        func = (co.object_function or "").lower()
        if not any(kw in func for kw in _TRIGGER_FUNCTION_KEYWORDS):
            continue
        if any(addr in co.connected_gas for addr in source_addresses):
            channels.add(_channel_key(co.name))
    return channels


def _channel_key(co_name: str) -> str:
    """Normalisiert 'Ausgang A'/'Ausgang 1' auf den kurzen Kanal-Schlüssel
    ('A') -- SceneValueEntry.channel speichert bei ABB nur den Buchstaben,
    bei Hager den vollen 'Ausgang N'-Namen (siehe extract_scene_values)."""
    name = (co_name or "").strip()
    if name.startswith("Ausgang ") and len(name.split()) == 2:
        suffix = name.split()[1]
        if len(suffix) == 1 and suffix.isalpha():
            return suffix
    return name


def _resolve_output_object(device, channel: str):
    """Findet die tatsaechlich schaltende ComObject eines Kanals (nicht
    Status/Trigger)."""
    candidate_names = {channel, f"Ausgang {channel}"}
    for co in device.communication_objects:
        if co.name.strip() not in candidate_names:
            continue
        if (co.object_function or "").strip().lower() in _OUTPUT_FUNCTIONS:
            return co
    return None


def link_scene_triggers(project: KnxProject) -> int:
    """Befuellt Scene.trigger numerierter Szenen mit dem Taster/der Taste,
    die laut Geräteparametern diese Szenennummer sendet (FA-1810). Legt bei
    Bedarf dieselben numerierten Szenen an wie link_scene_values (siehe
    _find_or_create_numbered_scene) -- Sensor- und Aktor-Seite landen so auf
    derselben Scene. Gibt die Anzahl aktualisierter Szenen zurück;
    idempotent (mehrere Ausloeser fuer dieselbe Szene werden gesammelt,
    keine doppelten Eintraege bei wiederholtem Aufruf)."""
    ga_by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    all_devices = [
        device
        for area in project.topology.areas
        for line in area.lines
        for device in line.devices
    ]

    updated = 0
    for device in all_devices:
        for entry in device.scene_triggers:
            co = _find_button_object(device, entry.button)
            if not co or not co.connected_gas:
                continue
            ga_address = co.connected_gas[0]
            if ga_address not in ga_by_address:
                continue
            channel_scene = _find_channel_scene(project, ga_address)
            if not channel_scene:
                continue
            target_scene = _find_or_create_numbered_scene(
                project, channel_scene, entry.scene_number,
            )
            description = _trigger_description(device, entry.button)
            if _add_trigger_description(target_scene, description):
                updated += 1

    if updated:
        logger.info(f"link_scene_triggers: {updated} Szene(n) mit Ausloeser-Info ergänzt.")
    return updated


def _find_button_object(device, button: str):
    """Findet die Szenen-Nummer-sendende ComObject einer Taste (Funktion
    oder Datentyp enthaelt 'Szene', z.B. Datentyp 'Szenen Nummer')."""
    for co in device.communication_objects:
        if co.name.strip() != button:
            continue
        combined = f"{co.object_function} {co.data_type}".lower()
        if "szene" in combined:
            return co
    return None


def _find_channel_scene(project: KnxProject, ga_address: str):
    """Findet die (unveraenderte) Kanal-Szene (scene_number=0) fuer eine
    Recall-GA, die detect_scenes/link_scene_values dafuer bereits angelegt
    hat -- dient als Namens-/Scope-Vorlage fuer neue numerierte Szenen."""
    for s in project.scenes:
        if s.is_detected and s.scene_number == 0 and ga_address in s.source_ga_addresses:
            return s
    return None


def _trigger_description(device, button: str) -> str:
    location = f" ({device.installation_location})" if device.installation_location else ""
    return f"Taster {device.physical_address}{location}, {button}"


def _add_trigger_description(scene, description: str) -> bool:
    existing = [t for t in scene.trigger.split("; ") if t]
    if description in existing:
        return False
    existing.append(description)
    scene.trigger = "; ".join(existing)
    return True
