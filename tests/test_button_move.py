"""Tasten verschieben und tauschen, Bedienelement entfernen (FA-1015 e)."""
from knix_arranger.models.building import Bedienelement, Room, SensorFunktion
from knix_arranger.services.button_move import (
    button_keys, move_button, remove_bedienelement,
)


def _sf(code, nr=1, **kw):
    return SensorFunktion(gewerk_code=code, element_number=nr, **kw)


def _taster(*funktionen, pn="1.1.101"):
    return Bedienelement(element_type="Tastereinheit", channels=4, participant_number=pn,
                         funktionen=list(funktionen))


def _codes(be):
    return [(sf.gewerk_code or sf.label) for sf in be.funktionen if not sf.press_of]


def test_swap_within_taster_keeps_long_press_and_own_label():
    licht, jalousie = _sf("L"), _sf("J")
    dimmen = SensorFunktion(ga_designation="1/0/2 DIM", press_of=licht.id)
    be = _taster(licht, jalousie, dimmen)
    labels = {"1.1.101|1||": "Decke"}          # eigene Bezeichnung Taste 1 = Licht

    move_button(be, licht, be, target=jalousie, labels=labels)

    assert _codes(be) == ["J", "L"]
    assert dimmen.press_of == licht.id         # langer Druck bleibt beim Licht
    assert labels == {"1.1.101|2||": "Decke"}  # Bezeichnung wandert mit
    assert be.is_auto is False


def test_move_to_free_key_of_other_taster():
    licht = _sf("L")
    src = _taster(licht, _sf("S"), pn="1.1.101")
    dst = _taster(_sf("J"), pn="1.1.102")
    lang = SensorFunktion(ga_designation="1/0/2 DIM", press_of=licht.id)
    src.funktionen.append(lang)

    move_button(src, licht, dst)

    assert _codes(src) == ["S"] and _codes(dst) == ["J", "L"]
    assert lang in dst.funktionen and lang not in src.funktionen


def test_imported_positions_stay_in_place():
    a = SensorFunktion(label="Taste 1, links", ga_designation="1/0/1 Licht")
    b = SensorFunktion(label="Taste 1, rechts", ga_designation="1/0/2 Storen")
    a_long = SensorFunktion(label="Taste 1, links (langer Tastendruck)",
                            ga_designation="1/0/3 Dimmen")
    be = _taster(a, b, a_long)

    move_button(be, a, be, target=b)

    # Position bleibt, Inhalt tauscht: links ist jetzt Storen
    assert (b.label, a.label) == ("Taste 1, links", "Taste 1, rechts")
    assert a_long.press_of == a.id             # langer Druck folgt dem Licht
    keys = button_keys(be)
    assert (keys[a.id].number, keys[a.id].side) == (1, "rechts")

    move_button(be, a, be, target_label="Taste 2, links")
    assert a.label == "Taste 2, links"


def test_wish_keeps_text_when_moved():
    wish = SensorFunktion(label="Licht Ein/Aus")
    src, dst = _taster(wish), _taster(pn="1.1.102")
    move_button(src, wish, dst, target_label="Taste 3, links")
    assert wish.label == "Licht Ein/Aus"


def test_remove_auto_suggestion_stays_suppressed_manual_is_deleted():
    room = Room(name="Technik")
    auto = _taster(_sf("L"))
    manual = _taster(_sf("L"), pn="1.1.103")
    manual.is_auto = False
    room.bedienelemente = [auto, manual]

    remove_bedienelement(room, auto)
    remove_bedienelement(room, manual)

    assert room.bedienelemente == [auto]
    assert auto.suppressed and not auto.funktionen and not auto.is_auto
