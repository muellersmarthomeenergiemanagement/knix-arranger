"""Tests fuer den Lizenz-Service."""
import os
import pytest
import knix_arranger.services.license_service as _ls_module
from knix_arranger.services.license_service import LicenseService, LicenseInfo


@pytest.fixture
def license_svc(tmp_path, monkeypatch):
    """LicenseService mit tmp_path als APPDATA_DIR, um echtes AppData nicht zu berühren."""
    monkeypatch.setattr(_ls_module, "APPDATA_DIR", str(tmp_path))
    svc = LicenseService()
    svc._license_file = str(tmp_path / "license.dat")
    return svc


class TestLicenseGeneration:
    def test_generate_key_format(self):
        svc = LicenseService()
        key = svc.generate_key("single", "2027-02-13")
        assert key.startswith("KNiX-")
        assert len(key) == 19
        assert key.count("-") == 3

    def test_generate_annual_key(self):
        svc = LicenseService()
        key = svc.generate_key("annual", "2027-06-01")
        parts = key.split("-")
        assert parts[1][0] == "A"  # Annual

    def test_generate_trial_key(self):
        svc = LicenseService()
        key = svc.generate_key("trial", "2026-06-01")
        parts = key.split("-")
        assert parts[1][0] == "T"  # Trial


class TestLicenseValidation:
    def test_validate_generated_key(self):
        svc = LicenseService()
        key = svc.generate_key("single", "2027-12-31")
        info = svc.validate_key(key)
        assert info.is_valid
        assert info.license_type == "single"

    def test_validate_annual_key(self):
        svc = LicenseService()
        key = svc.generate_key("annual", "2027-12-31")
        info = svc.validate_key(key)
        assert info.is_valid
        assert info.license_type == "annual"

    def test_validate_invalid_format(self):
        svc = LicenseService()
        info = svc.validate_key("INVALID-KEY")
        assert not info.is_valid
        assert "format" in info.message.lower() or "Format" in info.message

    def test_validate_wrong_checksum(self):
        svc = LicenseService()
        info = svc.validate_key("KNiX-AAAA-0400-XXXX")
        assert not info.is_valid

    def test_validate_expired_key(self):
        svc = LicenseService()
        key = svc.generate_key("trial", "2025-01-01")
        info = svc.validate_key(key)
        assert not info.is_valid
        assert "abgelaufen" in info.message.lower()


class TestLicenseInfo:
    def test_not_expired_no_date(self):
        info = LicenseInfo()
        assert not info.is_expired()

    def test_expired_past_date(self):
        info = LicenseInfo()
        info.expiry_date = "2020-01-01"
        assert info.is_expired()

    def test_not_expired_future_date(self):
        info = LicenseInfo()
        info.expiry_date = "2030-01-01"
        assert not info.is_expired()


class TestEulaAcceptance:
    def test_not_accepted_initially(self, license_svc):
        assert not license_svc.is_eula_accepted()

    def test_accepted_after_mark(self, license_svc):
        license_svc.mark_eula_accepted()
        assert license_svc.is_eula_accepted()

    def test_mark_creates_file(self, license_svc, tmp_path):
        license_svc.mark_eula_accepted()
        eula_file = tmp_path / "eula_accepted.dat"
        assert eula_file.exists()

    def test_mark_writes_timestamp(self, license_svc, tmp_path):
        license_svc.mark_eula_accepted()
        content = (tmp_path / "eula_accepted.dat").read_text(encoding="utf-8")
        # ISO-Zeitstempel enthält mindestens Jahr und Trennzeichen
        assert "2026" in content or "T" in content

    def test_idempotent_mark(self, license_svc):
        """Mehrfaches Aufrufen ist kein Fehler."""
        license_svc.mark_eula_accepted()
        license_svc.mark_eula_accepted()
        assert license_svc.is_eula_accepted()

    def test_save_and_load_license_uses_tmp(self, license_svc):
        """Stellt sicher dass der Lizenzschlüssel im tmp-Verzeichnis gespeichert wird."""
        key = license_svc.generate_key("single", "2027-12-31")
        license_svc.save_license(key)
        assert license_svc.load_license() == key

    def test_check_license_valid_after_save(self, license_svc):
        key = license_svc.generate_key("single", "2027-12-31")
        license_svc.save_license(key)
        info = license_svc.check_license()
        assert info.is_valid

    def test_check_license_invalid_without_key(self, license_svc):
        info = license_svc.check_license()
        assert not info.is_valid
