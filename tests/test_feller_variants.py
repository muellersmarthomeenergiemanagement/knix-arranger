"""Feller EDIZIOdue colore (Test 148, 1.1.103): KO-Nummern mit vielen
Parametervarianten je Belegung der Taste. KNiX wählt die Variante nach dem
Gewerk (Dimmen, Jalousie), legt die Rückmeldung auf das mithörende
Schaltobjekt und lässt Funktionen ohne passenden KO leer."""
from __future__ import annotations

from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.ko_plausibility import sensor_ko_problem
from knix_arranger.services.product_capabilities import device_capabilities
from knix_arranger.services.sensor_channels import (
    SensorLink, display_variant, split_rocker, suggested_sensor_co_map,
)

_SEND_RECEIVE, _SEND, _RECEIVE = "K-SÜ--", "K--Ü--", "K-S---"

# Wippe 1: links KO 0–2, rechts KO 3–5 (Auszug der echten Varianten)
_VARIANTS = [
    (0, "Object 1", "Object 1", "1 Bit", "KLSÜA-"),
    (0, "Taste 1", "EIN/AUS, Schalten", "1 Bit", _SEND_RECEIVE),
    (0, "Taste 1", "EIN/AUS, Dimmen", "1 Bit", _SEND_RECEIVE),
    (0, "Taste 1, links", "EIN/AUS, Dimmen", "1 Bit", _SEND_RECEIVE),
    (0, "Taste 1, links", "AUF/AB, Jalousie", "1 Bit", _SEND_RECEIVE),
    (0, "Taste 1, links", "abrufen, Szene", "1 Byte", _SEND),
    (1, "Object 2", "Object 2", "1 Bit", "KLSÜA-"),
    (1, "Taste 1, links (langer Tastendruck)", "Wert, Dimmen", "1 Byte", _SEND),
    (1, "Taste 1, links", "heller/dunkler, Dimmen", "4 Bit", _SEND),
    (1, "Taste 1, links", "schritt/stopp, Jalousie", "1 Bit", _SEND_RECEIVE),
    (2, "Taste 1, links, Signal LED", "anzeigen auf LED", "1 Bit", _RECEIVE),
    (3, "Object 4", "Object 4", "1 Bit", "KLSÜA-"),
    (3, "Taste 1, rechts", "EIN/AUS, Schalten", "1 Bit", _SEND_RECEIVE),
    (3, "Taste 1, rechts", "AUF/AB, Jalousie", "1 Bit", _SEND_RECEIVE),
    (4, "Taste 1, rechts (langer Tastendruck)", "AUF/AB, Jalousie", "1 Bit", _SEND),
    (4, "Taste 1, rechts", "schritt/stopp, Jalousie", "1 Bit", _SEND_RECEIVE),
    (4, "Taste 1, rechts", "heller/dunkler, Dimmen", "4 Bit", _SEND),
    (5, "Taste 1, rechts, Signal LED", "anzeigen auf LED", "1 Bit", _RECEIVE),
]


def _device():
    return Device(device_type="sensor", product="Tastereinheit",
                  product_name="EDIZIOdue colore Taster 1-8fach RGB Temp",
                  communication_objects=[
                      CommunicationObject(object_number=n, name=name, object_function=f,
                                          object_size=size, flags=flags)
                      for n, name, f, size, flags in _VARIANTS])


def _link(channel, code, element, function, dpt, feedback):
    return SensorLink(key=f"a|{code}|{element}|{function}", channel=channel,
                      function=function, ga_address="", ga_designation="",
                      ga_function=function, dpt=dpt, feedback=feedback)


_LINKS = [
    _link("Taste 1 kurz", "LD", 1, "E/A", "DPST-1-1", False),
    _link("Taste 1 lang", "LD", 1, "DIM", "DPST-3-7", False),
    _link("Status 1", "LD", 1, "RM", "DPST-1-1", True),
    _link("Status 1", "LD", 1, "RM WERT", "DPST-5-1", True),
    _link("Taste 2 kurz", "J", 1, "STOPP", "DPST-1-7", False),
    _link("Taste 2 lang", "J", 1, "AUF/AB", "DPST-1-8", False),
    _link("Status 2", "J", 1, "STATUS POSITION HOEHE", "DPST-5-1", True),
]


def test_variants_follow_the_planned_use_of_the_key():
    device = _device()
    result = suggested_sensor_co_map(device, _LINKS, device.communication_objects)
    by_function = {link.key.split("|", 1)[1]: result.get(link.key, -1) for link in _LINKS}
    assert by_function == {
        "LD|1|E/A": 0, "LD|1|DIM": 1,
        "LD|1|RM": 0,                      # Schaltobjekt hört die Rückmeldung mit
        "LD|1|RM WERT": -1,                # keine 1-Byte-Rückmeldung an der Taste
        "J|1|STOPP": 4, "J|1|AUF/AB": 3,
        "J|1|STATUS POSITION HOEHE": -1,   # Feller-Taste ohne Positionsstatus
    }


def test_display_shows_the_variant_of_the_row():
    device = _device()
    by_number = {}
    for co in device.communication_objects:
        by_number.setdefault(co.object_number, []).append(co)
    dim, stop = _LINKS[1], _LINKS[4]
    assert split_rocker(dim, _LINKS) is True          # Taste 1 und 2 = beide Seiten
    shown = display_variant(by_number[1], dim, split_rocker(dim, _LINKS))
    assert (shown.name, shown.object_function) == ("Taste 1, links", "heller/dunkler, Dimmen")
    shown = display_variant(by_number[4], stop, True)
    assert shown.object_function == "schritt/stopp, Jalousie"
    assert display_variant(by_number[0], _LINKS[0], True).name == "Taste 1, links"


def test_size_of_the_active_variant_counts():
    """Jalousiehöhe (1 Byte) auf «AUF/AB, Jalousie» (1 Bit) passt nicht --
    die 1-Byte-Variante «Wert, Dimmen» derselben Nummer gilt dort nicht."""
    device = _device()
    variants = [co for co in device.communication_objects if co.object_number == 1]
    problem = sensor_ko_problem(_LINKS[6], variants, [])
    assert problem.startswith("Grösse passt nicht")


def test_capabilities_see_the_rockers():
    caps = device_capabilities(_device())
    assert caps.rocker
