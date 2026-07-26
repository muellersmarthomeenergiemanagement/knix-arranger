"""Tests fuer das KNX-Secure-Archiv (FA-2701, FA-2703-2706, ueberarbeitet)."""
import pytest
from knix_arranger.models.knx_secure import (
    KnxSecureConfig, DeviceSecureInfo, GA_SECURITY_MODES, is_valid_knx_key,
)
from knix_arranger.services.knx_secure_service import (
    KnxSecureService, MixedLineWarning, KnxSecureWrongPassword,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.group_address import GroupAddress


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project() -> KnxProject:
    project = KnxProject(name="Secure-Test")
    return project


def _make_project_with_ga() -> KnxProject:
    """Projekt mit einigen GAs fuer Security-Tests."""
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup
    )
    project = KnxProject(name="Secure-GA-Test")
    structure = GroupAddressStructure()
    hg = MainGroup(number=1, name="Licht")
    mg = MiddleGroup(number=0, name="EG")
    mg.group_addresses = [
        GroupAddress(main_group=1, middle_group=0, sub_group=0,
                     designation="L.EG.01.01_ea", function_name="Schalten", security="Auto"),
        GroupAddress(main_group=1, middle_group=0, sub_group=1,
                     designation="L.EG.01.01_szene", function_name="Szene", security="Auto"),
        GroupAddress(main_group=1, middle_group=0, sub_group=2,
                     designation="L.EG.01.01_dim", function_name="Dimmen", security="Auto"),
    ]
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    project.group_addresses = structure
    return project


# ── Datenmodell ────────────────────────────────────────────────────────────────

class TestKnxSecureModel:
    def test_default_not_enabled(self):
        cfg = KnxSecureConfig()
        assert cfg.enabled is False

    def test_default_fields_empty(self):
        cfg = KnxSecureConfig()
        assert cfg.ets_project_password == ""
        assert cfg.ets_password_note == ""
        assert cfg.device_infos == {}
        assert cfg.is_locked is False

    def test_is_valid_knx_key_format(self):
        assert is_valid_knx_key("A" * 32) is True
        assert is_valid_knx_key("XYZ") is False
        assert is_valid_knx_key("A" * 31) is False

    def test_serialization_roundtrip(self):
        cfg = KnxSecureConfig(
            enabled=True,
            ets_project_password="geheim123",
            ets_password_note="Im Firmentresor hinterlegt",
        )
        cfg.device_infos["dev-1"] = DeviceSecureInfo(
            device_id="dev-1", device_name="Schalter", secure_supported=True,
            fdsk="AABBCCDDEEFF00112233445566778899"[:32],
        )
        restored = KnxSecureConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.ets_project_password == cfg.ets_project_password
        assert restored.ets_password_note == cfg.ets_password_note
        assert "dev-1" in restored.device_infos
        assert restored.device_infos["dev-1"].fdsk == cfg.device_infos["dev-1"].fdsk

    def test_no_tool_key_or_runtime_keys_on_device_info(self):
        """DeviceSecureInfo verwaltet keine ETS-Laufzeitschluessel mehr,
        nur das Zertifikat (FDSK)."""
        info = DeviceSecureInfo(device_id="d1")
        assert not hasattr(info, "tool_key")

    def test_project_knx_secure_default(self):
        """Neues Projekt hat nicht-aktivierten KNX Secure."""
        project = KnxProject()
        assert project.knx_secure.enabled is False

    def test_ga_security_modes_defined(self):
        for mode in ("Auto", "Ein", "Aus"):
            assert mode in GA_SECURITY_MODES


# ── KnxSecureService ──────────────────────────────────────────────────────────

class TestKnxSecureService:
    def setup_method(self):
        self.svc = KnxSecureService()
        self.project = _make_project()
        self.cfg = self.project.knx_secure

    def test_get_summary(self):
        summary = self.svc.get_summary(self.cfg, self.project)
        assert "enabled" in summary
        assert "ets_password_set" in summary
        assert "ga_security_on" in summary

    def test_reset_ga_security(self):
        project = _make_project_with_ga()
        for ga in project.group_addresses.all_addresses():
            ga.security = "Ein"
        n = self.svc.reset_ga_security_to_auto(project)
        assert n > 0
        for ga in project.group_addresses.all_addresses():
            assert ga.security == "Auto"


class TestAutoSuggestGaSecurity:
    def setup_method(self):
        self.svc = KnxSecureService()
        self.project = _make_project_with_ga()

    def test_schalten_gets_ein(self):
        """GA mit 'Schalten' in function_name bekommt Security='Ein'."""
        n = self.svc.auto_suggest_ga_security(self.project)
        assert n > 0
        for ga in self.project.group_addresses.all_addresses():
            if "schalten" in (ga.function_name or "").lower():
                assert ga.security == "Ein"

    def test_szene_gets_ein(self):
        """GA mit 'Szene' in function_name bekommt Security='Ein'."""
        self.svc.auto_suggest_ga_security(self.project)
        for ga in self.project.group_addresses.all_addresses():
            if "szene" in (ga.function_name or "").lower():
                assert ga.security == "Ein"

    def test_dim_stays_auto(self):
        """GA 'Dimmen' ohne Secure-Keywords bleibt auf 'Auto'."""
        self.svc.auto_suggest_ga_security(self.project)
        for ga in self.project.group_addresses.all_addresses():
            if ga.function_name == "Dimmen":
                assert ga.security == "Auto"

    def test_returns_changed_count(self):
        n = self.svc.auto_suggest_ga_security(self.project)
        assert isinstance(n, int)
        assert n >= 0


class TestMixedLineCheck:
    def setup_method(self):
        self.svc = KnxSecureService()

    def test_no_warnings_empty_project(self):
        """Leeres Projekt hat keine Mischlinien-Warnungen."""
        project = KnxProject()
        warnings = self.svc.check_mixed_lines(project.knx_secure, project)
        assert warnings == []

    def test_warning_on_mixed_line(self):
        """Linie mit Secure + Non-Secure produziert Warnung."""
        from knix_arranger.models.topology import Area, Line, Device
        project = KnxProject()
        area = Area(area_number=1, name="Bereich 1")
        line = Line(line_number=1, name="Linie 1")
        dev_secure = Device(id="d1", product="Secure-Gerät", physical_address="1.1.1")
        dev_nonsecure = Device(id="d2", product="Non-Secure", physical_address="1.1.2")
        line.devices = [dev_secure, dev_nonsecure]
        area.lines = [line]
        project.topology.areas = [area]

        cfg = project.knx_secure
        cfg.device_infos["d1"] = DeviceSecureInfo(
            device_id="d1", device_name="Secure-Gerät",
            secure_supported=True, line_id=line.id
        )
        cfg.device_infos["d2"] = DeviceSecureInfo(
            device_id="d2", device_name="Non-Secure",
            secure_supported=False, line_id=line.id
        )

        warnings = self.svc.check_mixed_lines(cfg, project)
        assert len(warnings) == 1
        assert "Non-Secure" in warnings[0].message

    def test_warning_message_contains_line_info(self):
        """Warnungsmeldung enthaelt Liniennummer."""
        from knix_arranger.models.topology import Area, Line, Device
        project = KnxProject()
        area = Area(area_number=2, name="Bereich 2")
        line = Line(line_number=3, name="Linie 3")
        dev_s = Device(id="s1", product="Secure", physical_address="2.3.1")
        dev_n = Device(id="n1", product="NonSecure", physical_address="2.3.2")
        line.devices = [dev_s, dev_n]
        area.lines = [line]
        project.topology.areas = [area]

        cfg = project.knx_secure
        cfg.device_infos["s1"] = DeviceSecureInfo(device_id="s1", secure_supported=True, line_id=line.id)
        cfg.device_infos["n1"] = DeviceSecureInfo(device_id="n1", secure_supported=False, line_id=line.id)

        warnings = self.svc.check_mixed_lines(cfg, project)
        assert len(warnings) == 1
        assert "2" in warnings[0].message and "3" in warnings[0].message


# ── FA-2706: Passwortbasierte Verschluesselung des Archivs ───────────────────

class TestKnxSecureEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        """Verschluesselung/Entschluesselung der sensiblen Felder ist verlustfrei."""
        cfg = KnxSecureConfig(
            enabled=True,
            ets_project_password="s3cr3t-ets-pw",
            ets_password_note="Backup im Tresor",
        )
        cfg.device_infos["d1"] = DeviceSecureInfo(
            device_id="d1", device_name="Schalter",
            fdsk="A1B2C3D4E5F6071829304A5B6C7D8E9F",
        )
        blob = KnxSecureService.encrypt_config(cfg, "master-passwort")
        assert blob.get("secure_blob") is not None
        # Sensible Felder liegen im Klartext-Teil nicht mehr vor
        assert blob["ets_project_password"] == ""
        assert blob["device_infos"]["d1"]["fdsk"] == ""

        restored = KnxSecureService.decrypt_config(blob, "master-passwort")
        assert restored.ets_project_password == cfg.ets_project_password
        assert restored.ets_password_note == cfg.ets_password_note
        assert restored.device_infos["d1"].fdsk == cfg.device_infos["d1"].fdsk

    def test_non_sensitive_fields_stay_plaintext(self):
        """secure_supported/Geraetestruktur bleiben ohne Passwort lesbar."""
        cfg = KnxSecureConfig(enabled=True, ets_project_password="pw")
        cfg.device_infos["d1"] = DeviceSecureInfo(
            device_id="d1", device_name="Aktor", secure_supported=True,
        )
        blob = KnxSecureService.encrypt_config(cfg, "master-passwort")
        loaded_without_password = KnxSecureConfig.from_dict(blob)
        assert loaded_without_password.device_infos["d1"].secure_supported is True
        assert loaded_without_password.device_infos["d1"].device_name == "Aktor"

    def test_wrong_password_raises(self):
        """Falsches Master-Passwort wirft KnxSecureWrongPassword statt leise zu scheitern."""
        cfg = KnxSecureConfig(enabled=True, ets_project_password="pw")
        blob = KnxSecureService.encrypt_config(cfg, "richtiges-passwort")
        with pytest.raises(KnxSecureWrongPassword):
            KnxSecureService.decrypt_config(blob, "falsches-passwort")

    def test_project_serialization_with_secure(self):
        """Archiv uebersteht Projekt-Serialisierung, wenn ein Session-Passwort gesetzt ist."""
        project = KnxProject(name="Secure-Projekt")
        project.knx_secure.enabled = True
        project.knx_secure.ets_project_password = "s3cr3t"
        KnxSecureService.unlock(project.knx_secure, "master-pw")

        data = project.to_dict()
        assert data["knx_secure"].get("secure_blob") is not None

        restored = KnxProject.from_dict(data)
        assert restored.knx_secure.enabled is True
        assert restored.knx_secure.is_locked is True
        # Ohne Passwort ist der Wert nicht lesbar
        assert restored.knx_secure.ets_project_password == ""
        unlocked = KnxSecureService.unlock(restored.knx_secure, "master-pw")
        assert unlocked.ets_project_password == "s3cr3t"

    def test_no_password_set_stores_plaintext(self):
        """Ohne je ein Master-Passwort gesetzt zu haben, wird (leeres) Archiv
        einfach als Klartext-Dict gespeichert -- kein Absturz."""
        project = KnxProject(name="Ohne-Passwort")
        data = project.to_dict()
        assert data["knx_secure"].get("secure_blob") is None
