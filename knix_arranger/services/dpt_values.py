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


# ── Wert eingeben -> Telegrammdaten (Senden, FA-3102b) ─────────────────────

_SENDABLE = (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 232)
_TRUE_WORDS = {"1", "ein", "an", "on", "true", "wahr", "ja"}
_FALSE_WORDS = {"0", "aus", "off", "false", "falsch", "nein"}


def can_encode(dpt: str) -> bool:
    """Lässt sich für diesen DPT ein Wert eingeben (encode_value)?"""
    return dpt_parts(dpt)[0] in _SENDABLE


def _parse_number(text: str) -> float:
    cleaned = text.strip().replace("'", "").replace("’", "").replace(",", ".")
    match = re.match(r"^[+\-−]?\d+(?:\.\d*)?|^[+\-−]?\.\d+", cleaned)
    if not match:
        raise ValueError(f"«{text}» ist keine Zahl.")
    return float(match.group(0).replace("−", "-"))


def _check(value: float, low: float, high: float, what: str = "Wert") -> None:
    if not low <= value <= high:
        raise ValueError(f"{what} muss zwischen {_number(low)} und {_number(high)} liegen.")


def _encode_float16(value: float) -> bytes:
    _check(value, -671088.64, 670760.96)
    mantissa, exponent = round(value * 100), 0
    while not -2048 <= mantissa <= 2047:
        exponent += 1
        mantissa = round(value * 100 / (2 ** exponent))
    raw = mantissa & 0x7FF
    sign = 0x80 if mantissa < 0 else 0
    return bytes([sign | (exponent << 3) | (raw >> 8), raw & 0xFF])


def encode_value(dpt: str, text: str) -> tuple[str, int]:
    """Eingegebener Wert -> (Daten als Hex, Datenlänge wie in der Busanalyse:
    0 = bis 6 Bit im APCI-Byte, sonst Anzahl Byte). Versteht, was
    decode_value anzeigt ("Ein", "21.5 °C", "50 %", "Szene 3", "heller 25 %").
    ValueError mit lesbarer Meldung, wenn der Wert nicht passt."""
    main, sub = dpt_parts(dpt)
    if main not in _SENDABLE:
        raise ValueError("Für diesen Datenpunkttyp kann KNiX keinen Wert senden – "
                         "DPT der GA prüfen." if main else
                         "Die GA hat keinen Datenpunkttyp – DPT angeben.")
    word = " ".join(text.strip().lower().split())
    if not word:
        raise ValueError("Wert fehlt.")
    if main == 1:
        names = [n.lower() for n in _BOOL.get(sub, ())]
        if names and word in names[1:] or word in _TRUE_WORDS:
            return "01", 0
        if names and word == names[0] or word in _FALSE_WORDS:
            return "00", 0
        allowed = " / ".join(_BOOL.get(sub, ("Aus", "Ein")))
        raise ValueError(f"Wert «{text}» unbekannt – {allowed} oder 0 / 1.")
    if main == 2:
        value = int(_parse_number(word))
        _check(value, 0, 3)
        return f"{value:02X}", 0
    if main == 3:
        return f"{_encode_step(sub, word):02X}", 0
    if main == 5:
        number = _parse_number(word)
        if sub == 1:
            _check(number, 0, 100)
            return f"{round(number * 255 / 100):02X}", 1
        if sub == 3:
            _check(number, 0, 360)
            return f"{round(number * 255 / 360):02X}", 1
        _check(number, 0, 255)
        return f"{round(number):02X}", 1
    if main == 6:
        number = round(_parse_number(word))
        _check(number, -128, 127)
        return struct.pack(">b", number).hex().upper(), 1
    if main in (7, 8, 12, 13):
        number = round(_parse_number(word))
        fmt, low, high = {7: (">H", 0, 65535), 8: (">h", -32768, 32767),
                          12: (">I", 0, 4294967295),
                          13: (">i", -2147483648, 2147483647)}[main]
        _check(number, low, high)
        return struct.pack(fmt, number).hex().upper(), struct.calcsize(fmt)
    if main == 9:
        return _encode_float16(_parse_number(word)).hex().upper(), 2
    if main == 14:
        return struct.pack(">f", _parse_number(word)).hex().upper(), 4
    if main == 10:
        match = re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", word)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59 \
                or int(match.group(3) or 0) > 59:
            raise ValueError("Uhrzeit als HH:MM oder HH:MM:SS eingeben.")
        h, m, s = (int(g or 0) for g in match.groups())
        return bytes([h, m, s]).hex().upper(), 3
    if main == 11:
        match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", word)
        if not match:
            raise ValueError("Datum als TT.MM.JJJJ eingeben.")
        d, m, y = (int(g) for g in match.groups())
        if not (1 <= d <= 31 and 1 <= m <= 12 and 1990 <= y <= 2089):
            raise ValueError("Datum ausserhalb 1990–2089 oder ungültig.")
        return bytes([d, m, y % 100]).hex().upper(), 3
    if main == 16:
        raw = text.strip().strip("«»").encode("latin-1", errors="replace")
        if len(raw) > 14:
            raise ValueError("Text höchstens 14 Zeichen.")
        return raw.ljust(14, b"\x00").hex().upper(), 14
    if main in (17, 18):
        store = main == 18 and "speicher" in word
        number = round(_parse_number(re.sub(r"[^\d.,+-]", " ", word).strip() or "x"))
        _check(number, 1, 64, "Szenennummer")
        return f"{(number - 1) | (0x80 if store else 0):02X}", 1
    if main == 20:
        number = round(_parse_number(word.replace("modus", "")))
        _check(number, 0, 255)
        return f"{number:02X}", 1
    # 232: Farbe
    color = word.removeprefix("rgb").strip().removeprefix("#")
    if not re.fullmatch(r"[0-9a-f]{6}", color):
        raise ValueError("Farbe als #RRGGBB eingeben, z.B. #FF8000.")
    return color.upper(), 3


def _encode_step(sub: int, word: str) -> int:
    """DPT 3 (Dimmen, Jalousie schrittweise): "Stopp", "heller 25 %",
    "ab", "+ 100" -> Richtung und Schrittweite (1 = 100 %, 7 = 1 %)."""
    if word in ("stopp", "stop", "0"):
        return 0
    up_words = ("heller", "ab", "+", "erhöhen", "hoch")
    down_words = ("dunkler", "auf", "-", "−", "verringern")
    up = next((True for w in up_words if word.startswith(w)), None)
    if up is None:
        up = next((False for w in down_words if word.startswith(w)), None)
    if up is None:
        names = {7: "heller / dunkler", 8: "ab / auf"}.get(sub, "+ / −")
        raise ValueError(f"Wert «{word}» unbekannt – {names} mit Prozent oder Stopp.")
    rest = re.sub(r"^[^\d]*", "", word)
    percent = _parse_number(rest) if rest else 100
    _check(percent, 1, 100, "Schrittweite")
    import math
    step = min(7, max(1, round(1 + math.log2(100 / percent))))
    return (0x08 if up else 0) | step


def value_suggestions(dpt: str) -> list[str]:
    """Werte zur Auswahl im Senden-Dialog (frei ergänzbar)."""
    main, sub = dpt_parts(dpt)
    if main == 1:
        off, on = _BOOL.get(sub, ("Aus", "Ein"))
        return [on, off] if on != off else [on]
    if main == 3:
        up, down = {7: ("heller", "dunkler"), 8: ("ab", "auf")}.get(sub, ("+", "−"))
        return [f"{up} 100 %", f"{down} 100 %", f"{up} 25 %", f"{down} 25 %", "Stopp"]
    if main == 5 and sub == 1:
        return ["0 %", "25 %", "50 %", "75 %", "100 %"]
    if main == 9 and sub == 1:
        return ["21 °C", "22 °C"]
    if main == 17:
        return ["Szene 1", "Szene 2", "Szene 3"]
    if main == 18:
        return ["Szene 1 abrufen", "Szene 1 speichern"]
    return []
