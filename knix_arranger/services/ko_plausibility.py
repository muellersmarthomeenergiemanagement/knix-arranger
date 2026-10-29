"""
Passt ein zugeordnetes KO zur GA-Funktion? (FA-634)

Die automatische KO-Zuordnung (actor_channels, sensor_channels, gemerkte
Vorlagen je Produkt) traf in Projekt_23 Objekte, deren Flags oder DPT der
Funktion widersprechen:
- Hager TXM616D: «RM WERT» (5.001) auf «Status indication priority» (1.011),
- Revox-Gateway: «Room 1: Select User 1 Fav Status» auf das Eingangs-KO
  «USER_3_ROOM_FAV_OFF» (K S) statt auf «USER_1_ROOM_FAV_STATUS» (K Ü),
- Feller EDIZIOdue: Jalousie-Rückmeldung von Taste 5 auf «Taste 2, links
  (langer Tastendruck)» -- ein KO einer anderen Taste.

Ein KO besteht, wenn eine seiner Varianten (gleiche Nummer, je nach
Parametrierung) passt. Flags nicht parametrierter Produktdaten-KOs («Object 2»
mit allen Flags) zählen nicht. Bewusst nicht geprüft: «Befehl auf Ausgangs-
KO» bei Aktoren/Gateways (ein Gateway sendet auch Befehle) und der DPT bei
Tastern (Varianten je Parameter, meldet ko_batch._dpt_problem).

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re

from .ko_links import TRANSMIT, WRITE, parse_flags
from .ko_links import unparametrized_co as _unparametrized
from .ko_size import co_bits, dpt_bits, size_text, sizes_compatible

_FEEDBACK_FUNCTION = re.compile(
    r"^(RM|STATUS)\b|\b(status|rückmeldung|rueckmeldung|feedback)\b", re.IGNORECASE)
_PARENTHESIS = re.compile(r"\s*\(.*?\)")
_KEY_STATUS = re.compile(r"^status\s*\d+$", re.IGNORECASE)
_BUTTON_SUFFIX = re.compile(
    r",?\s*(signal[\s-]*led|led|status\b.*|rückmeldung.*)$", re.IGNORECASE)


def is_feedback_function(function: str) -> bool:
    """GA-Funktion ist eine Rückmeldung: «RM», «STATUS POSITION HOEHE», aber
    auch Gateway-Funktionen wie «Room 1: Mute Status»."""
    return bool(_FEEDBACK_FUNCTION.search(function or ""))


def _dpt_main(text: str) -> str:
    from .actor_channels import _dpt_key
    return _dpt_key(text)[0]


def _named(variants: list) -> list:
    """Varianten mit sprechendem Text; die generische («Object 25», alle
    Flags) entlastet nicht, wenn die Nummer benannte Varianten hat -- sonst
    galt Feller KO 24 «alle teilnehmenden Tasten – sperren» als Rückmeldung
    einer Taste als unbedenklich."""
    from .ko_names import is_generic
    named = [co for co in variants if not is_generic(co)]
    return named or variants


def _first_problem(problems: list[str]) -> str:
    return "" if not problems or "" in problems else problems[0]


def actor_ko_problem(variants: list, function: str, ga_dpt: str = "") -> str:
    """Grund, warum das KO (Varianten derselben Nummer) nicht zur Funktion
    eines Aktor-/Gateway-Kanals passt; "" wenn es passt oder nichts bekannt ist."""
    feedback = is_feedback_function(function)
    ga_main = _dpt_main(ga_dpt)

    def problem(co) -> str:
        flags = parse_flags(co.flags)
        if feedback and flags and not _unparametrized(co) \
                and WRITE in flags and TRANSMIT not in flags:
            return "Rückmeldung auf Eingangs-KO (S ohne Ü)"
        co_main = _dpt_main(co.data_type)
        if ga_main and co_main and ga_main != co_main:
            return f"DPT passt nicht (KO {co_main}.x, GA {ga_main}.x)"
        if not sizes_compatible(co, ga_dpt):
            return (f"Grösse passt nicht (KO {size_text(co_bits(co))}, "
                    f"GA {size_text(dpt_bits(ga_dpt))})")
        return ""
    return _first_problem([problem(co) for co in _named(variants)])


def button_of(co) -> str:
    """Taste eines Tasten-KOs: «Taste 2, links (langer Tastendruck)» und
    «Taste 2, links, Signal LED» -> «taste 2, links»."""
    name = _PARENTHESIS.sub("", co.name or co.object_function or "")
    return _BUTTON_SUFFIX.sub("", name).strip().lower()


def sensor_ko_problem(link, variants: list, command_variants: list) -> str:
    """Grund, warum das KO nicht zur GA eines Tasters/Sensors passt; "" wenn
    es passt. command_variants: KOs (mit Varianten), die den Befehlen
    desselben Elements zugeordnet sind -- die Rückmeldung «Status n» gehört
    an dieselbe Taste wie der Befehl «Taste n». Rollen (Raumtemperatur,
    Aktorstatus …) werden nicht geprüft."""
    if link.role:
        return ""
    own_numbers = {c.object_number for c in command_variants}
    own_buttons = {button_of(c) for c in command_variants}
    # Nur die Varianten der Belegung (Feller: Jalousie-Taste -> «…, Jalousie»);
    # passt keine in der Grösse, passt das KO nicht (Jalousiehöhe 1 Byte auf
    # «AUF/AB, Jalousie» 1 Bit -- die Variante «Wert, Dimmen» gilt dort nicht)
    from .sensor_channels import family_variants
    fitting = family_variants(variants, link)
    dpt = getattr(link, "dpt", "")
    if dpt and fitting and not any(sizes_compatible(co, dpt) for co in fitting):
        return (f"Grösse passt nicht (KO {size_text(co_bits(fitting[0]))}, "
                f"GA {size_text(dpt_bits(dpt))})")

    def problem(co) -> str:
        if _unparametrized(co):
            return ""       # weder Flags noch Taste ablesbar
        flags = parse_flags(co.flags)
        if flags:
            if link.feedback and WRITE not in flags:
                return "Rückmeldung auf KO ohne S (empfängt nicht)"
            if not link.feedback and TRANSMIT not in flags:
                return "Befehl auf KO ohne Ü (sendet nicht)"
        if link.feedback and command_variants and _KEY_STATUS.match(link.channel or "") \
                and co.object_number not in own_numbers \
                and button_of(co) not in own_buttons:
            return "KO einer anderen Taste"
        return ""
    return _first_problem([problem(co) for co in _named(variants)])


def ko_variants(device) -> dict[int, list]:
    """KO-Nummer -> alle Varianten (gleiche Nummer, je nach Parametrierung)."""
    result: dict[int, list] = {}
    for co in device.communication_objects:
        result.setdefault(co.object_number, []).append(co)
    return result


def _element(link) -> str:
    return link.key.rsplit("|", 1)[0]


def sensor_selection_problems(links: list, selection: dict[str, int],
                              variants: dict[int, list]) -> dict[str, str]:
    """ga_key -> Grund für gewählte KOs (Nummer >= 0), die nicht passen;
    Rückmeldungen gegen die KOs der Befehle desselben Elements geprüft."""
    commands: dict[str, list] = {}
    for link in links:
        number = selection.get(link.key, -1)
        if not link.feedback and not link.role and number >= 0:
            commands.setdefault(_element(link), []).extend(variants.get(number, []))
    result = {}
    for link in links:
        number = selection.get(link.key, -1)
        if number < 0:
            continue
        problem = sensor_ko_problem(link, variants.get(number, []),
                                    commands.get(_element(link), []) if link.feedback else [])
        if problem:
            result[link.key] = problem
    return result


# -- Untertyp von KO und GA (FA-638) ---------------------------------------
#
# Bei diesen Haupttypen ändert der Untertyp, was ein Wert bedeutet: 5.001
# Prozent (255 = 100 %) gegen 5.010 Zählimpulse (255 = 255), 9.001 °C gegen
# 9.004 Lux, 3.007 Dimmen gegen 3.008 Jalousie. Bei DPT 1 sind 0/1 auf beiden
# Seiten gleich; dort weichen die Hersteller oft ab (Jalousieaktor
# «Beschattung» 1.022 an GA 1.023, Sperrobjekt 1.003 an GA 1.001), eine
# Prüfung brächte fast nur Fehlalarme (Chalet Franziska: 205 von 1307
# Verknüpfungen, alle harmlos). DPT 16 (ASCII/ISO) ebenfalls ohne Folgen.
VALUE_SUBTYPE_MAINS = frozenset({"3", "5", "6", "7", "8", "9", "12", "13", "14"})


def subtype_problem(co_dpts: list[str], ga_dpt: str) -> str:
    """Grund, warum der Untertyp des KOs (Varianten derselben Nummer) nicht
    zur GA passt; "" wenn er passt, eine Seite keinen Untertyp hat oder der
    Haupttyp ihn nicht braucht (VALUE_SUBTYPE_MAINS)."""
    from .actor_channels import _dpt_key
    from ..utils.ets_dpt_names import dpt_text
    ga_main, ga_sub = _dpt_key(ga_dpt)
    if ga_main not in VALUE_SUBTYPE_MAINS or not ga_sub:
        return ""
    others = []
    for dpt in co_dpts:
        main, sub = _dpt_key(dpt)
        if main != ga_main or not sub or sub == ga_sub:
            return ""          # andere Haupttypen meldet FA-634, gleiche passen
        others.append(dpt)
    if not others:
        return ""
    return f"KO {dpt_text(_canonical(others[0]))}, GA {dpt_text(_canonical(ga_dpt))}"


def _canonical(dpt: str) -> str:
    from .actor_channels import _dpt_key
    main, sub = _dpt_key(dpt)
    return f"DPST-{main}-{int(sub)}" if sub else f"DPT-{main}"
