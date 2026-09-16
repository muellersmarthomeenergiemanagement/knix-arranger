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
    create_w_block_schema, create_wp_block_schema, create_mm_block_schema,
    create_generic_5_block_schema, create_generic_10_block_schema,
)
from .naming_engine import NamingEngine
from .scene_addressing import group_named_scenes, scene_value_mapping_text
import re

logger = logging.getLogger("knix_arranger.address_generator")

_DPT_DOT_RE = re.compile(r"^(DPST?)-(\d+)\.(\d+)$")


def _normalize_dpt(dpt: str) -> str:
    """Normalisiert KNXPROD-DPT-Notation ("DPST-5.001") auf internes Format ("DPST-5-1")."""
    m = _DPT_DOT_RE.match(dpt.strip())
    if m:
        return f"{m.group(1)}-{m.group(2)}-{int(m.group(3))}"
    return dpt


def _com_object_needs_ga(co: dict) -> bool:
    """Repliziert ComObjectInfo.needs_ga auf einem serialisierten ComObject-Dict."""
    return co.get("communication_flag", True) and (
        co.get("write_flag", False)
        or co.get("transmit_flag", False)
        or co.get("read_flag", False)
        or co.get("update_flag", False)
    )


def _com_object_function_name(co: dict) -> str:
    """Leitet eine GA-Funktionsbezeichnung aus einem ComObject-Dict ab."""
    name = (co.get("function_text") or co.get("name") or "").strip()
    if len(name) > 40:
        name = name[:40].strip()
    return name


# Pseudo-Gewerk für Taster-Zusatzsensorik (Bedienelement.linked_product,
# z.B. eingebauter Temperaturfühler einer Tastereinheit). Bewusst NICHT in
# gewerke_catalog.json registriert, damit es nicht als manuell zuweisbares
# Gewerk in Schritt 5s "Gewerk hinzufügen"-Dropdown auftaucht – es wird nur
# intern synthetisiert, wenn ein Bedienelement ein Produkt mit ausgewählten
# ComObjects hat.
_BEDIENELEMENT_GEWERK = Gewerk(
    code="TS", name="Taster-Zusatzsensorik", ga_count=5, block_size=5,
    middle_group=4, category="allgemein", interface_type="system_sensor",
)


class AddressGenerator:
    """
    Generiert KNX-Gruppenadressen nach KNX Swiss Richtlinien.
    Unterstuetzt Variante A und B.
    """

    def __init__(self, catalog: GewerkCatalog, variant: str = "A"):
        self.catalog = catalog
        self.variant = variant  # "A" oder "B"

    def generate(self, areal: Areal, scenes: list | None = None,
                 project=None,
                 existing: GroupAddressStructure | None = None) -> GroupAddressStructure:
        """
        Generiert die vollstaendige Gruppenadress-Struktur.

        HG 0 = Zentraladressen (inkl. Szenen-GAs und ggf. Astro-GAs)
        HG 1+ = Stockwerke aufsteigend (FA-411)

        Stockwerke mit gleicher HG-Nummer werden zusammengeführt,
        um doppelte Adressen zu vermeiden.

        Args:
            project: Optional – wird für FA-3308 Astro-GA-Erkennung verwendet.
            existing: Optional – bisherige Struktur. Wenn gesetzt (und gleiche
                Variante), bleiben unveränderte Gewerk-Zuweisungsblöcke an
                ihrer Position (sub_group, id) erhalten; geänderte/neue Blöcke
                werden ans Ende der jeweiligen Mittelgruppe angehängt statt
                die gesamte Struktur neu durchzunummerieren.
        """
        if existing is not None and existing.variant != self.variant:
            existing = None  # Variantenwechsel erzwingt vollständige Neuordnung

        structure = GroupAddressStructure(variant=self.variant)

        # Prüfen ob Astro-SwitchPoints vorhanden (FA-3308)
        has_astro = False
        if project is not None:
            from .time_program_service import has_astro_switch_points
            has_astro = has_astro_switch_points(project)

        # HG 0: Zentraladressen + Szenen (+ Astro-GAs wenn vorhanden)
        central_hg = self._create_central_main_group(
            scenes or [], has_astro=has_astro, areal=areal, warnings=structure.warnings,
        )
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
                existing=existing, warnings=structure.warnings,
            )
            structure.main_groups.append(main_group)

        return structure

    @staticmethod
    def _index_existing_hg(
        existing: GroupAddressStructure | None, hg_number: int,
    ) -> tuple[dict[str, list[GroupAddress]], dict[int, int]]:
        """Liefert (assignment_id -> alle zugehörigen GAs über MG-Grenzen
        hinweg, mg_number -> nächste freie sub_group) für die passende HG in
        `existing` (falls vorhanden). Die assignment_id-Zuordnung ist über
        die gesamte HG hinweg eindeutig, nicht auf eine einzelne MG
        beschränkt, damit ein zuvor auf mehrere Mittelgruppen verteilter
        Block (Überlauf) als Ganzes wiedererkannt wird."""
        by_assignment: dict[str, list[GroupAddress]] = {}
        next_free: dict[int, int] = {}
        if existing is not None:
            hg = next((h for h in existing.main_groups if h.number == hg_number), None)
            if hg is not None:
                for mg in hg.middle_groups:
                    max_sub = -1
                    for ga in mg.group_addresses:
                        max_sub = max(max_sub, ga.sub_group)
                        if ga.assignment_id:
                            by_assignment.setdefault(ga.assignment_id, []).append(ga)
                    if mg.group_addresses:
                        next_free[mg.number] = max_sub + 1
        for gas in by_assignment.values():
            gas.sort(key=lambda g: (g.middle_group, g.sub_group))
        return by_assignment, next_free

    def _fill_entry_fields(self, ga: GroupAddress, entry: BlockEntry,
                           gewerk_code: str, room_number: str,
                           element_number: int, room_name: str,
                           room_id: str) -> None:
        """Setzt die inhaltlichen Felder einer GA gemäß Schema-Entry.
        Position (main/middle/sub_group) und id bleiben unberührt."""
        if entry.is_reserve or not entry.function:
            ga.designation = NamingEngine.create_placeholder_designation()
            ga.is_placeholder = True
            ga.datapoint_type = ""
            ga.gewerk_code = ""
            ga.room_number = ""
            ga.room_id = ""
            ga.element_number = 0
            ga.function_name = ""
        else:
            desc = room_name if entry.offset == 0 and room_name else ""
            ga.designation = NamingEngine.create_designation(
                gewerk_code, room_number, element_number,
                entry.function, desc,
            )
            ga.datapoint_type = entry.dpt
            ga.gewerk_code = gewerk_code
            ga.room_number = room_number
            ga.room_id = room_id
            ga.element_number = element_number
            ga.function_name = entry.function
            ga.is_placeholder = False

    def _update_block_in_place(self, existing_gas: list[GroupAddress],
                               schema: AddressBlockSchema, gewerk_code: str,
                               room_number: str, element_number: int,
                               room_name: str, room_id: str) -> None:
        """Aktualisiert bestehende GAs inhaltlich, ohne ihre Position/id zu ändern."""
        for ga, entry in zip(existing_gas, schema.entries):
            self._fill_entry_fields(
                ga, entry, gewerk_code, room_number, element_number,
                room_name, room_id,
            )

    def _generate_merged_floor_addresses(
        self, floors: list[Floor], hg_number: int, hg_name: str,
        is_multi_zone: bool = False,
        existing: GroupAddressStructure | None = None,
        warnings: list[str] | None = None,
    ) -> MainGroup:
        """Generiert Adressen für eine oder mehrere Stockwerke mit gleicher HG."""
        hg = MainGroup(number=hg_number, name=hg_name)
        if warnings is None:
            warnings = []

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

                    for ga in room.gewerk_assignments:
                        gewerk = self.catalog.get(ga.gewerk_code)
                        if not gewerk:
                            logger.warning(f"Unbekanntes Gewerk: {ga.gewerk_code}")
                            continue
                        mg_data.setdefault(gewerk.middle_group, []).append(
                            (room, ga, gewerk, room_number_ga, room_desc)
                        )

                    # Taster-Zusatzsensorik (z.B. eingebauter Temperaturfühler):
                    # jedes nicht unterdrückte Bedienelement mit verknüpftem
                    # Produkt und mindestens einem ausgewählten GA-relevanten
                    # ComObject bekommt einen eigenen Pseudo-Block unter "TS",
                    # ohne die Gewerk-Blockschemata dieses Raums zu berühren.
                    te_counter = 0
                    for be in room.bedienelemente:
                        if be.suppressed or not be.linked_product:
                            continue
                        co_list = be.linked_product.get("com_objects") or []
                        excluded = set(be.linked_product.get("excluded_co_numbers") or [])
                        if not any(
                            _com_object_needs_ga(co) and co.get("number") not in excluded
                            for co in co_list
                        ):
                            continue
                        te_counter += 1
                        pseudo = GewerkAssignment(
                            gewerk_code=_BEDIENELEMENT_GEWERK.code, count=1,
                            linked_product=be.linked_product,
                        )
                        pseudo.id = f"be:{be.id}"
                        be_room_number_ga = f"{room_number_ga}-T{te_counter}"
                        mg_data.setdefault(_BEDIENELEMENT_GEWERK.middle_group, []).append(
                            (room, pseudo, _BEDIENELEMENT_GEWERK, be_room_number_ga, room_desc)
                        )

        # ── Adressraum-Verwaltung für die ganze Hauptgruppe ─────────────────
        # Ein Zuweisungsblock, der seine Heimat-Mittelgruppe sprengt (z.B. ein
        # Gateway-Produkt mit hunderten ComObjects), wird automatisch mit der
        # nächsten freien Mittelgruppe derselben HG fortgesetzt, statt eine
        # ungültige sub_group > 255 zu erzeugen (siehe `place_new_block`).
        old_by_assignment, next_free = self._index_existing_hg(existing, hg_number)

        # Belegte MG-Nummern: eigene Heimat-MGs aller Gewerke in dieser HG,
        # Variante-B-Rückmeldungs-MGs, sowie alle MGs, die in `existing`
        # bereits Inhalt hatten (verhindert, dass ein neuer Überlauf-Block
        # eine MG "stiehlt", die eigentlich für eine noch zu verarbeitende
        # Wiederverwendung reserviert ist).
        claimed: set[int] = set(mg_data.keys()) | set(next_free.keys())
        if self.variant == "B":
            if 0 in mg_data:
                claimed.add(6)
            if 1 in mg_data:
                claimed.add(7)

        mg_registry: dict[int, MiddleGroup] = {}

        def get_or_create_mg(number: int, name: str | None = None) -> MiddleGroup:
            if number not in mg_registry:
                mg_registry[number] = MiddleGroup(
                    number=number, name=name or mg_names.get(number, f"MG {number}"),
                )
            return mg_registry[number]

        def open_overflow_mg(source_name: str) -> MiddleGroup | None:
            for candidate in range(8):
                if candidate not in claimed:
                    claimed.add(candidate)
                    return get_or_create_mg(candidate, name=f"{source_name} (Forts.)")
            return None  # Hauptgruppe erschöpft (alle 8 MGs belegt)

        def place_new_block(home_mg_num, gewerk, assignment, schema, id_key,
                            room, room_number_ga, room_desc,
                            skip_functions: frozenset = frozenset()) -> None:
            """Hängt einen neuen/veränderten Block an; wechselt bei Überlauf
            automatisch in die nächste freie MG derselben HG.

            `skip_functions` überspringt Funktions-Slots, die bereits manuell
            mit einer bestehenden GA verknüpft sind (FA-521f, siehe
            assignment.linked_ga_ids) -- die verknüpfte GA existiert schon
            (is_manual=True) und wird vom Aufrufer separat erhalten, hier
            darf keine zweite GA für dieselbe Funktion entstehen."""
            target = get_or_create_mg(home_mg_num)
            cursor = next_free.get(target.number, 0)
            needed = schema.block_size * assignment.count
            placed = 0
            for element_nr in range(1, assignment.count + 1):
                for entry in schema.entries:
                    if entry.function and entry.function in skip_functions:
                        continue
                    if cursor > 255:
                        next_mg = open_overflow_mg(gewerk.name)
                        if next_mg is None:
                            msg = (
                                f"HG {hg_number}: Keine freie Mittelgruppe mehr für "
                                f"'{gewerk.name}' (Raum {room.number}) – "
                                f"{needed - placed} von {needed} GAs konnten nicht "
                                f"platziert werden."
                            )
                            warnings.append(msg)
                            logger.warning(msg)
                            return
                        target = next_mg
                        cursor = next_free.get(target.number, 0)
                    ga = GroupAddress(
                        main_group=hg_number, middle_group=target.number,
                        sub_group=cursor, assignment_id=id_key,
                    )
                    self._fill_entry_fields(
                        ga, entry, gewerk.code, room_number_ga, element_nr,
                        room_desc, room.id,
                    )
                    target.group_addresses.append(ga)
                    cursor += 1
                    next_free[target.number] = cursor
                    placed += 1

        def reuse_block(old_gas, schema, gewerk, assignment,
                        room, room_number_ga, room_desc) -> None:
            """Aktualisiert einen unveränderten Block inhaltlich, ohne
            Position/id zu ändern – auch wenn er über mehrere MGs verteilt ist."""
            block_len = schema.block_size
            for idx, element_nr in enumerate(range(1, assignment.count + 1)):
                chunk = old_gas[idx * block_len:(idx + 1) * block_len]
                self._update_block_in_place(
                    chunk, schema, gewerk.code, room_number_ga, element_nr,
                    room_desc, room.id,
                )
                by_num: dict[int, list[GroupAddress]] = {}
                for ga in chunk:
                    by_num.setdefault(ga.middle_group, []).append(ga)
                for num, gas in by_num.items():
                    get_or_create_mg(num).group_addresses.extend(gas)
                    claimed.add(num)

        # Bereits existierende GAs (per id) -- fuer die Gueltigkeitspruefung
        # manuell verknuepfter Funktions-Slots (FA-521f, assignment.linked_ga_ids).
        existing_ga_by_id = (
            {ga.id: ga for ga in existing.all_addresses()} if existing else {}
        )

        # Pro Heimat-Mittelgruppe (Gewerk-Thema) die Adressen generieren
        for mg_num in sorted(mg_data.keys()):
            get_or_create_mg(mg_num)

            for room, assignment, gewerk, room_number_ga, room_desc in mg_data[mg_num]:
                schema = self._get_block_schema(gewerk, assignment=assignment, is_feedback=False)

                # Manuell verknuepfte Funktions-Slots (nur count==1, siehe
                # step05_gewerke._assign_channel): deren GA existiert bereits
                # (is_manual=True) und bleibt von dieser Generierung komplett
                # unberuehrt -- weder Neuplatzierung noch Umbenennung. Ein
                # verwaister Verweis (GA zwischenzeitlich geloescht) wird
                # bereinigt und faellt auf automatische Generierung zurueck.
                skip_functions: frozenset = frozenset()
                if assignment.count == 1 and assignment.linked_ga_ids:
                    stale = [
                        fn for fn, ga_id in assignment.linked_ga_ids.items()
                        if ga_id not in existing_ga_by_id
                    ]
                    for fn in stale:
                        del assignment.linked_ga_ids[fn]
                        warnings.append(
                            f"'{gewerk.name}' (Raum {room.number}): manuell "
                            f"verknüpfte GA für Funktion '{fn}' nicht mehr "
                            f"gefunden -- wird automatisch neu generiert."
                        )
                    skip_functions = frozenset(assignment.linked_ga_ids.keys())

                if skip_functions:
                    # Ganz oder teilweise manuell verknuepft: nie reuse_block
                    # (positionelles Matching waere bei importierten GAs
                    # unsicher, siehe Plan-Begruendung) -- nur die
                    # unverknuepften Slots neu generieren. Ein zuvor komplett
                    # automatisch generierter Block fuer dieselbe assignment.id
                    # wird dabei verworfen (nicht mehr positionsgetreu
                    # zuordenbar) und wie bei jeder Block-Formaenderung neu
                    # platziert -- kein neues Verhalten, nur konsequent
                    # angewendet.
                    old_by_assignment.pop(assignment.id, None)
                    place_new_block(
                        mg_num, gewerk, assignment, schema, assignment.id,
                        room, room_number_ga, room_desc,
                        skip_functions=skip_functions,
                    )
                    continue

                total_len = schema.block_size * assignment.count
                old_gas = old_by_assignment.pop(assignment.id, None)

                if old_gas is not None and len(old_gas) == total_len:
                    reuse_block(old_gas, schema, gewerk, assignment, room, room_number_ga, room_desc)
                else:
                    place_new_block(
                        mg_num, gewerk, assignment, schema, assignment.id,
                        room, room_number_ga, room_desc,
                    )

            # Variante B: Rückmeldungen in separaten MGs (eigener Namespace
            # "<id>:fb", damit sie nicht mit dem Vorwärts-Block desselben
            # assignment.id vermischt werden)
            if self.variant == "B" and mg_num in (0, 1):
                fb_mg_num = 6 if mg_num == 0 else 7
                get_or_create_mg(fb_mg_num)

                for room, assignment, gewerk, room_number_ga, room_desc in mg_data[mg_num]:
                    fb_schema = self._get_block_schema(
                        gewerk, assignment=assignment, is_feedback=True,
                    )
                    if not fb_schema:
                        continue

                    fb_id_key = f"{assignment.id}:fb"
                    total_len = fb_schema.block_size * assignment.count
                    old_gas = old_by_assignment.pop(fb_id_key, None)

                    if old_gas is not None and len(old_gas) == total_len:
                        reuse_block(old_gas, fb_schema, gewerk, assignment, room, room_number_ga, room_desc)
                    else:
                        place_new_block(
                            fb_mg_num, gewerk, assignment, fb_schema, fb_id_key,
                            room, room_number_ga, room_desc,
                        )

                if not mg_registry[fb_mg_num].group_addresses:
                    del mg_registry[fb_mg_num]

        for mg in mg_registry.values():
            mg.group_addresses.sort(key=lambda g: g.sub_group)
        hg.middle_groups = sorted(mg_registry.values(), key=lambda m: m.number)

        return hg

    def _create_central_main_group(self, scenes: list, has_astro: bool = False,
                                    areal=None, warnings: list | None = None) -> MainGroup:
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

        # MG 4: Szenen – eine feste Zentral-GA + je EINE gemeinsame
        # Szenenaufruf-GA pro Geltungsbereich (KNX-Konvention DPT 17/18:
        # eine GA traegt bis zu 64 Szenen als 1-Byte-Wert 0-63, Szene N ->
        # Wert N-1; welcher Aktor bei welcher Nummer was tut, steht in dessen
        # eigenen Parametern, nicht auf Busebene -- siehe scene_addressing.py).
        # Aus einem Import erkannte Szenen (FA-1808) werden ausgelassen, ihre
        # GA existiert bereits im importierten Bestand.
        mg_szenen = MiddleGroup(number=4, name="Szenen")
        mg_szenen.group_addresses.append(GroupAddress(
            main_group=0, middle_group=4, sub_group=1,
            designation="ZENTRAL Szene Abwesenheit",
            datapoint_type="DPST-17-1", central="true",
            function_name="SZENE",
        ))
        sub = 2
        groups = group_named_scenes(scenes, areal)
        for group_key in sorted(groups.keys()):
            designation, group_scenes = groups[group_key]
            numbers = [s.scene_number for s in group_scenes if s.scene_number > 0]
            duplicates = {n for n in numbers if numbers.count(n) > 1}
            if duplicates and warnings is not None:
                warnings.append(
                    f"'{designation}': Szenennummer(n) {sorted(duplicates)} "
                    f"sind mehrfach vergeben -- diese Szenen wuerden auf dem "
                    f"gemeinsamen Bus-Kanal denselben Wert senden und kollidieren."
                )
            mg_szenen.group_addresses.append(GroupAddress(
                main_group=0, middle_group=4, sub_group=sub,
                designation=designation,
                datapoint_type="DPST-17-1", central="true",
                function_name="SZENE",
                description=scene_value_mapping_text(group_scenes),
            ))
            sub += 1
            if sub > 255:
                logger.warning("Mehr als 254 Szenen-Geltungsbereiche – UG-Grenze erreicht.")
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

    def _build_product_schema(self, gewerk: Gewerk,
                              linked_product: dict) -> AddressBlockSchema | None:
        """Baut ein Adressblock-Schema aus den ComObjects eines verknüpften Produkts.

        Gibt None zurück, wenn das Produkt keine GA-relevanten ComObjects hat
        (z.B. weil es nicht via KNXPROD importiert wurde) – dann greift der
        generische/gewerk-spezifische Schema-Fallback.

        `linked_product["excluded_co_numbers"]` (optional, siehe
        ComObjectSelectDialog) nimmt einzelne ComObjects gezielt von der
        GA-Erzeugung aus, auch wenn sie `needs_ga` erfüllen – der Integrator
        wählt so bei grossen Produkten (Gateways mit hunderten ComObjects)
        gezielt aus, was tatsächlich eine GA braucht.
        """
        com_objects = linked_product.get("com_objects") or []
        excluded = set(linked_product.get("excluded_co_numbers") or [])
        entries: list[BlockEntry] = []
        for co in com_objects:
            if not _com_object_needs_ga(co):
                continue
            if co.get("number") in excluded:
                continue
            function = _com_object_function_name(co)
            is_fb = not co.get("write_flag", False) and (
                co.get("transmit_flag", False) or co.get("read_flag", False)
            )
            entries.append(BlockEntry(
                offset=len(entries),
                function=function,
                designation=function,
                dpt=_normalize_dpt(co.get("datapoint_type", "")),
                is_feedback=is_fb,
            ))

        if not entries:
            return None

        return AddressBlockSchema(
            gewerk_code=gewerk.code,
            block_size=len(entries),
            entries=entries,
            middle_group=gewerk.middle_group,
        )

    def _get_block_schema(self, gewerk: Gewerk,
                          assignment: GewerkAssignment | None = None,
                          is_feedback: bool = False) -> AddressBlockSchema | None:
        """Gibt das passende Adressblock-Schema zurück.

        Wenn assignment.extra_entries gesetzt sind, werden diese an den
        Standard-Block angehängt (nur für den Vorwärts-Block, nicht Rückmeldung).

        Ist assignment.linked_product mit GA-relevanten ComObjects gesetzt,
        wird das Schema vollständig aus diesen ComObjects gebaut (ersetzt
        Standard-/gewerk-spezifisches Schema).
        """
        product_schema = None
        if assignment and assignment.linked_product:
            product_schema = self._build_product_schema(gewerk, assignment.linked_product)

        if is_feedback:
            if product_schema:
                # Produkt-Block enthält Status-/Meldeobjekte bereits inline
                return None

            category = gewerk.category
            # Nur für Variante B
            if category == "licht":
                return create_light_feedback_block_b()
            elif category == "jalousie":
                return create_jalousie_feedback_block_b()
            return None

        if product_schema:
            if assignment and assignment.extra_entries:
                for e in assignment.extra_entries:
                    entry = BlockEntry.from_dict(e)
                    entry.offset = product_schema.block_size
                    product_schema.entries.append(entry)
                    product_schema.block_size += 1
            return product_schema

        category = gewerk.category

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
            "W":   create_w_block_schema,
            "WP":  create_wp_block_schema,
            "MM":  create_mm_block_schema,
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
                entry = BlockEntry.from_dict(e)
                entry.offset = schema.block_size
                schema.entries.append(entry)
                schema.block_size += 1

        return schema
