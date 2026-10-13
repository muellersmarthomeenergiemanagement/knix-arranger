"""
Einordnung von Katalogprodukten (product_classifier). Die Namen stammen aus
echten Herstellerkatalogen; bisher landeten viele davon als "Schaltaktor"
(Bedienelemente, Präsenzmelder, Regler) oder "Sonstiges" (Gateways).
"""
from __future__ import annotations

import json
import os

import pytest

from knix_arranger.services.product_classifier import classify, type_group
from knix_arranger.services.product_search_service import (
    ProductSearchService, _user_catalog_path,
)


@pytest.mark.parametrize("name, order, device_type, channels", [
    # Aktoren
    ("SA/S8.10.2.12 Switch Act, 8-f, 10A, MDRC", "2CDG 110 259 R0021", "Schaltaktor", 8),
    ("16-fold switch actuator 16A C-load 230V AC", "TXM616D", "Schaltaktor", 16),
    ("6 sorties ON/OFF 16A charges capacitives 230V AC", "TYA606", "Schaltaktor", 6),
    ("4-fold dimming actuator 300W, universal", "TXA664", "Dimmaktor", 4),
    ("1 sortie variateur universel 300W", "TRB", "Dimmaktor", 0),
    ("JRA/S4.230.2.1 Blind/RollerShutterAct,M,4f,230V", "", "Jalousieaktor", 4),
    ("1 sortie volets 6A 230V AC, encastré", "", "Jalousieaktor", 0),
    ("SAH/S16.16.7.11 Switch/Shutter Act, 16-f, 16A, M", "", "Schalt-/Jalousieaktor", 16),
    ("Actuator for thermal positioners N 605/01", "", "Heizungsaktor", 0),
    ("Vanne motorisée", "", "Heizungsaktor", 0),
    ("Fan coil actuator 2 gang 10A", "TYF642F", "Fan-Coil-Aktor", 2),
    ("4-channel analog actuator", "", "Analogaktor", 4),
    ("1-fold dimmer 200 W, 2 wires + 2 inputs, embedded", "", "Dimmaktor", 1),
    ("JM 4 T 24V", "4940260", "Jalousieaktor", 0),
    ("RM 8 I", "4940215", "Schaltaktor", 0),
    # Bedienung und Sensoren
    ("TB/U4.4, TB/U4.8 Tacteo 4-fold control element", "", "Tastereinheit", 4),
    ("6320/50-..-500 triton 5/10fach MF/IR", "", "Tastereinheit", 10),
    ("6108/07-500 Push-button coupling unit 4gang, FM", "", "Tastereinheit", 4),
    ("Télécommande 4 canaux radio", "", "Tastereinheit", 0),
    ("6108/18 Flush-mounted room temperature controller", "", "Raumthermostat", 0),
    ("SBC/U6.0 HVAC/CO2 device, 6gang BE", "", "Raumthermostat", 6),
    ("6131/21 Busch-Presence detector mini premium", "", "Praesenzmelder", 0),
    ("compact office EIB", "201 9 200", "Praesenzmelder", 0),
    ("BE/S4.230.2.1 Binary Input,4-fold,230V,MDRC", "", "Binäreingang", 4),
    ("Universalschnittstelle 8fach Komfort", "", "Binäreingang", 8),
    ("TA 4 S", "4969224", "Binäreingang", 0),
    ("Tasteriengang 4fach + LED-Ausgang 4fach", "", "Binäreingang", 4),
    ("KNX pulse gateway 3 channels", "", "Binäreingang", 3),
    ("AE/S4.1.1.3 Analogue Input, 4-fold, MDRC", "", "Analogeingang", 4),
    ("Dämerungsschalter, 6 Kanal", "", "Sensor", 6),
    ("Détecteur d'ouverture radio", "", "Fensterkontakt", 0),
    ("EZ-0320.01 Energy Meter 3-fold, 20 A, direct measurement", "", "Energiezähler", 3),
    ("Meteodata 140 basic", "", "Wetterstation", 0),
    # Gateways, Schnittstellen, Systemgeräte
    ("Revox Multiuser 3.0 KNX Gateway by Weinzierl", "", "Multimedia-Gateway", 0),
    ("KNX-OT-Box S", "8559201", "Heizungs-Gateway", 0),
    ("MG/S11.100.1.1 Modbus RTU - KNX TP Gateway", "", "Modbus-KNX-Gateway", 0),
    ("EG/A32.2.1 KNX/EnOcean Gateway", "", "EnOcean-Gateway", 0),
    ("SUG/U 1.1 Split Unit Gateway", "", "Klima-KNX-Gateway", 0),
    ("IPS/S3.5.1 IP Interface Secure,MDRC", "", "KNX-Schnittstelle", 0),
    ("USB interface", "", "KNX-Schnittstelle", 0),
    ("H8236 IP touch", "", "Visualisierung / Server", 0),
    ("DG/S8.1 DALI Gateway,8-fold,MDRC", "", "DALI-Gateway", 8),
    ("LK/S4.1 Coupler, MDRC", "", "Linienkoppler", 0),
    ("Medienkoppler TP-RF (ETS5)", "", "Linienkoppler", 0),
    ("IPsecure-Router", "9070770", "IP-Router", 0),
    ("SV/S30.640.5.1 Power Supply,Diagnosis,MDRC", "", "Netzteil", 0),
    ("Wochenschaltuhr, 2 Kanal", "", "Logik / Zeit", 2),
    ("ZS 600 DCF", "600 9 200", "Logik / Zeit", 0),
    ("MT/U2.12.2 Security Terminal,2-fold,FM", "", "Sicherheit", 2),
    ("US/E1 Overvoltage protector", "", "Zubehör", 0),
])
def test_classify_real_product_names(name, order, device_type, channels):
    found = classify(name, order)
    assert found.device_type == device_type
    assert found.channels == channels


def test_unknown_product_is_other_or_follows_hint():
    assert classify("Geraet XY").device_type == "Sonstiges"
    assert classify("Geraet XY", category_hint="sensor").device_type == "Sensor"
    assert classify("Geraet XY", category_hint="actor").device_type == "Schaltaktor"


def test_com_objects_help_when_name_says_nothing():
    cos = [{"name": f"K{i}", "function_text": text} for i, text in enumerate(
        ["Kanal A: Jalousie Auf/Ab", "Kanal A: Lamelle", "Kanal B: Jalousie Auf/Ab"])]
    assert classify("XY 2", "", "", cos).device_type == "Jalousieaktor"


def test_channels_from_com_objects():
    cos = [{"name": f"K{i}", "function_text": f"Ausgang {z} Schalten"}
           for i, z in enumerate((1, 2, 3, 4))]
    assert classify("Schaltaktor XY", "", "", cos).channels == 4


def test_type_groups():
    assert type_group("Dimmaktor") == "Aktoren"
    assert type_group("Binäreingang") == "Bedienung & Sensoren"
    assert type_group("Multimedia-Gateway") == "Gateways & Schnittstellen"
    assert type_group("Unbekannt") == "Systemgeräte"


def _write_user_catalog(products):
    with open(_user_catalog_path(), "w", encoding="utf-8") as f:
        json.dump({"format": 3, "products": products}, f)


def test_existing_catalog_is_reclassified_once_but_not_edited_products():
    base = {"manufacturer": "ABB", "category": "actor", "device_type": "Schaltaktor",
            "actor_type": "Schaltaktor", "channels": 0}
    _write_user_catalog([
        {**base, "order_number": "TB/U4.4", "product_name": "Tacteo 4-fold control element"},
        {**base, "order_number": "X1", "product_name": "Tacteo 2-fold control element",
         "user_edited": True},
    ])
    svc = ProductSearchService()
    tacteo = svc.find_product("ABB", "TB/U4.4")
    assert (tacteo["category"], tacteo["device_type"], tacteo["sensor_type"],
            tacteo["actor_type"], tacteo["channels"]) == (
        "sensor", "Tastereinheit", "Tastereinheit", "", 4)
    assert svc.find_product("ABB", "X1")["device_type"] == "Schaltaktor"   # von Hand
    raw = json.load(open(_user_catalog_path(), encoding="utf-8"))
    assert all(p.get("classified") == 1 for p in raw["products"] if not p.get("user_edited"))
    # gespeichert: beim nächsten Laden keine erneute Einordnung
    mtime = os.path.getmtime(_user_catalog_path())
    ProductSearchService()
    assert os.path.getmtime(_user_catalog_path()) == mtime


def test_edit_marks_product_as_user_edited():
    svc = ProductSearchService()
    svc.add_product({"manufacturer": "ABB", "order_number": "Z1", "product_name": "Tacteo",
                     "category": "sensor", "device_type": "Tastereinheit"})
    svc.edit_product("ABB", "Z1", {"device_type": "Raumthermostat"})
    assert ProductSearchService().find_product("ABB", "Z1")["user_edited"] is True
