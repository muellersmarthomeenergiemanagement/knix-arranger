"""KNX-Secure-Prüfungen der Validierung (FA-645) nach dem KNX-Swiss-Leitfaden
«Sichere Gebäudeinformatik / Gebäudetechnik»."""
from knix_arranger.models.group_address import GroupAddress, MainGroup, MiddleGroup
from knix_arranger.models.knx_secure import KnxSecureConfig
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
from knix_arranger.services.secure_checks import check_secure
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.services.report_service import VALIDATION_RULES


def _device(address, secure, ga="1/0/0", device_type="actor", product="Gerät"):
    return Device(physical_address=address, device_type=device_type, product=product,
                  secure_supported=secure,
                  communication_objects=[CommunicationObject(
                      object_number=0, name="Schalten", flags="K-S---",
                      connected_gas=[ga] if ga else [])])


def _project(devices, security="Ein") -> KnxProject:
    project = KnxProject(name="Secure")
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=1, devices=devices)])]
    project.group_addresses.main_groups = [MainGroup(number=1, middle_groups=[
        MiddleGroup(number=0, group_addresses=[GroupAddress(
            main_group=1, middle_group=0, sub_group=0, designation="Licht Küche",
            security=security)])])]
    return project


def test_gesicherte_ga_an_geraet_ohne_secure():
    project = _project([_device("1.1.1", True, product="Aktor secure"),
                        _device("1.1.2", False, product="Taster alt")])
    issues = [i for i in check_secure(project) if i.rule_id == "FA-645"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == "error" and issue.address == "1/0/0"
    assert issue.details["devices"] == ["1.1.2 Taster alt"]


def test_gesicherte_ga_nur_an_secure_geraeten_in_ordnung():
    project = _project([_device("1.1.1", True), _device("1.1.2", True)])
    assert check_secure(project) == []


def test_ga_auto_wird_nicht_geprueft():
    project = _project([_device("1.1.1", False)], security="Auto")
    assert check_secure(project) == []


def test_importiert_nur_warnung():
    project = _project([_device("1.1.2", False)])
    project.topology.is_imported = True
    assert [i.level for i in check_secure(project)] == ["warning"]


def test_secure_aus_dem_produktnamen():
    project = _project([_device("1.1.2", False, product="KNX IO 511.1 secure")])
    assert check_secure(project) == []


def test_koppler_ohne_secure_vor_secure_geraeten():
    coupler = _device("1.1.0", False, ga="", device_type="coupler", product="LK/S4.2.1")
    project = _project([coupler, _device("1.1.1", True)], security="Auto")
    project.knx_secure = KnxSecureConfig(enabled=True, secure_mode="data_secure")
    issues = check_secure(project)
    assert [(i.rule_id, i.level, i.address) for i in issues] == [
        ("FA-645b", "info", "1.1.0")]
    # ohne aktiviertes KNX Secure keine Meldung
    project.knx_secure.enabled = False
    assert check_secure(project) == []


def test_ip_secure_braucht_alle_ip_router():
    r1 = _device("1.1.0", True, ga="", device_type="coupler", product="KNX IP Router secure")
    r2 = _device("1.2.0", False, ga="", device_type="coupler", product="IPR/S3.5.1")
    project = _project([r1], security="Auto")
    project.topology.areas[0].lines.append(Line(line_number=2, devices=[r2]))
    project.knx_secure = KnxSecureConfig(enabled=True, secure_mode="ip_secure")
    issues = check_secure(project)
    assert [(i.rule_id, i.address) for i in issues] == [("FA-645c", "1.2.0")]
    # Data Secure allein: IP-Router nicht betroffen
    project.knx_secure.secure_mode = "data_secure"
    assert all(i.rule_id != "FA-645c" for i in check_secure(project))


def test_in_der_validierung_und_beschrieben():
    project = _project([_device("1.1.2", False)])
    issues = ValidationEngine().validate(project.group_addresses, project)
    assert any(i.rule_id == "FA-645" for i in issues)
    assert {"FA-645", "FA-645b", "FA-645c"} <= set(VALIDATION_RULES)


def test_auto_vorschlag_laesst_gas_an_geraeten_ohne_secure_aus():
    from knix_arranger.services.knx_secure_service import KnxSecureService
    project = _project([_device("1.1.1", True), _device("1.1.2", False)],
                       security="Auto")
    ga = project.group_addresses.all_addresses()[0]
    ga.function_name = "Schalten"
    svc = KnxSecureService()
    assert svc.auto_suggest_ga_security(project) == 0
    assert ga.security == "Auto" and svc.last_skipped == 1
    # nur Secure-Geräte: wird gesichert
    project.topology.areas[0].lines[0].devices[1].secure_supported = True
    assert svc.auto_suggest_ga_security(project) == 1
    assert ga.security == "Ein" and svc.last_skipped == 0
    assert check_secure(project) == []


def test_mischbetrieb_ist_hinweis_ohne_warnwort():
    from knix_arranger.services.knx_secure_service import KnxSecureService
    project = _project([_device("1.1.1", True, product="Aktor"),
                        _device("1.1.2", False, product="Taster")], security="Auto")
    svc = KnxSecureService()
    svc.update_device_compatibility(project.knx_secure, project)
    [hint] = svc.check_mixed_lines(project.knx_secure, project)
    assert "1 Secure- und 1 Nicht-Secure-Gerät(e)" in hint.message
    assert "Taster" in hint.message and "Gemischte" not in hint.message
