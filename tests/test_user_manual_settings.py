"""
Anpassungen der Bedienungsanleitung (FA-2005): eigene Texte, ausgeblendete
Abschnitte, eigene Abschnitte, Text je Raum und Foto je Taster.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement, SensorFunktion,
)
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.documentation import UserManualSettings
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.services.user_manual import MANUAL_TEXTS


def _project() -> KnxProject:
    project = KnxProject(name="Test")
    be = Bedienelement(element_type="Tastereinheit", is_auto=False, taster_index=1,
                       funktionen=[SensorFunktion(gewerk_code="L", element_number=1),
                                   SensorFunktion(gewerk_code="L", element_number=2)])
    room = Room(number="01", name="Wohnen", bedienelemente=[be])
    mg = MiddleGroup(number=0, name="Licht", group_addresses=[
        GroupAddress(main_group=1, middle_group=0, sub_group=nr, gewerk_code="L",
                     room_number="01", room_id=room.id, element_number=nr,
                     function_name="E/A", designation=f"L_01_0{nr} E/A (Wohnen)",
                     datapoint_type="DPST-1-1")
        for nr in (1, 2)])
    project.group_addresses = GroupAddressStructure(
        main_groups=[MainGroup(number=1, name="EG", middle_groups=[mg])])
    floor = Floor(name="Erdgeschoss", short_code="EG")
    floor.apartments = [Apartment(name="EG", rooms=[room])]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    return project


def _render(project, tmp_path) -> tuple[str, int]:
    path = str(tmp_path / "anleitung.pdf")
    company = CompanyProfile(company_name="Müller SmartHome", user_name="M. Müller")
    DocumentationService(project, company_profile=company).generate_user_manual(path)
    with fitz.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
        images = sum(len(page.get_images()) for page in doc)
    return " ".join(text.split()), images


def test_settings_roundtrip():
    settings = UserManualSettings(texts={"haus": "X"}, hidden=["zentral"],
                                  custom_sections=[{"title": "T", "text": "U"}],
                                  room_texts={"EG|01": "R"}, photos={"EG|01|T1": "p.jpg"})
    project = KnxProject(name="T")
    project.manual_settings = settings
    restored = KnxProject.from_dict(project.to_dict()).manual_settings
    assert restored == settings
    assert KnxProject.from_dict({"name": "alt"}).manual_settings == UserManualSettings()


def test_standard_texts_without_settings(tmp_path):
    text, images = _render(_project(), tmp_path)
    assert "Ihr Haus ist mit KNX ausgestattet" in text
    assert "Kurz drücken: Antippen" in text
    assert "Ihr Ansprechpartner" in text
    assert images <= 1          # höchstens das Firmenlogo, kein Taster-Foto


def test_own_texts_hidden_and_custom_sections(tmp_path):
    project = _project()
    project.manual_settings = UserManualSettings(
        texts={"intro": "Willkommen im Haus Muster.", "tipps": "• Einfach drücken."},
        hidden=["haus", "ansprechpartner"],
        custom_sections=[{"title": "Visualisierung", "text": "Die App heisst Gira X1."}],
        room_texts={"EG|01": "Die Storen fahren bei Wind automatisch hoch."},
    )
    text, _ = _render(project, tmp_path)
    assert "Willkommen im Haus Muster." in text
    assert MANUAL_TEXTS["intro"][1][:40] not in text
    assert "Einfach drücken." in text and "Kurz drücken: Antippen" not in text
    assert "Ihr Haus in Kürze" not in text
    assert "Ihr Ansprechpartner" not in text
    assert "Visualisierung" in text and "Die App heisst Gira X1." in text
    assert "Die Storen fahren bei Wind automatisch hoch." in text


def test_photo_next_to_button_plan(tmp_path):
    photo = tmp_path / "taster.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False)
    pix.clear_with(200)
    pix.save(str(photo))
    project = _project()
    _, without = _render(project, tmp_path)
    project.manual_settings.photos = {"EG|01|T1": str(photo)}
    _, with_photo = _render(project, tmp_path)
    assert with_photo == without + 1


def test_relative_photo_path_uses_project_folder(tmp_path):
    (tmp_path / "Fotos").mkdir()
    photo = tmp_path / "Fotos" / "t.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    pix.clear_with(100)
    pix.save(str(photo))
    project = _project()
    project._file_path = str(tmp_path / "Test.knxarr")
    _, without = _render(project, tmp_path)
    project.manual_settings.photos = {"EG|01|T1": os.path.join("Fotos", "t.png")}
    _, with_photo = _render(project, tmp_path)
    assert with_photo == without + 1


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_dialog_collects_settings(qapp, tmp_path):
    from knix_arranger.ui.dialogs.user_manual_settings_dialog import (
        UserManualSettingsDialog, manual_buttons,
    )
    project = _project()
    project._file_path = str(tmp_path / "Test.knxarr")
    assert manual_buttons(project) == [("EG|01|T1", "EG 01 Wohnen – Taster (Nr. 1)")]

    dlg = UserManualSettingsDialog(project)
    dlg._text_edits["haus"].setPlainText("  Eigenes Haus.  ")
    dlg._section_checks["zentral"].setChecked(False)
    dlg._add_custom()
    dlg._custom_title.setText("Alarm")
    dlg._custom_title.textEdited.emit("Alarm")
    dlg._custom_text.setPlainText("Code beim Bauherrn.")
    dlg._room_list.setCurrentRow(0)
    dlg._room_text.setPlainText("Raumtext")

    source = tmp_path / "quelle.jpg"
    source.write_bytes(b"jpg")
    dlg._photo_list.setCurrentRow(0)
    dlg._photos["EG|01|T1"] = dlg._store_photo(str(source))
    dlg._accept()

    s = dlg.settings
    assert s.texts == {"haus": "Eigenes Haus."}
    assert s.hidden == ["zentral"]
    assert s.custom_sections == [{"title": "Alarm", "text": "Code beim Bauherrn."}]
    assert s.room_texts == {"EG|01": "Raumtext"}
    assert s.photos == {"EG|01|T1": os.path.join("Fotos", "quelle.jpg")}
    assert (tmp_path / "Fotos" / "quelle.jpg").exists()
    # Das Projekt selbst bleibt bis zum Übernehmen im Berichte-Dialog unverändert
    assert project.manual_settings == UserManualSettings()
