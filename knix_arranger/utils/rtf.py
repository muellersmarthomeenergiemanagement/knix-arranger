"""
RTF -> Klartext fuer Freitextfelder aus ETS-Projekten.

ETS speichert Felder wie InstallationHints (Einbauort) als RTF, auch wenn sie
leer sind ("{\\rtf1\\ansi ... \\par}"). Umgesetzt wird nur, was diese Felder
brauchen: Text, Sonderzeichen (\\'fc, \\u252), Absaetze; Schrift-/Farbtabellen
und Formatierung entfallen.
"""
from __future__ import annotations
import re

# Gruppen ohne sichtbaren Text
_SKIP_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer",
})
_TOKEN_RE = re.compile(
    r"\\'([0-9a-fA-F]{2})"           # \'hh  Zeichen der Codepage
    r"|\\([a-zA-Z]+)(-?\d+)? ?"      # \wort[zahl]  Steuerwort (ein Leerzeichen gehoert dazu)
    r"|\\([^a-zA-Z])"                # \{ \} \\ \* ...  Steuersymbol
    r"|([{}])"                       # Gruppe auf/zu
    r"|([^\\{}\r\n]+)"               # Text
    r"|[\r\n]",                      # Zeilenumbrueche im Quelltext zaehlen nicht
)


def is_rtf(value: str) -> bool:
    return (value or "").lstrip().startswith("{\\rtf")


def rtf_to_text(value: str) -> str:
    """Klartext eines RTF-Strings; Nicht-RTF wird unveraendert zurueckgegeben."""
    if not is_rtf(value):
        return value
    codepage = "cp1252"
    m = re.search(r"\\ansicpg(\d+)", value)
    if m:
        codepage = f"cp{m.group(1)}"

    out: list[str] = []
    pending_bytes = bytearray()
    stack: list[bool] = []          # je offene Gruppe: wird uebersprungen?
    skip = False
    group_start = False             # erstes Token einer neuen Gruppe?
    uc_skip = 1                     # Ersatzzeichen nach \uN (Steuerwort \ucN)
    to_skip = 0                     # noch zu ueberspringende Ersatzzeichen

    def flush_bytes():
        if pending_bytes:
            try:
                out.append(pending_bytes.decode(codepage, errors="replace"))
            except LookupError:
                out.append(pending_bytes.decode("cp1252", errors="replace"))
            pending_bytes.clear()

    for tok in _TOKEN_RE.finditer(value):
        hex_byte, word, arg, symbol, brace, text = tok.groups()
        first = group_start
        group_start = False
        if brace == "{":
            flush_bytes()
            stack.append(skip)
            group_start = True
            continue
        if brace == "}":
            flush_bytes()
            skip = stack.pop() if stack else False
            continue
        if symbol == "*" and first:
            skip = True              # {\* ...} unbekannte Zieldaten
            continue
        if word and first and word in _SKIP_DESTINATIONS:
            skip = True
            continue
        if skip:
            continue
        if hex_byte:
            if to_skip:
                to_skip -= 1
                continue
            pending_bytes.append(int(hex_byte, 16))
            continue
        flush_bytes()
        if word:
            if word == "uc" and arg:
                uc_skip = int(arg)
            elif word == "u" and arg:
                code = int(arg)
                out.append(chr(code + 65536 if code < 0 else code))
                to_skip = uc_skip
            elif word in ("par", "line"):
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            continue
        if symbol:
            if symbol in "\\{}":
                out.append(symbol)
            elif symbol == "~":
                out.append(" ")
            continue
        if text:
            if to_skip:
                n = min(to_skip, len(text))
                text = text[n:]
                to_skip -= n
            out.append(text)
    flush_bytes()
    lines = [line.strip() for line in "".join(out).splitlines()]
    return "\n".join(line for line in lines if line)
