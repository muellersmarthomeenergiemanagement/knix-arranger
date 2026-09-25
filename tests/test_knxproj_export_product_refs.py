"""
Tests fuer den KNXPROJ-Export mit Produktreferenz (ProductRefId/
Hardware2ProgramRefId) und eingebetteten Herstellerdaten.
"""
import os
import zipfile
import xml.etree.ElementTree as ET

from knix_arranger.services.knxproj_export_service import (
    KnxprojExportService, PRODUCT_REFS_EMBEDDED, PRODUCT_REFS_NONE, PRODUCT_REFS_ONLY,
)
from knix_arranger.services.manufacturer_data_service import (
    ManufacturerDataLibrary, manufacturer_of,
)

from tests.test_knxproj_export_service import _make_project

_NS = "{http://knx.org/xml/project/23}"
_NS20 = "http://knx.org/xml/project/20"
_NS23 = "http://knx.org/xml/project/23"

HP_A = "M-0083_H-1_HP-0001-11-AAAA"
HP_B = "M-0083_H-2_HP-0002-11-BBBB"


def _knxprod(path, mfr="M-0083", hw2progs=(HP_A,), ns=_NS23, signed=True,
             master_version="200", padding=0):
    progs = "".join(
        f'<Hardware2Program Id="{h}"><ApplicationProgramRef RefId="A"/></Hardware2Program>'
        for h in hw2progs
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{mfr}/Hardware.xml", f'<KNX xmlns="{ns}"><Hardware2Programs>{progs}'
                                           f'</Hardware2Programs></KNX>')
        zf.writestr(f"{mfr}/Catalog.xml", f'<KNX xmlns="{ns}"/>')
        zf.writestr(f"{mfr}/Baggages/help.chm", "x" * padding)
        if signed:
            zf.writestr(f"{mfr}.signature", "SIG-" + os.path.basename(path))
        zf.writestr("knx_master.xml",
                    f'<KNX xmlns="{ns}"><MasterData Version="{master_version}"/></KNX>')
    return str(path)


def _project_with_refs():
    project = _make_project()
    actor, sensor = project.topology.areas[0].lines[0].devices
    actor.manufacturer = "MDT"
    actor.order_number = "AKS-0416.03"
    actor.product_ref_id = "M-0083_H-1_P-1"
    actor.hw2prog_id = HP_A
    return project, actor, sensor


def _device_elems(path):
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("/0.xml"))
        root = ET.fromstring(zf.read(name))
    return {e.get("Address"): e for e in root.iter(f"{_NS}DeviceInstance")}


class TestManufacturerDataLibrary:
    def test_manufacturer_of(self):
        assert manufacturer_of(HP_A) == "M-0083"
        assert manufacturer_of("P-1") == ""

    def test_prefers_full_coverage_then_ets6_then_size(self, tmp_path):
        _knxprod(tmp_path / "gross_ets5.knxprod", hw2progs=(HP_A, HP_B), ns=_NS20)
        _knxprod(tmp_path / "klein_ets6.knxprod", hw2progs=(HP_A,))
        _knxprod(tmp_path / "gross_ets6.knxprod", hw2progs=(HP_A, HP_B), padding=5000)
        lib = ManufacturerDataLibrary(str(tmp_path))

        only_a = lib.choose({"M-0083": {HP_A}})["M-0083"]
        assert os.path.basename(only_a.path) == "klein_ets6.knxprod"
        both = lib.choose({"M-0083": {HP_A, HP_B}})["M-0083"]
        assert os.path.basename(both.path) == "gross_ets6.knxprod"

    def test_signed_source_preferred_over_unsigned_ets6(self, tmp_path):
        _knxprod(tmp_path / "alt_extrahiert.knxprod", signed=False)
        _knxprod(tmp_path / "hersteller_ets5.knxprod", ns=_NS20, padding=5000)
        chosen = ManufacturerDataLibrary(str(tmp_path)).choose({"M-0083": {HP_A}})["M-0083"]
        assert os.path.basename(chosen.path) == "hersteller_ets5.knxprod"

    def test_unknown_program_has_no_source(self, tmp_path):
        _knxprod(tmp_path / "a.knxprod")
        assert ManufacturerDataLibrary(str(tmp_path)).choose({"M-0083": {"M-0083_X"}}) == {}

    def test_missing_folder(self):
        assert ManufacturerDataLibrary("").choose({"M-0083": {HP_A}}) == {}


class TestExportProductRefs:
    def test_none_writes_no_refs(self, tmp_path):
        project, _, _ = _project_with_refs()
        out = str(tmp_path / "p.knxproj")
        KnxprojExportService().export(project, out, product_refs=PRODUCT_REFS_NONE)
        assert "ProductRefId" not in _device_elems(out)["1"].attrib

    def test_refs_only(self, tmp_path):
        project, _, _ = _project_with_refs()
        out = str(tmp_path / "p.knxproj")
        summary = KnxprojExportService().export(project, out, product_refs=PRODUCT_REFS_ONLY)
        devs = _device_elems(out)
        assert devs["1"].get("ProductRefId") == "M-0083_H-1_P-1"
        assert devs["1"].get("Hardware2ProgramRefId") == HP_A
        assert "ProductRefId" not in devs["101"].attrib
        assert summary.product_ref_count == 1
        with zipfile.ZipFile(out) as zf:
            assert not any(n.startswith("M-") for n in zf.namelist())

    def test_embedded_copies_manufacturer_data_unchanged(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        src = _knxprod(lib / "MDT (M-0083).knxprod", padding=100)
        project, _, _ = _project_with_refs()
        out = str(tmp_path / "p.knxproj")
        summary = KnxprojExportService().export(
            project, out, product_refs=PRODUCT_REFS_EMBEDDED, product_data_folder=str(lib),
        )
        assert _device_elems(out)["1"].get("Hardware2ProgramRefId") == HP_A
        with zipfile.ZipFile(src) as zs, zipfile.ZipFile(out) as zo:
            for name in ("M-0083/Hardware.xml", "M-0083/Catalog.xml",
                         "M-0083/Baggages/help.chm", "M-0083.signature", "knx_master.xml"):
                assert zo.read(name) == zs.read(name)
        assert summary.product_ref_count == 1
        assert summary.embedded_manufacturers[0].startswith("MDT: MDT (M-0083).knxprod (ETS6")

    def test_embedded_without_source_leaves_device_without_ref(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _knxprod(lib / "andere.knxprod", hw2progs=(HP_B,))
        project, _, _ = _project_with_refs()
        out = str(tmp_path / "p.knxproj")
        summary = KnxprojExportService().export(
            project, out, product_refs=PRODUCT_REFS_EMBEDDED, product_data_folder=str(lib),
        )
        assert "ProductRefId" not in _device_elems(out)["1"].attrib
        assert summary.product_ref_count == 0
        assert any("ohne Produktreferenz" in w for w in summary.warnings)

    def test_master_with_highest_version_ets6_preferred(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _knxprod(lib / "a.knxprod", master_version="300", ns=_NS20)
        _knxprod(lib / "b.knxprod", mfr="M-0002", hw2progs=("M-0002_H-9_HP-1",),
                 master_version="215")
        project, _, sensor = _project_with_refs()
        sensor.product_ref_id, sensor.hw2prog_id = "M-0002_H-9_P-1", "M-0002_H-9_HP-1"
        out = str(tmp_path / "p.knxproj")
        KnxprojExportService().export(project, out, product_refs=PRODUCT_REFS_EMBEDDED,
                                      product_data_folder=str(lib))
        with zipfile.ZipFile(out) as zo:
            assert b'Version="215"' in zo.read("knx_master.xml")


class TestEts5ExportProductRefs:
    def test_embeds_only_ets5_format(self, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _knxprod(lib / "ets6.knxprod")
        project, _, _ = _project_with_refs()
        out = str(tmp_path / "p.knxproj")
        summary = KnxprojExportService().export_ets5_compat(
            project, out, product_refs=PRODUCT_REFS_EMBEDDED, product_data_folder=str(lib),
        )
        assert summary.product_ref_count == 0

        _knxprod(lib / "ets5.knxprod", ns=_NS20)
        summary = KnxprojExportService().export_ets5_compat(
            project, out, product_refs=PRODUCT_REFS_EMBEDDED, product_data_folder=str(lib),
        )
        assert summary.product_ref_count == 1
        with zipfile.ZipFile(out) as zo:
            assert zo.read("M-0083.signature") == b"SIG-ets5.knxprod"
            name = next(n for n in zo.namelist() if n.endswith("/0.xml"))
            root = ET.fromstring(zo.read(name))
        dev = next(e for e in root.iter(f"{{{_NS20}}}DeviceInstance") if e.get("Address") == "1")
        assert dev.get("Hardware2ProgramRefId") == HP_A
