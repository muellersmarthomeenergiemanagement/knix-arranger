"""
Projektdaten eines ETS-Projekts (0.xml) für Partnerprogramme speichern.

Die XML bleibt Zeichen für Zeichen wie in der .knxproj -- nur Schlüssel und
Passwörter werden entfernt: Geräte-Zugriffspasswort (BCUKey), Secure-
Geräteschlüssel (ToolKey, LoadedToolKey), Gruppenschlüssel sicherer GAs
(Key) sowie vorsorglich Management-Passwörter, Authentifizierungscodes,
IP-Secure-Schlüssel und FDSK. Die Geräte-Zertifikate (FDSK) stehen in der ETS
ohnehin in project.xml, nicht in den Projektdaten.
"""
from __future__ import annotations

import re

# Attribut mit Schlüssel oder Passwort: Name endet auf "Key" oder enthält
# "Password" bzw. "AuthenticationCode", oder heisst "FDSK"
_SECRET_ATTR_RE = re.compile(
    rb'\s(?P<name>(?:[A-Za-z_][\w.-]*?)?(?:Key|Password\w*|AuthenticationCode\w*)|FDSK)'
    rb'\s*=\s*(?:"[^"]*"|\'[^\']*\')'
)


def strip_secrets(xml: bytes) -> tuple[bytes, dict[str, int]]:
    """Entfernt Schlüssel- und Passwort-Attribute. Gibt die bereinigte XML
    und die Anzahl entfernter Attribute je Name zurück."""
    removed: dict[str, int] = {}

    def drop(match: re.Match) -> bytes:
        name = match.group("name").decode("ascii", "replace")
        removed[name] = removed.get(name, 0) + 1
        return b""

    return _SECRET_ATTR_RE.sub(drop, xml), removed
