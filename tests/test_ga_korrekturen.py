"""In KNiX bearbeitete GA-Felder importierter Projekte als Korrektur (FA-616c):
überleben jedes Einlesen, Abweichung zur ETS, Aufgabe in der Arbeitsliste."""
import copy

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.ets_corrections import (
    apply_ets_corrections, deviations, settle_ga_fields,
)
from knix_arranger.services.ga_edit import apply_changes, move_ga


def _structure() -> GroupAddressStructure:
    mg = MiddleGroup(number=1, name="Licht")
    mg.group_addresses = [
        GroupAddress(main_group=1, middle_group=1, sub_group=5,
                     designation="L.EG.01.01_ea", datapoint_type="DPST-1-1",
                     description=""),
        GroupAddress(main_group=1, middle_group=1, sub_group=6,
                     designation="L.EG.01.01_rm", datapoint_type="DPST-1-1"),
    ]
    return GroupAddressStructure(main_groups=[MainGroup(number=1, name="EG",
                                                        middle_groups=[mg])])


def _project(imported=True) -> KnxProject:
    project = KnxProject(name="Chalet")
    project.topology.is_imported = imported
    project.group_addresses = _structure()
    return project


def _ga(project, address="1/1/5"):
    return next(g for g in project.group_addresses.all_addresses() if g.address == address)


def _reimport(project, structure=None):
    """Wie ein erneutes Einlesen: frische GA-Objekte aus der ETS, dann der
    Ablauf der ImportPipeline (settle, danach apply)."""
    project.group_addresses = structure or _structure()
    settle_ga_fields(project)
    apply_ets_corrections(project)


def test_bearbeitung_wird_korrektur_und_ueberlebt_einlesen():
    project = _project()
    ga = _ga(project)
    apply_changes(project, [ga], {"designation": "Licht Wohnen Decke",
                                  "description": "über dem Esstisch"})
    assert ga.designation == "Licht Wohnen Decke"
    entry = project.ets_corrections.ga_fields["1/1/5"]
    assert entry["designation"] == {"value": "Licht Wohnen Decke", "ets": "L.EG.01.01_ea"}
    # speichern, laden, neu einlesen
    loaded = KnxProject.from_dict(project.to_dict())
    apply_ets_corrections(loaded)
    _reimport(loaded)
    assert _ga(loaded).designation == "Licht Wohnen Decke"
    assert _ga(loaded).description == "über dem Esstisch"


def test_abweichung_zur_ets_nur_fuer_ets_felder():
    project = _project()
    ga = _ga(project)
    apply_changes(project, [ga], {"designation": "Licht Wohnen", "datapoint_type": "DPST-5-1",
                                  "room_number": "02"})
    found = {(d.field, d.ets_value, d.knix_value) for d in deviations(project)}
    assert ("Name", "L.EG.01.01_ea", "Licht Wohnen") in found
    assert ("DPT", "DPST-1-1", "DPST-5-1") in found
    assert not any(field == "room_number" for field, _e, _k in found)
    assert project.ets_corrections.ga_fields["1/1/5"]["room_number"]["value"] == "02"


def test_zurueck_auf_ets_wert_hebt_korrektur_auf():
    project = _project()
    ga = _ga(project)
    apply_changes(project, [ga], {"designation": "Licht Wohnen"})
    apply_changes(project, [ga], {"designation": "L.EG.01.01_ea"})
    assert project.ets_corrections.ga_fields == {}
    assert deviations(project) == []


def test_in_der_ets_nachgefuehrt_entfaellt():
    project = _project()
    apply_changes(project, [_ga(project)], {"designation": "Licht Wohnen"})
    fresh = _structure()
    fresh.all_addresses()[0].designation = "Licht Wohnen"      # in der ETS umbenannt
    _reimport(project, fresh)
    assert project.ets_corrections.ga_fields == {}


def test_ets_aendert_anders_korrektur_bleibt_mit_neuem_ets_wert():
    project = _project()
    apply_changes(project, [_ga(project)], {"designation": "Licht Wohnen"})
    fresh = _structure()
    fresh.all_addresses()[0].designation = "L.EG.01.01_ea neu"
    _reimport(project, fresh)
    assert _ga(project).designation == "Licht Wohnen"
    assert project.ets_corrections.ga_fields["1/1/5"]["designation"]["ets"] == \
        "L.EG.01.01_ea neu"


def test_nicht_frische_gas_bleiben_beim_abgleich_unberuehrt():
    """Gebäude-Report ohne GAs: die GA-Objekte sind die angewendeten, der
    Abgleich darf die Korrektur nicht für erledigt halten."""
    project = _project()
    apply_changes(project, [_ga(project)], {"designation": "Licht Wohnen"})
    settle_ga_fields(project)
    assert "1/1/5" in project.ets_corrections.ga_fields
    # auch nach dem Laden (angewendet beim Öffnen)
    loaded = KnxProject.from_dict(project.to_dict())
    apply_ets_corrections(loaded)
    settle_ga_fields(loaded)
    assert "1/1/5" in loaded.ets_corrections.ga_fields
    # Kopie für Berichte behält die Markierung
    settle_ga_fields(copy.deepcopy(loaded))
    assert "1/1/5" in loaded.ets_corrections.ga_fields


def test_geplante_projekte_ohne_korrekturschicht():
    project = _project(imported=False)
    ga = _ga(project)
    ga.is_manual = True
    apply_changes(project, [ga], {"designation": "Licht Wohnen"})
    assert ga.designation == "Licht Wohnen"
    assert project.ets_corrections.ga_fields == {}


def test_gewerk_ueber_bestehende_gewerk_korrektur():
    project = _project()
    apply_changes(project, [_ga(project)], {"gewerk_code": "LD"})
    assert project.ets_corrections.gewerk_by_address == {"1/1/5": "LD"}
    assert "gewerk_code" not in project.ets_corrections.ga_fields.get("1/1/5", {})


def test_adresse_aus_der_ets_nicht_verschiebbar():
    project = _project()
    assert "in der ETS verschieben" in move_ga(project, _ga(project), 1, 1, 9)
    manual = _ga(project, "1/1/6")
    manual.is_manual = True
    assert move_ga(project, manual, 1, 1, 9) == ""


def test_arbeitsliste_nennt_die_aufgabe():
    from knix_arranger.services.ets_worklist import current_items
    project = _project()
    apply_changes(project, [_ga(project)], {"designation": "Licht Wohnen",
                                            "datapoint_type": "DPST-5-1"})
    tasks = {item.task for item in current_items(project) if item.rule_id == "FA-616"}
    assert "Umbenennen in «Licht Wohnen»." in tasks
    assert "Datenpunkttyp DPST-5-1 setzen." in tasks


# ── Neue GAs in eingelesenen Projekten ───────────────────────────────────

def test_neuaufbau_nennt_in_knix_angelegte_gas():
    from knix_arranger.services.rebuild_service import lost_content
    project = _project()
    assert not any(item.startswith("In KNiX angelegte GAs") for item in lost_content(set(), project))
    _ga(project, "1/1/6").is_manual = True
    _ga(project, "1/1/5").is_manual = True
    _ga(project, "1/1/5").function_id = "f1"          # Funktions-GA: eigener Weg
    assert "In KNiX angelegte GAs (1)" in lost_content(set(), project)


def test_hinweis_beim_anlegen_einmal_je_projekt(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.wizard.step07_addresses import Step07Addresses
    shown = []

    def click(label):
        def fake_exec(box):
            shown.append(box.text())
            box._clicked = next(b for b in box.buttons() if b.text() == label)
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._clicked)
    project = _project()
    step = Step07Addresses(project)
    click("Abbrechen")
    assert step._confirm_new_ga_imported() is False
    click("Trotzdem anlegen")
    assert step._confirm_new_ga_imported() is True
    assert step._confirm_new_ga_imported() is True     # kein zweites Mal
    assert len(shown) == 2 and "Erweiterung planen" in shown[0]
    planned = Step07Addresses(_project(imported=False))
    assert planned._confirm_new_ga_imported() is True and len(shown) == 2
