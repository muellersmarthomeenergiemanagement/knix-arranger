"""
Tests fuer die Erkennung KNX-Secure-faehiger Geraete (FA-2705):
ETS-Import (<Security>-Element, IsSecureEnabled der Applikation, Hardware-
Attribut), KNXPROD-Katalog, Produktname als Notbehelf und Abgleich in der
Secure-Ansicht.
"""
from __future__ import annotations
import zipfile

from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.knx_secure_service import KnxSecureService, is_secure_product_name
from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService
from knix_arranger.services.knxproj_import_service import KnxprojImportService

NS = "http://knx.org/xml/project/23"
MFR = "M-00C5"


def _hardware_xml() -> str:
    def hw(name, app, extra=""):
        return f"""
      <Hardware Id="{MFR}_H-{name}" Name="{name}" {extra}>
        <Products><Product Id="{MFR}_H-{name}_P-{name}" Text="{name}" OrderNumber="{name}"/></Products>
        <Hardware2Programs>
          <Hardware2Program Id="{MFR}_H-{name}_HP-{app}">
            <ApplicationProgramRef RefId="{MFR}_A-{app}"/>
          </Hardware2Program>
        </Hardware2Programs>
      </Hardware>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}"><Hardware>
{hw("IO511secure", "0001-10-AAAA")}
{hw("Router", "0002-10-BBBB", 'SupportsIPSecure="true"')}
{hw("Plain", "0003-10-CCCC")}
</Hardware></Manufacturer></ManufacturerData></KNX>"""


def _app_xml(app: str, secure: bool) -> str:
    flag = ' IsSecureEnabled="true"' if secure else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}"><ApplicationPrograms>
  <ApplicationProgram Id="{MFR}_A-{app}" Name="App"{flag}><Static/></ApplicationProgram>
</ApplicationPrograms></Manufacturer></ManufacturerData></KNX>"""


SERIAL_B64 = "AMUBCIo5"                       # 00C5:01088A39 (Chalet Franziska 1.1.21)
FDSK_B64 = "u8jMj+7o6e5gICp6V3A28A=="          # BBC8CC8FEEE8E9EE60202A7A577036F0


def _device(addr, name, app, security=False):
    sec = '<Security ToolKey="x" SequenceNumber="1"/>' if security else ""
    serial = f'SerialNumber="{SERIAL_B64}" ' if security else ""
    return (f'<DeviceInstance Id="P-TEST-0_DI-{addr}" Address="{addr}" {serial}'
            f'ProductRefId="{MFR}_H-{name}_P-{name}" '
            f'Hardware2ProgramRefId="{MFR}_H-{name}_HP-{app}">{sec}</DeviceInstance>')


def _knxproj(path, plain_app_secure: bool = False) -> str:
    devices = "".join([
        _device(21, "IO511secure", "0001-10-AAAA", security=True),
        _device(22, "Plain", "0003-10-CCCC"),
        _device(23, "Router", "0002-10-BBBB"),
    ])
    main = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><Installations><Installation Name="">
  <Topology><Area Id="P-TEST-0_A-1" Address="1"><Line Id="P-TEST-0_L-1" Address="1">
    <Segment Id="P-TEST-0_S-1">{devices}</Segment>
  </Line></Area></Topology>
</Installation></Installations></Project></KNX>"""
    project_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><ProjectInformation Name="Secure-Test">
  <DeviceCertificates><DeviceCertificate SerialNumber="{SERIAL_B64}" FDSK="{FDSK_B64}"/></DeviceCertificates>
</ProjectInformation></Project></KNX>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{MFR}/Hardware.xml", _hardware_xml())
        zf.writestr(f"{MFR}/{MFR}_A-0001-10-AAAA.xml", _app_xml("0001-10-AAAA", secure=False))
        zf.writestr(f"{MFR}/{MFR}_A-0002-10-BBBB.xml", _app_xml("0002-10-BBBB", secure=False))
        zf.writestr(f"{MFR}/{MFR}_A-0003-10-CCCC.xml", _app_xml("0003-10-CCCC", secure=plain_app_secure))
        zf.writestr("P-TEST/project.xml", project_xml)
        zf.writestr("P-TEST/0.xml", main)
    return str(path)


def _devices_by_address(project):
    return {d.physical_address: d for a in project.topology.areas for l in a.lines for d in l.devices}


class TestEtsImport:
    def test_security_element_and_hardware_attribute(self, tmp_path):
        project = KnxprojImportService().import_knxproj(_knxproj(tmp_path / "p.knxproj"))
        devices = _devices_by_address(project)
        assert devices["1.1.21"].secure_supported          # <Security> in ETS
        assert devices["1.1.23"].secure_supported          # SupportsIPSecure
        assert not devices["1.1.22"].secure_supported

    def test_application_is_secure_enabled(self, tmp_path):
        path = _knxproj(tmp_path / "p.knxproj", plain_app_secure=True)
        devices = _devices_by_address(KnxprojImportService().import_knxproj(path))
        assert devices["1.1.22"].secure_supported


class TestKnxprodCatalog:
    def test_application_flag_marks_product_secure(self, tmp_path):
        path = tmp_path / "weinzierl.knxprod"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{MFR}/Hardware.xml", _hardware_xml())
            zf.writestr(f"{MFR}/{MFR}_A-0001-10-AAAA.xml", _app_xml("0001-10-AAAA", secure=True))
            zf.writestr(f"{MFR}/{MFR}_A-0003-10-CCCC.xml", _app_xml("0003-10-CCCC", secure=False))
        products = {p.product_name: p for p in KnxprodCatalogService().import_file(str(path))}
        assert products["IO511secure"].secure_supported
        assert products["Router"].secure_supported
        assert not products["Plain"].secure_supported
        assert products["IO511secure"].to_catalog_dict()["secure_supported"] is True


class TestSecureView:
    def _project(self, *devices):
        project = KnxProject(name="Test")
        project.topology = Topology(areas=[Area(area_number=1, lines=[Line(line_number=1, devices=list(devices))])])
        return project

    def test_sources_combined(self):
        from_ets = Device(physical_address="1.1.21", product="KNX IO 511.1", secure_supported=True)
        by_name = Device(physical_address="1.1.30", product="IP Router Secure")
        plain = Device(physical_address="1.1.31", product="Schaltaktor")
        project = self._project(from_ets, by_name, plain)
        # Materialliste ohne Secure-Angabe darf die Erkennung nicht aufheben
        project.material_list.entries.append(MaterialEntry(device_id=from_ets.id))

        infos = {i.physical_address: i for i in
                 KnxSecureService().update_device_compatibility(project.knx_secure, project)}
        assert infos["1.1.21"].secure_supported
        assert infos["1.1.30"].secure_supported
        assert not infos["1.1.31"].secure_supported

    def test_product_name_heuristic(self):
        assert is_secure_product_name("KNX IO 511.1 secure")
        assert is_secure_product_name("Secure-Koppler")
        assert not is_secure_product_name("Unsecured Gateway")
        assert not is_secure_product_name("")

    def test_device_round_trip_and_product_assignment(self):
        from knix_arranger.services.product_search_service import ProductSuggestion
        device = Device(secure_supported=True)
        assert Device.from_dict(device.to_dict()).secure_supported
        device.apply_product(ProductSuggestion(manufacturer="MDT", secure_supported=False))
        assert not device.secure_supported
        device.apply_product(ProductSuggestion(manufacturer="Weinzierl", secure_supported=True))
        assert device.secure_supported


class TestDeviceCertificates:
    def test_certificate_read_and_applied_by_serial_number(self, tmp_path):
        importer = KnxprojImportService()
        project = importer.import_knxproj(_knxproj(tmp_path / "p.knxproj"))
        assert importer.device_certificates == {"00C5:01088A39": "BBC8CC8FEEE8E9EE60202A7A577036F0"}
        device = _devices_by_address(project)["1.1.21"]
        assert device.serial_number == "00C5:01088A39"

        service = KnxSecureService()
        added, conflicts = service.apply_device_certificates(
            project.knx_secure, project, importer.device_certificates,
        )
        assert (added, conflicts) == (1, [])
        info = project.knx_secure.device_infos[device.id]
        assert info.fdsk == "BBC8CC8FEEE8E9EE60202A7A577036F0" and info.secure_supported

    def test_existing_different_fdsk_is_kept(self, tmp_path):
        importer = KnxprojImportService()
        project = importer.import_knxproj(_knxproj(tmp_path / "p.knxproj"))
        device = _devices_by_address(project)["1.1.21"]
        service = KnxSecureService()
        service.update_device_compatibility(project.knx_secure, project)
        project.knx_secure.device_infos[device.id].fdsk = "11" * 16

        added, conflicts = service.apply_device_certificates(
            project.knx_secure, project, importer.device_certificates,
        )
        assert added == 0 and len(conflicts) == 1
        assert project.knx_secure.device_infos[device.id].fdsk == "11" * 16
