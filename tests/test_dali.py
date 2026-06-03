"""Tests fuer DALI-Konfiguration (FA-2801 bis FA-2806)."""
import pytest
from knix_arranger.models.dali_config import (
    DaliGateway, DaliDevice, DaliGroup, DaliScene, EMERGENCY_MODES
)
from knix_arranger.services.dali_service import DaliService
from knix_arranger.models.project import KnxProject


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project_with_dali() -> KnxProject:
    """Erstellt ein minimales Projekt mit einer DALI-Gateway-Konfiguration."""
    project = KnxProject(name="DALI-Testprojekt")
    gw = DaliGateway(
        gateway_device_id="dev-001",
        name="DALI-Gateway EG",
    )
    gw.devices = [
        DaliDevice(short_address=0, name="EVG 0", evg_type="LED", group_memberships=[0]),
        DaliDevice(short_address=1, name="EVG 1", evg_type="LED", group_memberships=[0, 1]),
        DaliDevice(short_address=2, name="Notlicht", evg_type="Notlicht",
                   is_emergency=True, emergency_mode="sustained", group_memberships=[2]),
    ]
    gw.groups = [
        DaliGroup(number=0, name="Reihe 1"),
        DaliGroup(number=1, name="Reihe 2"),
        DaliGroup(number=2, name="Notlicht"),
    ]
    gw.scenes = [DaliScene(number=0, name="Praesenz")]
    project.dali_configs["dev-001"] = gw
    return project


# ── Datenmodell ────────────────────────────────────────────────────────────────

class TestDaliDataModel:
    def test_dali_device_defaults(self):
        dev = DaliDevice()
        assert dev.short_address == 0
        assert dev.is_emergency is False
        assert dev.emergency_mode == "auto"
        assert dev.group_memberships == []

    def test_dali_group_defaults(self):
        grp = DaliGroup()
        assert grp.device_addresses == []
        assert grp.number == 0

    def test_dali_gateway_defaults(self):
        gw = DaliGateway()
        assert gw.devices == []
        assert gw.groups == []
        assert gw.scenes == []
        assert gw.ga_switch_broadcast == ""

    def test_dali_device_serialization(self):
        dev = DaliDevice(
            short_address=5, name="Leuchte", evg_type="LED",
            group_memberships=[0, 2], is_emergency=True, emergency_mode="standby",
        )
        restored = DaliDevice.from_dict(dev.to_dict())
        assert restored.short_address == 5
        assert restored.name == "Leuchte"
        assert restored.group_memberships == [0, 2]
        assert restored.is_emergency is True
        assert restored.emergency_mode == "standby"

    def test_dali_gateway_serialization(self):
        gw = DaliGateway(
            gateway_device_id="dev-42", name="Test-GW",
            ga_switch_broadcast="1/0/0", ga_dim_broadcast="1/0/1",
        )
        gw.devices.append(DaliDevice(short_address=0, name="EVG 0"))
        gw.groups.append(DaliGroup(number=0, name="Gruppe 0"))
        gw.scenes.append(DaliScene(number=0, name="Szene 0"))
        restored = DaliGateway.from_dict(gw.to_dict())
        assert restored.gateway_device_id == "dev-42"
        assert restored.ga_switch_broadcast == "1/0/0"
        assert len(restored.devices) == 1
        assert len(restored.groups) == 1
        assert len(restored.scenes) == 1

    def test_project_dali_configs_serialization(self):
        """DaliGateway-Konfigurationen ueberstehen Projekt-Serialisierung."""
        project = _make_project_with_dali()
        restored = KnxProject.from_dict(project.to_dict())
        assert "dev-001" in restored.dali_configs
        gw = restored.dali_configs["dev-001"]
        assert len(gw.devices) == 3
        assert gw.name == "DALI-Gateway EG"

    def test_empty_project_has_no_dali_configs(self):
        """Neues Projekt hat keine DALI-Konfigurationen."""
        project = KnxProject()
        assert project.dali_configs == {}

    def test_emergency_modes_defined(self):
        for mode in ("sustained", "standby", "auto"):
            assert mode in EMERGENCY_MODES


# ── DaliService ────────────────────────────────────────────────────────────────

class TestDaliService:
    def setup_method(self):
        self.svc = DaliService()
        self.project = _make_project_with_dali()
        self.gw = self.project.dali_configs["dev-001"]

    def test_get_or_create_new(self):
        project = KnxProject(name="Leer")
        gw = self.svc.get_or_create(project, "new-gw", name="Mein DALI")
        assert gw.gateway_device_id == "new-gw"
        assert gw.name == "Mein DALI"
        assert "new-gw" in project.dali_configs

    def test_get_or_create_existing(self):
        gw1 = self.svc.get_or_create(self.project, "dev-001")
        gw2 = self.svc.get_or_create(self.project, "dev-001")
        assert gw1 is gw2

    def test_sync_groups_from_devices(self):
        """sync_groups aktualisiert DaliGroup.device_addresses aus den EVGs."""
        self.svc.sync_groups_from_devices(self.gw)
        grp0 = next(g for g in self.gw.groups if g.number == 0)
        assert 0 in grp0.device_addresses
        assert 1 in grp0.device_addresses

    def test_sync_groups_notlicht(self):
        self.svc.sync_groups_from_devices(self.gw)
        grp2 = next(g for g in self.gw.groups if g.number == 2)
        assert 2 in grp2.device_addresses

    def test_generate_device_list_count(self):
        rows = self.svc.generate_device_list(self.gw, self.project)
        assert len(rows) == len(self.gw.devices)

    def test_generate_device_list_sorted(self):
        rows = self.svc.generate_device_list(self.gw, self.project)
        addresses = [r["short_address"] for r in rows]
        assert addresses == sorted(addresses)

    def test_generate_device_list_emergency_flag(self):
        rows = self.svc.generate_device_list(self.gw, self.project)
        emrg_rows = [r for r in rows if r["is_emergency"]]
        assert len(emrg_rows) == 1
        assert emrg_rows[0]["short_address"] == 2

    def test_generate_device_list_has_required_keys(self):
        rows = self.svc.generate_device_list(self.gw, self.project)
        for row in rows:
            for key in ("short_address", "name", "evg_type", "room", "groups", "is_emergency"):
                assert key in row

    def test_emergency_checklist_items_count(self):
        """Pro Notlicht-EVG werden 2 Pruefpunkte erzeugt."""
        items = self.svc.generate_emergency_checklist_items(self.gw)
        emergency_devs = sum(1 for d in self.gw.devices if d.is_emergency)
        assert len(items) == emergency_devs * 2

    def test_emergency_checklist_items_category(self):
        items = self.svc.generate_emergency_checklist_items(self.gw)
        for item in items:
            assert item["category"] == "DALI Notbeleuchtung"

    def test_emergency_checklist_empty_without_emergency(self):
        gw = DaliGateway(gateway_device_id="x", name="x")
        gw.devices.append(DaliDevice(short_address=0, is_emergency=False))
        items = self.svc.generate_emergency_checklist_items(gw)
        assert items == []

    def test_ensure_default_scenes(self):
        gw = DaliGateway(gateway_device_id="x", name="x")
        DaliService.ensure_default_scenes(gw)
        assert len(gw.scenes) == 4

    def test_ensure_default_scenes_noop_if_exists(self):
        gw = DaliGateway(gateway_device_id="x", name="x")
        gw.scenes.append(DaliScene(number=0, name="Meine Szene"))
        DaliService.ensure_default_scenes(gw)
        assert len(gw.scenes) == 1

    def test_link_gas_no_crash_on_empty_structure(self):
        """link_gas_from_structure laeuft fehlerfrei mit leerer GA-Struktur."""
        gw = DaliGateway(gateway_device_id="x", name="GW")
        n = self.svc.link_gas_from_structure(gw, self.project)
        assert n == 0


# ── Adressbereichs-Validierung ─────────────────────────────────────────────────

class TestDaliAddressRanges:
    def test_short_address_range(self):
        for addr in [0, 32, 63]:
            dev = DaliDevice(short_address=addr)
            assert 0 <= dev.short_address <= 63

    def test_group_range(self):
        for nr in [0, 7, 15]:
            grp = DaliGroup(number=nr)
            assert 0 <= grp.number <= 15

    def test_scene_range(self):
        for nr in [0, 7, 15]:
            sc = DaliScene(number=nr)
            assert 0 <= sc.number <= 15

    def test_max_64_devices(self):
        """Bis zu 64 EVGs sind moeglich."""
        gw = DaliGateway(gateway_device_id="x", name="x")
        for i in range(64):
            gw.devices.append(DaliDevice(short_address=i))
        assert len(gw.devices) == 64

    def test_max_16_groups(self):
        gw = DaliGateway(gateway_device_id="x", name="x")
        for i in range(16):
            gw.groups.append(DaliGroup(number=i))
        assert len(gw.groups) == 16

    def test_max_16_scenes(self):
        gw = DaliGateway(gateway_device_id="x", name="x")
        for i in range(16):
            gw.scenes.append(DaliScene(number=i))
        assert len(gw.scenes) == 16
