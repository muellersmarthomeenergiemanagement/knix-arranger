"""
Tests fuer CompanyProfile (FA-851-857, FA-1707 Aufwandsschaetzung).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.company_profile import CompanyProfile


class TestEffortEstimationDefaults:
    """Default-Richtwerte fuer die automatische Aufwandsschaetzung (FA-1707)."""

    def test_default_values(self):
        p = CompanyProfile()
        assert p.minutes_programming_per_device == 22.0
        assert p.minutes_commissioning_per_device == 22.0
        assert p.commissioning_base_hours == 2.0
        assert p.minutes_documentation_per_device == 5.0
        assert p.documentation_base_hours == 1.0
        assert p.hourly_rate_documentation == 125.0

    def test_to_dict_contains_effort_keys(self):
        p = CompanyProfile()
        d = p.to_dict()
        for key in (
            "minutes_programming_per_device",
            "minutes_commissioning_per_device",
            "commissioning_base_hours",
            "minutes_documentation_per_device",
            "documentation_base_hours",
            "hourly_rate_documentation",
        ):
            assert key in d

    def test_round_trip_preserves_custom_values(self):
        p = CompanyProfile(
            minutes_programming_per_device=30.0,
            minutes_commissioning_per_device=18.5,
            commissioning_base_hours=4.0,
            minutes_documentation_per_device=12.0,
            documentation_base_hours=2.5,
            hourly_rate_documentation=99.0,
        )
        restored = CompanyProfile.from_dict(p.to_dict())
        assert restored.minutes_programming_per_device == 30.0
        assert restored.minutes_commissioning_per_device == 18.5
        assert restored.commissioning_base_hours == 4.0
        assert restored.minutes_documentation_per_device == 12.0
        assert restored.documentation_base_hours == 2.5
        assert restored.hourly_rate_documentation == 99.0

    def test_from_dict_defaults_for_missing_keys(self):
        p = CompanyProfile.from_dict({})
        assert p.minutes_programming_per_device == 22.0
        assert p.minutes_commissioning_per_device == 22.0
        assert p.commissioning_base_hours == 2.0
        assert p.minutes_documentation_per_device == 5.0
        assert p.documentation_base_hours == 1.0
        assert p.hourly_rate_documentation == 125.0
