"""Tests fuer den Lizenz-Service (RSA-signierte .knxlic-Dateien, NFA-098)."""
import os
import json
import base64
import pytest
from datetime import date, timedelta

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization

import knix_arranger.services.license_service as _ls_module
from knix_arranger.services.license_service import (
    LicenseService, LicenseInfo, GRACE_PERIOD_DAYS, WARNING_DAYS,
)


@pytest.fixture(scope="module")
def rsa_keypair():
    """Erzeugt ein Test-RSA-Schluesselpaar, das den Produktiv-Public-Key ersetzt."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_pem


@pytest.fixture
def license_svc(tmp_path, monkeypatch, rsa_keypair):
    """LicenseService mit Test-Public-Key und tmp_path als APPDATA_DIR."""
    _, public_pem = rsa_keypair
    monkeypatch.setattr(_ls_module, "APPDATA_DIR", str(tmp_path))
    monkeypatch.setattr(_ls_module, "_PUBLIC_KEY_PEM", public_pem)
    svc = LicenseService()
    svc._license_file = str(tmp_path / "license.knxlic")
    return svc


def _sign_payload(private_key, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    sig = private_key.sign(
        canonical,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _write_license_file(path, private_key, payload: dict):
    data = {"payload": payload, "signature": _sign_payload(private_key, payload)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_payload(license_type="single", expiry=None, issued=None,
                   customer="Max Muster", email="max@example.com"):
    return {
        "customer": customer,
        "email": email,
        "type": license_type,
        "expiry": expiry or "2099-12-31",
        "issued": issued or "2026-01-01",
    }


class TestLicenseValidation:
    def test_validate_valid_license(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        path = tmp_path / "valid.knxlic"
        _write_license_file(path, private_key, _make_payload(license_type="annual", expiry="2099-12-31"))

        info = license_svc.validate_license_file(str(path))
        assert info.is_valid
        assert info.license_type == "annual"
        assert info.customer == "Max Muster"
        assert info.expiry_date == "2099-12-31"

    def test_validate_missing_file(self, license_svc, tmp_path):
        info = license_svc.validate_license_file(str(tmp_path / "missing.knxlic"))
        assert not info.is_valid
        assert "keine lizenzdatei" in info.message.lower()

    def test_validate_corrupted_json(self, license_svc, tmp_path):
        path = tmp_path / "broken.knxlic"
        path.write_text("{not valid json", encoding="utf-8")

        info = license_svc.validate_license_file(str(path))
        assert not info.is_valid
        assert "beschädigt" in info.message.lower()

    def test_validate_tampered_payload(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        path = tmp_path / "tampered.knxlic"
        _write_license_file(path, private_key, _make_payload())

        # Payload nach dem Signieren manipulieren -> Signatur passt nicht mehr
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["payload"]["customer"] = "Anderer Name"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        info = license_svc.validate_license_file(str(path))
        assert not info.is_valid
        assert "ungültig" in info.message.lower()

    def test_validate_wrong_key(self, license_svc, tmp_path):
        """Lizenzdatei signiert mit einem fremden Schluessel -> ungueltig."""
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path = tmp_path / "wrongkey.knxlic"
        _write_license_file(path, other_key, _make_payload())

        info = license_svc.validate_license_file(str(path))
        assert not info.is_valid

    def test_validate_expired_outside_grace(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        expiry = (date.today() - timedelta(days=GRACE_PERIOD_DAYS + 5)).isoformat()
        path = tmp_path / "expired.knxlic"
        _write_license_file(path, private_key, _make_payload(expiry=expiry))

        info = license_svc.validate_license_file(str(path))
        assert not info.is_valid
        assert "abgelaufen" in info.message.lower()

    def test_validate_expired_within_grace_period(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        expiry = (date.today() - timedelta(days=3)).isoformat()
        path = tmp_path / "grace.knxlic"
        _write_license_file(path, private_key, _make_payload(expiry=expiry))

        info = license_svc.validate_license_file(str(path))
        assert info.is_valid
        assert info.in_grace_period
        assert info.warning

    def test_validate_warning_before_expiry(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        expiry = (date.today() + timedelta(days=10)).isoformat()
        path = tmp_path / "soon.knxlic"
        _write_license_file(path, private_key, _make_payload(expiry=expiry))

        info = license_svc.validate_license_file(str(path))
        assert info.is_valid
        assert info.warning  # < WARNING_DAYS Tage bis Ablauf


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
        # ISO-Zeitstempel enthält ein "T" als Datum/Zeit-Trenner
        assert "T" in content

    def test_idempotent_mark(self, license_svc):
        """Mehrfaches Aufrufen ist kein Fehler."""
        license_svc.mark_eula_accepted()
        license_svc.mark_eula_accepted()
        assert license_svc.is_eula_accepted()


class TestImportAndCheckLicense:
    def test_check_license_invalid_without_key(self, license_svc):
        info = license_svc.check_license()
        assert not info.is_valid

    def test_import_license_copies_file(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        source = tmp_path / "incoming.knxlic"
        _write_license_file(source, private_key, _make_payload(expiry="2099-12-31"))

        info = license_svc.import_license(str(source))
        assert info.is_valid
        assert os.path.exists(license_svc._license_file)

    def test_check_license_valid_after_import(self, license_svc, rsa_keypair, tmp_path):
        private_key, _ = rsa_keypair
        source = tmp_path / "incoming.knxlic"
        _write_license_file(source, private_key, _make_payload(expiry="2099-12-31"))
        license_svc.import_license(str(source))

        info = license_svc.check_license()
        assert info.is_valid

    def test_import_invalid_license_not_copied(self, license_svc, tmp_path):
        source = tmp_path / "invalid.knxlic"
        source.write_text("{not valid json", encoding="utf-8")

        info = license_svc.import_license(str(source))
        assert not info.is_valid
        assert not os.path.exists(license_svc._license_file)
