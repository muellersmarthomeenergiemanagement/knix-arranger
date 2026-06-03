"""Tests fuer Zeitsteuerung (FA-2901–2906, FA-3301–3308)."""
import pytest
from datetime import date

from knix_arranger.models.time_program import (
    SwitchPoint, DayProfile, TimeProgram, ProjectLocation,
    WEEKDAY_MON, WEEKDAY_TUE, WEEKDAY_WED, WEEKDAY_THU, WEEKDAY_FRI,
    WEEKDAY_SAT, WEEKDAY_SUN, WEEKDAY_HOL,
    WEEKDAY_MON_FRI, WEEKDAY_ALL,
    mask_to_day_names,
)
from knix_arranger.services.time_program_service import (
    TimeProgramService, calc_astro_time, load_holidays, is_holiday,
    load_templates, create_program_from_template,
    validate_time_program, validate_all_programs,
    ensure_astro_gas,
)
from knix_arranger.models.project import KnxProject


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project() -> KnxProject:
    return KnxProject(name="Zeit-Test")


def _make_project_with_gas() -> KnxProject:
    """Projekt mit einigen GAs."""
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress
    )
    project = KnxProject(name="Zeit-GA-Test")
    structure = GroupAddressStructure()
    hg = MainGroup(number=1, name="Licht")
    mg = MiddleGroup(number=0, name="EG")
    mg.group_addresses = [
        GroupAddress(main_group=1, middle_group=0, sub_group=0,
                     designation="L.EG.01_ea", function_name="Schalten"),
        GroupAddress(main_group=1, middle_group=0, sub_group=1,
                     designation="L.EG.02_ea", function_name="Dimmen"),
    ]
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    project.group_addresses = structure
    return project


# ── Datenmodell ────────────────────────────────────────────────────────────────

class TestWeekdayConstants:
    def test_mon_fri_mask(self):
        assert WEEKDAY_MON_FRI == 0b0011111   # 31

    def test_all_mask(self):
        assert WEEKDAY_ALL == 0b1111111   # 127

    def test_mask_to_day_names_mon_fri(self):
        names = mask_to_day_names(WEEKDAY_MON_FRI)
        assert "Mo" in names
        assert "Fr" in names
        assert "Sa" not in names
        assert "So" not in names

    def test_mask_to_day_names_weekend(self):
        names = mask_to_day_names(WEEKDAY_SAT | WEEKDAY_SUN)
        assert names == ["Sa", "So"]

    def test_mask_to_day_names_holiday(self):
        names = mask_to_day_names(WEEKDAY_HOL)
        assert "FT" in names


class TestSwitchPoint:
    def test_default_fixed(self):
        sp = SwitchPoint()
        assert sp.time_type == "FIXED"
        assert sp.fixed_time == "08:00"

    def test_display_time_fixed(self):
        sp = SwitchPoint(fixed_time="14:30")
        assert sp.display_time == "14:30"

    def test_display_time_astro_no_offset(self):
        sp = SwitchPoint(time_type="ASTRO", astro_event="SUNRISE", astro_offset_min=0)
        assert "Sunrise" in sp.display_time or "SUNRISE" in sp.display_time.upper()

    def test_display_time_astro_with_offset(self):
        sp = SwitchPoint(time_type="ASTRO", astro_event="SUNSET", astro_offset_min=30)
        assert "+30 min" in sp.display_time

    def test_serialization_roundtrip(self):
        sp = SwitchPoint(
            time_type="ASTRO", astro_event="SUNRISE", astro_offset_min=-15,
            action_value="0", priority="Erhöht", date_range_start="2026-01-01",
        )
        restored = SwitchPoint.from_dict(sp.to_dict())
        assert restored.time_type == "ASTRO"
        assert restored.astro_offset_min == -15
        assert restored.priority == "Erhöht"
        assert restored.date_range_start == "2026-01-01"


class TestDayProfile:
    def test_default_mask(self):
        dp = DayProfile()
        assert dp.weekday_mask == WEEKDAY_MON_FRI

    def test_weekdays_property(self):
        dp = DayProfile(weekday_mask=WEEKDAY_SAT | WEEKDAY_SUN)
        assert dp.weekdays == ["Sa", "So"]

    def test_serialization_roundtrip(self):
        dp = DayProfile(weekday_mask=WEEKDAY_ALL)
        dp.switch_points = [SwitchPoint(fixed_time="07:00"), SwitchPoint(fixed_time="22:00")]
        restored = DayProfile.from_dict(dp.to_dict())
        assert restored.weekday_mask == WEEKDAY_ALL
        assert len(restored.switch_points) == 2


class TestTimeProgram:
    def test_default(self):
        tp = TimeProgram()
        assert tp.active is True
        assert tp.switch_point_count == 0

    def test_switch_point_count(self):
        tp = TimeProgram()
        dp = DayProfile()
        dp.switch_points = [SwitchPoint(), SwitchPoint()]
        tp.day_profiles = [dp]
        assert tp.switch_point_count == 2

    def test_has_astro_false(self):
        tp = TimeProgram()
        dp = DayProfile()
        dp.switch_points = [SwitchPoint(time_type="FIXED")]
        tp.day_profiles = [dp]
        assert not tp.has_astro

    def test_has_astro_true(self):
        tp = TimeProgram()
        dp = DayProfile()
        dp.switch_points = [SwitchPoint(time_type="ASTRO")]
        tp.day_profiles = [dp]
        assert tp.has_astro

    def test_serialization_roundtrip(self):
        tp = TimeProgram(name="Beschattung", active=False)
        dp = DayProfile(weekday_mask=WEEKDAY_ALL)
        dp.switch_points = [SwitchPoint(time_type="ASTRO", astro_event="SUNRISE")]
        tp.day_profiles = [dp]
        restored = TimeProgram.from_dict(tp.to_dict())
        assert restored.name == "Beschattung"
        assert restored.active is False
        assert restored.has_astro

    def test_all_switch_points(self):
        tp = TimeProgram()
        dp1 = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        dp1.switch_points = [SwitchPoint(), SwitchPoint()]
        dp2 = DayProfile(weekday_mask=WEEKDAY_SAT | WEEKDAY_SUN)
        dp2.switch_points = [SwitchPoint()]
        tp.day_profiles = [dp1, dp2]
        pairs = tp.all_switch_points
        assert len(pairs) == 3


class TestProjectLocation:
    def test_default_zurich(self):
        loc = ProjectLocation()
        assert abs(loc.latitude - 47.37) < 0.01
        assert loc.country == "CH"

    def test_serialization_roundtrip(self):
        loc = ProjectLocation(latitude=48.1, longitude=11.6, country="DE", region="BY")
        restored = ProjectLocation.from_dict(loc.to_dict())
        assert restored.latitude == pytest.approx(48.1)
        assert restored.country == "DE"
        assert restored.region == "BY"


# ── Projekt-Integration (FA-3301b, FA-3303a) ───────────────────────────────────

class TestProjectIntegration:
    def test_project_has_time_programs(self):
        project = KnxProject()
        assert hasattr(project, "time_programs")
        assert isinstance(project.time_programs, list)

    def test_project_has_location(self):
        project = KnxProject()
        assert hasattr(project, "location")
        assert isinstance(project.location, ProjectLocation)

    def test_serialization_preserves_programs(self):
        project = KnxProject(name="ZeitProjekt")
        tp = TimeProgram(name="Test-Programm")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        dp.switch_points = [SwitchPoint(fixed_time="06:00", action_value="1")]
        tp.day_profiles = [dp]
        project.time_programs.append(tp)
        project.location.latitude = 48.5
        project.location.country = "AT"

        restored = KnxProject.from_dict(project.to_dict())
        assert len(restored.time_programs) == 1
        assert restored.time_programs[0].name == "Test-Programm"
        assert restored.location.country == "AT"
        assert restored.location.latitude == pytest.approx(48.5)


# ── Astro-Berechnung (FA-3303) ────────────────────────────────────────────────

class TestAstroCalc:
    def test_sunrise_returns_string(self):
        loc = ProjectLocation(latitude=47.37, longitude=8.54)
        result = calc_astro_time("SUNRISE", date(2026, 6, 21), loc)
        assert result is not None
        assert ":" in result

    def test_sunset_returns_string(self):
        loc = ProjectLocation(latitude=47.37, longitude=8.54)
        result = calc_astro_time("SUNSET", date(2026, 6, 21), loc)
        assert result is not None
        assert ":" in result

    def test_sunrise_before_sunset(self):
        loc = ProjectLocation(latitude=47.37, longitude=8.54)
        rise = calc_astro_time("SUNRISE", date(2026, 3, 15), loc)
        sset = calc_astro_time("SUNSET", date(2026, 3, 15), loc)
        assert rise < sset

    def test_summer_sunrise_earlier_than_winter(self):
        loc = ProjectLocation(latitude=47.37, longitude=8.54)
        summer = calc_astro_time("SUNRISE", date(2026, 6, 21), loc)
        winter = calc_astro_time("SUNRISE", date(2026, 12, 21), loc)
        assert summer < winter  # Sommer: früherer Sonnenaufgang (UTC+1)

    def test_offset_shifts_time(self):
        loc = ProjectLocation(latitude=47.37, longitude=8.54)
        base = calc_astro_time("SUNRISE", date(2026, 4, 1), loc, offset_min=0)
        late = calc_astro_time("SUNRISE", date(2026, 4, 1), loc, offset_min=30)
        # Offset +30 → spätere Zeit
        assert late > base

    def test_service_today_astro(self):
        project = _make_project()
        svc = TimeProgramService()
        result = svc.today_astro(project)
        assert "SUNRISE" in result
        assert "SUNSET" in result


# ── Feiertagskalender (FA-3304) ───────────────────────────────────────────────

class TestHolidays:
    def test_load_returns_list(self):
        holidays = load_holidays("CH")
        assert isinstance(holidays, list)

    def test_ch_neujahr_2025(self):
        holidays = load_holidays("CH", year=2025)
        assert date(2025, 1, 1) in holidays

    def test_de_tag_der_deutschen_einheit(self):
        holidays = load_holidays("DE", year=2025)
        assert date(2025, 10, 3) in holidays

    def test_at_nationalfeiertag(self):
        holidays = load_holidays("AT", year=2025)
        assert date(2025, 10, 26) in holidays

    def test_is_holiday_true(self):
        assert is_holiday(date(2025, 1, 1), "CH")

    def test_is_holiday_false(self):
        assert not is_holiday(date(2025, 1, 15), "CH")

    def test_service_get_holidays(self):
        svc = TimeProgramService()
        h = svc.get_holidays("CH", 2025)
        assert len(h) > 0

    def test_service_is_holiday(self):
        svc = TimeProgramService()
        assert svc.is_holiday(date(2025, 1, 1), "CH")


# ── Vorlagen (FA-3305) ────────────────────────────────────────────────────────

class TestTemplates:
    def test_load_returns_templates(self):
        templates = load_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0

    def test_beschattung_template_exists(self):
        templates = load_templates()
        ids = [t["id"] for t in templates]
        assert "beschattung_standard" in ids

    def test_create_from_template_beschattung(self):
        tp = create_program_from_template("beschattung_standard")
        assert tp is not None
        assert tp.has_astro

    def test_create_from_template_unknown(self):
        tp = create_program_from_template("nicht_vorhanden_xyz")
        assert tp is None

    def test_service_add_from_template(self):
        project = _make_project()
        svc = TimeProgramService()
        tp = svc.add_from_template(project, "beschattung_standard")
        assert tp is not None
        assert len(project.time_programs) == 1
        assert tp.has_astro


# ── TimeProgramService – CRUD ─────────────────────────────────────────────────

class TestTimeProgramService:
    def setup_method(self):
        self.svc = TimeProgramService()
        self.project = _make_project()

    def test_add_program(self):
        tp = self.svc.add_program(self.project, "Licht")
        assert len(self.project.time_programs) == 1
        assert tp.name == "Licht"

    def test_remove_program(self):
        tp = self.svc.add_program(self.project)
        result = self.svc.remove_program(self.project, tp.id)
        assert result is True
        assert len(self.project.time_programs) == 0

    def test_remove_nonexistent(self):
        result = self.svc.remove_program(self.project, "not-an-id")
        assert result is False

    def test_get_program(self):
        tp = self.svc.add_program(self.project, "Test")
        found = self.svc.get_program(self.project, tp.id)
        assert found is tp

    def test_add_day_profile(self):
        tp = self.svc.add_program(self.project)
        dp = self.svc.add_day_profile(tp, WEEKDAY_SAT | WEEKDAY_SUN)
        assert dp in tp.day_profiles
        assert dp.weekday_mask == WEEKDAY_SAT | WEEKDAY_SUN

    def test_add_and_remove_switch_point(self):
        tp = self.svc.add_program(self.project)
        dp = self.svc.add_day_profile(tp)
        sp = self.svc.add_switch_point(dp, fixed_time="09:00")
        assert sp in dp.switch_points
        removed = self.svc.remove_switch_point(dp, sp.id)
        assert removed is True
        assert sp not in dp.switch_points

    def test_get_summary(self):
        tp = self.svc.add_program(self.project, "P1")
        dp = self.svc.add_day_profile(tp)
        self.svc.add_switch_point(dp, fixed_time="06:00")
        summary = self.svc.get_summary(self.project)
        assert summary["total"] == 1
        assert summary["active"] == 1
        assert summary["switch_point_count"] == 1
        assert "location" in summary

    def test_list_templates(self):
        templates = self.svc.list_templates()
        assert len(templates) > 0


# ── Validierung (FA-3306) ─────────────────────────────────────────────────────

class TestValidation:
    def setup_method(self):
        self.project = _make_project_with_gas()
        self.svc = TimeProgramService()

    def test_valid_program_no_errors(self):
        tp = TimeProgram(name="Valid")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        dp.switch_points = [SwitchPoint(fixed_time="08:00")]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert errors == []

    def test_empty_weekday_mask_warning(self):
        tp = TimeProgram(name="Leer")
        dp = DayProfile(weekday_mask=0)
        dp.switch_points = [SwitchPoint(fixed_time="08:00")]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert any(e.severity == "warning" for e in errors)

    def test_invalid_ga_reference(self):
        tp = TimeProgram(name="BadGA")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        sp = SwitchPoint(fixed_time="08:00", target_ga_id="nonexistent-ga-id")
        dp.switch_points = [sp]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert any(e.severity == "error" for e in errors)

    def test_valid_ga_reference_no_error(self):
        gas = list(self.project.group_addresses.all_addresses())
        tp = TimeProgram(name="GoodGA")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        sp = SwitchPoint(fixed_time="08:00", target_ga_id=gas[0].id)
        dp.switch_points = [sp]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert not any(e.severity == "error" for e in errors)

    def test_astro_offset_out_of_range(self):
        tp = TimeProgram(name="BigOffset")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        sp = SwitchPoint(time_type="ASTRO", astro_event="SUNRISE", astro_offset_min=200)
        dp.switch_points = [sp]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert any("Offset" in e.message for e in errors)

    def test_invalid_date_range(self):
        tp = TimeProgram(name="BadDate")
        dp = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        sp = SwitchPoint(fixed_time="08:00",
                         date_range_start="2026-12-31",
                         date_range_end="2026-01-01")
        dp.switch_points = [sp]
        tp.day_profiles = [dp]
        errors = validate_time_program(tp, self.project)
        assert any(e.severity == "error" for e in errors)

    def test_validate_all(self):
        self.project.time_programs = []
        tp1 = TimeProgram(name="OK")
        dp1 = DayProfile(weekday_mask=WEEKDAY_MON_FRI)
        dp1.switch_points = [SwitchPoint()]
        tp1.day_profiles = [dp1]
        self.project.time_programs.append(tp1)

        tp2 = TimeProgram(name="Bad")
        dp2 = DayProfile(weekday_mask=0)
        tp2.day_profiles = [dp2]
        self.project.time_programs.append(tp2)

        errors = validate_all_programs(self.project)
        assert any(e.program_name == "Bad" for e in errors)

    def test_service_validate(self):
        tp = TimeProgram(name="ServiceTest")
        dp = DayProfile(weekday_mask=WEEKDAY_ALL)
        dp.switch_points = [SwitchPoint(fixed_time="06:00")]
        tp.day_profiles = [dp]
        errors = self.svc.validate(tp, self.project)
        assert isinstance(errors, list)


# ── Astro-GAs (FA-3308) ───────────────────────────────────────────────────────

class TestAstroGas:
    def test_ensure_astro_gas_creates_four(self):
        project = _make_project()
        n = ensure_astro_gas(project)
        assert n == 4

    def test_ensure_astro_gas_idempotent(self):
        project = _make_project()
        ensure_astro_gas(project)
        n2 = ensure_astro_gas(project)
        assert n2 == 0  # Bereits vorhanden

    def test_astro_gas_in_hg0_mg7(self):
        project = _make_project()
        ensure_astro_gas(project)
        hg = next((g for g in project.group_addresses.main_groups if g.number == 0), None)
        assert hg is not None
        mg = next((m for m in hg.middle_groups if m.number == 7), None)
        assert mg is not None
        assert len(mg.group_addresses) == 4

    def test_service_ensure_astro_gas(self):
        project = _make_project()
        svc = TimeProgramService()
        n = svc.ensure_astro_gas(project)
        assert n == 4
