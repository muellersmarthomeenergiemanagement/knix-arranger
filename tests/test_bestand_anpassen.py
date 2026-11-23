"""Bestehende Anlagen anpassen: Wizard und CSV-Export bei eingelesenen
Projekten, Validierung mit «neu seit dem letzten Einlesen»."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from knix_arranger.models.project import KnxProject  # noqa: E402
from knix_arranger.services.validation_engine import ValidationIssue  # noqa: E402
from knix_arranger.ui.main_window import MainWindow  # noqa: E402
from knix_arranger.ui.views.validation_view import ValidationView, baseline_key  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def _click(monkeypatch, label):
    texts = []

    def fake_exec(box):
        texts.append(box.text())
        box._clicked = next(b for b in box.buttons() if b.text() == label)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._clicked)
    return texts


def _window_fake():
    fake = QWidget()
    fake._project = KnxProject(name="Chalet")
    fake._project.topology.is_imported = True
    navigated = []
    fake._sidebar = SimpleNamespace(select=lambda key: None)
    fake._navigate = navigated.append
    return fake, navigated


# ── Wizard bei eingelesenen Projekten ────────────────────────────────────

@pytest.mark.parametrize("label, opens, target", [
    ("Umbau-Varianten öffnen", False, ["renovation"]),
    ("Wizard trotzdem öffnen", True, []),
    ("Abbrechen", False, []),
])
def test_wizard_bei_eingelesenem_projekt(monkeypatch, label, opens, target):
    texts = _click(monkeypatch, label)
    fake, navigated = _window_fake()
    assert MainWindow._confirm_wizard_imported(fake) is opens
    assert navigated == target
    assert "Erweiterung planen" in texts[0]


def test_schritt9_ersetzt_importierte_gas_nur_ausdruecklich_mit_sicherung(monkeypatch):
    from knix_arranger.services.project_service import ProjectService
    from knix_arranger.ui.wizard.step07_addresses import Step07Addresses
    backups = []
    monkeypatch.setattr(ProjectService, "create_backup",
                        lambda self, path, reason="": backups.append(reason) or "")
    project = KnxProject(name="Chalet")
    project.topology.is_imported = True
    step = Step07Addresses(project)
    _click(monkeypatch, "Abbrechen")
    assert step._confirm_replace_imported() is False and backups == []
    _click(monkeypatch, "Gruppenadressen ersetzen")
    assert step._confirm_replace_imported() is True and backups == ["vor_GA_Generierung"]


# ── CSV-Export bei eingelesenen Projekten ────────────────────────────────

@pytest.mark.parametrize("label, exports, target", [
    ("Umbau-Varianten öffnen", False, ["renovation"]),
    ("Ganze Liste exportieren", True, []),
    ("Abbrechen", False, []),
])
def test_csv_export_bei_eingelesenem_projekt(monkeypatch, label, exports, target):
    texts = _click(monkeypatch, label)
    fake, navigated = _window_fake()
    assert MainWindow._confirm_full_export_imported(fake) is exports
    assert navigated == target
    assert "GA-Liste für die ETS" in texts[0]


# ── Validierung: neu seit dem letzten Einlesen ───────────────────────────

def _issues():
    return [
        ValidationIssue("error", "FA-614", "zweite sendende GA", address="1/1/1"),
        ValidationIssue("warning", "FA-607", "Bezeichnung", address="1/1/2"),
        ValidationIssue("info", "FA-610", "Schema", address="1/1/3"),
    ]


def _shown(view) -> list[str]:
    result = []
    root = view._tree.invisibleRootItem()
    for i in range(root.childCount()):
        level = root.child(i)
        for j in range(level.childCount()):
            rule = level.child(j)
            for k in range(rule.childCount()):
                result.append(rule.child(k).text(0))
    return result


def test_neue_meldungen_markiert_und_filterbar():
    view = ValidationView()
    issues = _issues()
    baseline = [baseline_key(issues[1]), baseline_key(issues[2])]
    view.set_issues(issues, baseline=baseline, imported=False)
    assert not view._only_new.isHidden()
    assert "(1)" in view._only_new.text()
    assert "1/1/1  (neu)" in _shown(view)
    view._only_new.setChecked(True)
    assert _shown(view) == ["1/1/1  (neu)"]
    view.set_issues(issues)                    # ohne Vergleich
    assert view._only_new.isHidden() and not view._only_new.isChecked()
    assert len(_shown(view)) == 3


def test_hinweise_bei_eingelesenen_projekten_ausgeblendet():
    view = ValidationView()
    view.set_issues(_issues(), imported=True)
    assert not view._level_boxes["info"].isChecked()
    assert len(_shown(view)) == 2
    view._level_boxes["info"].setChecked(True)      # Wahl des Anwenders bleibt
    view.set_issues(_issues(), imported=True)
    assert view._level_boxes["info"].isChecked()
    view.set_issues(_issues(), imported=False)      # geplantes Projekt
    assert view._level_boxes["info"].isChecked()
    view.set_issues([ValidationIssue("info", "FA-610", "Schema", "1/1/3")], imported=True)
    assert not view._level_boxes["info"].isChecked()
    assert "ausgeblendet" in view._tree.topLevelItem(0).text(0)


def test_vergleichsstand_nach_dem_einlesen():
    project = KnxProject(name="Chalet")
    keys = ["FA-614|1/1/1|a", "FA-607|1/1/2|b"]
    fake = SimpleNamespace(_issues_before_import=["FA-607|1/1/2|b", "FA-610|1/1/9|c"],
                           _project=project, _issue_keys=lambda: keys)
    note = MainWindow._store_issue_baseline(fake)
    assert project.validation_before_import == ["FA-607|1/1/2|b", "FA-610|1/1/9|c"]
    assert "1 neue Meldung(en), 1 entfallen" in note.text
    assert fake._issues_before_import is None
    # erstes Einlesen: kein Vergleich, nichts gemerkt
    fresh = KnxProject(name="Neu")
    fake = SimpleNamespace(_issues_before_import=None, _project=fresh, _issue_keys=lambda: keys)
    assert MainWindow._store_issue_baseline(fake) is None
    assert fresh.validation_before_import is None


def test_vergleichsstand_wird_gespeichert():
    project = KnxProject(name="Chalet")
    assert KnxProject.from_dict(project.to_dict()).validation_before_import is None
    project.validation_before_import = ["FA-614|1/1/1|a"]
    assert KnxProject.from_dict(project.to_dict()).validation_before_import == ["FA-614|1/1/1|a"]
