"""
Validierungs-Engine (FA-600)
Prüft Gruppenadressen, Bezeichnungen, Mittelgruppen-Zuordnung etc.
"""
from __future__ import annotations
import re
import logging
from ..models.group_address import GroupAddressStructure, GroupAddress
from ..models.gewerk import GewerkCatalog
from ..utils.validators import is_valid_ga, is_valid_designation

logger = logging.getLogger("knix_arranger.validation")


class ValidationIssue:
    """Ein Validierungsproblem."""

    def __init__(self, level: str, rule_id: str, message: str,
                 address: str = "", suggestion: str = ""):
        self.level = level        # "error", "warning", "info"
        self.rule_id = rule_id
        self.message = message
        self.address = address
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "rule_id": self.rule_id,
            "message": self.message,
            "address": self.address,
            "suggestion": self.suggestion,
        }


class ValidationEngine:
    """Prüft GA-Strukturen auf Konformitaet."""

    def __init__(self, catalog: GewerkCatalog | None = None):
        self.catalog = catalog

    def validate(self, structure: GroupAddressStructure,
                 project=None) -> list[ValidationIssue]:
        """Fuehrt alle Validierungen durch.

        Args:
            structure: Die zu pruefende GA-Struktur.
            project:   Optional – wird fuer projektweite Regeln (FA-3308b) benoetigt.
        """
        issues: list[ValidationIssue] = []
        all_gas = structure.all_addresses()

        issues.extend(self._check_valid_addresses(all_gas))
        issues.extend(self._check_duplicates(all_gas))
        issues.extend(self._check_dpt(all_gas))
        issues.extend(self._check_naming(all_gas))
        issues.extend(self._check_middle_group_assignment(all_gas))
        issues.extend(self._check_block_integrity(structure))

        if structure.variant == "B":
            issues.extend(self._check_feedback_variant_b(structure))

        # FA-3308b: Astro-GAs prüfen wenn Zeitprogramme mit ASTRO-Schaltpunkten vorhanden
        if project is not None:
            issues.extend(self._check_astro_gas(structure, project))

        return issues

    def _check_astro_gas(self, structure: GroupAddressStructure,
                         project) -> list[ValidationIssue]:
        """FA-3308b: Warnung wenn Astro-SwitchPoints vorhanden aber HG0/MG7 fehlt."""
        issues = []
        try:
            has_astro = any(
                sp.time_type == "ASTRO"
                for tp in project.time_programs
                if tp.active
                for dp in tp.day_profiles
                for sp in dp.switch_points
            )
            if not has_astro:
                return issues

            hg0 = next((g for g in structure.main_groups if g.number == 0), None)
            mg7 = next((m for m in hg0.middle_groups if m.number == 7), None) if hg0 else None

            if mg7 is None:
                issues.append(ValidationIssue(
                    level="warning",
                    rule_id="FA-3308b",
                    message=(
                        "Astro-Schaltpunkte im Zeitprogramm gefunden, "
                        "aber Astro-GAs in HG 0 / MG 7 fehlen."
                    ),
                    address="0/7/-",
                    suggestion=(
                        "Führen Sie die GA-Generierung erneut aus (Wizard Schritt 9), "
                        "oder klicken Sie in der Zeitsteuerungsansicht auf "
                        "'Astro-GAs anlegen'."
                    ),
                ))
            else:
                # Prüfen ob alle 4 Standard-GAs vorhanden (Sub 0–3)
                existing = {ga.sub_group for ga in mg7.group_addresses}
                missing = [s for s in range(4) if s not in existing]
                if missing:
                    issues.append(ValidationIssue(
                        level="warning",
                        rule_id="FA-3308b",
                        message=(
                            f"HG 0 / MG 7 vorhanden, aber {len(missing)} Astro-GAs fehlen "
                            f"(Sub-Gruppen: {', '.join(str(s) for s in missing)})."
                        ),
                        address="0/7/-",
                        suggestion=(
                            "GA-Generierung erneut ausführen oder manuell "
                            "die fehlenden Astro-GAs anlegen."
                        ),
                    ))
        except Exception as e:
            logger.debug(f"FA-3308b Prüfung fehlgeschlagen: {e}")
        return issues

    def _check_valid_addresses(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-601: Prüft gültige Adressen."""
        issues = []
        for ga in addresses:
            if ga.is_placeholder:
                continue
            # GA-08/FA-444: 0/0/0 ist Systemadresse – auch bei Zentraladressen prüfen
            if ga.main_group == 0 and ga.middle_group == 0 and ga.sub_group == 0:
                issues.append(ValidationIssue(
                    "error", "GA-08",
                    "Adresse 0/0/0 ist KNX-Systemadresse und darf nicht verwendet werden",
                    ga.address,
                    "Verwenden Sie 0/0/1 als erste Zentraladresse",
                ))
                continue
            if ga.central == "true":
                continue
            if not is_valid_ga(ga.main_group, ga.middle_group, ga.sub_group):
                issues.append(ValidationIssue(
                    "error", "FA-601",
                    f"Ungültige Gruppenadresse: {ga.address}",
                    ga.address,
                ))
        return issues

    def _check_duplicates(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-602: Prüft auf doppelte Adressen."""
        issues = []
        seen: dict[str, GroupAddress] = {}
        for ga in addresses:
            if ga.is_placeholder:
                continue
            key = ga.address
            if key in seen:
                issues.append(ValidationIssue(
                    "error", "FA-602",
                    f"Doppelte Gruppenadresse: {key} "
                    f"('{ga.designation}' und '{seen[key].designation}')",
                    key,
                    "Eine der beiden Adressen muss geändert werden.",
                ))
            else:
                seen[key] = ga
        return issues

    def _check_dpt(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-603, FA-604: Prüft Datenpunkttypen."""
        issues = []
        expected_dpts = {
            "E/A": "DPST-1-1", "RM": "DPST-1-1",
            "DIM": "DPST-3-7",
            "WERT": "DPST-5-1", "RM WERT": "DPST-5-1",
            "AUF/AB": "DPST-1-8", "BESCHATTUNG": "DPST-1-8",
            "STOPP": "DPST-1-7",
            "IST": "DPST-9-1", "BASIS-SOLL": "DPST-9-1",
        }
        for ga in addresses:
            if ga.is_placeholder:
                continue
            if not ga.datapoint_type:
                issues.append(ValidationIssue(
                    "warning", "FA-604",
                    f"Fehlender Datenpunkttyp fuer: {ga.designation}",
                    ga.address,
                    f"Vorschlag: {expected_dpts.get(ga.function_name, 'unbekannt')}",
                ))
            elif ga.function_name in expected_dpts:
                expected = expected_dpts[ga.function_name]
                if ga.datapoint_type != expected:
                    issues.append(ValidationIssue(
                        "warning", "FA-603",
                        f"Unerwarteter DPT für {ga.function_name}: "
                        f"{ga.datapoint_type} (erwartet: {expected})",
                        ga.address,
                    ))
        return issues

    def _check_naming(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-606, FA-610: Prüft Bezeichnungskonformitaet."""
        issues = []
        for ga in addresses:
            if ga.is_placeholder or ga.central == "true":
                continue
            if ga.designation and ga.designation != "--":
                if not is_valid_designation(ga.designation):
                    issues.append(ValidationIssue(
                        "info", "FA-610",
                        f"Bezeichnung nicht konform mit KNX Swiss Standard: "
                        f"'{ga.designation}'",
                        ga.address,
                        "Erwartetes Format: GEWERK_RAUM_NR FUNKTION (Klartext)",
                    ))
        return issues

    def _check_middle_group_assignment(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-607: Prüft Mittelgruppen-Zuordnung."""
        issues = []
        category_to_mg = {
            "licht": 0, "jalousie": 1, "heizung": 2, "alarm": 3,
        }
        if not self.catalog:
            return issues

        for ga in addresses:
            if ga.is_placeholder or ga.main_group == 0:
                continue
            if ga.gewerk_code:
                gewerk = self.catalog.get(ga.gewerk_code)
                if gewerk and gewerk.middle_group != ga.middle_group:
                    # Pruefen ob es eine Rueckmeldungs-MG ist (6 oder 7)
                    if ga.middle_group not in (6, 7):
                        issues.append(ValidationIssue(
                            "warning", "FA-607",
                            f"Gewerk {ga.gewerk_code} in falscher MG: "
                            f"{ga.middle_group} (erwartet: {gewerk.middle_group})",
                            ga.address,
                        ))
        return issues

    def _check_block_integrity(self, structure: GroupAddressStructure) -> list[ValidationIssue]:
        """FA-605: Prüft Adressblock-Integritaet (keine Luecken)."""
        issues = []
        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                if not gas:
                    continue
                # Pruefe ob Adressen lueckenlos aufeinanderfolgen
                for i in range(len(gas) - 1):
                    if gas[i + 1].sub_group != gas[i].sub_group + 1:
                        gap_start = gas[i].sub_group + 1
                        gap_end = gas[i + 1].sub_group - 1
                        issues.append(ValidationIssue(
                            "warning", "FA-605",
                            f"Luecke in MG {hg.number}/{mg.number}: "
                            f"Adressen {gap_start}-{gap_end} fehlen",
                            f"{hg.number}/{mg.number}/{gap_start}",
                        ))
        return issues

    def _check_feedback_variant_b(self, structure: GroupAddressStructure) -> list[ValidationIssue]:
        """FA-608: Prüft Variante B Rückmeldungen."""
        issues = []
        for hg in structure.main_groups:
            if hg.number == 0:
                continue
            # Finde MG 0 und MG 6 (Licht)
            mg0 = next((m for m in hg.middle_groups if m.number == 0), None)
            mg6 = next((m for m in hg.middle_groups if m.number == 6), None)
            if mg0 and not mg6:
                if any(not ga.is_placeholder for ga in mg0.group_addresses):
                    issues.append(ValidationIssue(
                        "warning", "FA-608",
                        f"HG {hg.number}: Licht-Adressen in MG 0 vorhanden, "
                        f"aber keine Rückmeldungen in MG 6",
                        f"{hg.number}/6/0",
                    ))
            # Finde MG 1 und MG 7 (Jalousie)
            mg1 = next((m for m in hg.middle_groups if m.number == 1), None)
            mg7 = next((m for m in hg.middle_groups if m.number == 7), None)
            if mg1 and not mg7:
                if any(not ga.is_placeholder for ga in mg1.group_addresses):
                    issues.append(ValidationIssue(
                        "warning", "FA-608",
                        f"HG {hg.number}: Jalousie-Adressen in MG 1 vorhanden, "
                        f"aber keine Rückmeldungen in MG 7",
                        f"{hg.number}/7/0",
                    ))
        return issues
