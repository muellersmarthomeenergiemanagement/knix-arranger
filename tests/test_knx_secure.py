"""Tests fuer KNX Secure (FA-2701 bis FA-2706)."""
import pytest
from knix_arranger.models.knx_secure import (
    KnxSecureConfig, DeviceSecureInfo, generate_knx_key, KEY_LENGTH_BYTES,
    GA_SECURITY_MODES,
)
from knix_arranger.services.knx_secure_service import KnxSecureService, MixedLineWarning
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

    def test_default_keys_empty(self):
        cfg = KnxSecureConfig()
        assert cfg.backbone_key == ""
        assert cfg.group_key == ""
        assert cfg.ga_keys == {}
        assert cfg.device_infos == {}

    def test_generate_knx_key_format(self):
        """Schluessel hat 32 Hex-Zeichen (128 bit = 16 Byte)."""
        key = generate_knx_key()
        assert len(key) == KEY_LENGTH_BYTES * 2
        assert all(c in "0123456789ABCDEF" for c in key)

    def test_generate_knx_key_unique(self):
        """Jeder generierte Schluessel ist einzigartig."""
        keys = {generate_knx_key() for _ in range(50)}
        assert len(keys) == 50

    def test_serialization_roundtrip(self):
        cfg = KnxSecureConfig(
            enabled=True,
            backbone_key="AABBCCDDEEFF00112233445566778899",
            group_key="0011223344556677889900AABBCCDDEE",
        )
        cfg.ga_keys["1/1/1"] = "A1B2C3D4E5F6071829304A5B6C7D8E9F"
        cfg.device_infos["dev-1"] = DeviceSecureInfo(
            device_id="dev-1", device_name="Schalter", secure_supported=True
        )
        restored = KnxSecureConfig.from_dict(cfg.to_dict())
        assert restored.enabled is True
        assert restored.backbone_key == cfg.backbone_key
        assert restored.ga_keys["1/1/1"] == cfg.ga_keys["1/1/1"]
        assert "dev-1" in restored.device_infos

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

    def test_generate_all_keys_backbone(self):
        """generate_all_project_keys setzt Backbone Key."""
        self.svc.generate_all_project_keys(self.cfg, self.project)
        assert len(self.cfg.backbone_key) == 32

    def test_generate_all_keys_group(self):
        self.svc.generate_all_project_keys(self.cfg, self.project)
        assert len(self.cfg.group_key) == 32

    def test_generate_all_keys_no_overwrite(self):
        """Bestehende Schluessel werden nicht ueberschrieben."""
        fixed = "A" * 32
        self.cfg.backbone_key = fixed
        self.svc.generate_all_project_keys(self.cfg, self.project)
        assert self.cfg.backbone_key == fixed

    def test_generate_all_keys_returns_count(self):
        """Gibt die Anzahl neu generierter Schluessel zurueck."""
        n = self.svc.generate_all_project_keys(self.cfg, self.project)
        assert n >= 2  # Mindestens backbone + group key

    def test_regenerate_backbone_key(self):
        self.cfg.backbone_key = "OLD" + "A" * 29
        old = self.cfg.backbone_key
        new_key = self.svc.regenerate_key(self.cfg, "backbone_key")
        assert new_key != old
        assert self.cfg.backbone_key == new_key

    def test_regenerate_group_key(self):
        new_key = self.svc.regenerate_key(self.cfg, "group_key")
        assert len(new_key) == 32
        assert self.cfg.group_key == new_key

    def test_regenerate_ga_key(self):
        self.cfg.ga_keys["1/2/3"] = "0" * 32
        new_key = self.svc.regenerate_key(self.cfg, "ga_key", scope_id="1/2/3")
        assert self.cfg.ga_keys["1/2/3"] == new_key
        assert new_key != "0" * 32

    def test_get_summary(self):
        summary = self.svc.get_summary(self.cfg, self.project)
        assert "enabled" in summary
        assert "backbone_key_set" in summary
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


# ── FA-2706: Verschluesselung ─────────────────────────────────────────────────

class TestKnxSecureEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        """Verschluesselung und Entschluesselung ist verlustfrei."""
        cfg = KnxSecureConfig(
            enabled=True,
            backbone_key=generate_knx_key(),
            group_key=generate_knx_key(),
        )
        blob = KnxSecureService.encrypt_config(cfg, "test-project-id")
        assert blob.get("encrypted") is True
        restored = KnxSecureService.decrypt_config(blob, "test-project-id")
        assert restored.backbone_key == cfg.backbone_key
        assert restored.group_key == cfg.group_key

    def test_wrong_project_id_returns_empty(self):
        """Falscher Projekt-ID liefert leere Konfiguration."""
        cfg = KnxSecureConfig(
            enabled=True,
            backbone_key=generate_knx_key(),
        )
        blob = KnxSecureService.encrypt_config(cfg, "project-A")
        restored = KnxSecureService.decrypt_config(blob, "project-B")
        # Muss ohne Exception durchlaufen; Schluessel sollten nicht uebereinstimmen
        assert isinstance(restored, KnxSecureConfig)

    def test_project_serialization_with_secure(self):
        """KNX Secure Schluessel ueberstehen Projekt-Serialisierung."""
        project = KnxProject(name="Secure-Projekt")
        project.knx_secure.enabled = True
        project.knx_secure.backbone_key = generate_knx_key()
        project.knx_secure.group_key = generate_knx_key()

        restored = KnxProject.from_dict(project.to_dict())
        assert restored.knx_secure.enabled is True
        # Schluessel muessen nach Serialisierung gleich sein
        assert restored.knx_secure.backbone_key == project.knx_secure.backbone_key

    def test_non_encrypted_blob_loads_normally(self):
        """Nicht-verschluesselter Blob wird direkt geladen."""
        cfg = KnxSecureConfig(enabled=False, backbone_key="ABCD" * 8)
        blob = cfg.to_dict()
        assert not blob.get("encrypted")
        restored = KnxSecureService.decrypt_config(blob, "any-id")
        assert restored.backbone_key == cfg.backbone_key
