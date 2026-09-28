"""KNX-Secure-Geheimnisse dürfen nie im Klartext in der Projektdatei stehen bleiben."""
from knix_arranger.models.knx_secure import DeviceSecureInfo, KnxSecureConfig
from knix_arranger.models.project import KnxProject
from knix_arranger.services.knx_secure_service import KnxSecureService

FDSK = "0123456789ABCDEF0123456789ABCDEF"


def test_has_plaintext_secrets():
    cfg = KnxSecureConfig()
    assert not cfg.has_plaintext_secrets
    cfg.device_infos["d1"] = DeviceSecureInfo(device_id="d1", fdsk=FDSK)
    assert cfg.has_plaintext_secrets
    KnxSecureService.unlock(cfg, "geheim")
    assert not cfg.has_plaintext_secrets


def test_project_password_counts_as_secret():
    cfg = KnxSecureConfig(ets_project_password="ets")
    assert cfg.has_plaintext_secrets


def test_old_plaintext_removed_from_file_after_encryption(tmp_path):
    """Früher unverschlüsselt gespeicherte FDSK dürfen nach dem Verschlüsseln
    auch nicht mehr im freien Speicher der SQLite-Datei stehen."""
    path = tmp_path / "p.knxarr"
    project = KnxProject(name="Test")
    project.knx_secure.device_infos["d1"] = DeviceSecureInfo(device_id="d1", fdsk=FDSK)
    project.save(str(path))
    assert FDSK.encode() in path.read_bytes()

    KnxSecureService.unlock(project.knx_secure, "geheim")
    project.save(str(path))

    assert FDSK.encode() not in path.read_bytes()
    loaded = KnxProject.load(str(path))
    assert loaded.knx_secure.is_locked
    unlocked = KnxSecureService.unlock(loaded.knx_secure, "geheim")
    assert unlocked.device_infos["d1"].fdsk == FDSK
