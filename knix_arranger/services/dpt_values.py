"""
Telegrammwerte nach Datenpunkttyp lesbar machen (Busanalyse, FA-640c).

Die Busanalyse speichert je Telegramm die Daten als Hex und die Datenlänge
(0 = Wert im APCI-Byte, bis 6 Bit; sonst Anzahl Byte). Hier wird daraus
mit dem DPT der Gruppenadresse ein Wert mit Einheit ("21.5 °C", "Ein",
"Szene 3"). Unbekannte Typen oder unpassende Länge: Hex bleibt stehen.
"""
from __future__ import annotations

import re
import struct

from .ko_size import dpt_bits

_DPT_RE = re.compile(r"DPS?T-(\d+)(?:-(\d+))?", re.IGNORECASE)
_DOTTED_RE = re.compile(r"^\s*(\d+)\.(\d+)")

# Einheiten je (Haupttyp, Untertyp)
_UNITS = {
    (5, 1): "%", (5, 3): "°", (5, 4): "%", (6, 1): "%",
    (7, 12): "mA", (7, 13): "lx", (7, 600): "K",
    (9, 1): "°C", (9, 2): "K", (9, 3): "K/h", (9, 4): "lx", (9, 5): "m/s", (9, 6): "Pa",
    (9, 7): "%", (9, 8): "ppm", (9, 9): "m³/h", (9, 10): "s", (9, 11): "ms", (9, 20): "mV",
    (9, 21): "mA", (9, 22): "W/m²", (9, 23): "K/%", (9, 24): "kW", (9, 25): "l/h",
    (9, 26): "l/m²", (9, 27): "°F", (9, 28): "km/h", (9, 29): "g/m³", (9, 30): "µg/m³",
    (13, 10): "Wh", (13, 13): "kWh", (13, 15): "kVAh", (13, 16): "kVARh",
    (14, 19): "A", (14, 27): "V", (14, 33): "Hz", (14, 56): "W", (14, 57): "",
    (14, 68): "°C", (14, 76): "m³", (14, 77): "m³/s",
}
_BOOL = {1: ("Aus", "Ein"), 2: ("falsch", "wahr"), 3: ("deaktivieren", "aktivieren"),
         5: ("kein Alarm", "Alarm"), 11: ("inaktiv", "aktiv"),
         7: ("verringern", "erhöhen"), 8: ("Auf", "Ab"), 9: ("Auf", "Zu"),
         10: ("Stopp", "Start"), 17: ("Trigger", "Trigger"), 18: ("keine Bewegung", "Bewegung"),
         19: ("geschlossen", "offen"), 22: ("Szene A", "Szene B"), 23: ("Auf/Ab", "Lamellen")}


def dpt_parts(dpt: str) -> tuple[int, int]:
    """("DPST-9-1" | "DPT-9" | "9.001") -> (9, 1); Untertyp 0 wenn unbekannt,
    (0, 0) wenn kein DPT erkennbar."""
    match = _DPT_RE.search(dpt or "")
    if match:
        return int(match.group(1)), int(match.group(2) or 0)
    match = _DOTTED_RE.match(dpt or "")
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def expected_size(dpt: str) -> int | None:
    """Datenlänge im Telegramm für diesen DPT: 0 (bis 6 Bit im APCI-Byte),
    sonst Anzahl Byte; None wenn unbekannt."""
    main, _sub = dpt_parts(dpt)
    bits = dpt_bits(f"DPT-{main}") if main else 0
    if not bits:
        return None
    return 0 if bits <= 6 else bits // 8


def size_text(size: int) -> str:
    return "bis 6 Bit" if size == 0 else f"{size} Byte"


def _number(value: float, unit: str = "", decimals: int = 2) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{value:.0f}"
    if text == "-0":
        text = "0"
    return f"{text} {unit}".strip()


def _float16(b: bytes) -> float:
    mantissa = ((b[0] & 0x07) << 8) | b[1]
    if b[0] & 0x80:
        mantissa -= 2048
    exponent = (b[0] >> 3) & 0x0F
    return 0.01 * mantissa * (2 ** exponent)


def decode_value(dpt: str, payload: str, size: int | None) -> str:
    """Wert lesbar; payload Hex wie gespeichert, size 0 = bis 6 Bit,
    None = unbekannt (dann aus der Länge des Hex geschätzt)."""
    if not payload:
        return ""
    main, sub = dpt_parts(dpt)
    expected = expected_size(dpt)
    if expected is None:
        return payload
    if size is None:                            # ältere Mitschnitte ohne Datenlänge
        size = 0 if expected == 0 and len(payload) <= 2 else len(payload) // 2
    if size != expected:
        return payload
    try:
        if size == 0:
            return _short(main, sub, int(payload, 16) & 0x3F)
        return _long(main, sub, bytes.fromhex(payload)) or payload
    except (ValueError, struct.error, IndexError):
        return payload


def _short(main: int, sub: int, v: int) -> str:
    if main == 1:
        names = _BOOL.get(sub)
        return names[v & 1] if names else str(v & 1)
    if main == 2:
        return f"Zwang {'ein' if v & 2 else 'aus'}, Wert {v & 1}"
    if main == 3:
        step = v & 0x07
        if not step:
            return "Stopp"
        up = bool(v & 0x08)
        word = ("heller" if up else "dunkler") if sub == 7 else \
               ("ab" if up else "auf") if sub == 8 else ("+" if up else "−")
        return f"{word} {100 // (2 ** (step - 1))} %"
    return f"{v:X}"


def _long(main: int, sub: int, b: bytes) -> str:
    unit = _UNITS.get((main, sub), "")
    if main == 5:
        if sub == 1:
            return _number(b[0] * 100 / 255, "%", 0)
        if sub == 3:
            return _number(b[0] * 360 / 255, "°", 0)
        return _number(b[0], unit, 0)
    if main == 6:
        return _number(struct.unpack(">b", b[:1])[0], unit, 0)
    if main == 7:
        return _number(struct.unpack(">H", b[:2])[0], unit, 0)
    if main == 8:
        return _number(struct.unpack(">h", b[:2])[0], unit, 0)
    if main == 9:
        return _number(_float16(b), unit)
    if main == 10:
        return f"{b[0] & 0x1F:02d}:{b[1] & 0x3F:02d}:{b[2] & 0x3F:02d}"
    if main == 11:
        year = b[2] & 0x7F
        year += 2000 if year < 90 else 1900
        return f"{b[0] & 0x1F:02d}.{b[1] & 0x0F:02d}.{year}"
    if main == 12:
        return _number(struct.unpack(">I", b[:4])[0], unit, 0)
    if main == 13:
        return _number(struct.unpack(">i", b[:4])[0], unit, 0)
    if main == 14:
        return _number(struct.unpack(">f", b[:4])[0], unit, 3)
    if main == 16:
        return "«" + b.split(b"\x00", 1)[0].decode("latin-1").rstrip() + "»"
    if main == 17:
        return f"Szene {(b[0] & 0x3F) + 1}"
    if main == 18:
        return f"Szene {(b[0] & 0x3F) + 1} {'speichern' if b[0] & 0x80 else 'abrufen'}"
    if main == 20:
        return f"Modus {b[0]}"
    if main == 232:
        return f"RGB #{b[:3].hex().upper()}"
    return ""
