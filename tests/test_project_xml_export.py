"""Projektdaten (0.xml) ohne Schlüssel für Partnerprogramme."""
import xml.etree.ElementTree as ET

from knix_arranger.services.project_xml_export import strip_secrets

XML = (
    b'<?xml version="1.0" encoding="utf-8"?>\r\n'
    b'<KNX xmlns="http://knx.org/xml/project/23">\r\n'
    b'  <Project Id="P-0001"><Installations>'
    b'<Installation Name="" BCUKey="4294967295" DefaultLine="L-1">\r\n'
    b'    <GroupAddress Id="GA-1" Address="1" Name="Licht" Key="c2VjcmV0" DatapointType="DPST-1-1" />\r\n'
    b'    <DeviceInstance Id="DI-1" Name="Taster" ProductRefId="M-0001_H-1">'
    b'<Security LoadedToolKey="AAAA" ToolKey="BBBB" SequenceNumber="12" '
    b"DeviceManagementPassword='pw' DeviceAuthenticationCode=\"code\" />"
    b'</DeviceInstance>\r\n'
    b'  </Installation></Installations></Project>\r\n'
    b'</KNX>\r\n'
)


def test_strip_secrets_removes_keys_and_passwords():
    cleaned, removed = strip_secrets(XML)

    for secret in (b"BCUKey", b"LoadedToolKey", b"ToolKey", b' Key=', b"c2VjcmV0",
                   b"DeviceManagementPassword", b"DeviceAuthenticationCode"):
        assert secret not in cleaned
    assert removed == {"BCUKey": 1, "Key": 1, "LoadedToolKey": 1, "ToolKey": 1,
                       "DeviceManagementPassword": 1, "DeviceAuthenticationCode": 1}


def test_strip_secrets_keeps_everything_else():
    cleaned, _ = strip_secrets(XML)

    for kept in (b'DatapointType="DPST-1-1"', b'SequenceNumber="12"', b'DefaultLine="L-1"',
                 b'ProductRefId="M-0001_H-1"', b"\r\n", b'<?xml version="1.0"'):
        assert kept in cleaned
    root = ET.fromstring(cleaned)   # weiterhin gültige XML
    assert root.tag.endswith("KNX")


def test_strip_secrets_without_secrets_is_unchanged():
    xml = b'<KNX><GroupAddress Name="Keyboard Licht" KeyName="x" /></KNX>'
    # "KeyName" endet nicht auf Key, der Wert "Keyboard" ist kein Attributname
    cleaned, removed = strip_secrets(xml)
    assert cleaned == xml and removed == {}
