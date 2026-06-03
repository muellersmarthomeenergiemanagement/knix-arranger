"""
TimeProgramService – Verwaltung von Zeitschaltprogrammen (FA-2901–2906, FA-3301–3308).

Verantwortlich für:
- Astro-Berechnung (Sonnenauf-/-untergang, NOAA-Algorithmus, FA-3303)
- Feiertagskalender CH/DE/AT (FA-3304)
- Zeitprogramm-Vorlagen (FA-3305)
- Validierung (FA-3306)
- Astro-GA-Autogenerierung in HG0/MG7 (FA-3308)
"""
from __future__ import annotations
import json
import logging
import math
import os
from datetime import date, datetime, timedelta
from typing import Optional

from ..models.time_program import (
    TimeProgram, DayProfile, SwitchPoint, ProjectLocation,
    WEEKDAY_MON, WEEKDAY_TUE, WEEKDAY_WED, WEEKDAY_THU, WEEKDAY_FRI,
    WEEKDAY_SAT, WEEKDAY_SUN, WEEKDAY_HOL, WEEKDAY_MON_FRI, WEEKDAY_ALL,
)

logger = logging.getLogger("knix_arranger.time_program")

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


# ── NOAA Solar Calculator (FA-3303) ──────────────────────────────────────────

def _julian_day(d: date) -> float:
    """Julianisches Datum für Mitternacht UTC."""
    a = (14 - d.month) // 12
    y = d.year + 4800 - a
    m = d.month + 12 * a - 3
    return d.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _solar_noon_fraction(jd: float, longitude: float) -> float:
    """Sonnenmittagszeit als Tagesbruchzahl (0..1) UTC."""
    jc = (jd - 2451545.0) / 36525.0
    # Geometrische Mittlänge
    gmls = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    # Mittlere Anomalie
    gmas = math.radians(357.52911 + jc * (35999.05029 - 0.0001537 * jc))
    # Equation of Center
    ec = (math.sin(gmas) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
          + math.sin(2 * gmas) * (0.019993 - 0.000101 * jc)
          + math.sin(3 * gmas) * 0.000289)
    # Wahre Länge / Rektaszension
    stl = (gmls + ec) % 360
    omega = math.radians(125.04 - 1934.136 * jc)
    al = stl - 0.00569 - 0.00478 * math.sin(omega)
    # Mean Obliquity / Declination
    oe = (23.0 + (26.0 + (21.448 - jc * (46.8150 + jc * (0.00059 - jc * 0.001813))) / 60) / 60)
    ob = math.radians(oe + 0.00256 * math.cos(omega))
    decl = math.degrees(math.asin(math.sin(ob) * math.sin(math.radians(al))))
    # Equation of Time (Minuten)
    y_val = math.tan(ob / 2) ** 2
    l2 = math.radians(2 * gmls)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    eot = (4 * math.degrees(y_val * math.sin(l2) - 2 * e * math.sin(gmas)
           + 4 * e * y_val * math.sin(gmas) * math.cos(l2)
           - 0.5 * y_val ** 2 * math.sin(2 * l2)
           - 1.25 * e ** 2 * math.sin(2 * gmas)))
    solar_noon_min = 720 - 4 * longitude - eot
    return solar_noon_min / 1440.0  # Tagesbruchzahl UTC


def _sunrise_sunset(d: date, lat: float, lon: float,
                    zenith: float = 90.833) -> tuple[Optional[datetime], Optional[datetime]]:
    """Berechnet Sonnenauf- und -untergang (NOAA) für ein Datum und Koordinaten.

    Gibt (sunrise_utc, sunset_utc) zurück. None wenn keine Sonne (Polarnacht/Mitternachtssonne).
    """
    jd = _julian_day(d)
    jc = (jd - 2451545.0) / 36525.0
    gmas = math.radians(357.52911 + jc * (35999.05029 - 0.0001537 * jc))
    gmls = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    ec = (math.sin(gmas) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
          + math.sin(2 * gmas) * (0.019993 - 0.000101 * jc)
          + math.sin(3 * gmas) * 0.000289)
    stl = (gmls + ec) % 360
    omega = math.radians(125.04 - 1934.136 * jc)
    al = stl - 0.00569 - 0.00478 * math.sin(omega)
    oe = (23.0 + (26.0 + (21.448 - jc * (46.8150 + jc * (0.00059 - jc * 0.001813))) / 60) / 60)
    ob = math.radians(oe + 0.00256 * math.cos(omega))
    decl = math.degrees(math.asin(math.sin(ob) * math.sin(math.radians(al))))

    lat_r = math.radians(lat)
    decl_r = math.radians(decl)
    zen_r = math.radians(zenith)

    cos_ha = (math.cos(zen_r) / (math.cos(lat_r) * math.cos(decl_r))
              - math.tan(lat_r) * math.tan(decl_r))
    if cos_ha < -1:   # Mitternachtssonne
        return None, None
    if cos_ha > 1:    # Polarnacht
        return None, None

    ha = math.degrees(math.acos(cos_ha))   # Stunden bis Auf/Untergang

    noon_frac = _solar_noon_fraction(jd, lon)
    noon_min = noon_frac * 1440

    rise_min = noon_min - ha * 4
    set_min = noon_min + ha * 4

    def _to_dt(minutes: float) -> datetime:
        h = int(minutes // 60) % 24
        m = int(minutes % 60)
        return datetime(d.year, d.month, d.day, h, m)

    return _to_dt(rise_min), _to_dt(set_min)


def calc_astro_time(event: str, d: date, location: ProjectLocation,
                    offset_min: int = 0) -> Optional[str]:
    """Berechnet den Astro-Zeitpunkt als 'HH:MM' (Lokalzeit approximiert = UTC+1 CH/DE/AT).

    event: 'SUNRISE' | 'SUNSET'
    Gibt None zurück bei Polarnacht/Mitternachtssonne.
    """
    rise, sset = _sunrise_sunset(d, location.latitude, location.longitude)
    if rise is None:
        return None
    result = rise if event == "SUNRISE" else sset
    result += timedelta(minutes=offset_min + 60)  # UTC+1 Annäherung (CH/DE/AT Winterzeit)
    return result.strftime("%H:%M")


# ── Feiertagskalender (FA-3304) ───────────────────────────────────────────────

def load_holidays(country: str = "CH", year: Optional[int] = None) -> list[date]:
    """Lädt Feiertage aus config/holidays.json für Land und Jahr.

    Gibt eine Liste von date-Objekten zurück.
    """
    filepath = os.path.join(_CONFIG_DIR, "holidays.json")
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    country_data = data.get(country, {})
    result = []
    for y, dates in country_data.items():
        if year is not None and int(y) != year:
            continue
        for d_str in dates:
            try:
                result.append(date.fromisoformat(d_str))
            except ValueError:
                pass
    return sorted(result)


def is_holiday(d: date, country: str = "CH") -> bool:
    """Prüft ob ein Datum ein Feiertag im gegebenen Land ist."""
    return d in load_holidays(country, year=d.year)


# ── Zeitprogramm-Vorlagen (FA-3305) ──────────────────────────────────────────

def load_templates() -> list[dict]:
    """Lädt Zeitprogramm-Vorlagen aus config/time_program_templates.json."""
    filepath = os.path.join(_CONFIG_DIR, "time_program_templates.json")
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f).get("templates", [])


def create_program_from_template(template_id: str) -> Optional[TimeProgram]:
    """Erstellt ein TimeProgram aus einer Vorlage."""
    templates = load_templates()
    tmpl = next((t for t in templates if t.get("id") == template_id), None)
    if tmpl is None:
        return None
    tp = TimeProgram(name=tmpl.get("name", "Zeitprogramm"))
    for dp_data in tmpl.get("day_profiles", []):
        dp = DayProfile(weekday_mask=dp_data.get("weekday_mask", WEEKDAY_MON_FRI))
        for sp_data in dp_data.get("switch_points", []):
            sp = SwitchPoint(
                time_type=sp_data.get("time_type", "FIXED"),
                fixed_time=sp_data.get("fixed_time", "08:00"),
                astro_event=sp_data.get("astro_event", "SUNRISE"),
                astro_offset_min=sp_data.get("astro_offset_min", 0),
                action_value=sp_data.get("action_value", "1"),
                priority=sp_data.get("priority", "Normal"),
            )
            dp.switch_points.append(sp)
        tp.day_profiles.append(dp)
    return tp


# ── Validierung (FA-3306) ─────────────────────────────────────────────────────

class TimeProgramError:
    """Validierungsfehler in einem Zeitprogramm."""
    def __init__(self, program_name: str, message: str, severity: str = "warning"):
        self.program_name = program_name
        self.message = message
        self.severity = severity  # "warning" | "error"

    def __repr__(self):
        return f"TimeProgramError({self.program_name!r}, {self.message!r})"


def validate_time_program(tp: TimeProgram, project) -> list[TimeProgramError]:
    """Validiert ein Zeitprogramm und gibt eine Liste von Fehlern/Warnungen zurück."""
    errors = []
    known_ga_ids = {ga.id for ga in project.group_addresses.all_addresses()}

    for dp in tp.day_profiles:
        if dp.weekday_mask == 0:
            errors.append(TimeProgramError(
                tp.name, "Tagesprofil hat keine Wochentage aktiviert.", "warning"
            ))

        prev_time = None
        for sp in sorted(dp.switch_points,
                         key=lambda s: s.fixed_time if s.time_type == "FIXED" else "00:00"):
            # GA-Referenz prüfen
            if sp.target_ga_id and sp.target_ga_id not in known_ga_ids:
                errors.append(TimeProgramError(
                    tp.name,
                    f"Schaltzeitpunkt {sp.display_time}: Gruppenadresse '{sp.target_ga_id}' "
                    f"nicht gefunden.",
                    "error",
                ))
            # Zeitformat prüfen
            if sp.time_type == "FIXED":
                try:
                    h, m = sp.fixed_time.split(":")
                    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                        raise ValueError
                except (ValueError, AttributeError):
                    errors.append(TimeProgramError(
                        tp.name,
                        f"Ungültige Uhrzeit: '{sp.fixed_time}'.",
                        "error",
                    ))
            # Offset-Bereich
            if sp.time_type == "ASTRO" and not (-120 <= sp.astro_offset_min <= 120):
                errors.append(TimeProgramError(
                    tp.name,
                    f"Astro-Offset {sp.astro_offset_min} min ist ausserhalb von ±120 min.",
                    "warning",
                ))
            # Datumsbereich
            if sp.date_range_start and sp.date_range_end:
                try:
                    s = date.fromisoformat(sp.date_range_start)
                    e = date.fromisoformat(sp.date_range_end)
                    if s > e:
                        errors.append(TimeProgramError(
                            tp.name,
                            f"Datumsbereich: Start {sp.date_range_start} liegt nach Ende {sp.date_range_end}.",
                            "error",
                        ))
                except ValueError:
                    errors.append(TimeProgramError(
                        tp.name, "Ungültiger Datumsbereich.", "error"
                    ))
    return errors


def validate_all_programs(project) -> list[TimeProgramError]:
    """Validiert alle Zeitprogramme eines Projekts."""
    errors = []
    for tp in project.time_programs:
        errors.extend(validate_time_program(tp, project))
    return errors


# ── Astro-GA Autogenerierung (FA-3308) ────────────────────────────────────────

def ensure_astro_gas(project) -> int:
    """Erstellt fehlende Astro-Gruppen­adressen in HG0/MG7 (FA-3308).

    Standard-Astro-GAs gemaess Pflichtenheft FA-3308a:
    - 0/7/0  Uhrzeit und Datum  (DPT-19-1)   – Zeitstempel fuer Astro-Berechnungen
    - 0/7/1  Sonnenaufgang      (DPST-1-1)   – Schaltsignal bei Sonnenaufgang
    - 0/7/2  Sonnenuntergang    (DPST-1-1)   – Schaltsignal bei Sonnenuntergang
    - 0/7/3  Daemmerung aktiv   (DPST-1-1)   – True zwischen Daemmerungszeiten

    Gibt die Anzahl neu erzeugter GAs zurueck.
    """
    from ..models.group_address import GroupAddress, MainGroup, MiddleGroup

    ASTRO_GAS = [
        (0, "SYS.ASTRO.00_utc",  "Uhrzeit und Datum", "ASTRO_TIME", "DPT-19-1"),
        (1, "SYS.ASTRO.01_rise", "Sonnenaufgang",     "ASTRO",      "DPST-1-1"),
        (2, "SYS.ASTRO.02_set",  "Sonnenuntergang",   "ASTRO",      "DPST-1-1"),
        (3, "SYS.ASTRO.03_dusk", "Daemmerung aktiv",  "ASTRO",      "DPST-1-1"),
    ]

    structure = project.group_addresses
    # HG0 finden oder anlegen
    hg = next((g for g in structure.main_groups if g.number == 0), None)
    if hg is None:
        hg = MainGroup(number=0, name="Zentraladressen")
        structure.main_groups.insert(0, hg)

    # MG7 finden oder anlegen
    mg = next((m for m in hg.middle_groups if m.number == 7), None)
    if mg is None:
        mg = MiddleGroup(number=7, name="Astro")
        hg.middle_groups.append(mg)

    existing_subs = {ga.sub_group for ga in mg.group_addresses}
    count = 0
    for sub, designation, description, func, dpt in ASTRO_GAS:
        if sub not in existing_subs:
            ga = GroupAddress(
                main_group=0, middle_group=7, sub_group=sub,
                designation=designation,
                function_name=func,
                description=description,
                datapoint_type=dpt,
                central="true",
            )
            mg.group_addresses.append(ga)
            count += 1
    return count


def has_astro_switch_points(project) -> bool:
    """Gibt True zurueck wenn das Projekt aktive Astro-SwitchPoints hat (FA-3308b)."""
    try:
        return any(
            sp.time_type == "ASTRO"
            for tp in project.time_programs
            if tp.active
            for dp in tp.day_profiles
            for sp in dp.switch_points
        )
    except Exception:
        return False


# ── TimeProgramService ────────────────────────────────────────────────────────

class TimeProgramService:
    """Zentrale Verwaltung von Zeitschaltprogrammen."""

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_program(self, project, name: str = "Zeitprogramm") -> TimeProgram:
        tp = TimeProgram(name=name)
        project.time_programs.append(tp)
        logger.info(f"Zeitprogramm '{name}' angelegt (id={tp.id}).")
        return tp

    def remove_program(self, project, program_id: str) -> bool:
        before = len(project.time_programs)
        project.time_programs = [tp for tp in project.time_programs if tp.id != program_id]
        return len(project.time_programs) < before

    def get_program(self, project, program_id: str) -> Optional[TimeProgram]:
        return next((tp for tp in project.time_programs if tp.id == program_id), None)

    # ── Vorlagen ──────────────────────────────────────────────────────────────

    @staticmethod
    def list_templates() -> list[dict]:
        return load_templates()

    @staticmethod
    def create_from_template(template_id: str) -> Optional[TimeProgram]:
        return create_program_from_template(template_id)

    def add_from_template(self, project, template_id: str) -> Optional[TimeProgram]:
        tp = create_program_from_template(template_id)
        if tp is not None:
            project.time_programs.append(tp)
        return tp

    # ── Astro ─────────────────────────────────────────────────────────────────

    @staticmethod
    def calc_astro(event: str, d: date, location: ProjectLocation,
                   offset_min: int = 0) -> Optional[str]:
        return calc_astro_time(event, d, location, offset_min)

    @staticmethod
    def today_astro(project) -> dict[str, Optional[str]]:
        """Gibt Sonnenaufgang/Sonnenuntergang für heute zurück (Lokalzeit CH/DE/AT)."""
        loc = project.location
        today = date.today()
        return {
            "SUNRISE": calc_astro_time("SUNRISE", today, loc),
            "SUNSET": calc_astro_time("SUNSET", today, loc),
        }

    # ── Feiertage ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_holidays(country: str = "CH", year: Optional[int] = None) -> list[date]:
        return load_holidays(country, year)

    @staticmethod
    def is_holiday(d: date, country: str = "CH") -> bool:
        return is_holiday(d, country)

    # ── Validierung ───────────────────────────────────────────────────────────

    @staticmethod
    def validate(tp: TimeProgram, project) -> list[TimeProgramError]:
        return validate_time_program(tp, project)

    @staticmethod
    def validate_all(project) -> list[TimeProgramError]:
        return validate_all_programs(project)

    # ── Astro-GAs (FA-3308) ───────────────────────────────────────────────────

    @staticmethod
    def ensure_astro_gas(project) -> int:
        return ensure_astro_gas(project)

    # ── DayProfile-Hilfsfunktionen ────────────────────────────────────────────

    @staticmethod
    def add_day_profile(tp: TimeProgram, weekday_mask: int = WEEKDAY_MON_FRI) -> DayProfile:
        dp = DayProfile(weekday_mask=weekday_mask)
        tp.day_profiles.append(dp)
        return dp

    @staticmethod
    def add_switch_point(dp: DayProfile, **kwargs) -> SwitchPoint:
        sp = SwitchPoint(**kwargs)
        dp.switch_points.append(sp)
        return sp

    @staticmethod
    def remove_switch_point(dp: DayProfile, sp_id: str) -> bool:
        before = len(dp.switch_points)
        dp.switch_points = [sp for sp in dp.switch_points if sp.id != sp_id]
        return len(dp.switch_points) < before

    # ── Zusammenfassung (FA-3307) ─────────────────────────────────────────────

    @staticmethod
    def get_summary(project) -> dict:
        total = len(project.time_programs)
        active = sum(1 for tp in project.time_programs if tp.active)
        total_sp = sum(tp.switch_point_count for tp in project.time_programs)
        has_astro = any(tp.has_astro for tp in project.time_programs)
        return {
            "total": total,
            "active": active,
            "switch_point_count": total_sp,
            "has_astro": has_astro,
            "location": {
                "latitude": project.location.latitude,
                "longitude": project.location.longitude,
                "country": project.location.country,
            },
        }
