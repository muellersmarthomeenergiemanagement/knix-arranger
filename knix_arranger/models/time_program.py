"""
Zeitsteuerung Datenmodell (FA-3301).

TimeProgram → DayProfile → SwitchPoint

Bitmaske Wochentage (FA-3301d):
  Bit 0 = Montag, Bit 1 = Dienstag, ..., Bit 6 = Sonntag, Bit 7 = Feiertag
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid

# Wochentag-Bitmasken
WEEKDAY_MON = 1 << 0  # 1
WEEKDAY_TUE = 1 << 1  # 2
WEEKDAY_WED = 1 << 2  # 4
WEEKDAY_THU = 1 << 3  # 8
WEEKDAY_FRI = 1 << 4  # 16
WEEKDAY_SAT = 1 << 5  # 32
WEEKDAY_SUN = 1 << 6  # 64
WEEKDAY_HOL = 1 << 7  # 128 (Feiertag)

WEEKDAY_MON_FRI = WEEKDAY_MON | WEEKDAY_TUE | WEEKDAY_WED | WEEKDAY_THU | WEEKDAY_FRI
WEEKDAY_ALL     = WEEKDAY_MON_FRI | WEEKDAY_SAT | WEEKDAY_SUN

WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                 "Freitag", "Samstag", "Sonntag", "Feiertag"]
WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So", "FT"]


def mask_to_day_names(mask: int) -> list[str]:
    """Gibt eine Liste der aktivierten Wochentage als Kurzbezeichnung zurück."""
    return [WEEKDAY_SHORT[i] for i in range(8) if mask & (1 << i)]


@dataclass
class SwitchPoint:
    """Ein einzelner Schaltzeitpunkt (FA-3301a, FA-3301c)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    time_type: str = "FIXED"          # "FIXED" | "ASTRO"
    fixed_time: str = "08:00"         # HH:MM (nur bei FIXED)
    astro_event: str = "SUNRISE"      # "SUNRISE" | "SUNSET" (nur bei ASTRO)
    astro_offset_min: int = 0         # -120 bis +120 Minuten
    target_ga_id: str = ""            # GroupAddress.id
    action_value: str = "1"           # Aktionswert als String (FA-3301e)
    date_range_start: str = ""        # YYYY-MM-DD oder "" (optional)
    date_range_end: str = ""          # YYYY-MM-DD oder ""
    priority: str = "Normal"          # "Normal" | "Erhöht"

    @property
    def display_time(self) -> str:
        if self.time_type == "FIXED":
            return self.fixed_time
        off = f"{self.astro_offset_min:+d} min" if self.astro_offset_min else ""
        return f"{self.astro_event.capitalize()}{off}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "time_type": self.time_type,
            "fixed_time": self.fixed_time,
            "astro_event": self.astro_event,
            "astro_offset_min": self.astro_offset_min,
            "target_ga_id": self.target_ga_id,
            "action_value": self.action_value,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SwitchPoint:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            time_type=d.get("time_type", "FIXED"),
            fixed_time=d.get("fixed_time", "08:00"),
            astro_event=d.get("astro_event", "SUNRISE"),
            astro_offset_min=int(d.get("astro_offset_min", 0)),
            target_ga_id=d.get("target_ga_id", ""),
            action_value=d.get("action_value", "1"),
            date_range_start=d.get("date_range_start", ""),
            date_range_end=d.get("date_range_end", ""),
            priority=d.get("priority", "Normal"),
        )


@dataclass
class DayProfile:
    """Tagesprofil – SwitchPoints für eine Gruppe von Wochentagen (FA-3301a, FA-3301d)."""
    weekday_mask: int = WEEKDAY_MON_FRI   # Bitmaske der aktiven Tage
    switch_points: list[SwitchPoint] = field(default_factory=list)

    @property
    def weekdays(self) -> list[str]:
        """Liste der aktivierten Wochentage als Kurzbezeichnungen."""
        return mask_to_day_names(self.weekday_mask)

    def to_dict(self) -> dict:
        return {
            "weekday_mask": self.weekday_mask,
            "switch_points": [sp.to_dict() for sp in self.switch_points],
        }

    @classmethod
    def from_dict(cls, d: dict) -> DayProfile:
        dp = cls(weekday_mask=int(d.get("weekday_mask", WEEKDAY_MON_FRI)))
        dp.switch_points = [SwitchPoint.from_dict(sp) for sp in d.get("switch_points", [])]
        return dp


@dataclass
class TimeProgram:
    """Zeitschaltprogramm (Wochenprogramm) (FA-3301a, FA-3301b)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Zeitprogramm"
    active: bool = True
    day_profiles: list[DayProfile] = field(default_factory=list)

    @property
    def all_switch_points(self) -> list[tuple[DayProfile, SwitchPoint]]:
        """Flache Liste aller (DayProfile, SwitchPoint)-Paare."""
        return [(dp, sp) for dp in self.day_profiles for sp in dp.switch_points]

    @property
    def switch_point_count(self) -> int:
        return sum(len(dp.switch_points) for dp in self.day_profiles)

    @property
    def has_astro(self) -> bool:
        return any(sp.time_type == "ASTRO"
                   for _, sp in self.all_switch_points)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "active": self.active,
            "day_profiles": [dp.to_dict() for dp in self.day_profiles],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TimeProgram:
        tp = cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Zeitprogramm"),
            active=d.get("active", True),
        )
        tp.day_profiles = [DayProfile.from_dict(dp) for dp in d.get("day_profiles", [])]
        return tp


@dataclass
class ProjectLocation:
    """Projektstandort für Astro-Timer-Berechnung (FA-3303a)."""
    latitude: float = 47.37      # Standardwert: Zürich
    longitude: float = 8.54
    country: str = "CH"          # "CH" | "DE" | "AT"
    region: str = "ZH"           # Kanton / Bundesland-Kürzel
    postal_code: str = ""

    def to_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "country": self.country,
            "region": self.region,
            "postal_code": self.postal_code,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProjectLocation:
        return cls(
            latitude=float(d.get("latitude", 47.37)),
            longitude=float(d.get("longitude", 8.54)),
            country=d.get("country", "CH"),
            region=d.get("region", "ZH"),
            postal_code=d.get("postal_code", ""),
        )
