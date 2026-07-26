"""
Gebäudestruktur-Modelle: Areal > Gebäude > Flügel > Stockwerk > Wohnung/Zone > Raum
Gemaess FA-101, FA-102, FA-103, FA-105, FA-106, FA-107
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


@dataclass
class LineCoupler:
    """Linienkoppler in einem Verteiler."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    physical_address: str = ""   # z.B. "1.2.0"
    datasheets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "physical_address": self.physical_address,
            "datasheets": self.datasheets,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LineCoupler:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            physical_address=data.get("physical_address", ""),
            datasheets=data.get("datasheets", []),
        )


@dataclass
class PowerSupply:
    """KNX-Speisung in einem Verteiler."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    power_ma: int = 0            # Nennstrom in mA
    datasheets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "power_ma": self.power_ma,
            "datasheets": self.datasheets,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PowerSupply:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            power_ma=data.get("power_ma", 0),
            datasheets=data.get("datasheets", []),
        )


@dataclass
class Interface:
    """KNX-Schnittstelle in einem Verteiler (IP, USB, RS232, ...)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    interface_type: str = ""     # z.B. "IP Interface", "USB Interface"
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    datasheets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "interface_type": self.interface_type,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "datasheets": self.datasheets,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Interface:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            interface_type=data.get("interface_type", ""),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            datasheets=data.get("datasheets", []),
        )


@dataclass
class Verteiler:
    """Elektroverteilkasten (HV, UV, NV, ...) innerhalb eines Raums."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""               # z.B. "HV", "UV Küche"
    verteiler_type: str = ""     # "HV", "UV", "NV", "TV", ...
    designation: str = ""        # Aufschrift / Bezeichnung (Typenschild)
    actor_assignments: list[ActorAssignment] = field(default_factory=list)
    line_couplers: list[LineCoupler] = field(default_factory=list)
    power_supplies: list[PowerSupply] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "verteiler_type": self.verteiler_type,
            "designation": self.designation,
            "actor_assignments": [a.to_dict() for a in self.actor_assignments],
            "line_couplers": [lc.to_dict() for lc in self.line_couplers],
            "power_supplies": [ps.to_dict() for ps in self.power_supplies],
            "interfaces": [i.to_dict() for i in self.interfaces],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Verteiler:
        v = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            verteiler_type=data.get("verteiler_type", ""),
            designation=data.get("designation", ""),
        )
        v.actor_assignments = [
            ActorAssignment.from_dict(a) for a in data.get("actor_assignments", [])
        ]
        v.line_couplers = [
            LineCoupler.from_dict(lc) for lc in data.get("line_couplers", [])
        ]
        v.power_supplies = [
            PowerSupply.from_dict(ps) for ps in data.get("power_supplies", [])
        ]
        v.interfaces = [
            Interface.from_dict(i) for i in data.get("interfaces", [])
        ]
        return v


@dataclass
class Room:
    """Ein Raum innerhalb einer Wohnung/Zone."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    number: str = ""          # z.B. "E01", "UG02"
    name: str = ""            # Klartext, z.B. "Schlafzimmer"
    planned_sensors: int = 4  # FA-106: Standard 4 Sensoren
    planned_actors: int = 2   # FA-106: Standard 2 Aktoren
    # ID des physischen Stockwerks (Floor.id) – für Dokumentation und Raumnummerierung.
    # Wird beim Laden aus alten Projekten automatisch aus dem Parent-Floor gesetzt.
    floor_id: str = ""
    gewerk_assignments: list[GewerkAssignment] = field(default_factory=list)
    bedienelemente: list[Bedienelement] = field(default_factory=list)
    verteiler: list[Verteiler] = field(default_factory=list)
    # Typ pro Tastereinheit: Schlüssel = str(te_index), Wert = "Taster"|"Präsenzmelder"
    # Fehlender Eintrag → Standard "Taster"
    te_types: dict[str, str] = field(default_factory=dict)
    # Explizit gespeicherte Anzahl Tastereinheiten (0 = nicht gesetzt, aus taster_indices ableiten)
    te_count: int = 0
    # Freitext-Anmerkungen des Bauherrn zu diesem Raum (FA-1501 Bauherrenberatung)
    bauherr_notes: str = ""

    def get_te_type(self, te_idx: int) -> str:
        """Gibt den Typ der Tastereinheit zurück ('Taster' oder 'Präsenzmelder')."""
        return self.te_types.get(str(te_idx), "Taster")

    def set_te_type(self, te_idx: int, te_type: str):
        if te_type == "Taster":
            self.te_types.pop(str(te_idx), None)  # Standard nicht explizit speichern
        else:
            self.te_types[str(te_idx)] = te_type

    @property
    def has_verteiler(self) -> bool:
        """True wenn mindestens ein Verteiler (HV/UV/...) im Raum vorhanden."""
        return len(self.verteiler) > 0

    def total_devices(self) -> int:
        """
        Gesamtzahl der geplanten Geräte im Raum.

        Wenn Gewerk-Zuweisungen vorhanden sind, wird die Anzahl realistisch
        aus Gewerken abgeleitet:
          - Sensoren: Anzahl eindeutiger (sensor_type, taster_index)-Gruppen
          - Aktoren:  Anzahl Aktor-Kanäle / typische Kanalzahl pro Gerät (≈2)

        Ohne Gewerk-Zuweisungen: Platzhalter-Summe (planned_sensors + planned_actors).
        """
        if not self.gewerk_assignments:
            return self.planned_sensors + self.planned_actors

        from .device import GEWERK_TO_SENSOR_TYPE, GEWERK_TO_ACTOR_TYPE

        # Sensoren: eine Tastereinheit pro (sensor_type, taster_index)-Kombination
        # taster_indices ist eine Liste → viele-zu-viele möglich
        sensor_groups: set[tuple[str, int]] = set()
        for ga in self.gewerk_assignments:
            st = GEWERK_TO_SENSOR_TYPE.get(ga.gewerk_code)
            if st:
                for ti in ga.taster_indices:
                    sensor_groups.add((st, ti))
        n_sensors = len(sensor_groups)

        # Aktoren: Aktor-Kanäle summieren, dann durch 2 teilen (≈ 2 Kanäle/Gerät)
        actor_channels = sum(
            ga.count
            for ga in self.gewerk_assignments
            if GEWERK_TO_ACTOR_TYPE.get(ga.gewerk_code)
        )
        import math
        n_actors = max(1, math.ceil(actor_channels / 2)) if actor_channels else 0

        return n_sensors + n_actors

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "number": self.number,
            "name": self.name,
            "planned_sensors": self.planned_sensors,
            "planned_actors": self.planned_actors,
            "floor_id": self.floor_id,
            "gewerk_assignments": [g.to_dict() for g in self.gewerk_assignments],
            "bedienelemente": [b.to_dict() for b in self.bedienelemente],
            "verteiler": [v.to_dict() for v in self.verteiler],
        }
        if self.te_types:
            d["te_types"] = self.te_types
        if self.te_count:
            d["te_count"] = self.te_count
        if self.bauherr_notes:
            d["bauherr_notes"] = self.bauherr_notes
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Room:
        room = cls(
            id=data.get("id", str(uuid.uuid4())),
            number=data.get("number", ""),
            name=data.get("name", ""),
            planned_sensors=data.get("planned_sensors", 4),
            planned_actors=data.get("planned_actors", 2),
            floor_id=data.get("floor_id", ""),
        )
        room.gewerk_assignments = [
            GewerkAssignment.from_dict(g) for g in data.get("gewerk_assignments", [])
        ]
        # Abwärtskompatibilität: altes Feld "sensor_assignments" einlesen
        raw_be = data.get("bedienelemente") or data.get("sensor_assignments", [])
        room.bedienelemente = [Bedienelement.from_dict(b) for b in raw_be]
        room.verteiler = [
            Verteiler.from_dict(v) for v in data.get("verteiler", [])
        ]
        room.te_types = {str(k): v for k, v in data.get("te_types", {}).items()}
        room.te_count = data.get("te_count", 0)
        room.bauherr_notes = data.get("bauherr_notes", "")
        return room


@dataclass
class GewerkAssignment:
    """Zuweisung eines Gewerks zu einem Raum (FA-301, FA-304)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    gewerk_code: str = ""     # Kürzel, z.B. "LD", "J", "H"
    count: int = 1            # Anzahl Elemente
    datasheets: list[str] = field(default_factory=list)  # Pfade zu PDFs
    # Physische Tastereinheiten, denen diese Zuweisung gehört (viele-zu-viele).
    # [1] = Standard (erste Tastereinheit), [1, 2] = erste UND zweite Tastereinheit.
    taster_indices: list[int] = field(default_factory=lambda: [1])
    # Manueller Sensortyp-Override (FA-1407); None = automatisch aus Gewerk ableiten
    sensor_type_override: str | None = None
    # Zusätzliche GA-Einträge über den Standard-Block hinaus (serialisierte BlockEntry-Dicts)
    extra_entries: list[dict] = field(default_factory=list)
    # Verknüpftes Produkt (FA-Produktbasierte GA-Generierung): wenn gesetzt,
    # wird der GA-Block aus den ComObjects dieses Produkts generiert statt
    # aus dem generischen/gewerk-spezifischen Schema.
    # {"manufacturer": str, "order_number": str, "product_name": str,
    #  "com_objects": list[dict], "material_entry_id": str}
    linked_product: dict | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "gewerk_code": self.gewerk_code,
            "count": self.count,
            "datasheets": self.datasheets,
            "taster_indices": self.taster_indices,
            "sensor_type_override": self.sensor_type_override,
            "extra_entries": self.extra_entries,
            "linked_product": self.linked_product,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GewerkAssignment:
        # Migration: altes Feld taster_index (int) → taster_indices (list[int])
        if "taster_indices" in data:
            taster_indices = data["taster_indices"]
        elif "taster_index" in data:
            taster_indices = [data["taster_index"]]
        else:
            taster_indices = [1]
        obj = cls(
            id=data.get("id", str(uuid.uuid4())),
            gewerk_code=data.get("gewerk_code", ""),
            count=data.get("count", 1),
            datasheets=data.get("datasheets", []),
            taster_indices=taster_indices,
            sensor_type_override=data.get("sensor_type_override"),
        )
        obj.extra_entries = data.get("extra_entries", [])
        obj.linked_product = data.get("linked_product")
        return obj


def _migrate_control_functions(raw: list[dict]) -> list[SensorFunktion]:
    """FA-1410d: Migriert alte control_functions-Liste zu SensorFunktion-Objekten.

    Einträge mit gleichem (gewerk_code, element_number, source_room_id) werden
    zusammengefasst (verschiedene function_names = verschiedene GAs derselben
    logischen Einheit).  Einträge mit ga_designation bleiben Einzelfunktionen.
    """
    seen: dict[tuple, SensorFunktion] = {}
    result: list[SensorFunktion] = []
    for cf_data in raw:
        ga_des = cf_data.get("ga_designation", "")
        if ga_des:
            # Direkte GA → eigene degenerierte SensorFunktion
            result.append(SensorFunktion(
                label=cf_data.get("label", ""),
                ga_designation=ga_des,
            ))
            continue
        gewerk = cf_data.get("gewerk_code", "")
        elem = cf_data.get("element_number", 1)
        src = cf_data.get("source_room_id", "")
        key = (gewerk, elem, src)
        if key not in seen:
            sf = SensorFunktion(
                label=cf_data.get("label", ""),
                gewerk_code=gewerk,
                element_number=elem,
                source_room_id=src,
            )
            seen[key] = sf
            result.append(sf)
    return result


# Migrations-Mapping: alte "Taster X-fach"-element_types → ("Tastereinheit", channels).
# Wurde in älteren Versionen fälschlicherweise als Sensortyp statt als Formatmerkmal
# einer Tastereinheit gespeichert.
_TASTER_NFACH_CHANNELS: dict[str, int] = {
    "Taster 1-fach": 1,
    "Taster 2-fach": 2,
    "Taster 4-fach": 4,
    "Taster 6-fach": 6,
}


@dataclass
class Bedienelement:
    """Bedienelement (Taster, Thermostat, Sensor, ...) in einem Raum (FA-1404).

    Hat eine herstellerabhängige Anzahl Kanäle. Pro Gerät wird eine
    Linienteilnehmernummer auf der KNX-Linie vergeben.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    element_type: str = ""        # z.B. "Tastereinheit", "Raumthermostat", "Präsenzmelder"
    channels: int = 1             # Anzahl Kanäle (produktabhängig, z.B. 1, 2, 4, 6, 8)
    participant_number: str = ""  # Linienteilnehmernummer (physikalische Adresse)
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    datasheets: list[str] = field(default_factory=list)
    function_assignments: list[FunctionAssignment] = field(default_factory=list)
    # FA-1410: Sensorfunktionen (logische Steuereinheiten) dieses Bedienelements.
    # is_auto=True  → automatisch aus Gewerken abgeleitet, wird bei Änderung neu berechnet
    # is_auto=False → manuell konfiguriert, wird NICHT automatisch überschrieben
    funktionen: list[SensorFunktion] = field(default_factory=list)
    is_auto: bool = True
    # True = auto-BE wurde vom Nutzer explizit gelöscht; wird von auto_assign_functions
    # als Tombstone behandelt und nicht neu erstellt. Manuell erstellte BEs werden
    # stattdessen direkt entfernt (kein Tombstone nötig).
    suppressed: bool = False
    # Nummer der Tastereinheit im Raum (1 = erste, 2 = zweite, …).
    # Entspricht dem taster_index der GewerkAssignment-Gruppierung.
    taster_index: int = 1
    # Freitext-Anmerkung des Bauherrn zu diesem Bedienelement (FA-1501 Bauherrenberatung)
    bauherr_annotation: str = ""

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "element_type": self.element_type,
            "channels": self.channels,
            "participant_number": self.participant_number,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "datasheets": self.datasheets,
            "function_assignments": [f.to_dict() for f in self.function_assignments],
            "funktionen": [sf.to_dict() for sf in self.funktionen],
            "is_auto": self.is_auto,
            "suppressed": self.suppressed,
            "taster_index": self.taster_index,
        }
        if self.bauherr_annotation:
            d["bauherr_annotation"] = self.bauherr_annotation
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Bedienelement:
        element_type = data.get("element_type") or data.get("sensor_type", "")
        channels = data.get("channels", 1)
        # Migration: "Taster X-fach" → element_type="Tastereinheit" + channels=X.
        # Ältere Versionen speicherten das Format fälschlicherweise als Sensortyp.
        if element_type in _TASTER_NFACH_CHANNELS:
            channels = _TASTER_NFACH_CHANNELS[element_type]
            element_type = "Tastereinheit"
        be = cls(
            id=data.get("id", str(uuid.uuid4())),
            element_type=element_type,
            channels=channels,
            participant_number=data.get("participant_number", ""),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            datasheets=data.get("datasheets", []),
            is_auto=data.get("is_auto", True),
            suppressed=data.get("suppressed", False),
            taster_index=data.get("taster_index", 1),
            bauherr_annotation=data.get("bauherr_annotation", ""),
        )
        be.function_assignments = [
            FunctionAssignment.from_dict(f) for f in data.get("function_assignments", [])
        ]
        if "funktionen" in data:
            be.funktionen = [SensorFunktion.from_dict(sf) for sf in data["funktionen"]]
        elif "control_functions" in data:
            # FA-1410d: Migration alter control_functions → SensorFunktion
            be.funktionen = _migrate_control_functions(data["control_functions"])
        return be


# Abwärtskompatibilität für Code der noch SensorAssignment importiert
SensorAssignment = Bedienelement


@dataclass
class SensorFunktion:
    """
    Sensorfunktion an einem Bedienelement (FA-1410).

    Eine Sensorfunktion ist die logische Steuereinheit: Sie bündelt alle
    Gruppenadressen (Primär + Rückmeldung) einer Gewerk-Instanz in einem
    einzigen Objekt.  Zwei Varianten:

    1. Gewerk-basiert  (gewerk_code gesetzt, source_room_id optional)
       → alle Primär- und Rückmelde-GAs werden automatisch abgeleitet
    2. Direkte GA      (ga_designation gesetzt, gewerk_code leer)
       → degenerierter Sonderfall mit genau einer GA
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""              # Optionale Freibezeichnung
    # Variante 1: Gewerk-Instanz
    gewerk_code: str = ""        # z.B. "L", "LD", "J"
    element_number: int = 1      # Instanz im Quell-Raum (1, 2, …)
    source_room_id: str = ""     # Leer = eigener Raum, sonst UUID des Fremdraums
    # Variante 2: Direkte GA
    ga_designation: str = ""     # z.B. "3/0/15 Flur Licht E/A"
    # Aktionstyp für direkte GAs (Variante 2): "kurz", "lang", "" = unspezifisch
    action_type: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "gewerk_code": self.gewerk_code,
            "element_number": self.element_number,
            "source_room_id": self.source_room_id,
            "ga_designation": self.ga_designation,
            "action_type": self.action_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SensorFunktion:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            label=data.get("label", ""),
            gewerk_code=data.get("gewerk_code", ""),
            element_number=data.get("element_number", 1),
            source_room_id=data.get("source_room_id", ""),
            ga_designation=data.get("ga_designation", ""),
            action_type=data.get("action_type", ""),
        )


@dataclass
class ControlFunction:
    """
    Veraltetes Einzelfunktions-Objekt (vor FA-1410).  Wird nur noch beim
    Einlesen alter Projektdaten benötigt; neue Daten verwenden SensorFunktion.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""
    gewerk_code: str = ""
    element_number: int = 1
    function_name: str = ""
    source_room_id: str = ""
    ga_designation: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "gewerk_code": self.gewerk_code,
            "element_number": self.element_number,
            "function_name": self.function_name,
            "source_room_id": self.source_room_id,
            "ga_designation": self.ga_designation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ControlFunction:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            label=data.get("label", ""),
            gewerk_code=data.get("gewerk_code", ""),
            element_number=data.get("element_number", 1),
            function_name=data.get("function_name", ""),
            source_room_id=data.get("source_room_id", ""),
            ga_designation=data.get("ga_designation", ""),
        )


@dataclass
class FunctionAssignment:
    """Funktionszuordnung Taste/Kanal -> GA (FA-1502)."""
    button_channel: str = ""   # z.B. "Taste 1"
    function_ga: str = ""      # z.B. "LD_E01_01 E/A"
    description: str = ""
    # Aktionstyp: "kurz" = kurz drücken, "lang" = lang drücken,
    # "loslassen" = beim Loslassen, "" = unspezifisch (Kontakt, Sensor)
    action_type: str = ""
    # True = Rückmelde-GA (LED-Ansteuerung, nur empfangen),
    # False = Steuer-GA (Taster sendet)
    is_feedback: bool = False
    # Id der SensorFunktion, aus der dieser Eintrag abgeleitet wurde (FA-2503).
    # Direkte GA (Variante 2): eindeutig 1:1 -- per Matrix-Doppelklick editierbar.
    # Gewerk-basiert (Variante 1): mehrere FunctionAssignment teilen sich eine
    # sf_id (Primär+Rückmeldung) -- nicht einzeln editierbar, siehe Schritt 5 Gewerke.
    sf_id: str = ""

    def to_dict(self) -> dict:
        return {
            "button_channel": self.button_channel,
            "function_ga": self.function_ga,
            "description": self.description,
            "action_type": self.action_type,
            "is_feedback": self.is_feedback,
            "sf_id": self.sf_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FunctionAssignment:
        return cls(
            button_channel=data.get("button_channel", ""),
            function_ga=data.get("function_ga", ""),
            description=data.get("description", ""),
            action_type=data.get("action_type", ""),
            is_feedback=data.get("is_feedback", False),
            sf_id=data.get("sf_id", ""),
        )


@dataclass
class ActorAssignment:
    """Aktor-Zuweisung in einem HV/UV-Raum (FA-1305)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    actor_type: str = ""              # z.B. "Schaltaktor 8-fach"
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    datasheets: list[str] = field(default_factory=list)
    channel_assignments: list[ChannelAssignment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor_type": self.actor_type,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "datasheets": self.datasheets,
            "channel_assignments": [c.to_dict() for c in self.channel_assignments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ActorAssignment:
        aa = cls(
            id=data.get("id", str(uuid.uuid4())),
            actor_type=data.get("actor_type", ""),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            datasheets=data.get("datasheets", []),
        )
        aa.channel_assignments = [
            ChannelAssignment.from_dict(c) for c in data.get("channel_assignments", [])
        ]
        return aa


@dataclass
class ChannelAssignment:
    """Kanalzuordnung Aktor-Kanal -> Gewerk/Raum."""
    channel: str = ""         # z.B. "Ausgang A"
    gewerk_room: str = ""     # z.B. "L_E01_01"

    def to_dict(self) -> dict:
        return {"channel": self.channel, "gewerk_room": self.gewerk_room}

    @classmethod
    def from_dict(cls, data: dict) -> ChannelAssignment:
        return cls(channel=data.get("channel", ""), gewerk_room=data.get("gewerk_room", ""))


@dataclass
class Apartment:
    """Wohnung oder Zone innerhalb eines Stockwerks (FA-107)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""            # z.B. "Wohnung 1", "Zone Nord"
    rooms: list[Room] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rooms": [r.to_dict() for r in self.rooms],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Apartment:
        apt = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
        )
        apt.rooms = [Room.from_dict(r) for r in data.get("rooms", [])]
        return apt


@dataclass
class Floor:
    """Stockwerk eines Gebäudes."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""            # z.B. "UG", "EG", "1.OG", "DG"
    short_code: str = ""      # z.B. "UG", "EG", "OG", "DG"
    main_group_number: int = -1  # Hauptgruppen-Nr. (-1 = auto)
    apartments: list[Apartment] = field(default_factory=list)

    @property
    def all_rooms(self) -> list[Room]:
        """Alle Räume ueber alle Wohnungen/Zonen."""
        rooms = []
        for apt in self.apartments:
            rooms.extend(apt.rooms)
        return rooms

    def total_devices(self) -> int:
        return sum(r.total_devices() for r in self.all_rooms)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "short_code": self.short_code,
            "main_group_number": self.main_group_number,
            "apartments": [a.to_dict() for a in self.apartments],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Floor:
        f = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            short_code=data.get("short_code", ""),
            main_group_number=data.get("main_group_number", -1),
        )
        f.apartments = [Apartment.from_dict(a) for a in data.get("apartments", [])]
        # Migration: room.floor_id aus Parent-Floor ableiten falls noch nicht gesetzt
        for apt in f.apartments:
            for room in apt.rooms:
                if not room.floor_id:
                    room.floor_id = f.id
        return f


@dataclass
class Wing:
    """Gebäude-Flügel (optional)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    floors: list[Floor] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "floors": [f.to_dict() for f in self.floors],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Wing:
        w = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
        )
        w.floors = [Floor.from_dict(f) for f in data.get("floors", [])]
        return w


@dataclass
class Building:
    """Ein Gebäude innerhalb eines Areals."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    wings: list[Wing] = field(default_factory=list)

    @property
    def all_floors(self) -> list[Floor]:
        floors = []
        for wing in self.wings:
            floors.extend(wing.floors)
        return floors

    @property
    def all_rooms(self) -> list[Room]:
        rooms = []
        for floor in self.all_floors:
            rooms.extend(floor.all_rooms)
        return rooms

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "wings": [w.to_dict() for w in self.wings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Building:
        b = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
        )
        b.wings = [Wing.from_dict(w) for w in data.get("wings", [])]
        return b


@dataclass
class Areal:
    """Areal (oberstes Element der Gebäudestruktur, optional)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    buildings: list[Building] = field(default_factory=list)

    @property
    def all_floors(self) -> list[Floor]:
        floors = []
        for building in self.buildings:
            floors.extend(building.all_floors)
        return floors

    @property
    def all_rooms(self) -> list[Room]:
        rooms = []
        for building in self.buildings:
            rooms.extend(building.all_rooms)
        return rooms

    @property
    def is_multi_zone(self) -> bool:
        """True wenn das Projekt mehr als eine Zone (Wohnung) enthält.

        Massgebend sind die eindeutigen Apartment-Namen über alle Stockwerke.
        Zwei Stockwerke mit demselben Namen = eine Zone (Maisonette).
        """
        names = {
            apt.name
            for floor in self.all_floors
            for apt in floor.apartments
        }
        return len(names) > 1

    def zone_name_for_room(self, room_id: str) -> str:
        """Gibt den Zonennamen für eine Room-ID zurück (leer wenn nicht gefunden)."""
        for floor in self.all_floors:
            for apt in floor.apartments:
                for room in apt.rooms:
                    if room.id == room_id:
                        return apt.name
        return ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "buildings": [b.to_dict() for b in self.buildings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Areal:
        a = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
        )
        a.buildings = [Building.from_dict(b) for b in data.get("buildings", [])]
        return a


# Standard-Stockwerksbezeichnungen (FA-103)
STANDARD_FLOOR_NAMES = {
    "UG": "Untergeschoss",
    "EG": "Erdgeschoss",
    "OG": "Obergeschoss",
    "1.OG": "1. Obergeschoss",
    "2.OG": "2. Obergeschoss",
    "3.OG": "3. Obergeschoss",
    "DG": "Dachgeschoss",
}

# Standard-Hauptgruppen-Zuordnung (FA-411)
# Jeder Kurzcode bekommt eine eindeutige Nummer.
FLOOR_TO_MAIN_GROUP = {
    "UG": 1,
    "EG": 2,
    "OG": 3,
    "1.OG": 4,
    "2.OG": 5,
    "3.OG": 6,
    "DG": 7,
}
