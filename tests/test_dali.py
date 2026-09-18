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


# ---------------------------------------------------------------------------
# link_gas_from_structure -- Regression: die LDA-Namenskonvention aus einem
# ETS6-XLSX-Import ("LDA.OG.00.02_ea", Punkt-getrennt, wie vom Installateur
# selbst vergeben) wurde nicht erkannt -- nur die KNiX-eigene NamingEngine-
# Konvention ("LDA_E05_01 E/A", Unterstrich+Leerzeichen, nur bei in KNiX
# Arranger selbst neu generierten Adressen). Bei importierten Projekten (der
# haeufigere Fall) verknuepfte der Button "GAs automatisch verknuepfen"
# dadurch ueberhaupt nichts.
# ---------------------------------------------------------------------------

def _make_ga_structure(designations: list[str]):
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
    )
    structure = GroupAddressStructure()
    mg = MiddleGroup(number=0, name="DALI")
    hg = MainGroup(number=0, name="Zentral")
    hg.middle_groups = [mg]
    structure.main_groups = [hg]
    for i, desig in enumerate(designations):
        mg.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=i, designation=desig,
        ))
    return structure


class TestLinkGasFromStructureImportConvention:
    def setup_method(self):
        self.svc = DaliService()
        self.project = KnxProject(name="Test")
        self.gw = DaliGateway(gateway_device_id="dev-1", name="GW")

    def test_dot_convention_links_switch_and_dim(self):
        """Realer Fall (Chalet-Projekt): 'LDA.OG.00.02+LDA.OG.00.01_ea' bzw.
        '..._dim' muessen als E/A- bzw. DIM-Broadcast-GA erkannt werden."""
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.02+LDA.OG.00.01_ea",
            "LDA.OG.00.02+LDA.OG.00.01_dim",
            "LDA.OG.00.02+LDA.OG.00.01_wert",
        ])

        n = self.svc.link_gas_from_structure(self.gw, self.project)

        assert self.gw.ga_switch_broadcast == "0/0/0"
        assert self.gw.ga_dim_broadcast == "0/0/1"
        assert n >= 2

    def test_dot_convention_links_scene_and_status(self):
        self.project.group_addresses = _make_ga_structure([
            "LDA.EG.00.01_szene",
            "LDA.EG.00.01_rmwert",
            "LDA.EG.00.01_stoerung",
        ])

        self.svc.link_gas_from_structure(self.gw, self.project)

        assert self.gw.ga_scene == "0/0/0"
        assert self.gw.ga_status_value == "0/0/1"
        assert self.gw.ga_status_fault == "0/0/2"

    def test_dot_convention_ignores_unrelated_wert_only_suffix(self):
        """'_wert' allein (Sollwert-Kanal, kein Feedback) ist keine der fuenf
        DaliGateway-Zielgroessen und darf nichts faelschlich belegen."""
        self.project.group_addresses = _make_ga_structure([
            "LDA.EG.00.01_wert",
        ])

        n = self.svc.link_gas_from_structure(self.gw, self.project)

        assert n == 0
        assert self.gw.ga_switch_broadcast == ""
        assert self.gw.ga_dim_broadcast == ""

    def test_naming_engine_convention_still_works(self):
        """Regressionsschutz: die urspruengliche KNiX-eigene Konvention
        (Unterstrich+Leerzeichen) darf durch die neue Punkt-Erkennung nicht
        brechen."""
        self.project.group_addresses = _make_ga_structure([
            "LDA_E05_01 E/A",
            "LDA_E05_01 DIM",
        ])

        self.svc.link_gas_from_structure(self.gw, self.project)

        assert self.gw.ga_switch_broadcast == "0/0/0"
        assert self.gw.ga_dim_broadcast == "0/0/1"

    def test_dot_convention_tolerates_freitext_zwischen_suffix_und_klammer(self):
        """Regression (Chalet Franziska 2005): 'LDA.EG.00.01_ea von pir
        ( Spots Haupteingang )' -- der Installateur haengt in ETS teils noch
        einen Freitext-Kommentar ("von pir") HINTER das Funktions-Suffix,
        VOR die Klammer-Bezeichnung. Der alte Endanker (\\s*$) verlangte den
        Suffix als letztes Wort vor der Klammer und schlug hier fehl, wodurch
        diese GA nie verknuepft wurde (unsichtbar in der DALI-Konfiguration,
        obwohl sie laut CO-Verknuepfung an DALI-COs haengt)."""
        self.project.group_addresses = _make_ga_structure([
            "LDA.EG.00.01_ea von pir  ( Spots Haupteingang )",
        ])

        n = self.svc.link_gas_from_structure(self.gw, self.project)

        assert n == 1
        assert self.gw.ga_switch_broadcast == "0/0/0"


# ---------------------------------------------------------------------------
# _derive_groups_from_import / _derive_evgs_from_import -- dieselbe
# Importkonvention ("LDA.OG.00.02_ea") muss auch bei der automatischen
# Gruppen-/EVG-Ableitung nach Import erkannt werden, nicht nur beim manuellen
# "GAs automatisch verknüpfen"-Button (link_gas_from_structure).
# ---------------------------------------------------------------------------

def _make_device_with_kos(phys_addr: str, ga_room_pairs: list[tuple[str, str]]):
    """Gerät mit einem KO pro (ga_address, ga_address)-Paar, alle auf
    dieselbe GA-Adresse verweisend (vereinfachtes Setup: die tatsächliche
    Funktion wird über die GA-Bezeichnung in der GA-Struktur bestimmt, nicht
    über den KO-Namen)."""
    from knix_arranger.models.topology import Device, CommunicationObject
    device = Device(physical_address=phys_addr, device_type="gateway", product="DALI-Gateway")
    for i, (ga_addr, _label) in enumerate(ga_room_pairs):
        device.communication_objects.append(CommunicationObject(
            object_number=i, name=_label, connected_gas=[ga_addr],
        ))
    return device


class TestDeriveGroupsFromImportDotConvention:
    def setup_method(self):
        self.svc = DaliService()
        self.project = KnxProject(name="Test")
        self.gw = DaliGateway(gateway_device_id="dev-1", name="GW")

    def test_dot_convention_groups_are_derived(self):
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.02_ea",
            "LDA.OG.00.02_dim",
            "LDA.OG.00.02_wert",
            "LDA.EG.01.01_ea",
            "LDA.EG.01.01_dim",
        ])
        device = _make_device_with_kos("1.1.1", [
            ("0/0/0", "a"), ("0/0/1", "b"), ("0/0/2", "c"),
            ("0/0/3", "d"), ("0/0/4", "e"),
        ])

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 2
        by_switch = {g.ga_switch: g for g in self.gw.groups if g.ga_switch}
        assert by_switch["0/0/0"].ga_dim == "0/0/1"
        assert by_switch["0/0/0"].ga_value == "0/0/2"
        assert by_switch["0/0/3"].ga_dim == "0/0/4"

    def test_dot_convention_multi_room_broadcast_gets_combined_name(self):
        """Eine per '+' verbundene Broadcast-GA ('LDA.OG.00.02+LDA.OG.00.01')
        muss trotzdem als eine Gruppe erkannt werden, mit einem aus beiden
        Raumnamen zusammengesetzten Namen."""
        from knix_arranger.models.building import (
            Areal, Building, Wing, Floor, Apartment, Room,
        )
        room1 = Room(number="00", name="Wohnen")
        room2 = Room(number="01", name="Essen")
        apt = Apartment(name="OG", rooms=[room1, room2])
        floor = Floor(name="Obergeschoss", short_code="OG", apartments=[apt])
        wing = Wing(name="Haupthaus", floors=[floor])
        building = Building(name="Haus", wings=[wing])
        self.project.areal = Areal(buildings=[building])

        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.02+LDA.OG.01.01_ea",
            "LDA.OG.00.02+LDA.OG.01.01_dim",
        ])
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a"), ("0/0/1", "b")])

        self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert len(self.gw.groups) == 1
        assert self.gw.groups[0].name == "Wohnen + Essen"

    def test_naming_engine_convention_groups_still_work(self):
        """Regressionsschutz: die urspruengliche KNiX-eigene Konvention darf
        durch die neue Punkt-Erkennung nicht brechen."""
        self.project.group_addresses = _make_ga_structure([
            "LDA_00_01 E/A",
            "LDA_00_01 DIM",
        ])
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a"), ("0/0/1", "b")])

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 1
        assert self.gw.groups[0].ga_switch == "0/0/0"
        assert self.gw.groups[0].ga_dim == "0/0/1"

    def test_mg0_mg7_spiegeladresse_erzeugt_keine_zweite_gruppe(self):
        """Regression (Chalet Franziska 2005): fast jede DALI-Gruppe trug dort
        neben ihrer MG-0-Steuer-GA eine MG-7-"Status"-Spiegeladresse mit
        IDENTISCHEM Freitext (nur Haupt-/Untergruppe gleich, Mittelgruppe
        0 vs 7) -- das darf nicht zu einer verdoppelten Gruppe fuehren."""
        from knix_arranger.models.group_address import GroupAddress, MiddleGroup
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.02_ea  ( Wandleuchten )",
        ])
        ga2 = GroupAddress(
            main_group=0, middle_group=7, sub_group=0,
            designation="LDA.OG.00.02_ea  ( Wandleuchten )",
        )
        self.project.group_addresses.main_groups[0].middle_groups.append(
            MiddleGroup(number=7, name="Status", group_addresses=[ga2])
        )
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a"), ("0/7/0", "b")])

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 1
        assert self.gw.groups[0].ga_switch == "0/0/0"  # MG-0-Adresse gewinnt

    def test_echte_kollision_wird_als_eigene_gruppe_sichtbar(self):
        """Regression (Chalet Franziska 2005): GA 2/0/3 ("Spots Haupteingang",
        per Bewegungsmelder ausgeloest) trug denselben LDA-Raum/Element-Code
        wie die unabhaengige GA 2/0/0 -- gleiche Haupt- UND Mittelgruppe,
        aber andere Untergruppe = keine Spiegeladresse, echte Kollision.
        Vorher ging 2/0/3 dabei stillschweigend verloren (last-write-wins)
        und tauchte in der DALI-Konfiguration nirgends auf, obwohl sie laut
        CO-Verknuepfung an DALI-COs haengt."""
        from knix_arranger.models.group_address import GroupAddress
        self.project.group_addresses = _make_ga_structure([
            "LDA.EG.00.01_ea  ( Spots Haupteingang )",
        ])
        ga2 = GroupAddress(
            main_group=0, middle_group=0, sub_group=3,
            designation="LDA.EG.00.01_ea von pir  ( Spots Haupteingang )",
        )
        self.project.group_addresses.main_groups[0].middle_groups[0].group_addresses.append(ga2)
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a"), ("0/0/3", "b")])

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 2
        switches = {g.ga_switch for g in self.gw.groups}
        assert switches == {"0/0/0", "0/0/3"}
        new_grp = next(g for g in self.gw.groups if g.ga_switch == "0/0/3")
        assert new_grp.name == "Spots Haupteingang"

    def test_freitext_nach_suffix_verhindert_gruppe_nicht(self):
        """Regression (Chalet Franziska 2005, Formular DA DALI-Konfiguration):
        eine GA mit Freitext zwischen Funktions-Suffix und Klammer-Bezeichnung
        ("LDA.EG.00.01_ea von pir  ( Spots Haupteingang )") muss trotzdem eine
        eigene DALI-Gruppe ergeben, statt beim Parsen uebersehen zu werden."""
        self.project.group_addresses = _make_ga_structure([
            "LDA.EG.00.01_ea von pir  ( Spots Haupteingang )",
        ])
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a")])

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 1
        assert self.gw.groups[0].ga_switch == "0/0/0"

    def test_gruppennummer_folgt_echtem_ko_namen(self):
        """Regression (Chalet Franziska 2005): ohne Abgleich mit dem echten
        KO-Namen ("G5, Schalten,") lief die in der App angezeigte
        Gruppennummer rein nach Sortierreihenfolge der Raum-Schluessel und
        driftete von der physischen DALI-Gruppennummer im Gateway auseinander.
        Jetzt muss "G5" zu number=4 werden (0-basiert: DALI-Gruppe 1 = 0)."""
        from knix_arranger.models.topology import Device, CommunicationObject
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.05_ea",
        ])
        device = Device(physical_address="1.1.1", device_type="gateway", product="DALI-Gateway")
        device.communication_objects = [
            CommunicationObject(object_number=0, name="G5, Schalten,", connected_gas=["0/0/0"]),
        ]

        self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert len(self.gw.groups) == 1
        assert self.gw.groups[0].number == 4

    def test_ausgeschriebene_ko_form_wird_auch_erkannt(self):
        """'Gruppe 3 Schalten' (bereits vorher unterstuetzte Langform) muss
        weiterhin zur physischen Nummer fuehren, nicht nur die Kurzform 'G3,'."""
        from knix_arranger.models.topology import Device, CommunicationObject
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.03_ea",
        ])
        device = Device(physical_address="1.1.1", device_type="gateway", product="DALI-Gateway")
        device.communication_objects = [
            CommunicationObject(object_number=0, name="Gruppe 3 Schalten", connected_gas=["0/0/0"]),
        ]

        self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert self.gw.groups[0].number == 2

    def test_mehrdeutige_ga_faellt_auf_naechste_freie_nummer_zurueck(self):
        """Wird dieselbe GA von zwei verschiedenen physischen Gruppen-COs
        referenziert (reale, mehrdeutige Verdrahtung -- siehe GA 2/0/3-Fall),
        darf das Ableiten nicht crashen oder eine falsche Nummer erzwingen;
        beide Gruppen muessen trotzdem eindeutige Nummern erhalten."""
        from knix_arranger.models.topology import Device, CommunicationObject
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.01_ea",
            "LDA.OG.00.02_ea",
        ])
        device = Device(physical_address="1.1.1", device_type="gateway", product="DALI-Gateway")
        device.communication_objects = [
            # Beide GAs sind ambig (auch an G2/G5 gebunden) -- keine eindeutige
            # physische Nummer ableitbar, aber es darf trotzdem funktionieren.
            CommunicationObject(object_number=0, name="G2, Schalten,",
                                 connected_gas=["0/0/0", "0/0/1"]),
            CommunicationObject(object_number=1, name="G5, Schalten,",
                                 connected_gas=["0/0/0", "0/0/1"]),
        ]

        n = self.svc._derive_groups_from_import(self.gw, device, self.project)

        assert n == 2
        numbers = [g.number for g in self.gw.groups]
        assert len(numbers) == len(set(numbers))  # keine doppelte Nummer

    def test_switch_wahl_bei_kollidierenden_gas_ist_deterministisch(self):
        """Regression: zwei verschiedene GAs mit '_ea'-Suffix, die auf
        denselben LDA-Schluessel fallen (widerspruechliche Import-Daten,
        unterschiedliche Untergruppe = echte Kollision, siehe
        _same_mirrored_target), duerfen nicht je nach Python-Hash-
        Reihenfolge ein anderes Ergebnis liefern -- sortierte Verarbeitung
        macht es reproduzierbar (die zuerst sortierte Adresse bleibt unter
        dem urspruenglichen Schluessel, die zweite wird als eigene Gruppe
        disambiguiert)."""
        self.project.group_addresses = _make_ga_structure([
            "LDA.OG.00.02_ea",
            "LDA.OG.00.02_ea",  # zweite GA mit identischem Schluessel+Funktion
        ])
        # Zweite GA-Adresse manuell auf eine andere Adresse setzen
        self.project.group_addresses.all_addresses()[1].sub_group = 9
        device = _make_device_with_kos("1.1.1", [("0/0/0", "a"), ("0/0/9", "b")])

        for _ in range(5):
            gw = DaliGateway(gateway_device_id="dev-1", name="GW")
            self.svc._derive_groups_from_import(gw, device, self.project)
            switches = {g.ga_switch for g in gw.groups}
            assert switches == {"0/0/0", "0/0/9"}


class TestResyncGroupNumbers:
    """DaliService.resync_group_numbers() -- manueller Abgleich der
    Gruppennummer mit der echten DALI-Gruppennummer im Gateway (FA-2801-
    Folgefehler, Chalet Franziska 2005: "Gruppe 1" in der App war real
    "G5" im Gateway)."""

    def setup_method(self):
        self.svc = DaliService()

    def _make_device(self, kos: list[tuple[str, list[str]]]):
        from knix_arranger.models.topology import Device, CommunicationObject
        device = Device(physical_address="1.1.1", device_type="gateway", product="DALI-Gateway")
        for i, (name, gas) in enumerate(kos):
            device.communication_objects.append(
                CommunicationObject(object_number=i, name=name, connected_gas=gas)
            )
        return device

    def test_korrigiert_abweichende_nummer(self):
        device = self._make_device([("G5, Schalten,", ["0/0/0"])])
        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        gw.groups = [DaliGroup(number=1, name="Galerie", ga_switch="0/0/0")]

        n = self.svc.resync_group_numbers(gw, device)

        assert n == 1
        assert gw.groups[0].number == 4

    def test_bereits_korrekte_nummer_bleibt_unveraendert(self):
        device = self._make_device([("G5, Schalten,", ["0/0/0"])])
        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        gw.groups = [DaliGroup(number=4, name="Galerie", ga_switch="0/0/0")]

        n = self.svc.resync_group_numbers(gw, device)

        assert n == 0
        assert gw.groups[0].number == 4

    def test_evg_group_memberships_werden_mitverschoben(self):
        """Kritisch: EVGs verweisen per Nummer (nicht per Objekt-Referenz) auf
        ihre Gruppe -- eine Renummerierung ohne Mitverschieben wuerde ein EVG
        stillschweigend einer voellig anderen Gruppe zuordnen."""
        device = self._make_device([("G5, Schalten,", ["0/0/0"])])
        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        gw.groups = [DaliGroup(number=1, name="Galerie", ga_switch="0/0/0")]
        gw.devices = [DaliDevice(short_address=0, name="EVG 0", group_memberships=[1])]

        self.svc.resync_group_numbers(gw, device)

        assert gw.devices[0].group_memberships == [4]

    def test_unaufloesbare_gruppe_behaelt_nummer_wenn_frei(self):
        device = self._make_device([("G5, Schalten,", ["0/0/0"])])
        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        gw.groups = [
            DaliGroup(number=1, name="Galerie", ga_switch="0/0/0"),
            DaliGroup(number=7, name="Unbekannt", ga_switch="9/9/9"),  # keine KO-Entsprechung
        ]

        self.svc.resync_group_numbers(gw, device)

        numbers = {g.name: g.number for g in gw.groups}
        assert numbers["Galerie"] == 4
        assert numbers["Unbekannt"] == 7  # unveraendert, da frei

    def test_keine_kollision_bei_mehreren_gruppen(self):
        device = self._make_device([
            ("G2, Schalten,", ["0/0/0"]),
            ("G5, Schalten,", ["0/0/1"]),
        ])
        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        gw.groups = [
            DaliGroup(number=0, name="Erste", ga_switch="0/0/0"),
            DaliGroup(number=1, name="Zweite", ga_switch="0/0/1"),
        ]

        self.svc.resync_group_numbers(gw, device)

        numbers = sorted(g.number for g in gw.groups)
        assert numbers == [1, 4]


class TestDeriveEvgsRoomFromDotConvention:
    def test_room_and_name_resolved_from_dot_convention(self):
        from knix_arranger.models.topology import Device, CommunicationObject
        from knix_arranger.models.building import (
            Areal, Building, Wing, Floor, Apartment, Room,
        )
        room = Room(number="02", name="Küche")
        apt = Apartment(name="EG", rooms=[room])
        floor = Floor(name="Erdgeschoss", short_code="EG", apartments=[apt])
        wing = Wing(name="Haupthaus", floors=[floor])
        building = Building(name="Haus", wings=[wing])

        svc = DaliService()
        project = KnxProject(name="Test")
        project.areal = Areal(buildings=[building])
        project.group_addresses = _make_ga_structure(["LDA.EG.02.03_ea"])

        device = Device(physical_address="1.1.1", device_type="gateway", product="DALI-Gateway")
        device.communication_objects.append(CommunicationObject(
            object_number=0, name="EVG 1 Schalten", connected_gas=["0/0/0"],
        ))

        gw = DaliGateway(gateway_device_id="dev-1", name="GW")
        added = svc._derive_evgs_from_import(gw, device, project)

        assert added == 1
        assert gw.devices[0].room_id == room.id
        assert gw.devices[0].name == "Küche"


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
