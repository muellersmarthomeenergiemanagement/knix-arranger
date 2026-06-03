"""
Adressblock-Schemata für GA-Generierung (FA-431 bis FA-436)
5er-Bloecke (Licht), 10er-Bloecke (Jalousie, Heizung)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BlockEntry:
    """Ein Eintrag innerhalb eines Adressblocks."""
    offset: int = 0
    function: str = ""        # z.B. "E/A", "DIM", "WERT"
    designation: str = ""     # z.B. "E/A", "DIM"
    dpt: str = ""             # z.B. "DPST-1-1"
    is_feedback: bool = False # Ist Rueckmeldung
    is_reserve: bool = False  # Reserve-Platzhalter

    def to_dict(self) -> dict:
        return {
            "offset": self.offset,
            "function": self.function,
            "designation": self.designation,
            "dpt": self.dpt,
            "is_feedback": self.is_feedback,
            "is_reserve": self.is_reserve,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BlockEntry:
        return cls(
            offset=data.get("offset", 0),
            function=data.get("function", ""),
            designation=data.get("designation", ""),
            dpt=data.get("dpt", ""),
            is_feedback=data.get("is_feedback", False),
            is_reserve=data.get("is_reserve", False),
        )


@dataclass
class AddressBlockSchema:
    """Schema für einen Adressblock (5er oder 10er)."""
    gewerk_code: str = ""     # z.B. "L", "LD", "J", "H"
    block_size: int = 5       # 5 oder 10
    entries: list[BlockEntry] = field(default_factory=list)
    middle_group: int = 0     # Standard-Mittelgruppe

    def to_dict(self) -> dict:
        return {
            "gewerk_code": self.gewerk_code,
            "block_size": self.block_size,
            "entries": [e.to_dict() for e in self.entries],
            "middle_group": self.middle_group,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AddressBlockSchema:
        schema = cls(
            gewerk_code=data.get("gewerk_code", ""),
            block_size=data.get("block_size", 5),
            middle_group=data.get("middle_group", 0),
        )
        schema.entries = [BlockEntry.from_dict(e) for e in data.get("entries", [])]
        return schema


# Vordefinierte Adressblock-Schemata (FA-431)

def create_light_block_schema_a() -> AddressBlockSchema:
    """Licht 5er-Block Variante A (inkl. RM)."""
    return AddressBlockSchema(
        gewerk_code="L",
        block_size=5,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A", "E/A", "DPST-1-1"),
            BlockEntry(1, "DIM", "DIM", "DPST-3-7"),
            BlockEntry(2, "WERT", "WERT", "DPST-5-1"),
            BlockEntry(3, "RM", "RM", "DPST-1-1", is_feedback=True),
            BlockEntry(4, "RM WERT", "RM WERT", "DPST-5-1", is_feedback=True),
        ],
    )


def create_light_block_schema_b() -> AddressBlockSchema:
    """Licht 5er-Block Variante B (ohne RM, RM in MG 6)."""
    return AddressBlockSchema(
        gewerk_code="L",
        block_size=5,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A", "E/A", "DPST-1-1"),
            BlockEntry(1, "DIM", "DIM", "DPST-3-7"),
            BlockEntry(2, "WERT", "WERT", "DPST-5-1"),
            BlockEntry(3, "", "", "", is_reserve=True),
            BlockEntry(4, "", "", "", is_reserve=True),
        ],
    )


def create_light_feedback_block_b() -> AddressBlockSchema:
    """Licht-Rueckmeldung 5er-Block für Variante B (MG 6)."""
    return AddressBlockSchema(
        gewerk_code="L",
        block_size=5,
        middle_group=6,
        entries=[
            BlockEntry(0, "RM", "RM", "DPST-1-1", is_feedback=True),
            BlockEntry(1, "", "", "", is_reserve=True),
            BlockEntry(2, "RM WERT", "RM WERT", "DPST-5-1", is_feedback=True),
            BlockEntry(3, "", "", "", is_reserve=True),
            BlockEntry(4, "", "", "", is_reserve=True),
        ],
    )


def create_jalousie_block_schema_a() -> AddressBlockSchema:
    """Jalousie 10er-Block Variante A (inkl. Status)."""
    return AddressBlockSchema(
        gewerk_code="J",
        block_size=10,
        middle_group=1,
        entries=[
            BlockEntry(0, "AUF/AB", "AUF/AB", "DPST-1-8"),
            BlockEntry(1, "STOPP", "STOPP", "DPST-1-7"),
            BlockEntry(2, "POSITION HOEHE", "POSITION HOEHE", "DPST-5-1"),
            BlockEntry(3, "POSITION LAMELLEN", "POSITION LAMELLEN", "DPST-5-1"),
            BlockEntry(4, "BESCHATTUNG", "BESCHATTUNG", "DPST-1-8"),
            BlockEntry(5, "SPERREN", "SPERREN", "DPST-1-1"),
            BlockEntry(6, "STATUS POSITION HOEHE", "STATUS POSITION HOEHE", "DPST-5-1", is_feedback=True),
            BlockEntry(7, "STATUS POSITION LAMELLEN", "STATUS POSITION LAMELLEN", "DPST-5-1", is_feedback=True),
            BlockEntry(8, "", "", "", is_reserve=True),
            BlockEntry(9, "", "", "", is_reserve=True),
        ],
    )


def create_jalousie_block_schema_b() -> AddressBlockSchema:
    """Jalousie 10er-Block Variante B (ohne Status, Status in MG 7)."""
    return AddressBlockSchema(
        gewerk_code="J",
        block_size=10,
        middle_group=1,
        entries=[
            BlockEntry(0, "AUF/AB", "AUF/AB", "DPST-1-8"),
            BlockEntry(1, "STOPP", "STOPP", "DPST-1-7"),
            BlockEntry(2, "POSITION HOEHE", "POSITION HOEHE", "DPST-5-1"),
            BlockEntry(3, "POSITION LAMELLEN", "POSITION LAMELLEN", "DPST-5-1"),
            BlockEntry(4, "BESCHATTUNG", "BESCHATTUNG", "DPST-1-8"),
            BlockEntry(5, "SPERREN", "SPERREN", "DPST-1-1"),
            BlockEntry(6, "", "", "", is_reserve=True),
            BlockEntry(7, "", "", "", is_reserve=True),
            BlockEntry(8, "", "", "", is_reserve=True),
            BlockEntry(9, "", "", "", is_reserve=True),
        ],
    )


def create_jalousie_feedback_block_b() -> AddressBlockSchema:
    """Jalousie-Rueckmeldung für Variante B (MG 7)."""
    return AddressBlockSchema(
        gewerk_code="J",
        block_size=10,
        middle_group=7,
        entries=[
            BlockEntry(0, "", "", "", is_reserve=True),
            BlockEntry(1, "", "", "", is_reserve=True),
            BlockEntry(2, "STATUS POSITION HOEHE", "STATUS POSITION HOEHE", "DPST-5-1", is_feedback=True),
            BlockEntry(3, "STATUS POSITION LAMELLEN", "STATUS POSITION LAMELLEN", "DPST-5-1", is_feedback=True),
            BlockEntry(4, "", "", "", is_reserve=True),
            BlockEntry(5, "", "", "", is_reserve=True),
            BlockEntry(6, "", "", "", is_reserve=True),
            BlockEntry(7, "", "", "", is_reserve=True),
            BlockEntry(8, "", "", "", is_reserve=True),
            BlockEntry(9, "", "", "", is_reserve=True),
        ],
    )


def create_heating_block_schema() -> AddressBlockSchema:
    """Heizung 10er-Block (identisch für A und B)."""
    return AddressBlockSchema(
        gewerk_code="H",
        block_size=10,
        middle_group=2,
        entries=[
            BlockEntry(0, "STELLGROESSE", "STELLGROESSE", "DPST-5-1"),
            BlockEntry(1, "IST", "IST", "DPST-9-1"),
            BlockEntry(2, "BASIS-SOLL", "BASIS-SOLL", "DPST-9-1"),
            BlockEntry(3, "RM AKTUELLER SOLLWERT", "RM AKTUELLER SOLLWERT", "DPST-9-1", is_feedback=True),
            BlockEntry(4, "UMSCHALTEN BETRIEBSART", "UMSCHALTEN BETRIEBSART", "DPST-20-102"),
            BlockEntry(5, "STATUS BETRIEBSART", "STATUS BETRIEBSART", "DPST-20-102", is_feedback=True),
            BlockEntry(6, "", "", "", is_reserve=True),
            BlockEntry(7, "", "", "", is_reserve=True),
            BlockEntry(8, "STOERUNG", "STOERUNG", "DPST-1-1"),
            BlockEntry(9, "SPERREN", "SPERREN", "DPST-1-1"),
        ],
    )


def create_dali_block_schema() -> AddressBlockSchema:
    """DALI-Licht 10er-Block (LDA)."""
    return AddressBlockSchema(
        gewerk_code="LDA",
        block_size=10,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A",      "E/A",      "DPST-1-1"),
            BlockEntry(1, "DIM",      "DIM",      "DPST-3-7"),
            BlockEntry(2, "WERT",     "WERT",     "DPST-5-1"),
            BlockEntry(3, "RM",       "RM",       "DPST-1-1", is_feedback=True),
            BlockEntry(4, "RM WERT",  "RM WERT",  "DPST-5-1", is_feedback=True),
            BlockEntry(5, "SZENE",    "SZENE",    "DPST-18-1"),
            BlockEntry(6, "",         "",         "", is_reserve=True),
            BlockEntry(7, "",         "",         "", is_reserve=True),
            BlockEntry(8, "STOERUNG", "STOERUNG", "DPST-1-1"),
            BlockEntry(9, "SPERREN",  "SPERREN",  "DPST-1-1"),
        ],
    )


def create_lc_block_schema() -> AddressBlockSchema:
    """Licht Farbe RGB 10er-Block (LC). DPT 232.600 fuer RGB-Farbwert."""
    return AddressBlockSchema(
        gewerk_code="LC",
        block_size=10,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A",       "E/A",       "DPST-1-1"),
            BlockEntry(1, "DIM",       "DIM",       "DPST-3-7"),
            BlockEntry(2, "FARBE RGB", "FARBE RGB", "DPST-232-600"),
            BlockEntry(3, "HELLIGKEIT","HELLIGKEIT", "DPST-5-1"),
            BlockEntry(4, "RM",        "RM",        "DPST-1-1",    is_feedback=True),
            BlockEntry(5, "RM WERT",   "RM WERT",   "DPST-5-1",    is_feedback=True),
            BlockEntry(6, "RM FARBE",  "RM FARBE",  "DPST-232-600",is_feedback=True),
            BlockEntry(7, "SZENE",     "SZENE",     "DPST-18-1"),
            BlockEntry(8, "STOERUNG",  "STOERUNG",  "DPST-1-1"),
            BlockEntry(9, "SPERREN",   "SPERREN",   "DPST-1-1"),
        ],
    )


def create_lct_block_schema() -> AddressBlockSchema:
    """Licht Tunable White 10er-Block (LCT). DPT 7.600 fuer Farbtemperatur (Kelvin)."""
    return AddressBlockSchema(
        gewerk_code="LCT",
        block_size=10,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A",           "E/A",           "DPST-1-1"),
            BlockEntry(1, "DIM",           "DIM",           "DPST-3-7"),
            BlockEntry(2, "HELLIGKEIT",    "HELLIGKEIT",    "DPST-5-1"),
            BlockEntry(3, "FARBTEMPERATUR","FARBTEMPERATUR","DPT-7-600"),
            BlockEntry(4, "RM",            "RM",            "DPST-1-1",  is_feedback=True),
            BlockEntry(5, "RM HELL",       "RM HELL",       "DPST-5-1",  is_feedback=True),
            BlockEntry(6, "RM CCT",        "RM CCT",        "DPT-7-600", is_feedback=True),
            BlockEntry(7, "SZENE",         "SZENE",         "DPST-18-1"),
            BlockEntry(8, "STOERUNG",      "STOERUNG",      "DPST-1-1"),
            BlockEntry(9, "SPERREN",       "SPERREN",       "DPST-1-1"),
        ],
    )


def create_lcw_block_schema() -> AddressBlockSchema:
    """Licht Farbe RGBW 10er-Block (LCW). DPT 251.600 fuer RGBW-Farbwert."""
    return AddressBlockSchema(
        gewerk_code="LCW",
        block_size=10,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A",        "E/A",        "DPST-1-1"),
            BlockEntry(1, "DIM",        "DIM",        "DPST-3-7"),
            BlockEntry(2, "FARBE RGBW", "FARBE RGBW", "DPST-251-600"),
            BlockEntry(3, "HELLIGKEIT", "HELLIGKEIT",  "DPST-5-1"),
            BlockEntry(4, "RM",         "RM",         "DPST-1-1",     is_feedback=True),
            BlockEntry(5, "RM WERT",    "RM WERT",    "DPST-5-1",     is_feedback=True),
            BlockEntry(6, "RM FARBE",   "RM FARBE",   "DPST-251-600", is_feedback=True),
            BlockEntry(7, "SZENE",      "SZENE",      "DPST-18-1"),
            BlockEntry(8, "STOERUNG",   "STOERUNG",   "DPST-1-1"),
            BlockEntry(9, "SPERREN",    "SPERREN",    "DPST-1-1"),
        ],
    )


def create_dmx_block_schema() -> AddressBlockSchema:
    """DMX-Gateway 10er-Block. Wie LC-RGB mit DMX-Szenen-Steuerung."""
    return AddressBlockSchema(
        gewerk_code="DMX",
        block_size=10,
        middle_group=0,
        entries=[
            BlockEntry(0, "E/A",       "E/A",       "DPST-1-1"),
            BlockEntry(1, "DIM",       "DIM",       "DPST-3-7"),
            BlockEntry(2, "FARBE RGB", "FARBE RGB", "DPST-232-600"),
            BlockEntry(3, "HELLIGKEIT","HELLIGKEIT", "DPST-5-1"),
            BlockEntry(4, "RM",        "RM",        "DPST-1-1",    is_feedback=True),
            BlockEntry(5, "RM WERT",   "RM WERT",   "DPST-5-1",    is_feedback=True),
            BlockEntry(6, "",          "",          "",            is_reserve=True),
            BlockEntry(7, "SZENE",     "SZENE",     "DPST-18-1"),
            BlockEntry(8, "STOERUNG",  "STOERUNG",  "DPST-1-1"),
            BlockEntry(9, "SPERREN",   "SPERREN",   "DPST-1-1"),
        ],
    )


def create_lueftung_block_schema() -> AddressBlockSchema:
    """Lueftung/KWL Gateway 10er-Block (LU)."""
    return AddressBlockSchema(
        gewerk_code="LU",
        block_size=10,
        middle_group=5,
        entries=[
            BlockEntry(0, "BETRIEBSART",        "BETRIEBSART",        "DPST-5-1"),
            BlockEntry(1, "STUFE",              "STUFE",              "DPST-5-1"),
            BlockEntry(2, "BYPASS",             "BYPASS",             "DPST-1-1"),
            BlockEntry(3, "SPERREN",            "SPERREN",            "DPST-1-1"),
            BlockEntry(4, "STATUS BETRIEBSART", "STATUS BETRIEBSART", "DPST-5-1",  is_feedback=True),
            BlockEntry(5, "STATUS STUFE",       "STATUS STUFE",       "DPST-5-1",  is_feedback=True),
            BlockEntry(6, "CO2",                "CO2",                "DPT-9-8",   is_feedback=True),
            BlockEntry(7, "FEUCHTE",            "FEUCHTE",            "DPT-9-7",   is_feedback=True),
            BlockEntry(8, "STOERUNG",           "STOERUNG",           "DPST-1-1"),
            BlockEntry(9, "FILTER",             "FILTER",             "DPST-1-1"),
        ],
    )


def create_kl_block_schema() -> AddressBlockSchema:
    """Klimageraet/Split-AC Gateway 10er-Block (KL). DPT 20.105 HVAC-Modus."""
    return AddressBlockSchema(
        gewerk_code="KL",
        block_size=10,
        middle_group=5,
        entries=[
            BlockEntry(0, "E/A",              "E/A",              "DPST-1-1"),
            BlockEntry(1, "BETRIEBSART",      "BETRIEBSART",      "DPT-20-105"),
            BlockEntry(2, "SOLLWERT",         "SOLLWERT",         "DPT-9-1"),
            BlockEntry(3, "SPERREN",          "SPERREN",          "DPST-1-1"),
            BlockEntry(4, "IST",              "IST",              "DPT-9-1",    is_feedback=True),
            BlockEntry(5, "STATUS BETRIEB",   "STATUS BETRIEB",   "DPT-20-105", is_feedback=True),
            BlockEntry(6, "RM SOLLWERT",      "RM SOLLWERT",      "DPT-9-1",    is_feedback=True),
            BlockEntry(7, "VENTILATOR",       "VENTILATOR",       "DPST-5-1"),
            BlockEntry(8, "STOERUNG",         "STOERUNG",         "DPST-1-1"),
            BlockEntry(9, "",                 "",                 "",           is_reserve=True),
        ],
    )


def create_ev_block_schema() -> AddressBlockSchema:
    """E-Mobilitaet Wallbox Gateway 10er-Block (EV)."""
    return AddressBlockSchema(
        gewerk_code="EV",
        block_size=10,
        middle_group=6,
        entries=[
            BlockEntry(0, "FREIGABE",        "FREIGABE",        "DPST-1-1"),
            BlockEntry(1, "LADELEISTUNG SOLL","LADELEISTUNG SOLL","DPT-9-1"),
            BlockEntry(2, "MODUS",           "MODUS",           "DPST-5-1"),
            BlockEntry(3, "SPERREN",         "SPERREN",         "DPST-1-1"),
            BlockEntry(4, "STATUS",          "STATUS",          "DPST-1-1",  is_feedback=True),
            BlockEntry(5, "LADELEISTUNG IST","LADELEISTUNG IST","DPT-9-1",   is_feedback=True),
            BlockEntry(6, "ENERGIE",         "ENERGIE",         "DPT-9-1",   is_feedback=True),
            BlockEntry(7, "LADESTAND",       "LADESTAND",       "DPST-5-1",  is_feedback=True),
            BlockEntry(8, "STOERUNG",        "STOERUNG",        "DPST-1-1"),
            BlockEntry(9, "",                "",                "",          is_reserve=True),
        ],
    )


def create_pv_block_schema() -> AddressBlockSchema:
    """Photovoltaik Gateway 10er-Block (PV)."""
    return AddressBlockSchema(
        gewerk_code="PV",
        block_size=10,
        middle_group=6,
        entries=[
            BlockEntry(0, "FREIGABE",     "FREIGABE",     "DPST-1-1"),
            BlockEntry(1, "LIMIT",        "LIMIT",        "DPST-5-1"),
            BlockEntry(2, "",             "",             "", is_reserve=True),
            BlockEntry(3, "",             "",             "", is_reserve=True),
            BlockEntry(4, "LEISTUNG IST", "LEISTUNG IST", "DPT-9-1",  is_feedback=True),
            BlockEntry(5, "ERTRAG TAG",   "ERTRAG TAG",   "DPT-9-1",  is_feedback=True),
            BlockEntry(6, "ERTRAG GESAMT","ERTRAG GESAMT","DPT-9-1",  is_feedback=True),
            BlockEntry(7, "EINSPEISUNG",  "EINSPEISUNG",  "DPT-9-1",  is_feedback=True),
            BlockEntry(8, "STOERUNG",     "STOERUNG",     "DPST-1-1"),
            BlockEntry(9, "",             "",             "", is_reserve=True),
        ],
    )


def create_sp_block_schema() -> AddressBlockSchema:
    """Stromspeicher/Batterie Gateway 10er-Block (SP)."""
    return AddressBlockSchema(
        gewerk_code="SP",
        block_size=10,
        middle_group=6,
        entries=[
            BlockEntry(0, "FREIGABE",       "FREIGABE",       "DPST-1-1"),
            BlockEntry(1, "LADEMODUS",      "LADEMODUS",      "DPST-5-1"),
            BlockEntry(2, "",               "",               "", is_reserve=True),
            BlockEntry(3, "",               "",               "", is_reserve=True),
            BlockEntry(4, "SOC",            "SOC",            "DPST-5-1",  is_feedback=True),
            BlockEntry(5, "LADELEISTUNG",   "LADELEISTUNG",   "DPT-9-1",  is_feedback=True),
            BlockEntry(6, "ENTLADELEISTUNG","ENTLADELEISTUNG","DPT-9-1",  is_feedback=True),
            BlockEntry(7, "STATUS",         "STATUS",         "DPST-1-1", is_feedback=True),
            BlockEntry(8, "STOERUNG",       "STOERUNG",       "DPST-1-1"),
            BlockEntry(9, "",               "",               "", is_reserve=True),
        ],
    )


def create_generic_5_block_schema(gewerk_code: str, middle_group: int = 4) -> AddressBlockSchema:
    """Generischer 5er-Block für sonstige Gewerke (FA-436)."""
    return AddressBlockSchema(
        gewerk_code=gewerk_code,
        block_size=5,
        middle_group=middle_group,
        entries=[
            BlockEntry(0, "E/A", "E/A", "DPST-1-1"),
            BlockEntry(1, "WERT", "WERT", "DPST-5-1"),
            BlockEntry(2, "RM", "RM", "DPST-1-1", is_feedback=True),
            BlockEntry(3, "", "", "", is_reserve=True),
            BlockEntry(4, "", "", "", is_reserve=True),
        ],
    )


def create_generic_10_block_schema(gewerk_code: str, middle_group: int = 4) -> AddressBlockSchema:
    """Generischer 10er-Block für Gewerke mit 10 GA."""
    return AddressBlockSchema(
        gewerk_code=gewerk_code,
        block_size=10,
        middle_group=middle_group,
        entries=[
            BlockEntry(0, "E/A", "E/A", "DPST-1-1"),
            BlockEntry(1, "WERT 1", "WERT 1", "DPST-5-1"),
            BlockEntry(2, "WERT 2", "WERT 2", "DPST-5-1"),
            BlockEntry(3, "RM", "RM", "DPST-1-1", is_feedback=True),
            BlockEntry(4, "RM WERT", "RM WERT", "DPST-5-1", is_feedback=True),
            BlockEntry(5, "STATUS", "STATUS", "DPST-1-1", is_feedback=True),
            BlockEntry(6, "", "", "", is_reserve=True),
            BlockEntry(7, "", "", "", is_reserve=True),
            BlockEntry(8, "STOERUNG", "STOERUNG", "DPST-1-1"),
            BlockEntry(9, "SPERREN", "SPERREN", "DPST-1-1"),
        ],
    )
