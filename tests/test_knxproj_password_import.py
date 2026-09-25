"""
Tests fuer den Import passwortgeschuetzter ETS6-Projekte (FA-524/525):
P-XXXX.zip ist mit einem aus dem Projektpasswort abgeleiteten Schluessel
AES-verschluesselt; ein Cloud-Lizenz-Zertifikat verhindert den Import nicht.
"""
from __future__ import annotations
import io
import os
import zipfile

import pytest

pyzipper = pytest.importorskip("pyzipper")

from knix_arranger.services.knxproj_import_service import (
    KnxprojImportService, KnxprojPasswordRequired, KnxprojPasswordWrong,
)

CHALET = os.path.join(os.path.dirname(__file__), "..", "241114_Chalet 64.knxproj")
PASSWORD = "Test_Passwort_2026"


def _encrypted_zip(files: dict[str, bytes], zip_password: bytes) -> bytes:
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(zip_password)
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_ets6_derived_password_is_found():
    svc = KnxprojImportService()
    derived, raw = svc._zip_password_candidates(PASSWORD)
    data = _encrypted_zip({"project.xml": b"<KNX/>"}, derived)
    assert svc._find_zip_password(data, PASSWORD) == derived
    assert svc._find_zip_password(data, "falsch") is None


def test_unchanged_password_still_accepted():
    svc = KnxprojImportService()
    data = _encrypted_zip({"project.xml": b"<KNX/>"}, PASSWORD.encode("utf-8"))
    assert svc._find_zip_password(data, PASSWORD) == PASSWORD.encode("utf-8")


@pytest.fixture
def encrypted_chalet(tmp_path):
    """Chalet 64 wie ein ETS6-Export mit Passwort: Projektdaten in einer
    verschluesselten P-06C2.zip, Cloud-Lizenz-Zertifikat daneben."""
    if not os.path.exists(CHALET):
        pytest.skip("Referenzprojekt 241114_Chalet 64.knxproj fehlt")
    derived = KnxprojImportService._zip_password_candidates(PASSWORD)[0]
    with zipfile.ZipFile(CHALET) as src:
        inner = {
            name[len("P-06C2/"):]: src.read(name)
            for name in src.namelist()
            if name.startswith("P-06C2/") and not name.endswith("/")
        }
        outer = {
            name: src.read(name) for name in src.namelist()
            if not name.startswith("P-06C2/") and not name.endswith("/")
        }
    path = tmp_path / "verschluesselt.knxproj"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in outer.items():
            zf.writestr(name, data)
        zf.writestr("P-06C2.zip", _encrypted_zip(inner, derived))
    return str(path)


def test_encrypted_project_with_cloud_certificate(encrypted_chalet):
    svc = KnxprojImportService()
    with pytest.raises(KnxprojPasswordRequired):
        svc.import_knxproj(encrypted_chalet)
    with pytest.raises(KnxprojPasswordWrong):
        svc.import_knxproj(encrypted_chalet, password="falsch")

    project = svc.import_knxproj(encrypted_chalet, password=PASSWORD)
    devices = [d for a in project.topology.areas for l in a.lines for d in l.devices]
    assert len(devices) == 72
    assert project.group_addresses.all_addresses()
