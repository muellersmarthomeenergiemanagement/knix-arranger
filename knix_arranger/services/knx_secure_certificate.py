"""
KNX-Secure-Gerätezertifikate einlesen (FA-2704b): Aufkleber-Text, QR-Code
aus einem Foto oder live von der Kamera.

Das Zertifikat auf Aufkleber und Karte ist Base32 aus Seriennummer (6 Byte),
FDSK (16 Byte) und 4 Bit Prüfsumme -- 36 Zeichen, gedruckt in Sechsergruppen
(«ADCQCC-EKHG54-…»), im QR-Code ohne Bindestriche. Die Prüfsumme ist noch
nicht bestimmt (ein Beispiel bekannt) und wird nicht geprüft; der QR-Code
korrigiert Lesefehler selbst.

Über die Seriennummer findet das Zertifikat sein Gerät (Seriennummer aus dem
ETS-Import). Geplante Geräte haben keine: dann wählt man das Gerät, und es
übernimmt die Seriennummer des Zertifikats.

Reine Datenoperation ohne Qt; QR-Erkennung über zxing-cpp (optional).
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass

_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_CODE_LENGTH = 36
# Im Text: 36 Base32-Zeichen, wahlweise in Gruppen mit Bindestrich/Leerzeichen
_CODE_IN_TEXT = re.compile(
    r"(?<![A-Z2-7])((?:[A-Z2-7]{6}[\s-]?){5}[A-Z2-7]{6})(?![A-Z2-7])")

NEW = "neu"
KNOWN = "bereits erfasst"
DIFFERENT = "abweichend"
UNKNOWN = "Gerät wählen"


@dataclass(frozen=True)
class Certificate:
    serial: str          # «00C5:01088A39», leer bei reinem FDSK
    fdsk: str            # 32 Hex-Zeichen

    @property
    def label(self) -> str:
        return self.serial or "ohne Seriennummer"


def parse_certificate(text: str) -> Certificate | None:
    """Aufkleber-Text (36 Zeichen, Gruppen erlaubt) oder reiner FDSK (32
    Hex-Zeichen) -> Zertifikat; None, wenn es keins ist."""
    code = re.sub(r"[\s-]", "", text or "").upper()
    if len(code) == 32 and all(c in "0123456789ABCDEF" for c in code):
        return Certificate("", code)
    if len(code) != _CODE_LENGTH or any(c not in _BASE32 for c in code):
        return None
    raw = base64.b32decode(code + "====")      # 180 Bit -> 22 Byte + Prüfsumme
    serial = raw[:6].hex().upper()
    return Certificate(f"{serial[:4]}:{serial[4:]}", raw[6:22].hex().upper())


def certificates_in_text(text: str) -> list[Certificate]:
    """Alle Zertifikate in einem Text (eingefügt, mehrere Zeilen), ohne
    Doppelte; eine Zeile mit reinem FDSK zählt auch."""
    found: list[Certificate] = []
    upper = (text or "").upper()
    for match in _CODE_IN_TEXT.finditer(upper):
        cert = parse_certificate(match.group(1))
        if cert and cert not in found:
            found.append(cert)
    for line in upper.splitlines():
        cert = parse_certificate(line)
        if cert and not cert.serial and cert not in found:
            found.append(cert)
    return found


def qr_available() -> bool:
    try:
        import zxingcpp  # noqa: F401
    except ImportError:
        return False
    return True


def read_qr_texts(image) -> list[str]:
    """Texte aller QR-Codes in einem Bild (QImage, PIL-Bild oder Array)."""
    import zxingcpp
    return [r.text for r in zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
            if r.text]


def certificates_in_image(image) -> list[Certificate]:
    found: list[Certificate] = []
    for text in read_qr_texts(image):
        cert = parse_certificate(text)
        if cert and cert not in found:
            found.append(cert)
    return found


@dataclass
class CertificateMatch:
    certificate: Certificate
    device: object | None        # Topologie-Gerät
    status: str                  # NEW, KNOWN, DIFFERENT, UNKNOWN


def device_name(device) -> str:
    """Wie im Secure-Archiv (KnxSecureService.update_device_compatibility)."""
    return device.product_name or device.product or device.physical_address


def _devices(project):
    return [d for area in project.topology.areas for line in area.lines
            for d in line.devices]


def match_certificates(config, project, certificates: list[Certificate]) -> list[CertificateMatch]:
    """Zu jedem Zertifikat das Gerät mit derselben Seriennummer und ob der
    FDSK neu, schon erfasst oder abweichend ist."""
    by_serial = {d.serial_number.upper(): d for d in _devices(project) if d.serial_number}
    result = []
    for cert in certificates:
        device = by_serial.get(cert.serial.upper()) if cert.serial else None
        result.append(CertificateMatch(cert, device, _status(config, device, cert)))
    return result


def _status(config, device, cert: Certificate) -> str:
    if device is None:
        return UNKNOWN
    info = config.device_infos.get(device.id)
    current = (info.fdsk if info else "").upper()
    if not current:
        return NEW
    return KNOWN if current == cert.fdsk else DIFFERENT


def assignable_devices(project, config) -> list:
    """Geräte, denen ein Zertifikat ohne bekannte Seriennummer zugewiesen
    werden kann: ohne Seriennummer, Secure-fähige zuerst."""
    devices = [d for d in _devices(project) if not d.serial_number]
    infos = config.device_infos

    def secure(d) -> bool:
        info = infos.get(d.id)
        return bool(info and info.secure_supported)
    return sorted(devices, key=lambda d: (not secure(d), d.physical_address or "~"))


def apply_certificate(config, device, cert: Certificate, overwrite: bool = False) -> str:
    """FDSK ins Archiv (das entsperrt sein muss), Seriennummer ans Gerät,
    falls es noch keine hat. Ein abweichender FDSK wird nur mit overwrite
    ersetzt. Rückgabe: Status vorher (NEW, KNOWN, DIFFERENT)."""
    from ..models.knx_secure import DeviceSecureInfo
    status = _status(config, device, cert)
    if cert.serial and not device.serial_number:
        device.serial_number = cert.serial
    # Ein Gerät mit Secure-Zertifikat ist Secure-fähig -- am Gerät, sonst
    # setzt die nächste Kompatibilitätsprüfung das Archiv-Flag zurück
    device.secure_supported = True
    info = config.device_infos.get(device.id)
    if info is None:
        info = config.device_infos[device.id] = DeviceSecureInfo(
            device_id=device.id, device_name=device_name(device),
            physical_address=device.physical_address)
    info.secure_supported = True
    if status == NEW or (status == DIFFERENT and overwrite):
        info.fdsk = cert.fdsk
    return status
