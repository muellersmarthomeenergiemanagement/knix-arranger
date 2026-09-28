"""Szenenreport: nach Szenen-Gruppenadresse gegliedert (FA-1811)."""
import pytest
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.report_service import ReportService


def _project() -> KnxProject:
    gas = [
        GroupAddress(main_group=0, middle_group=4, sub_group=1,
                     designation="Anwesenheit Chalet", datapoint_type="DPST-5-1"),
        GroupAddress(main_group=0, middle_group=4, sub_group=101,
                     designation="Szene 01", datapoint_type="DPST-17-1"),
        GroupAddress(main_group=0, middle_group=2, sub_group=150,
                     designation="WP Betriebsart", datapoint_type="DPST-26-1"),
        GroupAddress(main_group=2, middle_group=4, sub_group=0,
                     designation="Raum1_Szene High", datapoint_type="DPST-1-1"),
    ]
    project = KnxProject(name="Szenen")
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=n, middle_groups=[MiddleGroup(number=m, group_addresses=[
            g for g in gas if (g.main_group, g.middle_group) == (n, m)]) for m in range(8)])
        for n in (0, 2)])

    def detected(name, number, addr, kind="dpt", actions=()):
        return Scene(name=name, scene_number=number, scope="central", is_detected=True,
                     detection_kind=kind, source_ga_addresses=[addr], actions=list(actions))
    project.scenes = [
        detected("Anwesenheit Chalet", 0, "0/4/1"),                       # Kanal-Eintrag
        detected("Anwesenheit Chalet – Szene 2", 2, "0/4/1", actions=[
            SceneAction(group_address="HS.OG.05.02_ea   ( Etuvé )", value="AUS")]),
        detected("Anwesenheit Chalet – Szene 1", 1, "0/4/1", actions=[
            SceneAction(group_address="HS.OG.05.04_ea", value="EIN")]),
        detected("Szene 01", 1, "0/4/101", actions=[
            SceneAction(group_address="Szene 01", ga_address="0/4/101")]),  # Selbstverweis
        detected("WP Betriebsart", 0, "0/2/150"),
        detected("High (Carnozet)", 0, "2/4/0", kind="pattern"),
    ]
    return project


def test_gliederung_nach_adresse(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = str(tmp_path / "szenen.pdf")
    ReportService(_project()).generate_szenen_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    sections = [t[1] for t in doc.get_toc() if t[0] == 2]
    bookmarks = [t[1] for t in doc.get_toc() if t[0] == 3]
    doc.close()

    assert sections == ["Übersicht", "Szenen-Adressen", "Szenen der Visualisierung",
                        "Nicht eindeutig"]
    # Adresse zuoberst, Szenen darunter; der Kanal-Eintrag (Nr. 0) ist keine Szene
    assert bookmarks == ["0/4/1  Anwesenheit Chalet", "0/4/101  Szene 01"]
    assert "2 Szenen-Adressen mit 3 Szenen" in text
    assert text.index("Szene 1") < text.index("Szene 2")          # nach Nummer sortiert
    assert "Anwesenheit Chalet – Szene 1" not in text              # Adressname nur im Kopf
    assert "HS.OG.05.02_ea (Etuvé) → AUS" in text                  # Leerzeichen bereinigt
    assert "5.001 – für Szenen wird 17.001" in text                # falscher DPT gemeldet
    assert "Kein Aktor ist mit dieser Adresse verknüpft" in text
    # UniPro-Szenen separat, fragliche Erkennung unter "Nicht eindeutig"
    assert "High (Carnozet)" in text and "keine KNX-Szenenadressen" in text
    assert "WP Betriebsart" in text.split("Nicht eindeutig")[-1]


def test_szene_ohne_gruppenadresse(tmp_path):
    fitz = pytest.importorskip("fitz")
    project = KnxProject(name="Planung")
    project.scenes = [Scene(name="Kino", scene_number=3, scope="central")]
    path = str(tmp_path / "szenen.pdf")
    ReportService(project).generate_szenen_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "Ohne Gruppenadresse" in text and "Kino" in text and "Schritt 10" in text
