"""Bedienabläufe Neu / Einlesen / Anpassen: Rückfrage vor dem Projektwechsel,
Prüfung der ETS-Projektkennung, Neuaufbau ohne stille Verluste, Ablage
eingelesener Projekte, Import-Zusammenfassung, CSV-Export."""
import os
import zipfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from knix_arranger.models.building import (  # noqa: E402
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.project import KnxProject  # noqa: E402
from knix_arranger.services.knxproj_import_service import KnxprojImportService  # noqa: E402
from knix_arranger.services.rebuild_service import (  # noqa: E402
    REBUILD_OPTIONS, adopt_bauherr_notes, kept_content, lost_content,
)
from knix_arranger.ui.main_window import IMPORTED_PROJECT_NAME, MainWindow  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def _option(key):
    return next(o for o in REBUILD_OPTIONS if o.key == key)


def _areal(note="", annotation="", pa="1.1.5") -> Areal:
    room = Room(name="Wohnen", number="08", bauherr_notes=note,
                bedienelemente=[Bedienelement(participant_number=pa,
                                              bauherr_annotation=annotation)])
    floor = Floor(name="Erdgeschoss", short_code="EG",
                  apartments=[Apartment(rooms=[room])])
    return Areal(buildings=[Building(wings=[Wing(floors=[floor])])])


# ── ETS-Projektkennung ───────────────────────────────────────────────────

def test_projektkennung_aus_knxproj(tmp_path):
    classic = tmp_path / "alt.knxproj"
    with zipfile.ZipFile(classic, "w") as zf:
        zf.writestr("P-0A1B/0.xml", "<x/>")
    nested = tmp_path / "neu.knxproj"
    with zipfile.ZipFile(nested, "w") as zf:
        zf.writestr("P-77CC.zip", b"")
    broken = tmp_path / "kaputt.knxproj"
    broken.write_bytes(b"kein zip")
    service = KnxprojImportService()
    assert service.read_project_id(str(classic)) == "P-0A1B"
    assert service.read_project_id(str(nested)) == "P-77CC"
    assert service.read_project_id(str(broken)) == ""


def test_projektkennung_wird_gespeichert():
    project = KnxProject(name="Chalet")
    project.ets_project_id = "P-0A1B"
    assert KnxProject.from_dict(project.to_dict()).ets_project_id == "P-0A1B"


def _knxproj(path, project_id):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{project_id}/0.xml", "<x/>")
    return str(path)


def _legacy_project(tmp_path) -> KnxProject:
    """Projekt ohne gemerkte Kennung (vor 1.4.62), früher eingelesene
    .knxproj im Import-Ordner."""
    folder = tmp_path / "Chalet"
    (folder / "Import").mkdir(parents=True)
    _knxproj(folder / "Import" / "Chalet.knxproj", "P-06C2")
    _knxproj(folder / "Import" / "Chalet_20261118_1234.knxproj", "P-06C2")
    (folder / "Import" / "Monitor.xml").write_text("<x/>")
    project = KnxProject(name="Chalet")
    project._file_path = str(folder / "Chalet.knxarr")
    return project


def test_kennung_aus_dem_import_ordner(tmp_path):
    from knix_arranger.services import import_folder
    project = _legacy_project(tmp_path)
    assert import_folder.known_project_ids(project) == {"P-06C2"}
    # die gewählte Datei selbst zählt nicht als früherer Stand
    own = project.folder_path + "/Import/Chalet.knxproj"
    other = _knxproj(tmp_path / "Chalet" / "Import" / "Fremd.knxproj", "P-9999")
    assert import_folder.known_project_ids(project, exclude=other) == {"P-06C2"}
    assert "P-06C2" in import_folder.known_project_ids(project, exclude=own)
    assert import_folder.known_project_ids(KnxProject()) == set()   # ungespeichert


def test_alte_projekte_erkennen_andere_anlage_ueber_den_import_ordner(tmp_path, monkeypatch):
    project = _legacy_project(tmp_path)
    fremd = _knxproj(tmp_path / "fremd.knxproj", "P-049F")
    gleich = _knxproj(tmp_path / "neu.knxproj", "P-06C2")
    texts = []

    def fake_exec(box):
        texts.append(box.text())
        box._clicked = next(b for b in box.buttons() if b.text() == "Abbrechen")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._clicked)
    from PySide6.QtWidgets import QWidget
    fake = QWidget()
    fake._project = project
    assert MainWindow._ets_project_target(fake, gleich) == "open" and texts == []
    assert MainWindow._ets_project_target(fake, fremd) == "cancel"
    assert "P-049F" in texts[0] and "P-06C2" in texts[0]


def test_gleiche_oder_unbekannte_kennung_liest_ohne_rueckfrage_ein(tmp_path, monkeypatch):
    path = tmp_path / "a.knxproj"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("P-0A1B/0.xml", "<x/>")
    monkeypatch.setattr(QMessageBox, "exec", lambda *a: pytest.fail("keine Rückfrage erwartet"))
    project = KnxProject(name="Chalet")
    fake = SimpleNamespace(_project=project)
    assert MainWindow._ets_project_target(fake, str(path)) == "open"   # noch keine Kennung
    project.ets_project_id = "P-0A1B"
    assert MainWindow._ets_project_target(fake, str(path)) == "open"
    assert MainWindow._ets_project_target(SimpleNamespace(_project=None), str(path)) == "open"


@pytest.mark.parametrize("button, expected", [
    ("Als neues Projekt einlesen", "new"),
    ("Trotzdem ins offene Projekt", "open"),
    ("Abbrechen", "cancel"),
])
def test_andere_anlage_wird_erkannt(tmp_path, monkeypatch, button, expected):
    path = tmp_path / "b.knxproj"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("P-9999/0.xml", "<x/>")
    texts = []

    def fake_exec(box):
        texts.append(box.text())
        box._clicked = next(b for b in box.buttons() if b.text() == button)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._clicked)
    project = KnxProject(name="Chalet")
    project.ets_project_id = "P-0A1B"
    from PySide6.QtWidgets import QWidget
    fake = QWidget()            # Eltern-Fenster der Rückfrage
    fake._project = project
    assert MainWindow._ets_project_target(fake, str(path)) == expected
    assert "P-9999" in texts[0] and "P-0A1B" in texts[0]


# ── Rückfrage vor dem Projektwechsel ─────────────────────────────────────

@pytest.mark.parametrize("answer, saved, expected", [
    (QMessageBox.Discard, True, True),
    (QMessageBox.Cancel, True, False),
    (QMessageBox.Save, True, True),
    (QMessageBox.Save, False, False),      # Speichern fehlgeschlagen: bleiben
])
def test_ungespeicherte_aenderungen(monkeypatch, answer, saved, expected):
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)
    fake = SimpleNamespace(_project=KnxProject(name="Chalet"),
                           _has_unsaved_changes=lambda: True,
                           _save_project=lambda: calls.append("save") or saved)
    assert MainWindow._confirm_discard_changes(fake) is expected
    assert calls == (["save"] if answer == QMessageBox.Save else [])


def test_ohne_aenderungen_keine_rueckfrage(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("Rückfrage"))
    fake = SimpleNamespace(_project=None, _has_unsaved_changes=lambda: False)
    assert MainWindow._confirm_discard_changes(fake) is True


# ── Neuaufbau: nichts geht still verloren ────────────────────────────────

def test_neue_optionen_standardmaessig_behalten():
    for key in ("bauherr_notes", "manual_settings", "revisions", "bus_connection"):
        assert _option(key).default, key


def test_verlust_wird_konkret_benannt():
    project = KnxProject(name="Chalet")
    project.time_programs = [object(), object()]
    project.areal = _areal(note="Kinderzimmer: Storen tief", annotation="Taste 1 = Licht")
    assert kept_content(_option("time_programs"), project) == "2"
    assert kept_content(_option("bauherr_notes"), project) == "2"
    assert kept_content(_option("commissioning"), project) == ""
    lost = lost_content(set(), project)
    assert "Zeitprogramme (2)" in lost and "Notizen der Bauherrenberatung (2)" in lost
    assert not any(item.startswith("Inbetriebnahme") for item in lost)
    assert lost_content({o.key for o in REBUILD_OPTIONS}, project) == []


def test_bauherr_notizen_nach_neuaufbau_zurueck():
    old = KnxProject()
    old.areal = _areal(note="Storen tief", annotation="oben = Licht")
    old.areal.all_rooms[0].bedienelemente[0].datasheets = ["Taster.pdf"]
    fresh = KnxProject()
    fresh.areal = _areal()
    assert adopt_bauherr_notes(old, fresh) == 2
    room = fresh.areal.all_rooms[0]
    assert room.bauherr_notes == "Storen tief"
    assert room.bedienelemente[0].bauherr_annotation == "oben = Licht"
    assert room.bedienelemente[0].datasheets == ["Taster.pdf"]
    # anderes Gerät: keine Übernahme
    other = KnxProject()
    other.areal = _areal(pa="1.1.9")
    adopt_bauherr_notes(old, other)
    assert other.areal.all_rooms[0].bedienelemente[0].bauherr_annotation == ""


def test_dialog_zeigt_verlust():
    from knix_arranger.ui.dialogs.rebuild_dialog import RebuildDialog
    project = KnxProject(name="Chalet")
    project.time_programs = [object()]
    dialog = RebuildDialog(project.name, filepath="neu.knxproj", project=project)
    assert "Zeitprogramme (1)" in dialog._lost.text()   # Standard: nicht behalten
    dialog._checks["time_programs"].setChecked(True)
    assert dialog._lost.text() == ""


# ── Seitenleiste ─────────────────────────────────────────────────────────

def test_wizard_bei_importierten_projekten_nicht_in_der_seitenleiste():
    from knix_arranger.ui.widgets.sidebar import Sidebar
    sidebar = Sidebar()
    sidebar.set_imported(False)
    assert sidebar._wizard_area.isVisibleTo(sidebar)
    sidebar.set_imported(True)
    assert not sidebar._wizard_area.isVisibleTo(sidebar)
    fresh = Sidebar()
    assert {"Projekt", "Planung"} <= set(fresh.expanded_groups())


# ── Startdialog und Ablage eingelesener Projekte ─────────────────────────

def test_startdialog_bietet_einlesen():
    from knix_arranger.ui.dialogs.welcome_dialog import ACTION_IMPORT, WelcomeDialog
    dialog = WelcomeDialog()
    dialog._btn_import.click()
    assert dialog.action == ACTION_IMPORT


def _place_fake(tmp_path, project, source="C:/Daten/Chalet 64.knxproj"):
    from knix_arranger.services import project_service as ps
    written = []

    def write(path):
        project._file_path = path
        written.append(path)
        return True

    status = SimpleNamespace(set_project_name=lambda name: None)
    return SimpleNamespace(
        _new_import=source, _project=project,
        _ensure_workspace=lambda: str(tmp_path), _write_project=write,
        _update_window_title=lambda: None, _status_bar=status), written, ps


def test_eingelesenes_projekt_landet_im_arbeitsverzeichnis(tmp_path, monkeypatch):
    from knix_arranger.models.topology import Area
    project = KnxProject(name="Chalet Franziska")
    project.topology.areas = [Area(area_number=1)]
    fake, written, ps = _place_fake(tmp_path, project)
    monkeypatch.setattr(ps, "APPDATA_DIR", str(tmp_path / "appdata"))
    # gleichnamiges Projekt existiert schon
    existing = tmp_path / "Chalet Franziska" / "Chalet Franziska.knxarr"
    existing.parent.mkdir()
    existing.write_text("alt")
    path = MainWindow._place_imported_project(fake)
    assert path == written[0]
    assert os.path.basename(path) == "Chalet Franziska (2).knxarr"
    assert os.path.isdir(os.path.join(os.path.dirname(path), "Import"))
    assert fake._new_import == ""


def test_ohne_ets_namen_dateiname_als_projektname(tmp_path, monkeypatch):
    from knix_arranger.models.topology import Area
    project = KnxProject(name=IMPORTED_PROJECT_NAME)
    project.topology.areas = [Area(area_number=1)]
    fake, _written, ps = _place_fake(tmp_path, project)
    monkeypatch.setattr(ps, "APPDATA_DIR", str(tmp_path / "appdata"))
    path = MainWindow._place_imported_project(fake)
    assert os.path.basename(path) == "Chalet 64.knxarr" and project.name == "Chalet 64"


def test_import_ins_offene_projekt_wird_nicht_verschoben(tmp_path):
    project = KnxProject(name="Chalet")
    project._file_path = str(tmp_path / "Chalet.knxarr")
    fake, written, _ps = _place_fake(tmp_path, project)
    assert MainWindow._place_imported_project(fake) == "" and written == []
    leer = KnxProject(name="Leer")                       # Import abgebrochen
    fake, written, _ps = _place_fake(tmp_path, leer)
    assert MainWindow._place_imported_project(fake) == "" and written == []


# ── Import-Zusammenfassung ───────────────────────────────────────────────

def _pipeline(**kw):
    values = dict(channel_conflicts=[], params_from_report=True, worklist_diff=None,
                  pending_unlinks=[], problems=[])
    values.update(kw)
    return SimpleNamespace(**values)


def _diff(**kw):
    values = dict(devices_matched=0, rooms_matched=0, has_removed=False,
                  has_ga_conflicts=False, report_params_kept=0)
    values.update(kw)
    return SimpleNamespace(**values)


def test_hinweise_in_einer_liste():
    fake = SimpleNamespace(_report_params_note=MainWindow._report_params_note)
    notes = MainWindow._import_notes(
        fake, _pipeline(channel_conflicts=["1.1.5 KO 3"], problems=["DALI"],
                        worklist_diff=SimpleNamespace(first=False, done=2, new=0, open=0)),
        _diff(), Areal())
    titles = [n.title for n in notes]
    assert titles == ["Keine Gebäudestruktur erkannt", "Mehrere Gewerke auf einem Kanal",
                      "ETS-Arbeitsliste", "Import unvollständig"]
    assert [n.warning for n in notes] == [True, True, False, True]
    assert MainWindow._import_notes(fake, _pipeline(), _diff()) == []


def test_zusammenfassung_warnungen_zuerst():
    from knix_arranger.ui.dialogs.import_summary_dialog import (
        ImportNote, ImportSummaryDialog, notes_html,
    )
    notes = [ImportNote("Info", "a"), ImportNote("Warnung", "b <c>", True)]
    html = notes_html(notes)
    assert html.index("Warnung") < html.index("Info") and "b &lt;c&gt;" in html
    ImportSummaryDialog("Import abgeschlossen", "KNXPROJ importiert", notes)
    ImportSummaryDialog("Import abgeschlossen", "KNXPROJ importiert", [])


# ── CSV-Export ───────────────────────────────────────────────────────────

def test_exportdialog_ohne_doppelte_ueberschreibfrage():
    from PySide6.QtWidgets import QCheckBox
    from knix_arranger.ui.dialogs.export_dialog import ExportDialog
    dialog = ExportDialog(12)
    assert dialog.overwrite is True
    assert dialog.findChildren(QCheckBox) == []
    assert dialog._path_edit.isReadOnly()
