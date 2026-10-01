"""Revisionspaket, DALI-Liste und KNX-Secure-Bericht (kleinere Korrekturen)."""
import os

import fitz

from knix_arranger.models.dali_config import DaliGateway
from knix_arranger.models.knx_secure import DeviceSecureInfo
from knix_arranger.services.documentation_service import DocumentationService
from tests.test_multi_ga_check import _project


def test_revisionspaket_mit_abnahme_ohne_leere_dali(tmp_path):
    project = _project()
    gateway = project.topology.areas[0].lines[1].devices[0]
    project.dali_configs = {gateway.id: DaliGateway(gateway_device_id=gateway.id,
                                                    name="DALI-Gateway",
                                                    ga_switch_broadcast="0/0/105")}
    DocumentationService(project).generate_revision_package(str(tmp_path))
    files = os.listdir(tmp_path)
    assert any("Abnahmeprotokoll" in f for f in files)
    assert not any("DALI" in f for f in files)          # keine EVGs erfasst
    index = next(f for f in files if "Inhaltsverzeichnis" in f)
    text = fitz.open(os.path.join(tmp_path, index))[0].get_text()
    assert "Seiten" in text and "Belegungsplan (Verknüpfungsmatrix)" in text


def test_dali_liste_mit_adresse_statt_id(tmp_path):
    project = _project()
    gateway = project.topology.areas[0].lines[1].devices[0]
    project.dali_configs = {gateway.id: DaliGateway(gateway_device_id=gateway.id,
                                                    name="DALI-Gateway",
                                                    ga_switch_broadcast="0/0/105")}
    path = str(tmp_path / "dali.pdf")
    DocumentationService(project).generate_dali_device_list(path)
    text = fitz.open(path)[0].get_text()
    assert "1.2.7" in text and gateway.id not in text
    assert "0/0/105" not in text                         # GA gibt es nicht


def test_secure_linie_aus_topologie(tmp_path):
    project = _project()
    project.knx_secure.enabled = True
    taster = project.topology.areas[0].lines[0].devices[0]
    project.knx_secure.device_infos = {taster.id: DeviceSecureInfo(
        device_id=taster.id, device_name="Push button (EN)", physical_address="1.1.51",
        line_id="veraltet")}
    taster.product_name = "Taster EDIZIOdue"
    path = str(tmp_path / "secure.pdf")
    DocumentationService(project).generate_knx_secure_report(path)
    text = "".join(pg.get_text() for pg in fitz.open(path))
    assert "Taster EDIZIOdue" in text and "Push button" not in text
    row = text[text.index("Taster EDIZIOdue"):]
    assert "1.1.51" in row and "\n1.1\n" in row
