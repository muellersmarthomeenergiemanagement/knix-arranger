"""Kundenofferte übernimmt Name und Adresse aus dem Kundenprofil."""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from unittest.mock import patch

from knix_arranger.models.client_profile import ClientProfile
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.project import KnxProject
from knix_arranger.services.project_service import ProjectService
from knix_arranger.ui.views.customer_quote_view import CustomerQuoteView, address_block

fitz = pytest.importorskip("fitz")


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project() -> KnxProject:
    project = KnxProject(name="Chalet")
    project.client_profile = ClientProfile(
        name="Franziska Muster", contact_address="Postfach 12, 3780 Gstaad",
        object_address="Chaletweg 5, 3780 Gstaad",
        salutation="Sehr geehrte Frau Muster")
    return project


def test_adresse_wird_zum_adressblock():
    assert address_block("Postfach 12, 3780 Gstaad") == "Postfach 12\n3780 Gstaad"
    assert address_block("Weg 1\n3780 Gstaad") == "Weg 1\n3780 Gstaad"
    assert address_block("") == ""


def test_neue_offerte_vom_kundenprofil_vorbelegt():
    project = _project()
    view = CustomerQuoteView()
    view.set_project(project)
    view._add_quote()
    cq = project.customer_quotes[0]
    assert cq.customer_name == "Franziska Muster"
    assert cq.customer_address == "Postfach 12\n3780 Gstaad"
    assert cq.salutation == "Sehr geehrte Frau Muster"


def test_bestehende_offerte_nur_auf_knopfdruck():
    project = _project()
    view = CustomerQuoteView()
    view.set_project(project)
    view._add_quote()
    view._quote_table.selectRow(0)
    project.client_profile.name = "Neuer Name"
    assert project.customer_quotes[0].customer_name == "Franziska Muster"
    view._fill_from_client()
    view._apply_quote()
    assert project.customer_quotes[0].customer_name == "Neuer Name"


def test_brief_zeigt_objektadresse(tmp_path):
    project = _project()
    view = CustomerQuoteView()
    view.set_project(project)
    view._add_quote()
    cq = project.customer_quotes[0]
    path = str(tmp_path / "brief.pdf")
    with patch.object(ProjectService, "load_company_profile", return_value=CompanyProfile()):
        view._write_quote_letter_pdf(cq, project.name, path)
    text = fitz.open(path)[0].get_text()
    assert "Objekt: Chaletweg 5, 3780 Gstaad" in text
    assert "Sehr geehrte Frau Muster," in text
    assert "Damen und Herren" not in text
    assert "Postfach 12\n3780 Gstaad" in text


def test_ohne_anrede_damen_und_herren(tmp_path):
    project = KnxProject(name="X")
    view = CustomerQuoteView()
    view.set_project(project)
    view._add_quote()
    path = str(tmp_path / "brief.pdf")
    with patch.object(ProjectService, "load_company_profile", return_value=CompanyProfile()):
        view._write_quote_letter_pdf(project.customer_quotes[0], project.name, path)
    assert "Sehr geehrte Damen und Herren," in fitz.open(path)[0].get_text()


def test_anrede_wird_gespeichert():
    profile = ClientProfile(salutation="Sehr geehrter Herr Muster")
    assert ClientProfile.from_dict(profile.to_dict()).salutation == "Sehr geehrter Herr Muster"
