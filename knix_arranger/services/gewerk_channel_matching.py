"""
GewerkChannelMatching – ordnet die ComObjects eines Aktor-Kanals den
Funktions-Slots eines Adressblock-Schemas zu (FA-521f).

Motivation: in der Praxis gehört eine ganze Gruppe von Gruppenadressen zu
EINEM Aktor-Kanal (z.B. "Ausgang A" eines Schaltaktors traegt die
ComObjects fuer Schalten, Telegr. Status Schalten, ggf. 8-Bit-Szene) --
das entspricht fast 1:1 den Funktions-Slots eines Gewerk-Schemas (E/A, RM,
...). Diese Heuristik ordnet sie automatisch zu, mit der Erwartung, dass
das Ergebnis vor der Uebernahme in einer Vorschau geprueft/korrigiert wird
(siehe ui/dialogs/gewerk_channel_assign_dialog.py) -- Fehlzuordnungen sind
also nicht sicherheitskritisch, nur unklare/nicht gematchte Slots bleiben
schlicht leer statt geraten zu werden.

Zwei-Stufen-Matching, analog zum bereits vorhandenen Muster in
services/scene_value_linking.py (_resolve_output_object,
_listening_channels):
1. ComObjects nach Rueckmeldungs-Charakter trennen (Text enthaelt
   "status"/"rückmeldung"/"meldung" -> Kandidat fuer is_feedback-Slots,
   sonst fuer schreibende Slots).
2. Innerhalb der passenden Gruppe per Stichwort-Liste (siehe
   _FUNCTION_KEYWORDS) auf die Schema-Funktion matchen.
"""
from __future__ import annotations
import re

from ..models.address_block import AddressBlockSchema
from ..models.topology import CommunicationObject, Device

# Manche Hersteller (z.B. Griesser Jalousieaktoren JAX-9, siehe Chalet-
# Projekt Geraet 1.1.4) geben jeder Funktion einen eigenen, unterschied-
# lichen ComObject-Namen -- "Bedienung Storen (M1), Endlage", "Bedienung
# Storen (M1), Wippen", "Sonnenschutz (M1), Rueckmeldung Hoehe",
# "Sicherheit 1 (M1), Alarm" tragen alle vier den echten Kanal nur als
# Klammer-Tag "(M1)" im Namen -- ein exakter Namensvergleich wuerde diesen
# EINEN physischen Ausgang faelschlich in vier separate "Kanaele"
# aufsplitten. Wird ein solches Tag gefunden, gilt es als Kanal-
# Schluessel statt des vollen Namens.
_CHANNEL_TAG_RE = re.compile(r"\(([A-Za-z]+\d+)\)")


def _channel_key(name: str) -> str:
    m = _CHANNEL_TAG_RE.search(name)
    return m.group(1) if m else name

# Stichwoerter, die eine ComObject-Funktion/-Datentyp mit einer
# Schema-Funktion in Verbindung bringen. Schluessel sind die exakten
# BlockEntry.function-Strings aus models/address_block.py. Deckt die
# haeufigsten Gewerke ab (Licht, Jalousie, Heizung-Stoerung/Sperren,
# DALI-Szene) -- andere Schemata (Wetterstation, EV, PV, SP, LC/LCT/LCW,
# DMX, Lueftung, generisch) werden nicht erkannt und bleiben leer (in der
# Vorschau manuell zuweisbar), statt geraten zu werden.
_FUNCTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "E/A": ("schalten",),
    "DIM": ("dimmen", "heller/dunkler", "heller / dunkler"),
    "WERT": ("wert setzen", "wert senden", "wert"),
    "RM": ("status", "rückmeldung", "meldung"),
    "RM WERT": ("status", "wert"),
    "AUF/AB": ("auf/ab", "auf / ab", "fahren"),
    "STOPP": ("stopp", "schritt", "lamelle verstellen"),
    "POSITION HOEHE": ("position höhe", "position", "höhe"),
    "POSITION LAMELLEN": ("position lamellen", "lamellen", "winkel"),
    # Bewusst OHNE das generische Stichwort "status": innerhalb des
    # Rueckmeldungs-Pools (bereits durch _is_feedback_co gefiltert) muss
    # zwischen mehreren Feedback-Slots derselben Kategorie unterschieden
    # werden koennen (z.B. Jalousie hat zwei), "status" allein wuerde jedes
    # beliebige Status-ComObject treffen.
    "STATUS POSITION HOEHE": ("position höhe", "höhe"),
    "STATUS POSITION LAMELLEN": ("position lamellen", "lamellen"),
    "BESCHATTUNG": ("beschattung",),
    "STOERUNG": ("störung", "fehler", "alarm"),
    "SPERREN": ("sperren", "sperre"),
    "SZENE": ("szene", "8-bit-szene", "szenensteuerung"),
}

_FEEDBACK_KEYWORDS = ("status", "rückmeldung", "meldung")


def all_linked_ga_ids(project) -> dict[str, tuple[str, str]]:
    """GA-ids, die projektweit über `GewerkAssignment.linked_ga_ids`
    tatsächlich einer Zuweisung zugeordnet sind -- {ga_id: (gewerk_code,
    room_number)}. Bewusst NICHT `GroupAddress.gewerk_code` (das ist nur
    eine beim Import aus der Bezeichnung geratene Text-Klassifizierung,
    siehe xlsx_import_service._parse_xlsx_designation -- praktisch jede
    importierte GA trägt so ein Tag, das wäre als "bereits verwendet"
    ein Dauer-Fehlalarm)."""
    result: dict[str, tuple[str, str]] = {}
    for room in project.all_rooms:
        for assignment in room.gewerk_assignments:
            for ga_id in assignment.linked_ga_ids.values():
                result[ga_id] = (assignment.gewerk_code, room.number)
    return result


def group_channels_by_name(device: Device) -> dict[str, list[CommunicationObject]]:
    """Gruppiert die ComObjects eines Geräts zu Kanälen -- entweder nach
    exakt gleichem Namen ('Ausgang A', 'Ausgang 1', ...) oder, falls der
    Name ein Klammer-Tag wie '(M1)' enthält, nach diesem Tag (siehe
    _channel_key)."""
    channels: dict[str, list[CommunicationObject]] = {}
    for co in device.communication_objects:
        channels.setdefault(_channel_key(co.name), []).append(co)
    return channels


def _is_feedback_co(co: CommunicationObject) -> bool:
    # Auch den Namen pruefen, nicht nur object_function: bei manchen
    # Herstellern (Griesser JAX-9) tragen Schreib- und Rueckmelde-
    # ComObject exakt denselben object_function-Text ("Hoehe 0...255"),
    # nur der Name unterscheidet sie ("... Hoehe" vs "... Rueckmeldung
    # Hoehe") -- ein reiner object_function-Check wuerde die Rueckmeldung
    # dann faelschlich als schreibendes Objekt einordnen.
    text = f"{co.object_function or ''} {co.name or ''}".lower()
    return any(kw in text for kw in _FEEDBACK_KEYWORDS)


def match_channel_to_schema(
    channel_cos: list[CommunicationObject], schema: AddressBlockSchema,
) -> dict[str, CommunicationObject]:
    """Ordnet die ComObjects eines Kanals den nicht-Reserve-Funktions-Slots
    des Schemas zu. Gibt {function: CommunicationObject} zurück -- nur für
    tatsächlich erkannte Slots, keine Rateversuche für den Rest."""
    write_cos = [co for co in channel_cos if not _is_feedback_co(co)]
    feedback_cos = [co for co in channel_cos if _is_feedback_co(co)]

    matched: dict[str, CommunicationObject] = {}
    used_ids: set[int] = set()
    for entry in schema.entries:
        if entry.is_reserve or not entry.function:
            continue
        keywords = _FUNCTION_KEYWORDS.get(entry.function)
        if not keywords:
            continue
        pool = feedback_cos if entry.is_feedback else write_cos
        for co in pool:
            if id(co) in used_ids:
                continue
            text = f"{co.object_function} {co.data_type}".lower()
            if any(kw in text for kw in keywords):
                matched[entry.function] = co
                used_ids.add(id(co))
                break
    return matched
