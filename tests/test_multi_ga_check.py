"""Tests: pro Sensorkanal nur eine sendende GA (FA-614) – Praxisfall Chalet 1.1.51."""
from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement,
    SensorFunktion, SensorFunktionGa,
)
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.multi_ga_check import (
    VERDICT_AUSSERHALB, VERDICT_MITHOEREN, VERDICT_RUECKMELDUNG, ROLE_MITHOEREN,
    apply_listen_roles, find_multi_ga, unlink_ga,
)
from knix_arranger.services.validation_engine import ValidationEngine


def _ga(addr, designation):
    h, m, s = (int(p) for p in addr.split("/"))
    return GroupAddress(main_group=h, middle_group=m, sub_group=s, designation=designation)


def _co(nr, name, flags, *gas):
    return CommunicationObject(object_number=nr, name=name, flags=flags,
                               connected_gas=list(gas))


def _project(variant="B"):
    """Taster 1.1.51 mit zwei Doppelbelegungen, Aktor 1.1.15, Gateway 1.2.7."""
    project = KnxProject(name="Chalet")
    project.config.mg_variant = variant
    project.topology.is_imported = True   # aus der ETS (Richtlinien nur Hinweis)
    halle = Room(number="00", name="Halle")
    sf = SensorFunktion(label="Taste 2, links", ga_designation="12/0/120  Musik_ea",
                        extra_gas=[SensorFunktionGa(ga_designation="12/1/62  S1 Wohnen_ea",
                                                    role="rueckmeldung",
                                                    description="Taste 2, links")])
    sf1 = SensorFunktion(label="Taste 1, links", ga_designation="1/0/0  Licht_ea",
                         extra_gas=[SensorFunktionGa(ga_designation="1/7/0  Licht_rm",
                                                     role="rueckmeldung",
                                                     description="Taste 1, links")])
    halle.bedienelemente = [Bedienelement(element_type="Tastereinheit",
                                          participant_number="1.1.51",
                                          funktionen=[sf1, sf], is_auto=False)]
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [Apartment(name="", rooms=[halle])]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])

    structure = GroupAddressStructure()
    for addr, name in [("1/0/0", "Licht_ea"), ("1/7/0", "Licht_rm"),
                       ("12/0/120", "Musik_ea"), ("12/1/62", "S1 Wohnen_ea"),
                       ("12/1/33", "S1 Studio_wert")]:
        h, m, _s = addr.split("/")
        hg = next((g for g in structure.main_groups if g.number == int(h)), None)
        if hg is None:
            hg = MainGroup(number=int(h))
            structure.main_groups.append(hg)
        mg = next((g for g in hg.middle_groups if g.number == int(m)), None)
        if mg is None:
            mg = MiddleGroup(number=int(m))
            hg.middle_groups.append(mg)
        mg.group_addresses.append(_ga(addr, name))
    project.group_addresses = structure

    taster = Device(physical_address="1.1.51", device_type="sensor", communication_objects=[
        _co(0, "Taste 1, links", "K-SÜ--", "1/0/0", "1/7/0"),
        _co(2, "Taste 1, links, Signal-LED", "K-S-A-", "1/7/0"),
        _co(6, "Taste 2, links", "K-SÜ--", "12/0/120", "12/1/62"),
        _co(9, "Taste 3, links", "K-SÜ--", "12/0/121", "12/1/33"),
    ])
    aktor = Device(physical_address="1.1.15", device_type="actor", communication_objects=[
        _co(1, "Ausgang 1", "KL-Ü--", "1/7/0"),
    ])
    gateway = Device(physical_address="1.2.7", device_type="gateway", communication_objects=[
        _co(170, "Wohnen: Benutzer 1 Ein / Aus", "K-SÜ--", "12/1/62"),
        _co(106, "Studio: Benutzer 1 Status", "K--Ü--", "12/1/33"),
    ])
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=1, devices=[taster, aktor]),
        Line(line_number=2, devices=[gateway]),
    ])]
    return project


def _verdicts(project):
    return {f.extra_ga: f.verdict for f in find_multi_ga(project)}


def test_variante_b_mg7_ist_rueckmeldung_fremder_befehl_wird_gemeldet():
    verdicts = _verdicts(_project("B"))
    assert verdicts["1/7/0"] == VERDICT_RUECKMELDUNG
    assert verdicts["12/1/62"] == VERDICT_MITHOEREN
    assert verdicts["12/1/33"] == VERDICT_AUSSERHALB   # Status, aber MG 1


def test_variante_a_entscheidet_der_sender():
    verdicts = _verdicts(_project("A"))
    assert verdicts["1/7/0"] == VERDICT_RUECKMELDUNG     # Aktor-Status ohne S-Flag
    assert verdicts["12/1/33"] == VERDICT_RUECKMELDUNG   # Status-KO des Gateways
    assert verdicts["12/1/62"] == VERDICT_MITHOEREN      # Ein/Aus-Befehl des Gateways


def test_led_kos_werden_nicht_geprueft():
    findings = find_multi_ga(_project())
    assert all(f.co_number != 2 for f in findings)


def test_rolle_mithoeren_wird_gesetzt():
    project = _project()
    assert apply_listen_roles(project) == 1
    sf = project.all_rooms[0].bedienelemente[0].funktionen[1]
    assert sf.extra_gas[0].role == ROLE_MITHOEREN
    assert project.all_rooms[0].bedienelemente[0].funktionen[0].extra_gas[0].role == "rueckmeldung"


def test_trennen_entfernt_ga_am_ko_und_an_der_taste():
    project = _project()
    assert unlink_ga(project, "1.1.51", 6, "12/1/62")
    taster = project.topology.areas[0].lines[0].devices[0]
    assert taster.communication_objects[2].connected_gas == ["12/0/120"]
    sf = project.all_rooms[0].bedienelemente[0].funktionen[1]
    assert sf.extra_gas == []
    assert sf.ga_designation.startswith("12/0/120")
    # Gateway bleibt unverändert
    gateway = project.topology.areas[0].lines[1].devices[0]
    assert gateway.communication_objects[0].connected_gas == ["12/1/62"]
    assert "12/1/62" not in _verdicts(project)


def test_trennen_nur_am_gewaehlten_ko():
    project = _project()
    assert unlink_ga(project, "1.1.51", 0, "1/7/0")
    taster = project.topology.areas[0].lines[0].devices[0]
    assert taster.communication_objects[1].connected_gas == ["1/7/0"]   # LED bleibt


def test_validierung_meldet_nur_weitere_sendende_gas():
    project = _project()
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-614"]
    levels = {i.address: i.level for i in issues}
    # 12/1/62: nachweislich Befehl des Gateways -> Fehler
    assert levels == {"12/1/62": "error", "12/1/33": "info"}


def test_ohne_gefundenen_sender_nur_warnung():
    project = _project()
    gateway = project.topology.areas[0].lines[1].devices[0]
    gateway.communication_objects[0].connected_gas = []     # Sender fehlt
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-614"]
    assert {i.address: i.level for i in issues}["12/1/62"] == "warning"


def test_validierungsansicht_filtert():
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])  # noqa: F841
    from knix_arranger.ui.views.validation_view import ValidationView
    project = _project()
    view = ValidationView()
    view.set_issues(ValidationEngine().validate(project.group_addresses, project=project))
    top = [view._tree.topLevelItem(i).text(0) for i in range(view._tree.topLevelItemCount())]
    assert top[0].startswith("Fehler")
    view._level_boxes["info"].setChecked(False)
    view._level_boxes["warning"].setChecked(False)   # u.a. fehlender DPT
    view._search.setText("12/1/62")
    top = [view._tree.topLevelItem(i).text(0) for i in range(view._tree.topLevelItemCount())]
    assert top == ["Fehler  (1)"]
    view._search.setText("gibt es nicht")
    assert view._tree.topLevelItem(0).text(0) == "Keine Meldung passt zum Filter."
