"""
Reorganisation bestehender Projekte (FA-700)
Sortierung, Re-Blocking, Re-Naming.
"""
from __future__ import annotations
import copy
import logging
from ..models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from ..models.gewerk import GewerkCatalog
from .naming_engine import NamingEngine

logger = logging.getLogger("knix_arranger.reorganization")


class ReorganizationEngine:
    """Reorganisiert bestehende GA-Strukturen richtlinienkonform."""

    def __init__(self, catalog: GewerkCatalog | None = None):
        self.catalog = catalog

    def reorganize(self, structure: GroupAddressStructure,
                   rename: bool = True) -> GroupAddressStructure:
        """
        Reorganisiert die GA-Struktur (FA-701).

        FA-701: Sortierung: Stockwerk > MG > Raum > Gewerk > Funktion
        FA-702: Bloecke zusammenhalten
        FA-703: Zentraladressen separat behandeln
        FA-705: Central/Unfiltered/Security beibehalten
        FA-706: Bezeichnungen anpassen (optional)

        Gibt eine Kopie zurück (Original bleibt unveraendert = Backup FA-042).
        """
        result = GroupAddressStructure(variant=structure.variant)

        for hg in sorted(structure.main_groups, key=lambda m: m.number):
            new_hg = MainGroup(number=hg.number, name=hg.name)

            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                new_mg = MiddleGroup(number=mg.number, name=mg.name)

                # Sammle alle nicht-Platzhalter-Adressen
                real_gas = [ga for ga in mg.group_addresses if not ga.is_placeholder]

                if hg.number == 0:
                    # FA-703: Zentraladressen separat - nur sortieren
                    sorted_gas = sorted(real_gas, key=lambda g: g.sub_group)
                else:
                    # FA-701: Nach Raum > Gewerk > Funktion sortieren
                    sorted_gas = sorted(
                        real_gas,
                        key=lambda g: (g.room_number, g.gewerk_code, g.element_number, g.sub_group),
                    )

                # Neu nummerieren
                sub_counter = 0
                for ga in sorted_gas:
                    new_ga = copy.deepcopy(ga)
                    new_ga.sub_group = sub_counter
                    new_ga.main_group = hg.number
                    new_ga.middle_group = mg.number

                    if rename and ga.gewerk_code and ga.room_number and hg.number != 0:
                        new_ga.designation = NamingEngine.create_designation(
                            ga.gewerk_code, ga.room_number,
                            ga.element_number, ga.function_name,
                        )

                    new_mg.group_addresses.append(new_ga)
                    sub_counter += 1

                new_hg.middle_groups.append(new_mg)

            result.main_groups.append(new_hg)

        logger.info("Reorganisation abgeschlossen")
        return result

    def create_diff(self, original: GroupAddressStructure,
                    reorganized: GroupAddressStructure) -> list[dict]:
        """
        Erstellt einen Vorher-/Nachher-Vergleich (FA-704).
        """
        changes = []
        orig_gas = {ga.id: ga for ga in original.all_addresses()}
        reorg_gas = {ga.id: ga for ga in reorganized.all_addresses()}

        for ga_id, orig_ga in orig_gas.items():
            reorg_ga = reorg_gas.get(ga_id)
            if reorg_ga:
                if (orig_ga.address != reorg_ga.address or
                        orig_ga.designation != reorg_ga.designation):
                    changes.append({
                        "type": "changed",
                        "old_address": orig_ga.address,
                        "new_address": reorg_ga.address,
                        "old_designation": orig_ga.designation,
                        "new_designation": reorg_ga.designation,
                    })

        return changes
