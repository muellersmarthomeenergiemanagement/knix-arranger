"""KNX-Secure-Zertifikate einlesen (FA-2704b): Aufkleber-Text und QR-Code ->
Seriennummer + FDSK, Zuordnung zum Gerät über die Seriennummer."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.knx_secure import DeviceSecureInfo, KnxSecureConfig
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services import knx_secure_certificate as kc

# Weinzierl KNX IO 511.1 secure: Aufkleber, QR-Code ohne Bindestriche
STICKER = "ADCQCC-EKHG54-RTEP53\nUOT3TA-EAVHUV-3QG3YL"
QR_TEXT = "ADCQCCEKHG54RTEP53UOT3TAEAVHUV3QG3YL"
SERIAL = "00C5:01088A39"
FDSK = "BBC8CC8FEEE8E9EE60202A7A577036F0"


def test_sticker_and_qr_text_give_serial_and_fdsk():
    for text in (STICKER, QR_TEXT, QR_TEXT.lower(), "adcqcc ekhg54 rtep53 uot3ta eavhuv 3qg3yl"):
        assert kc.parse_certificate(text) == kc.Certificate(SERIAL, FDSK)
    assert kc.parse_certificate(FDSK) == kc.Certificate("", FDSK)
    assert kc.parse_certificate("ADCQCC-EKHG54") is None
    assert kc.parse_certificate("1.1.21") is None


def test_several_certificates_in_pasted_text():
    text = f"Liftsteuerung 1.1.21: {STICKER.replace(chr(10), '-')}\n{QR_TEXT}\n{FDSK}\n"
    assert kc.certificates_in_text(text) == [kc.Certificate(SERIAL, FDSK),
                                              kc.Certificate("", FDSK)]


def _project(serial=SERIAL):
    device = Device(device_type="actor", physical_address="1.1.21",
                    product="KNX IO 511.1 secure", serial_number=serial)
    other = Device(device_type="actor", physical_address="1.1.22", product="Schaltaktor")
    project = KnxProject(name="Secure")
    project.topology = Topology(areas=[Area(area_number=1, lines=[
        Line(name="Linie 1", line_number=1, devices=[device, other])])])
    return project, device, other


def test_match_by_serial_and_apply():
    project, device, _other = _project()
    config = KnxSecureConfig()
    cert = kc.Certificate(SERIAL, FDSK)
    [match] = kc.match_certificates(config, project, [cert])
    assert (match.device, match.status) == (device, kc.NEW)
    assert kc.apply_certificate(config, device, cert) == kc.NEW
    assert config.device_infos[device.id].fdsk == FDSK
    assert device.secure_supported
    assert kc.match_certificates(config, project, [cert])[0].status == kc.KNOWN
    # anderer FDSK: nur mit overwrite ersetzt
    other_cert = kc.Certificate(SERIAL, "0" * 32)
    assert kc.apply_certificate(config, device, other_cert) == kc.DIFFERENT
    assert config.device_infos[device.id].fdsk == FDSK
    kc.apply_certificate(config, device, other_cert, overwrite=True)
    assert config.device_infos[device.id].fdsk == "0" * 32


def test_planned_device_takes_serial_of_certificate():
    project, device, other = _project(serial="")
    config = KnxSecureConfig()
    config.device_infos[other.id] = DeviceSecureInfo(device_id=other.id, secure_supported=True)
    cert = kc.Certificate(SERIAL, FDSK)
    assert kc.match_certificates(config, project, [cert])[0].status == kc.UNKNOWN
    # Secure-fähige Geräte ohne Seriennummer zuerst
    assert kc.assignable_devices(project, config) == [other, device]
    kc.apply_certificate(config, device, cert)
    assert device.serial_number == SERIAL
    assert kc.match_certificates(config, project, [cert])[0].device is device


@pytest.mark.skipif(not kc.qr_available(), reason="zxing-cpp fehlt")
def test_qr_code_in_image():
    import zxingcpp
    import numpy as np
    image = np.array(zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(QR_TEXT, zxingcpp.BarcodeFormat.QRCode), scale=6))
    # zwei Karten nebeneinander auf einem Foto
    other = np.array(zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(FDSK, zxingcpp.BarcodeFormat.QRCode), scale=6))
    height = max(image.shape[0], other.shape[0])
    photo = np.full((height, image.shape[1] + other.shape[1] + 40), 255, dtype=np.uint8)
    photo[:image.shape[0], :image.shape[1]] = image
    photo[:other.shape[0], image.shape[1] + 40:] = other
    assert set(kc.certificates_in_image(photo)) == {kc.Certificate(SERIAL, FDSK),
                                                     kc.Certificate("", FDSK)}


@pytest.mark.skipif(not kc.qr_available(), reason="zxing-cpp fehlt")
def test_dialog_applies_typed_certificate():
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.dialogs.secure_certificate_dialog import SecureCertificateDialog
    QApplication.instance() or QApplication([])
    project, device, _other = _project()
    dialog = SecureCertificateDialog(project)
    dialog._text.setPlainText(STICKER)
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 2).text() == kc.NEW
    dialog._apply()
    assert dialog.applied == 1
    assert project.knx_secure.device_infos[device.id].fdsk == FDSK
