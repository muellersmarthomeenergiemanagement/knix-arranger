"""
Eingabevalidierung für KNiX Arranger.
"""
import re


def is_valid_room_number(number: str) -> bool:
    """Prüft ob eine Raumnummer gültig ist (z.B. E01, UG02, O03)."""
    return bool(re.match(r'^[A-Z]{1,2}\d{2,3}$', number))


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
    pattern = r'^[A-Z]{1,3}_[A-Z]{1,2}\d{2,3}_\d{2}\s+\S+'
    return bool(re.match(pattern, designation))


def is_valid_license_key(key: str) -> bool:
    """Prüft das Format des Lizenzschlüssels (NFA-062)."""
    return bool(re.match(r'^KNiX-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', key))
