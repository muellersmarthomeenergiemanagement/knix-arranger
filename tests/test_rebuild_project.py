"""Projekt neu aus ETS aufbauen (FA-527) und Sicherungen (NFA-042)."""
import os

from knix_arranger.models.building import Areal, Building
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene
from knix_arranger.services import project_service as ps
from knix_arranger.services.rebuild_service import (
    REBUILD_OPTIONS, build_fresh_project, default_keep,
)


def _old_project() -> KnxProject:
    old = KnxProject(name="Chalet", project_number="2005")
    old.project_info.client_name = "Familie Muster"
    old.client_profile.name = "Muster"
    old.knx_secure.ets_project_password = "geheim"
    old.custom_gewerke = [{"code": "XY"}]
    old.areal = Areal(buildings=[Building(name="Alt")])
    old.scenes = [Scene(name="Kino", scene_number=1)]
    old.verteiler_room_overrides = {"HV": ["EG", "01"]}
    from knix_arranger.models.material_list import MaterialEntry
    old.material_list.entries = [MaterialEntry(device_type="Schaltaktor 8-fach")]
    old._file_path = r"C:\Projekte\Chalet\Chalet.knxarr"
    return old


def test_standard_behalt_nur_was_die_ets_nicht_liefert():
    old = _old_project()
    fresh = build_fresh_project(old, default_keep())
    assert fresh.name == "Chalet" and fresh.project_info.client_name == "Familie Muster"
    assert fresh.client_profile.name == "Muster"
    assert fresh.knx_secure.ets_project_password == "geheim"
    assert fresh.custom_gewerke == [{"code": "XY"}]
    assert fresh._file_path == old._file_path
    # frisch aus der ETS
    assert fresh.areal.buildings == [] and fresh.scenes == []
    assert fresh.material_list.entries == []
    assert fresh.verteiler_room_overrides == {}


def test_auswahl_wird_respektiert():
    old = _old_project()
    fresh = build_fresh_project(old, {"verteiler_rooms"})
    assert fresh.verteiler_room_overrides == {"HV": ["EG", "01"]}
    assert fresh.knx_secure.ets_project_password == ""
    assert fresh.project_info.client_name == ""


def test_optionen_verweisen_auf_projektfelder():
    project = KnxProject()
    for option in REBUILD_OPTIONS:
        for attr in option.attributes:
            assert hasattr(project, attr), attr
    assert "material_list" not in {a for o in REBUILD_OPTIONS for a in o.attributes}


def test_geraete_ids_fuer_secure_archiv_uebernommen():
    from knix_arranger.models.topology import Area, Line, Device
    from knix_arranger.services.rebuild_service import adopt_device_ids
    old = KnxProject()
    old.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=[
        Device(id="alt-1", physical_address="1.1.1"),
        Device(id="alt-sv", physical_address="1.1.-"),
    ])])]
    imported = KnxProject()
    neu = Device(id="neu-1", physical_address="1.1.1")
    neu_sv = Device(id="neu-sv", physical_address="1.1.-")
    neu_2 = Device(id="neu-2", physical_address="1.1.2")
    imported.topology.areas = [Area(area_number=1, lines=[Line(line_number=1,
                                                               devices=[neu, neu_sv, neu_2])])]
    assert adopt_device_ids(old, imported) == 1
    assert neu.id == "alt-1"
    assert neu_sv.id == "neu-sv"          # Adresse B.L.- ist nicht eindeutig
    assert neu_2.id == "neu-2"


def test_sicherung_im_unterordner_mit_begrenzung(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "APPDATA_DIR", str(tmp_path / "appdata"))
    project_file = tmp_path / "Chalet" / "Chalet.knxarr"
    project_file.parent.mkdir()
    project_file.write_bytes(b"stand")
    service = ps.ProjectService()
    folder = project_file.parent / "Sicherungen"
    for i in range(12):
        (folder).mkdir(exist_ok=True)
        (folder / f"Chalet_202601{i + 10:02d}_120000.knxarr").write_bytes(b"alt")

    path = service.create_backup(str(project_file), "vor_Import")

    assert os.path.dirname(path) == str(folder)
    assert os.path.basename(path).endswith("_vor_Import.knxarr")
    backups = sorted(os.listdir(folder))
    assert len(backups) == service.BACKUPS_KEPT
    assert os.path.basename(path) in backups                     # neueste bleibt
    assert "Chalet_20260110_120000.knxarr" not in backups        # älteste weg


def test_keine_sicherung_ohne_gespeicherte_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "APPDATA_DIR", str(tmp_path / "appdata"))
    assert ps.ProjectService().create_backup("") == ""
    assert ps.ProjectService().create_backup(str(tmp_path / "fehlt.knxarr")) == ""


# ── ETS6 Import in ein bestehendes Projekt (FA-527a) ──────────────────────

def _decide(project, rebuild_result=True):
    """MainWindow._knxproj_rebuilds ohne Hauptfenster."""
    from types import SimpleNamespace
    from knix_arranger.ui.main_window import MainWindow
    calls = []

    def rebuild(path, **kw):
        calls.append((path, kw))
        return rebuild_result

    fake = SimpleNamespace(_project=project, _rebuild_project=rebuild)
    return MainWindow._knxproj_rebuilds(fake, "neu.knxproj"), calls


def _imported_project() -> KnxProject:
    from knix_arranger.models.topology import Area
    project = _old_project()
    project.topology.is_imported = True
    project.topology.areas = [Area(area_number=1, name="Bereich 1")]
    return project


def test_import_in_importiertes_projekt_baut_neu_auf():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    done, calls = _decide(_imported_project())
    assert done is True and calls == [("neu.knxproj", {})]
    # «Nur abgleichen» im Dialog: normaler Import geht weiter
    done, _ = _decide(_imported_project(), rebuild_result=False)
    assert done is False


def test_import_ohne_bestehenden_stand_gleicht_wie_bisher_ab():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    empty = _old_project()
    empty.topology.is_imported = True          # gespeichert, aber ohne Topologie/GAs
    assert _decide(empty) == (False, [])
    unsaved = _imported_project()
    unsaved._file_path = ""
    assert _decide(unsaved) == (False, [])
    assert _decide(None) == (False, [])


def test_dialog_aus_dem_import():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.rebuild_dialog import RebuildDialog, RECONCILE, REBUILD
    project = _imported_project()
    project.bus_recordings = [{"file": "Chalet.xml"}, {"file": "Chalet2.xml"}]
    dialog = RebuildDialog(project.name, filepath="neu.knxproj", project=project,
                           offer_reconcile=True)
    assert dialog.filepath == "neu.knxproj" and dialog._btn_ok.isEnabled()
    assert "2: Chalet.xml, Chalet2.xml" in dialog._checks["bus_recordings"].text()
    dialog._checks["bus_recordings"].setChecked(False)
    assert "bus_recordings" not in dialog.keep
    assert dialog.choice == REBUILD
    dialog._reconcile()
    assert dialog.choice == RECONCILE
    # Menü «Projekt neu aus ETS aufbauen»: Datei wählen, kein Abgleich
    plain = RebuildDialog(project.name)
    assert not plain._btn_ok.isEnabled() and not hasattr(plain, "_btn_reconcile")
