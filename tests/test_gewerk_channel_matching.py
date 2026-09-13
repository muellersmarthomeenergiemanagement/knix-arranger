"""
Tests fuer GewerkChannelMatching: ordnet die ComObjects eines Aktor-Kanals
den Funktions-Slots eines Adressblock-Schemas zu (FA-521f).
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.topology import Device, CommunicationObject
from knix_arranger.models.address_block import (
    create_light_block_schema_a, create_jalousie_block_schema_a,
)
from knix_arranger.services.gewerk_channel_matching import (
    group_channels_by_name, match_channel_to_schema,
)


def _griesser_style_device() -> Device:
    """Griesser JAX-9 Jalousieaktor (1.1.4, Chalet-Projekt): jede Funktion
    hat einen eigenen COName, der echte Kanal steht nur als Klammer-Tag
    '(M1)' im Namen (siehe gewerk_channel_matching._channel_key)."""
    device = Device(physical_address="1.1.4", manufacturer="Griesser AG")
    device.communication_objects = [
        CommunicationObject(
            name="Bedienung Storen (M1), Endlage", object_function="Auf / Ab",
            data_type="Auf/Ab", connected_gas=["3/1/55"],
        ),
        CommunicationObject(
            name="Bedienung Storen (M1), Wippen", object_function="Schritt / Stopp",
            data_type="Schritt", connected_gas=["3/1/56"],
        ),
        CommunicationObject(
            name="Bedienung Storen (M1), Höhe", object_function="Höhe 0…255",
            data_type="Prozent (0..100%)", connected_gas=["3/1/57"],
        ),
        CommunicationObject(
            name="Sonnenschutz (M1), Rückmeldung Höhe", object_function="Höhe 0…255",
            data_type="Prozent (0..100%)", connected_gas=["3/6/57"],
        ),
        CommunicationObject(
            name="Sicherheit 1 (M1), Alarm", object_function="Ein / Aus",
            data_type="Alarm", connected_gas=["0/5/13"],
        ),
        CommunicationObject(
            name="Bedienung Storen (M2), Endlage", object_function="Auf / Ab",
            data_type="Auf/Ab", connected_gas=["3/1/50"],
        ),
    ]
    return device


def _abb_style_device() -> Device:
    """Kanal 'Ausgang A' eines ABB SA/S8.16.1 (1.1.10, Chalet-Projekt) --
    reiner Schaltaktor-Kanal ohne Dimmfunktion."""
    device = Device(physical_address="1.1.10", manufacturer="ABB")
    device.communication_objects = [
        CommunicationObject(
            object_number=1, name="Ausgang A", object_function="Schalten",
            data_type="1 bit", connected_gas=["0/2/50"],
        ),
        CommunicationObject(
            object_number=2, name="Ausgang A", object_function="8-Bit-Szene",
            data_type="1 byte", connected_gas=["0/4/1"],
        ),
        CommunicationObject(
            object_number=3, name="Ausgang A",
            object_function="Telegr. Status Schalten", data_type="1 bit",
            connected_gas=["0/2/51"],
        ),
    ]
    return device


def _dimmer_style_device() -> Device:
    """Ein Dimmaktor-Kanal mit vollem Funktionsumfang."""
    device = Device(physical_address="1.1.20", manufacturer="Test")
    device.communication_objects = [
        CommunicationObject(name="Kanal 1", object_function="Schalten",
                            connected_gas=["1/0/1"]),
        CommunicationObject(name="Kanal 1", object_function="Dimmen (Heller/Dunkler)",
                            connected_gas=["1/0/2"]),
        CommunicationObject(name="Kanal 1", object_function="Wert setzen",
                            connected_gas=["1/0/3"]),
        CommunicationObject(name="Kanal 1", object_function="Telegr. Status Schalten",
                            connected_gas=["1/0/4"]),
        CommunicationObject(name="Kanal 1", object_function="Status Wert",
                            connected_gas=["1/0/5"]),
    ]
    return device


class TestGroupChannelsByName:
    def test_groups_by_exact_name(self):
        device = _abb_style_device()
        device.communication_objects.append(
            CommunicationObject(name="Ausgang B", object_function="Schalten")
        )
        channels = group_channels_by_name(device)
        assert set(channels.keys()) == {"Ausgang A", "Ausgang B"}
        assert len(channels["Ausgang A"]) == 3
        assert len(channels["Ausgang B"]) == 1

    def test_groups_by_parenthesised_tag_when_present(self):
        """Realdaten-Fall (Griesser JAX-9, Chalet-Projekt 1.1.4): fuenf
        unterschiedlich benannte ComObjects mit '(M1)' im Namen gehoeren
        zu einem Kanal, ein sechstes mit '(M2)' zu einem anderen."""
        device = _griesser_style_device()
        channels = group_channels_by_name(device)
        assert set(channels.keys()) == {"M1", "M2"}
        assert len(channels["M1"]) == 5
        assert len(channels["M2"]) == 1


class TestMatchChannelToSchema:
    def test_simple_switch_actuator_matches_ea_and_rm_only(self):
        """Realdaten-Fall (Chalet-Projekt, ABB 1.1.10 'Ausgang A'): nur
        Schalten + Status vorhanden -- DIM/WERT/RM WERT bleiben unbesetzt,
        werden NICHT geraten."""
        device = _abb_style_device()
        channels = group_channels_by_name(device)
        schema = create_light_block_schema_a()

        matched = match_channel_to_schema(channels["Ausgang A"], schema)

        assert set(matched.keys()) == {"E/A", "RM"}
        assert matched["E/A"].connected_gas == ["0/2/50"]
        assert matched["RM"].connected_gas == ["0/2/51"]

    def test_full_dimmer_channel_matches_all_four_slots(self):
        device = _dimmer_style_device()
        channels = group_channels_by_name(device)
        schema = create_light_block_schema_a()

        matched = match_channel_to_schema(channels["Kanal 1"], schema)

        assert matched["E/A"].connected_gas == ["1/0/1"]
        assert matched["DIM"].connected_gas == ["1/0/2"]
        assert matched["WERT"].connected_gas == ["1/0/3"]
        assert matched["RM"].connected_gas == ["1/0/4"]
        assert matched["RM WERT"].connected_gas == ["1/0/5"]

    def test_no_scene_com_object_leaks_into_matching(self):
        """Das '8-Bit-Szene'-ComObject des Kanals darf keinem Licht-Slot
        zugeordnet werden (kein Funktions-Keyword passt)."""
        device = _abb_style_device()
        channels = group_channels_by_name(device)
        schema = create_light_block_schema_a()

        matched = match_channel_to_schema(channels["Ausgang A"], schema)

        matched_gas = {co.connected_gas[0] for co in matched.values()}
        assert "0/4/1" not in matched_gas

    def test_griesser_m1_channel_matches_multiple_jalousie_functions(self):
        """Nach der Kanal-Tag-Gruppierung liefert 'M1' einen starken,
        mehrfachen Treffer statt fuenf schwacher Einzel-Kanaele."""
        device = _griesser_style_device()
        channels = group_channels_by_name(device)
        schema = create_jalousie_block_schema_a()

        matched = match_channel_to_schema(channels["M1"], schema)

        assert set(matched.keys()) == {"AUF/AB", "STOPP", "POSITION HOEHE", "STATUS POSITION HOEHE"}
        assert matched["AUF/AB"].connected_gas == ["3/1/55"]
        assert matched["STATUS POSITION HOEHE"].connected_gas == ["3/6/57"]

    def test_unrelated_schema_finds_nothing(self):
        """Ein Schaltaktor-Kanal (Licht) matcht nicht auf ein Jalousie-Schema."""
        device = _abb_style_device()
        channels = group_channels_by_name(device)
        schema = create_jalousie_block_schema_a()

        matched = match_channel_to_schema(channels["Ausgang A"], schema)

        assert matched == {}
