"""
Grösse von Kommunikationsobjekten und Datenpunkttypen.

Die Herstellerdatei nennt je KO die Grösse ("1 Bit", "4 Bit", "1 Byte",
"2 Bytes"), oft ohne Datenpunkttyp (Theben DM 4 T). Eine GA kann nur mit
einem KO gleicher Grösse verknüpft werden -- das ist der verlässlichste
Anhaltspunkt, wenn die Texte nichts sagen. Die Grösse eines DPT folgt aus
seinem Haupttyp (KNX-Spezifikation 3/7/2).
"""
from __future__ import annotations

import re

_SIZE_RE = re.compile(r"(\d+)\s*(bit|byte)", re.IGNORECASE)
_DPT_MAIN_RE = re.compile(r"DPS?T-(\d+)", re.IGNORECASE)

# Haupttyp -> Grösse in Bit
_DPT_BITS: dict[int, int] = {
    1: 1, 2: 2, 3: 4, 4: 8, 5: 8, 6: 8, 7: 16, 8: 16, 9: 16, 10: 24, 11: 24,
    12: 32, 13: 32, 14: 32, 15: 32, 16: 112, 17: 8, 18: 8, 19: 64, 20: 8,
    21: 8, 22: 16, 23: 2, 25: 8, 26: 8, 27: 32, 28: 0, 29: 64, 30: 24, 31: 8,
    217: 16, 219: 48, 222: 48, 225: 24, 229: 48, 230: 64, 232: 24, 234: 16,
    235: 48, 237: 16, 238: 8, 239: 16, 240: 24, 241: 32, 242: 48,
    244: 16, 246: 40, 249: 48, 250: 24, 251: 48,
}

# Grössen, deren Haupttyp eindeutig ist (nur diese dürfen einen fehlenden
# DPT ersetzen): 1 Bit = Schalten & Co. (DPT 1), 2 Bit = Zwang (DPT 2),
# 4 Bit = Dimmen/Jalousie relativ (DPT 3)
_UNIQUE_DPT_BY_BITS = {1: "DPT-1", 2: "DPT-2", 4: "DPT-3"}


def size_bits(size: str) -> int:
    """"1 Bit" -> 1, "1 Byte" -> 8, "2 Bytes" -> 16; 0 wenn unbekannt."""
    match = _SIZE_RE.search(size or "")
    if not match:
        return 0
    value = int(match.group(1))
    return value if match.group(2).lower() == "bit" else value * 8


def dpt_bits(dpt: str) -> int:
    """Grösse eines DPT ("DPST-5-1", "DPT-9") in Bit; 0 wenn unbekannt."""
    match = _DPT_MAIN_RE.search(dpt or "")
    return _DPT_BITS.get(int(match.group(1)), 0) if match else 0


def size_text(bits: int) -> str:
    """1 -> "1 Bit", 8 -> "1 Byte", 16 -> "2 Byte"; "" wenn unbekannt."""
    if bits <= 0:
        return ""
    if bits < 8 or bits % 8:
        return f"{bits} Bit"
    return f"{bits // 8} Byte"


def dpt_from_size(size: str) -> str:
    """Datenpunkt-Haupttyp aus der Grösse, nur wenn eindeutig (1/2/4 Bit)."""
    return _UNIQUE_DPT_BY_BITS.get(size_bits(size), "")


def co_bits(co) -> int:
    """Grösse eines KO (CommunicationObject oder Katalog-Dict): aus der
    Grösse, sonst aus dem DPT. 0 wenn unbekannt."""
    if isinstance(co, dict):
        size, dpt = co.get("object_size", ""), co.get("datapoint_type", "")
    else:
        size, dpt = getattr(co, "object_size", ""), getattr(co, "data_type", "")
    # data_type trägt bei ETS-Importen teils die Grösse ("1 bit")
    return size_bits(size) or dpt_bits(dpt) or size_bits(dpt)


def sizes_compatible(co, ga_dpt: str) -> bool:
    """False nur, wenn beide Grössen bekannt sind und sich unterscheiden."""
    ko, ga = co_bits(co), dpt_bits(ga_dpt)
    return not ko or not ga or ko == ga


def ko_direction(co) -> str:
    """«sendet» (Ü ohne S), «empfängt» (S ohne Ü), «sendet/empfängt»; ""
    ohne Flags oder bei nicht parametrierten Produktdaten (alle Flags)."""
    from .ko_links import TRANSMIT, WRITE, parse_flags, unparametrized_co
    flags = parse_flags(getattr(co, "flags", "") or "")
    if not flags or unparametrized_co(co):
        return ""
    send, receive = TRANSMIT in flags, WRITE in flags
    if send and receive:
        return "sendet/empfängt"
    return "sendet" if send else ("empfängt" if receive else "")


def ko_dpt_text(co) -> str:
    """Datentyp eines KOs für die Anzeige: «1.008 Auf/Ab» mit Untertyp,
    sonst die Grösse («1 Byte») bzw. der Text aus dem Report."""
    from ..utils.ets_dpt_names import dpt_table, dpt_text
    dpt = getattr(co, "data_type", "") or getattr(co, "datapoint_type", "") or ""
    if dpt in dpt_table() and dpt.startswith("DPST-"):
        return dpt_text(dpt)
    return size_text(co_bits(co)) or dpt


def ko_label(co, number: bool = True, details: bool = True) -> str:
    """KO wie in der ETS (Name – Objektfunktion), mit details Datentyp bzw.
    Grösse und Richtung, z.B. «9: Kanal C1 – Rückmeldung Ein/Aus (1.001
    Schalten, sendet)»."""
    name, function = co.name or "", co.object_function or ""
    text = name if function in name else f"{name} – {function}".strip(" –")
    if details:
        extras = [e for e in (ko_dpt_text(co), ko_direction(co)) if e]
        if extras:
            text += f" ({', '.join(extras)})"
    return f"{co.object_number}: {text}" if number else text
