"""ETS-Arbeitsliste (FA-618): Aufgaben, Abgleich nach dem Re-Import, Ausgabe."""
import pytest

from tests.test_multi_ga_check import _project as multi_project
from knix_arranger.models.project import KnxProject
from knix_arranger.services import ets_worklist as wl
from knix_arranger.services.ets_corrections import set_gewerk
from knix_arranger.services.multi_ga_check import unlink_ga


def _project():
    project = multi_project()          # 1.1.51 KO 6: 12/1/62 vom Gateway gesendet (Fehler)
    project.group_addresses.all_addresses()[2].gewerk_code = "MM"
    return project


def _by_key(items):
    return {i.key: i for i in items}


def test_aufgaben_mit_prioritaet_und_handgriff():
    items = wl.current_items(_project())
    must = [i for i in items if i.priority == wl.PRIO_MUST]
    assert [(i.where, i.rule_id) for i in must] == [("1.1.51 KO 6 «Taste 2, links»", "FA-614")]
    assert must[0].task.startswith("GA 12/1/62 von diesem Objekt trennen")
    assert must[0].how == "A: Gerät 1.1.51 → KO 6 → Verbindung zu 12/1/62 löschen, 1.1.51 programmieren."
    # Hinweise (z.B. Rückmeldung ausserhalb MG 6/7) gehören nicht in die Liste
    assert not any(i.rule_id == "FA-614" and "12/1/33" in i.key for i in items)
    # Reihenfolge: zuerst Muss, dann Prüfen
    assert [i.priority for i in items] == sorted(i.priority for i in items)


def test_abweichungen_als_unterlagen_bzw_muss():
    project = _project()
    project.group_addresses.all_addresses()[0].designation = "L.EG.00.01_ea Licht"
    set_gewerk(project, ["1/0/0"], "LD")
    unlink_ga(project, "1.1.51", 6, "12/1/62")
    items = _by_key(wl.current_items(project))
    gewerk = items["FA-616|Gewerk|1/0/0"]
    assert gewerk.priority == wl.PRIO_DOCS
    assert "«LD.EG.00.01_ea Licht»" in gewerk.task
    unlink = items["FA-616|Verknüpfung|1.1.51|6|12/1/62"]
    assert unlink.priority == wl.PRIO_MUST            # wirkt auf den Bus, bis die ETS trennt
    assert unlink.where == "1.1.51 KO 6 «Taste 2, links»"
    # der FA-614-Fehler ist mit der Trennung in KNiX weg -- keine doppelte Aufgabe
    assert not any(k.startswith("FA-614|1.1.51 KO 6") for k in items)


def test_abgleich_nach_reimport():
    project = _project()
    assert wl.ensure_baseline(project)
    assert not wl.ensure_baseline(project)            # nur einmal
    first = wl.build_worklist(project)
    assert all(i.status == wl.STATUS_OPEN for i in first.items)

    # in der ETS behoben: die Verknüpfung fehlt im Re-Import
    taster = project.topology.areas[0].lines[0].devices[0]
    taster.communication_objects[2].connected_gas = ["12/0/120"]
    # und ein neuer Fehler ist dazugekommen
    taster.communication_objects[3].connected_gas.append("12/1/62")
    diff = wl.sync_worklist(project, "05.10.2026")
    assert (diff.done, diff.new) == (1, 1)

    worklist = wl.build_worklist(project)
    done = {i.key: i.done_on for i in worklist.done}
    assert done == {"FA-614|1.1.51 KO 6 «Taste 2, links»|12/1/62": "05.10.2026"}
    new = [i for i in worklist.items if i.status == wl.STATUS_NEW]
    assert [i.where for i in new] == ["1.1.51 KO 9 «Taste 3, links»"]
    # Stand übersteht Speichern und Laden
    loaded = KnxProject.from_dict(project.to_dict())
    assert wl.build_worklist(loaded).new_count == 1


def test_ohne_ausgangsstand_kein_vergleich():
    project = _project()
    diff = wl.sync_worklist(project, "01.10.2026")
    assert diff.first and diff.done == 0 and diff.new == 0 and diff.open > 0


def test_export_pdf_und_excel(tmp_path):
    fitz = pytest.importorskip("fitz")
    openpyxl = pytest.importorskip("openpyxl")
    project = _project()
    wl.ensure_baseline(project)
    pdf = tmp_path / "liste.pdf"
    wl.export_pdf(project, str(pdf))
    text = "".join(page.get_text() for page in fitz.open(str(pdf)))
    assert "Muss behoben werden" in text and "Handgriffe in der ETS" in text
    assert "Verbindung zu 12/1/62 löschen" in text

    xlsx = tmp_path / "liste.xlsx"
    wl.export_excel(project, str(xlsx))
    wb = openpyxl.load_workbook(str(xlsx))
    assert wb.sheetnames[:2] == ["Anleitung", "Arbeitsliste"]
    values = [c for row in wb["Arbeitsliste"].iter_rows(values_only=True) for c in row]
    assert "☐ offen" in values
    assert wb["Arbeitsliste"].data_validations.dataValidation
