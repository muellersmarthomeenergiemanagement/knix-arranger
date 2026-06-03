"""
Gruppenadress-Generierung - KERN-ENGINE (FA-400)
Generiert vollstaendige GA-Struktur basierend auf Gebäudestruktur,
Topologie und Gewerken.

Referenz: Pflichtenheft Anhang A
"""
from __future__ import annotations
import copy
import logging
from ..models.building import Areal, Floor, Room, GewerkAssignment
from ..models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
    MIDDLE_GROUP_NAMES_A, MIDDLE_GROUP_NAMES_B, CENTRAL_MIDDLE_GROUPS,
)
from ..models.gewerk import GewerkCatalog, Gewerk
from ..models.address_block import (
    AddressBlockSchema, BlockEntry,
    create_light_block_schema_a, create_light_block_schema_b,
    create_light_feedback_block_b,
    create_jalousie_block_schema_a, create_jalousie_block_schema_b,
    create_jalousie_feedback_block_b,
    create_heating_block_schema,
    create_dali_block_schema,
    create_lc_block_schema, create_lct_block_schema, create_lcw_block_schema,
    create_dmx_block_schema,
    create_lueftung_block_schema, create_kl_block_schema,
    create_ev_block_schema, create_pv_block_schema, create_sp_block_schema,
    create_generic_5_block_schema, create_generic_10_block_schema,
)
from .naming_engine import NamingEngine

logger = logging.getLogger("knix_arranger.address_generator")


class AddressGenerator:
    """
    Generiert KNX-Gruppenadressen nach KNX Swiss Richtlinien.
    Unterstuetzt Variante A und B.
    """

    def __init__(self, catalog: GewerkCatalog, variant: str = "A"):
        self.catalog = catalog
        self.variant = variant  # "A" oder "B"

    def generate(self, areal: Areal, scenes: list | None = None,
                 project=None) -> GroupAddressStructure:
        """
        Generiert die vollstaendige Gruppenadress-Struktur.

        HG 0 = Zentraladressen (inkl. Szenen-GAs und ggf. Astro-GAs)
        HG 1+ = Stockwerke aufsteigend (FA-411)

        Stockwerke mit gleicher HG-Nummer werden zusammengeführt,
        um doppelte Adressen zu vermeiden.

        Args:
            project: Optional – wird für FA-3308 Astro-GA-Erkennung verwendet.
        """
        structure = GroupAddressStructure(variant=self.variant)

        # Prüfen ob Astro-SwitchPoints vorhanden (FA-3308)
        has_astro = False
        if project is not None:
            from .time_program_service import has_astro_switch_points
            has_astro = has_astro_switch_points(project)

        # HG 0: Zentraladressen + Szenen (+ Astro-GAs wenn vorhanden)
        central_hg = self._create_central_main_group(scenes or [], has_astro=has_astro)
        structure.main_groups.append(central_hg)

        # Stockwerke nach HG-Nummer gruppieren (verhindert Duplikate)
        floors_by_hg: dict[int, list[Floor]] = {}
        for floor in areal.all_floors:
            hg_number = floor.main_group_number
            if hg_number <= 0:
                continue
            if hg_number not in floors_by_hg:
                floors_by_hg[hg_number] = []
            floors_by_hg[hg_number].append(floor)

        # Projektweite Mehrzonenprüfung: Zone/Wohnung im Klartext anzeigen,
        # wenn das Projekt mehr als eine Zone hat – unabhängig davon, ob ein
        # einzelnes Stockwerk nur eine Zone hat.
        is_multi_zone = areal.is_multi_zone

        # Pro HG-Nummer eine MainGroup generieren
        for hg_number in sorted(floors_by_hg.keys()):
            floors = floors_by_hg[hg_number]
            # Name: Alle Stockwerk-Namen zusammensetzen
            hg_name = " / ".join(f.name for f in floors)
            main_group = self._generate_merged_floor_addresses(
                floors, hg_number, hg_name, is_multi_zone=is_multi_zone,
            )
            structure.main_groups.append(main_group)

        return structure

    def _generate_merged_floor_addresses(
        self, floors: list[Floor], hg_number: int, hg_name: str,
        is_multi_zone: bool = False,
    ) -> MainGroup:
        """Generiert Adressen für eine oder mehrere Stockwerke mit gleicher HG."""
        hg = MainGroup(number=hg_number, name=hg_name)

        mg_names = (MIDDLE_GROUP_NAMES_A if self.variant == "A"
                    else MIDDLE_GROUP_NAMES_B)

        # is_multi_apt: lokal – entscheidet ob Raumnummer mit Wohnungsname prefixiert wird
        is_multi_apt = any(len(f.apartments) > 1 for f in floors)

        # Alle Raumnummern sammeln um Duplikate zu erkennen
        all_room_numbers: list[str] = [
            room.number
            for floor in floors
            for apt in floor.apartments
            for room in apt.rooms
        ]
        duplicate_numbers = {
            n for n in all_room_numbers if all_room_numbers.count(n) > 1
        }

        # Sammle alle Gewerk-Zuweisungen ueber alle Stockwerke (mit Apartment-Kontext)
        mg_data: dict[int, list[tuple[Room, GewerkAssignment, Gewerk, str, str]]] = {}

        for floor in floors:
            for apt in floor.apartments:
                for room in apt.rooms:
                    for ga in room.gewerk_assignments:
                        gewerk = self.catalog.get(ga.gewerk_code)
                        if not gewerk:
                            logger.warning(f"Unbekanntes Gewerk: {ga.gewerk_code}")
                            continue
                        mg = gewerk.middle_group
                        if mg not in mg_data:
                            mg_data[mg] = []
                        # Bei doppelter Raumnummer: Wohnungsname als Prefix
                        if room.number in duplicate_numbers:
                            room_number_ga = f"{apt.name}-{room.number}"
                        else:
                            room_number_ga = room.number
                        # Beschreibung: bei mehreren Zonen im Projekt immer Zonenname voranstellen
                        room_desc = (
                            f"{apt.name} / {room.name}"
                            if is_multi_zone else room.name
                        )
                        mg_data[mg].append((room, ga, gewerk, room_number_ga, room_desc))

        # Pro Mittelgruppe die Adressen generieren
        for mg_num in sorted(mg_data.keys()):
            mg = MiddleGroup(
                number=mg_num,
                name=mg_names.get(mg_num, f"MG {mg_num}"),
            )
            sub_counter = 0

            for room, assignment, gewerk, room_number_ga, room_desc in mg_data[mg_num]:
                for element_nr in range(1, assignment.count + 1):
                    schema = self._get_block_schema(gewerk, assignment=assignment, is_feedback=False)
                    sub_counter = self._generate_block(
                        mg, schema, hg_number, mg_num, sub_counter,
                        gewerk.code, room_number_ga, element_nr,
                        room_desc, room.id,
                    )
                    if sub_counter > 256:
                        logger.warning(
                            f"HG {hg_number} MG {mg_num}: "
                            f"UG-Zähler {sub_counter - 1} überschreitet Maximum 255 "
                            f"(Raum {room.number}, Gewerk {gewerk.code}). "
                            f"Gruppenadresse ungültig – Linie aufteilen oder Gewerke reduzieren."
                        )

            hg.middle_groups.append(mg)

            # Variante B: Rückmeldungen in separaten MGs
            if self.variant == "B" and mg_num in (0, 1):
                fb_mg_num = 6 if mg_num == 0 else 7
                fb_mg = MiddleGroup(
                    number=fb_mg_num,
                    name=mg_names.get(fb_mg_num, f"MG {fb_mg_num}"),
                )
                sub_counter_fb = 0

                for room, assignment, gewerk, room_number_ga, room_desc in mg_data[mg_num]:
                    for element_nr in range(1, assignment.count + 1):
                        fb_schema = self._get_block_schema(
                            gewerk, is_feedback=True,
                        )
                        if fb_schema:
                            sub_counter_fb = self._generate_block(
                                fb_mg, fb_schema, hg_number, fb_mg_num,
                                sub_counter_fb,
                                gewerk.code, room_number_ga, element_nr,
                                room_desc, room.id,
                            )
                            if sub_counter_fb > 256:
                                logger.warning(
                                    f"HG {hg_number} MG {fb_mg_num} (Rückmeldung): "
                                    f"UG-Zähler {sub_counter_fb - 1} überschreitet Maximum 255 "
                                    f"(Raum {room.number}, Gewerk {gewerk.code})."
                                )

                if fb_mg.group_addresses:
                    hg.middle_groups.append(fb_mg)

        return hg

    def _create_central_main_group(self, scenes: list,
                                    has_astro: bool = False) -> MainGroup:
        """Erstellt HG 0 mit Zentraladressen, Szenen und ggf. Astro-GAs (FA-441, FA-3308)."""
        hg = MainGroup(number=0, name="Zentraladressen")

        # MG 0: Zentral Licht (ab sub_group=1, da 0/0/0 Systemadresse, FA-444/GA-08)
        mg_licht = MiddleGroup(number=0, name="Licht")
        mg_licht.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=1,
            designation="ZENTRAL Alle Lichter AUS",
            datapoint_type="DPST-1-1", central="true",
            gewerk_code="L", function_name="E/A",
        ))
        mg_licht.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=2,
            designation="ZENTRAL Alle Lichter EIN (Panik)",
            datapoint_type="DPST-1-1", central="true",
            gewerk_code="L", function_name="E/A",
        ))
        hg.middle_groups.append(mg_licht)

        # MG 1: Zentral Jalousie (ab sub_group=1)
        mg_jalousie = MiddleGroup(number=1, name="Jalousie")
        mg_jalousie.group_addresses.append(GroupAddress(
            main_group=0, middle_group=1, sub_group=1,
            designation="ZENTRAL Alle Jalousien AUF",
            datapoint_type="DPST-1-8", central="true",
            gewerk_code="J", function_name="AUF/AB",
        ))
        mg_jalousie.group_addresses.append(GroupAddress(
            main_group=0, middle_group=1, sub_group=2,
            designation="ZENTRAL Beschattung",
            datapoint_type="DPST-1-8", central="true",
            gewerk_code="J", function_name="BESCHATTUNG",
        ))
        hg.middle_groups.append(mg_jalousie)

        # MG 2: Zentral Heizung – nur hinzufügen wenn GAs vorhanden
        # (aktuell keine vordefinierten Zentral-Heizungs-GAs)
        mg_heizung = MiddleGroup(number=2, name="Heizung")
        if mg_heizung.group_addresses:
            hg.middle_groups.append(mg_heizung)

        # MG 4: Szenen – eine feste Zentral-GA + eine GA pro Projekt-Szene
        mg_szenen = MiddleGroup(number=4, name="Szenen")
        mg_szenen.group_addresses.append(GroupAddress(
            main_group=0, middle_group=4, sub_group=1,
            designation="ZENTRAL Szene Abwesenheit",
            datapoint_type="DPST-17-1", central="true",
            function_name="SZENE",
        ))
        sub = 2
        for scene in scenes:
            if not scene.name:
                continue
            designation = self._scene_designation(scene)
            mg_szenen.group_addresses.append(GroupAddress(
                main_group=0, middle_group=4, sub_group=sub,
                designation=designation,
                datapoint_type="DPST-17-1", central="true",
                function_name="SZENE",
            ))
            sub += 1
            if sub > 255:
                logger.warning("Mehr als 254 Szenen – UG-Grenze erreicht.")
                break
        hg.middle_groups.append(mg_szenen)

        # MG 7: Astro-Gruppen (FA-3308) – nur wenn Astro-SwitchPoints vorhanden
        if has_astro:
            mg_astro = MiddleGroup(number=7, name="Astro")
            _ASTRO_GAS = [
                (0, "SYS.ASTRO.00_utc",  "Uhrzeit und Datum", "ASTRO_TIME", "DPT-19-1"),
                (1, "SYS.ASTRO.01_rise", "Sonnenaufgang",     "ASTRO",      "DPST-1-1"),
                (2, "SYS.ASTRO.02_set",  "Sonnenuntergang",   "ASTRO",      "DPST-1-1"),
                (3, "SYS.ASTRO.03_dusk", "Daemmerung aktiv",  "ASTRO",      "DPST-1-1"),
            ]
            for sub, designation, description, func, dpt in _ASTRO_GAS:
                mg_astro.group_addresses.append(GroupAddress(
                    main_group=0, middle_group=7, sub_group=sub,
                    designation=designation,
                    function_name=func,
                    description=description,
                    datapoint_type=dpt,
                    central="true",
                ))
            hg.middle_groups.append(mg_astro)
            logger.info("HG 0 / MG 7: Astro-GAs angelegt (FA-3308).")

        return hg

    @staticmethod
    def _scene_designation(scene) -> str:
        """Erzeugt die GA-Bezeichnung für eine Projekt-Szene."""
        if scene.scene_number > 0:
            return f"SZENE {scene.scene_number:02d} {scene.name}"
        return f"SZENE {scene.name}"

    def _get_block_schema(self, gewerk: Gewerk,
                          assignment: GewerkAssignment | None = None,
                          is_feedback: bool = False) -> AddressBlockSchema | None:
        """Gibt das passende Adressblock-Schema zurück.

        Wenn assignment.extra_entries gesetzt sind, werden diese an den
        Standard-Block angehängt (nur für den Vorwärts-Block, nicht Rückmeldung).
        """
        category = gewerk.category

        if is_feedback:
            # Nur für Variante B
            if category == "licht":
                return create_light_feedback_block_b()
            elif category == "jalousie":
                return create_jalousie_feedback_block_b()
            return None

        # Spezifische Schemata nach Gewerk-Code (Vorrang vor Kategorie)
        _CODE_SCHEMA = {
            "LDA": create_dali_block_schema,
            "LC":  create_lc_block_schema,
            "LCT": create_lct_block_schema,
            "LCW": create_lcw_block_schema,
            "DMX": create_dmx_block_schema,
            "LU":  create_lueftung_block_schema,
            "KL":  create_kl_block_schema,
            "EV":  create_ev_block_schema,
            "PV":  create_pv_block_schema,
            "SP":  create_sp_block_schema,
        }
        if gewerk.code in _CODE_SCHEMA:
            schema = _CODE_SCHEMA[gewerk.code]()
        elif category == "licht":
            if self.variant == "A":
                schema = create_light_block_schema_a()
            else:
                schema = create_light_block_schema_b()
        elif category == "licht_color":
            schema = create_lc_block_schema()   # Fallback für unbekannte Farbgewerke
        elif category == "jalousie":
            if self.variant == "A":
                schema = create_jalousie_block_schema_a()
            else:
                schema = create_jalousie_block_schema_b()
        elif category == "heizung":
            schema = create_heating_block_schema()
        elif category == "lueftung":
            schema = create_lueftung_block_schema()
        elif gewerk.block_size == 10:
            schema = create_generic_10_block_schema(gewerk.code, gewerk.middle_group)
        else:
            schema = create_generic_5_block_schema(gewerk.code, gewerk.middle_group)

        # Zuweigungs-spezifische Extra-Einträge anhängen
        if assignment and assignment.extra_entries:
            schema = copy.deepcopy(schema)
            for e in assignment.extra_entries:
                from ..models.address_block import BlockEntry
                entry = BlockEntry.from_dict(e)
                entry.offset = schema.block_size
                schema.entries.append(entry)
                schema.block_size += 1

        return schema

    def _generate_block(self, mg: MiddleGroup, schema: AddressBlockSchema,
                        hg_number: int, mg_number: int, sub_start: int,
                        gewerk_code: str, room_number: str,
                        element_number: int,
                        room_name: str = "", room_id: str = "") -> int:
        """
        Generiert einen Block von Gruppenadressen.
        Gibt den naechsten freien sub_group-Wert zurück.
        """
        for entry in schema.entries:
            sub = sub_start + entry.offset

            if entry.is_reserve or not entry.function:
                # Platzhalter/Reserve (FA-434)
                ga = GroupAddress(
                    main_group=hg_number,
                    middle_group=mg_number,
                    sub_group=sub,
                    designation=NamingEngine.create_placeholder_designation(),
                    is_placeholder=True,
                )
            else:
                desc = room_name if entry.offset == 0 and room_name else ""
                designation = NamingEngine.create_designation(
                    gewerk_code, room_number, element_number,
                    entry.function, desc,
                )
                ga = GroupAddress(
                    main_group=hg_number,
                    middle_group=mg_number,
                    sub_group=sub,
                    designation=designation,
                    datapoint_type=entry.dpt,
                    gewerk_code=gewerk_code,
                    room_number=room_number,
                    room_id=room_id,
                    element_number=element_number,
                    function_name=entry.function,
                )

            mg.group_addresses.append(ga)

        return sub_start + schema.block_size
