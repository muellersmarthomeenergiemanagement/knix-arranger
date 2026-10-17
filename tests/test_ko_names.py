"""
KO-Namen je Produkt aus ETS-Projekten (FA-1411d): lernen, merken, bei
Platzhalter-KOs desselben Produkts einsetzen.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services import ko_names
from knix_arranger.services.product_capabilities import device_capabilities


def _device(pa, cos, order="470x-x-B.xxx"):
    return Device(device_type="sensor", product="Tastereinheit", physical_address=pa,
                  manufacturer="Feller", order_number=order,
                  product_name="EDIZIOdue colore Taster 1-8fach RGB Temp",
                  communication_objects=cos)


def _project(*devices):
    project = KnxProject(name="Namen")
    project.topology = Topology(areas=[Area(area_number=1, lines=[
        Line(name="L1", line_number=1, devices=list(devices))])])
    return project


def _ets():
    return _project(_device("1.1.31", [
        CommunicationObject(object_number=0, name="Taste 1, links",
                            object_function="EIN/AUS, Schalten", flags="K-SÜ--"),
        CommunicationObject(object_number=3, name="Taste 1, rechts",
                            object_function="EIN/AUS, Schalten", flags="K-SÜ--"),
        CommunicationObject(object_number=70, name="Raumtemperatur",
                            object_function="senden", flags="K--Ü--", data_type="DPST-9-1"),
    ]))


def _catalog_device():
    return _device("1.1.101", [
        CommunicationObject(object_number=0, name="Object 1", object_function="Object 1",
                            flags="KLSÜA-"),
        CommunicationObject(object_number=3, name="Object 4", object_function="Object 4",
                            flags="KLSÜA-"),
        CommunicationObject(object_number=5, name="Object 6", object_function="Object 6",
                            flags="KLSÜA-"),
        CommunicationObject(object_number=70, name="Raumtemperatur",
                            object_function="Raumtemperatur", flags="K--Ü--",
                            data_type="DPST-9-1"),
    ])


def test_generic_names():
    assert ko_names.is_generic(CommunicationObject(name="Object 27", object_function="Object 27"))
    assert ko_names.is_generic(CommunicationObject(name="GO0002", object_function="{{0:GO}}"))
    assert not ko_names.is_generic(CommunicationObject(name="Taste 1, links"))


def test_learn_and_apply():
    learned = ko_names.learn_from_project(_ets())
    assert sum(learned.values()) == 3
    device = _catalog_device()
    target = _project(device)
    assert ko_names.apply_to_project(target) == 2         # KO 0 und 3, nicht 70 (schon benannt)
    by = {co.object_number: co for co in device.communication_objects}
    assert (by[0].name, by[0].flags) == ("Taste 1, links", "K-SÜ--")
    assert by[3].name == "Taste 1, rechts"
    assert by[5].name == "Object 6"                        # unbekannt: bleibt
    assert by[70].object_function == "Raumtemperatur"
    caps = device_capabilities(device)
    assert caps.keys == 8 and caps.rocker                  # nicht 2 aus den zwei Namen


def test_other_product_untouched():
    ko_names.learn_from_project(_ets())
    other = _device("1.1.102", [CommunicationObject(object_number=0, name="Object 1",
                                                    object_function="Object 1")],
                    order="470x-x.FMI.xx")
    assert ko_names.apply_to_device(other) == 0
    assert other.communication_objects[0].name == "Object 1"
