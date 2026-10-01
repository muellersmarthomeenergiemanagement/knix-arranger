"""Inbetriebnahme-Checkliste: eine Zeile je Taste, Stockwerk-Gliederung."""
from knix_arranger.models.documentation import ChecklistItem
from knix_arranger.services.documentation_service import DocumentationService
from tests.test_multi_ga_check import _project


def test_eine_zeile_je_taste():
    project = _project()
    sections = DocumentationService(project)._checklist_sections()
    assert [(floor, room) for floor, room, _ in sections] == [("EG", "00 Halle")]
    title, rows = sections[0][2][0]
    assert title.startswith("1.1.51")
    tasten = [r[0] for r in rows]
    assert tasten[0] == "Gerät"
    # Taste 1 links: Befehl + Rückmeldung in EINER Zeile
    t1 = next(r for r in rows if r[0] == "1 links")
    assert "1/0/0" in t1[2] and "1/7/0" in t1[2]
    assert tasten.count("1 links") == 1


def test_ergebnis_je_zeile_zusammengefasst():
    saved = {
        ("r", "T", "1", "Taste 1", "1/0/0"): ChecklistItem(result="OK"),
        ("r", "T", "1", "Taste 1", "1/7/0"): ChecklistItem(result="Mangel", notes="LED dunkel"),
    }
    keys = list(saved)
    assert DocumentationService._combined_result(keys, saved) == ("Mangel", "LED dunkel")
    assert DocumentationService._combined_result(keys[:1], saved) == ("OK", "")
    assert DocumentationService._combined_result([("x",)], saved) == ("", "")
