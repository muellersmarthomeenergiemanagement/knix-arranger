"""
Eingabevalidierung für KNiX Arranger.
"""
import re


# Prüfrahmen für Raumnummern: Grossbuchstaben, Ziffern sowie "-" und "." als
# Gliederung (z.B. E01, OG03, SEG02, S-EG02, S.EG.02). Der Unterstrich ist das
# Trennzeichen der GA-Bezeichnung GEWERK_RAUM_NR und darf nicht vorkommen.
ROOM_NUMBER_PATTERN = r"[A-Z0-9](?:[A-Z0-9.\-]*[A-Z0-9])?"

_DESIGNATION_RE = re.compile(
    r"^[A-Z]{1,3}_(" + ROOM_NUMBER_PATTERN + r")_\d{2}\s+\S+"
)


def is_valid_room_number(number: str) -> bool:
    """Prüft ob eine Raumnummer im Prüfrahmen liegt (z.B. E01, SEG02, S-EG02)."""
    return bool(re.fullmatch(ROOM_NUMBER_PATTERN, number))


def room_number_problems(number: str) -> list[str]:
    """Gründe, weshalb eine Raumnummer ausserhalb des Prüfrahmens liegt.

    Leere Liste = Raumnummer in Ordnung. Die Texte erscheinen als Warnung
    beim Erfassen der Räume (Wizard Schritt 3).
    """
    if not number:
        return ["Raumnummer fehlt"]
    problems = []
    if "_" in number:
        problems.append(
            "Unterstrich ist das Trennzeichen der GA-Bezeichnung (GEWERK_RAUM_NR)"
        )
    if any(c.isspace() for c in number):
        problems.append("Leerzeichen trennt in der GA-Bezeichnung die Funktion ab")
    if any(c.islower() for c in number):
        problems.append("Kleinbuchstaben (KNX Swiss: Grossbuchstaben)")
    # Kleinbuchstaben, Leerzeichen und "_" sind oben schon begründet
    others = sorted({
        c for c in number
        if c not in "-._" and not c.isspace() and not (c.isascii() and c.isalnum())
    })
    if others:
        problems.append(
            "Zeichen ausserhalb des Prüfrahmens: " + " ".join(others)
            + " (erlaubt: A–Z, 0–9, - und .)"
        )
    if not problems and not is_valid_room_number(number):
        problems.append("- und . nur zwischen Buchstaben oder Ziffern")
    return problems


def is_valid_ga(main: int, middle: int, sub: int) -> bool:
    """Prüft ob eine Gruppenadresse gültig ist (FA-601)."""
    if main == 0 and middle == 0 and sub == 0:
        return False  # GA-08: 0/0/0 ist Systemadresse
    return 0 <= main <= 31 and 0 <= middle <= 7 and 0 <= sub <= 255


def is_valid_physical_address(address: str) -> bool:
    """Prüft ob eine physikalische Adresse gültig ist (B.L.T)."""
    parts = address.split(".")
    if len(parts) != 3:
        return False
    try:
        b, l, t = int(parts[0]), int(parts[1]), int(parts[2])
        return 0 <= b <= 15 and 0 <= l <= 15 and 0 <= t <= 255
    except ValueError:
        return False


def is_valid_gewerk_code(code: str) -> bool:
    """Prüft ob ein Gewerke-Kürzel gültig ist."""
    return bool(re.match(r'^[A-Z]{1,3}$', code))


def is_valid_designation(designation: str) -> bool:
    """
    Prüft ob eine GA-Bezeichnung dem KNX Swiss Format entspricht (BZ-01).
    Format: [Gewerk]_[Raum]_[Nr] [Funktion] ([Klartext])
    """
    return bool(_DESIGNATION_RE.match(designation))


def designation_room_number(designation: str) -> str:
    """Raumteil einer KNX-Swiss-Bezeichnung ("" wenn nicht konform)."""
    m = _DESIGNATION_RE.match(designation)
    return m.group(1) if m else ""


def is_valid_license_key(key: str) -> bool:
    """Prüft das Format des Lizenzschlüssels (NFA-062)."""
    return bool(re.match(r'^KNiX-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', key))
