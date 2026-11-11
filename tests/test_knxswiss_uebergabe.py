"""Ergänzungen nach der KNX-Swiss-Planungshilfe (Anhang 5.1/5.2) und dem
Merkblatt ETS-Konfigurationsdatei: Prüfpunkte der Inbetriebnahme,
Stromunterbruch in der Bedienungsanleitung, Übergabe im Abnahmeprotokoll."""
import json
import os

import fitz
import pytest

from knix_arranger.models.knx_secure import KnxSecureConfig
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.documentation_service import DocumentationService

I18N = os.path.join(os.path.dirname(__file__), "..", "knix_arranger", "i18n")


def _project(secure=True) -> KnxProject:
    project = KnxProject(name="Übergabe")
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=[
        Device(physical_address="1.1.0", device_type="coupler", product="LK/S4.2.1",
               installation_location="UV EG"),
        Device(physical_address="1.1.1", device_type="actor", product="Schaltaktor secure",
               installation_location="UV EG"),
        Device(physical_address="1.1.2", device_type="gateway", product="Wetterstation GPS",
               installation_location="UV EG"),
    ])])]
    project.knx_secure = KnxSecureConfig(enabled=secure)
    return project


def _checks(project) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for cl in DocumentationService(project).create_checklists():
        for item in cl.items:
            result.setdefault(item.be_number, set()).add(item.check_type)
    return result


def test_zusaetzliche_pruefpunkte_im_verteiler():
    checks = _checks(_project())
    assert "Filtertabelle" in checks["1.1.0"]
    assert "KNX Secure" in checks["1.1.1"] and "Filtertabelle" not in checks["1.1.1"]
    assert "Kalibrierung" in checks["1.1.2"]


def test_secure_pruefpunkt_nur_bei_aktiviertem_secure():
    assert "KNX Secure" not in _checks(_project(secure=False))["1.1.1"]


def test_pruefpunkte_im_ausdruck(tmp_path):
    path = str(tmp_path / "checkliste.pdf")
    DocumentationService(_project()).export_checklists_pdf(path)
    text = "".join(page.get_text() for page in fitz.open(path))
    assert "Filtertabelle aktiviert" in text
    assert "KNX Secure aktiviert" in text
    assert "kalibriert" in text


@pytest.mark.parametrize("lang,word", [("de", "Stromunterbruch"), ("fr", "coupure de courant"),
                                       ("it", "interruzione di corrente"), ("en", "power failure")])
def test_anleitung_stromunterbruch_in_allen_sprachen(lang, word):
    with open(os.path.join(I18N, f"manual_{lang}.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert word in data["texts"]["stoerungen"]


def test_abnahmeprotokoll_uebergabe(tmp_path):
    path = str(tmp_path / "abnahme.pdf")
    DocumentationService(_project()).export_acceptance_protocol(path)
    text = "".join(page.get_text() for page in fitz.open(path))
    assert "ETS-Bericht «Projekt-Sicherheit»" in text
    assert "A: dem Bauherrn übergeben, inklusive Passwörter" in text
    assert "B: beim Integrator aufbewahrt" in text
    assert "Physikalische Adressen an den Geräten beschriftet" in text
    assert "Verhalten bei Stromunterbruch" in text
