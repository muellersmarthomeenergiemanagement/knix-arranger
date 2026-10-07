"""Präsenz- und Bewegungsmelder: Kanäle statt Tasten, nur der Schaltbefehl
(Projekt_23: Bewegungsmelder Waschküche erschien in der Topologie mit
"Taste 1 ... kurz", Dimmen und Rückmeldungen)."""
from knix_arranger.models.building import Room, SensorFunktion
from knix_arranger.services.sensor_service import PRESENCE_BEDIENART, SensorService


def _lookup(room):
    designations = {
        ("L", 1, "E/A"): "L_CUG01_01 E/A", ("L", 1, "RM"): "L_CUG01_01 RM",
        ("LDA", 1, "E/A"): "LDA_CUG01_01 E/A", ("LDA", 1, "DIM"): "LDA_CUG01_01 DIM",
        ("LDA", 1, "RM"): "LDA_CUG01_01 RM",
    }
    return {(code, room.id, nr, fn): d for (code, nr, fn), d in designations.items()}


def _expand(element_type):
    room = Room(number="CUG01", name="Waschküche")
    funktionen = [SensorFunktion(gewerk_code="L", element_number=1),
                  SensorFunktion(gewerk_code="LDA", element_number=1)]
    fas, _ = SensorService()._expand_funktionen(funktionen, room, _lookup(room), element_type)
    return [(fa.button_channel, fa.function_ga, fa.action_type, fa.role, fa.bedienart)
            for fa in fas]


def test_motion_sensor_has_channels_and_only_the_command():
    assert _expand("Bewegungsmelder") == [
        ("Kanal 1", "L_CUG01_01 E/A", "", "befehl", PRESENCE_BEDIENART),
        ("Kanal 2", "LDA_CUG01_01 E/A", "", "befehl", PRESENCE_BEDIENART),
    ]
    assert _expand("Präsenzmelder")[0][0] == "Kanal 1"


def test_push_button_unchanged():
    channels = [c for c, *_ in _expand("Tastereinheit")]
    assert channels[:2] == ["Taste 1", "Status 1"]
    assert ("Taste 2", "LDA_CUG01_01 DIM", "lang") in [r[:3] for r in _expand("Tastereinheit")]
