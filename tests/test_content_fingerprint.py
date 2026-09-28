"""Inhalts-Prüfsumme erkennt ungespeicherte Änderungen (Speichern-Frage beim Schliessen)."""
from knix_arranger.models.knx_secure import DeviceSecureInfo
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene
from knix_arranger.services.knx_secure_service import KnxSecureService


def test_fingerprint_changes_with_content_only():
    project = KnxProject(name="Test")
    before = project.content_fingerprint()
    project.touch()
    assert project.content_fingerprint() == before     # Änderungsdatum zählt nicht
    project.scenes.append(Scene(name="Abwesend", scene_number=2))
    assert project.content_fingerprint() != before


def test_fingerprint_stable_with_encrypted_secure_archive():
    """Die Verschlüsselung nutzt jedes Mal ein neues Salt -- die Prüfsumme
    darf dadurch nicht schwanken."""
    project = KnxProject(name="Test")
    project.knx_secure.device_infos["d1"] = DeviceSecureInfo(device_id="d1", fdsk="AB" * 16)
    KnxSecureService.unlock(project.knx_secure, "geheim")
    assert project.content_fingerprint() == project.content_fingerprint()


def test_fingerprint_survives_save_and_load(tmp_path):
    path = tmp_path / "p.knxarr"
    project = KnxProject(name="Test")
    project.save(str(path))
    assert KnxProject.load(str(path)).content_fingerprint() == project.content_fingerprint()
