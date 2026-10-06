"""
Bedienungsanleitung in der Sprache des Bauherrn (FA-2006, NFA-156).
"""
from __future__ import annotations
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

import fitz
import pytest

from knix_arranger.services.manual_i18n import MANUAL_LANGUAGES, ManualLanguage, _I18N_DIR
from knix_arranger.services.documentation_service import DocumentationService
from test_time_program_additions import _project as _time_project
from test_user_manual_settings import _project


def _load(lang):
    with open(os.path.join(_I18N_DIR, f"manual_{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("lang", ["fr", "it", "en"])
def test_language_files_complete(lang):
    de = _load("de")["texts"]
    other = _load(lang)
    assert set(other["texts"]) == set(de), set(de) ^ set(other["texts"])
    # gleiche Platzhalter wie im deutschen Text
    for key, text in de.items():
        assert sorted(part.split("}")[0] for part in text.split("{")[1:]) == \
            sorted(part.split("}")[0] for part in other["texts"][key].split("{")[1:]), key
    assert other["phrases"]


def test_phrase_translation_whole_words_longest_first():
    fr = ManualLanguage("fr")
    assert fr.phrase("kurz drücken: Ein · lang drücken: heller") == \
        "appui bref: Marche · appui long: plus clair"
    assert fr.phrase("drücken: Ein/Aus") == "appuyer: Marche/Arrêt"
    # Wortteile bleiben: Eingang, Ausgang, Ablage
    assert fr.phrase("Eingang Ausgang Ablage") == "Eingang Ausgang Ablage"
    assert ManualLanguage("de").phrase("kurz drücken") == "kurz drücken"


def test_text_fallback_and_placeholders():
    it = ManualLanguage("it")
    assert it.text("toc_buttons", n=3) == "3 pulsante/i"
    assert it.text("central_where", room="Soggiorno", type="Pulsante", key="1") == \
        "Soggiorno – Pulsante, tasto 1"
    assert ManualLanguage("xx").lang == "de"


def test_date_formats():
    when = datetime(2026, 10, 6)
    assert ManualLanguage("de").date(when) == "06.10.2026"
    assert ManualLanguage("it").date(when) == "06.10.2026"
    assert ManualLanguage("fr").date(when) == "06/10/2026"
    assert ManualLanguage("en").date(when) == "06/10/2026"


def _text(project, tmp_path, lang=None) -> str:
    path = tmp_path / f"anleitung_{lang}.pdf"
    DocumentationService(project).generate_user_manual(str(path), language=lang)
    with fitz.open(path) as doc:
        return " ".join("".join(p.get_text() for p in doc).split())


@pytest.mark.parametrize("lang, expected", [
    ("fr", ["Mode d'emploi", "Généralités", "Utilisation des poussoirs", "Touche",
            "Marche/Arrêt", "Rez-de-chaussée", "Page 1 /"]),
    ("it", ["Istruzioni per l'uso", "Generalità", "Tasto", "Acceso/Spento",
            "Pianterreno", "Pagina 1 /"]),
    ("en", ["Operating instructions", "General", "Button", "On/Off",
            "Ground floor", "Page 1 /"]),
])
def test_manual_in_language(tmp_path, lang, expected):
    text = _text(_project(), tmp_path, lang)
    for part in expected:
        assert part in text, (lang, part)
    for german in ("Bedienungsanleitung", "Allgemeines", "drücken", "Seite 1 /"):
        assert german not in text, (lang, german)
    assert "Wohnen" in text          # Raumname aus dem Projekt bleibt


def test_language_from_project_settings(tmp_path):
    project = _project()
    project.manual_settings.language = "en"
    assert "Operating instructions" in _text(project, tmp_path)
    assert "Bedienungsanleitung" in _text(project, tmp_path, "de")


def test_time_control_section_translated(tmp_path):
    text = _text(_time_project(), tmp_path, "fr")
    assert "Commande horaire automatique" in text
    assert "07:00 h" in text and "Monter" in text and "lu, sa" in text
    assert "01/04 – 30/09" in text


def test_dialog_language_choice(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.user_manual_settings_dialog import UserManualSettingsDialog
    project = _project()
    dlg = UserManualSettingsDialog(project)
    assert [dlg._language.itemData(i) for i in range(dlg._language.count())] == \
        list(MANUAL_LANGUAGES)
    dlg._language.setCurrentIndex(dlg._language.findData("it"))
    assert dlg._text_edits["intro"].placeholderText().startswith("Queste istruzioni")
    dlg._accept()
    assert dlg.settings.language == "it"
