"""
DaliService – DALI-Konfigurationsverwaltung (FA-2801 bis FA-2806).

Verantwortlich für:
- Ermittlung von DALI-Gateways aus der Topologie
- Anlegen/Abrufen von DaliGateway-Konfigurationen
- Verknüpfung von KNX-GAs mit dem DALI-Gateway (FA-2803)
- Generierung der DALI-Geräteliste für Dokumentation (FA-2805)
- Checklisten-Punkte für Notbeleuchtung (FA-2804)
"""
from __future__ import annotations
import re
import logging
from ..models.dali_config import DaliGateway, DaliDevice, DaliGroup, DaliScene, EMERGENCY_MODES

logger = logging.getLogger("knix_arranger.dali_service")

# GA-Adress-Pattern für Validierung
_GA_RE = re.compile(r"^\d+/\d+/\d+$")

# LDA-GA-Bezeichnung: "LDA_001_01 E/A" → (room_nr="001", elem_nr="01", func="E/A")
_LDA_PREFIX_RE = re.compile(r"^LDA_(\w+)_(\d{2})\s+(.+)$", re.IGNORECASE)

# KO-Name-Pattern für Gruppen/Kanäle:
#   Deutsch: "Gruppe 3 Schalten", "Kanal 2 Dimmen relativ"
#   Englisch: "Group 1, Switching", "Group 2, Dimming", "Group 3, Set Value"
_KO_GROUP_RE = re.compile(
    r"(?:gruppe|group|kanal|channel|ausgang|output)\s+(\d+)[\s,]+"
    r"(schalten|switching|switch|on[./]?off|dimmen|dimming|dim"
    r"|helligkeitswert|set\s+value|value|wert)",
    re.IGNORECASE,
)

# KO-Name-Pattern für Einzelgeräte/EVGs (Herstellervarianten):
#   "EVG 5 Schalten", "Betriebsgerät 3 Dimmen", "Einzelgerät 1 - Schalten",
#   "Individual 2 On/Off", "Ballast 4 Dim", "Leuchte 7 Schalten", "Gear 1 Switch"
_KO_EVG_RE = re.compile(
    r"(?:evg|betriebsger[äa]t|einzelger[äa]t|ballast|individual|leuchte|gear)\s*[-–]?\s*(\d+)"
    r"(?:\s*[-–]\s*|\s+)"
    r"(schalten|switch|on[./]?off|dimmen|dim|relativ|helligkeitswert|value|wert)",
    re.IGNORECASE,
)


class DaliService:
    """Verwaltung der DALI-Konfigurationen eines Projekts."""

    # ── Gateway-Ermittlung ────────────────────────────────────────────────────

    def get_dali_gateways_from_topology(self, project) -> list:
        """Gibt alle Topology-Devices zurück, die DALI-Gateways sind.

        Bedingung: device_type in {"gateway"} und gewerk_code == "LDA"
        oder actor_type enthält "DALI".
        """
        gateways = []
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if self._is_dali_gateway(device):
                        gateways.append(device)
        return gateways

    @staticmethod
    def _is_dali_gateway(device) -> bool:
        """Prüft ob ein Topology-Device ein DALI-Gateway ist.

        Primärkriterium: Produktname enthält "dali" (herstellerunabhängig).
        Sekundärkriterium: device_type ist kein reines Infrastrukturgerät.

        Hintergrund: Der XLSX-Topologie-Import klassifiziert Geräte anhand
        der physikalischen Adresse (1–100 = actor, 101–199 = sensor). Ein
        DALI-Gateway mit hoher Teilnehmernummer würde sonst als "sensor"
        eingestuft und nicht erkannt.
        """
        product_lower = (device.product or "").lower()
        if "dali" not in product_lower:
            return False
        # Koppler und Speisegeräte ausschliessen
        return device.device_type not in ("coupler", "power_supply")

    # ── Konfiguration anlegen/abrufen ─────────────────────────────────────────

    def get_or_create(self, project, gateway_device_id: str, name: str = "") -> DaliGateway:
        """Gibt die DaliGateway-Konfiguration für ein Device zurück; legt sie an falls nötig."""
        if gateway_device_id not in project.dali_configs:
            config = DaliGateway(
                gateway_device_id=gateway_device_id,
                name=name or f"DALI-Gateway {gateway_device_id[:8]}",
            )
            project.dali_configs[gateway_device_id] = config
        return project.dali_configs[gateway_device_id]

    # ── GA-Verknüpfung (FA-2803) ──────────────────────────────────────────────

    def link_gas_from_structure(self, dali_gw: DaliGateway, project) -> int:
        """Sucht passende KNX-GAs in der GA-Struktur und verknüpft sie.

        Strategie (FA-2803):
        1. Findet das Gateway-Device in der Topologie über gateway_device_id,
           ermittelt dessen Linie und die zugehörigen Räume.
        2. Sucht GAs mit LDA_-Prefix nach KNX-Arranger-Namenskonvention:
           E/A → switch_broadcast, DIM → dim_broadcast,
           RM WERT → status_value, RM → (Rückmeldung, kein Fault)
        3. Fallback: Keyword-Suche in allen GAs.

        Gibt die Anzahl verknüpfter GAs zurück.
        """
        all_gas = project.group_addresses.all_addresses()
        linked = 0

        # ── Schritt 1: Räume auf der Gateway-Linie ermitteln ─────────────────
        room_numbers: set[str] = set()
        if dali_gw.gateway_device_id:
            for area in project.topology.areas:
                for line in area.lines:
                    if any(d.id == dali_gw.gateway_device_id for d in line.devices):
                        room_index = {r.id: r for r in project.all_rooms}
                        for rid in line.assigned_room_ids:
                            room = room_index.get(rid)
                            if room and room.number:
                                room_numbers.add(room.number)
                        break

        # ── Schritt 2: LDA-GAs nach Namenskonvention suchen ──────────────────
        # Filtert optional auf Räume der Gateway-Linie (wenn bekannt)
        def find_lda_ga(suffix: str, exclude_suffix: str = "") -> str:
            # Sucht LDA_xxx_xx <suffix> [optionaler Kommentar]
            # suffix z.B. " E/A", " DIM", " RM WERT", " RM"
            suffix_lc = suffix.strip().lower()
            excl_lc = exclude_suffix.strip().lower()
            candidates = []
            for ga in all_gas:
                desig = (ga.designation or "").strip()
                if not desig.upper().startswith("LDA_"):
                    continue
                if not _GA_RE.match(ga.address or ""):
                    continue
                # Funktions-Teil: alles nach "LDA_xxx_xx "
                parts = desig.split(" ", 1)
                if len(parts) < 2:
                    continue
                func_lc = parts[1].lower()
                # func_lc ist z.B. "e/a (garage)" oder "dim" oder "rm wert"
                if not (func_lc == suffix_lc or func_lc.startswith(suffix_lc + " ")):
                    continue
                if excl_lc and (func_lc == excl_lc or func_lc.startswith(excl_lc + " ")):
                    continue
                room_nr = desig.split("_")[1] if "_" in desig else ""
                priority = 0 if room_nr in room_numbers else 1
                candidates.append((priority, ga.address))
            if candidates:
                return sorted(candidates)[0][1]
            return ""

        # ── Schritt 3: Keyword-Fallback für nicht-LDA-GAs ────────────────────
        def find_ga_keyword(keywords: list[str], exclude: list[str] = None) -> str:
            exclude = exclude or []
            for ga in all_gas:
                text = (ga.designation or "").lower()
                if any(kw in text for kw in keywords) and \
                   not any(ex in text for ex in exclude):
                    if _GA_RE.match(ga.address or ""):
                        return ga.address
            return ""

        # switch_broadcast: E/A
        if not dali_gw.ga_switch_broadcast:
            addr = find_lda_ga(" e/a") or find_ga_keyword(
                ["schalten", "switch", "on_off", "broadcast"], ["dim", "szene", "status"])
            if addr:
                dali_gw.ga_switch_broadcast = addr
                linked += 1

        # dim_broadcast: DIM (aber nicht RM WERT)
        if not dali_gw.ga_dim_broadcast:
            addr = find_lda_ga(" dim") or find_ga_keyword(
                ["dimmen", "dim", "helligkeit", "brightness"], ["szene", "status", "rm"])
            if addr:
                dali_gw.ga_dim_broadcast = addr
                linked += 1

        # scene: SZENE aus LDA-GA (neuer 10er-Block), Fallback Keyword
        if not dali_gw.ga_scene:
            addr = find_lda_ga("szene") or find_ga_keyword(["szene", "scene"])
            if addr:
                dali_gw.ga_scene = addr
                linked += 1

        # status_value: RM WERT (bevorzugt vor RM)
        if not dali_gw.ga_status_value:
            addr = find_lda_ga("rm wert") or find_lda_ga("rm") or find_ga_keyword(
                ["istwert", "rueckmeldung", "feedback", "rm wert"], ["stoerung", "fault"])
            if addr:
                dali_gw.ga_status_value = addr
                linked += 1

        # status_fault: nur aus LDA-STOERUNG-GA, kein Keyword-Fallback
        if not dali_gw.ga_status_fault:
            addr = find_lda_ga("stoerung")
            if addr:
                dali_gw.ga_status_fault = addr
                linked += 1

        logger.info(f"DaliService: {linked} GAs für Gateway '{dali_gw.name}' verknüpft.")
        return linked

    # ── Geräteliste für Dokumentation (FA-2805) ───────────────────────────────

    def generate_device_list(self, dali_gw: DaliGateway, project) -> list[dict]:
        """Generiert eine strukturierte DALI-Geräteliste für Revisionsunterlagen.

        Rückgabe: Liste von Dicts mit keys:
            short_address, name, evg_type, room, groups, is_emergency, emergency_mode,
            ga_switch, ga_dim, ga_scene
        """
        room_map = {r.id: r.name for r in project.all_rooms}

        rows = []
        for dev in sorted(dali_gw.devices, key=lambda d: d.short_address):
            group_names = []
            for g_nr in sorted(dev.group_memberships):
                grp = next((g for g in dali_gw.groups if g.number == g_nr), None)
                group_names.append(grp.name if grp and grp.name else f"Gruppe {g_nr}")

            rows.append({
                "short_address": dev.short_address,
                "name": dev.name or f"EVG {dev.short_address}",
                "evg_type": dev.evg_type,
                "room": room_map.get(dev.room_id, ""),
                "groups": ", ".join(group_names),
                "is_emergency": dev.is_emergency,
                "emergency_mode": EMERGENCY_MODES.get(dev.emergency_mode, dev.emergency_mode),
                "ga_switch": dali_gw.ga_switch_broadcast,
                "ga_dim": dali_gw.ga_dim_broadcast,
                "ga_scene": dali_gw.ga_scene,
            })
        return rows

    # ── Notlicht-Checkliste (FA-2804) ─────────────────────────────────────────

    def generate_emergency_checklist_items(self, dali_gw: DaliGateway) -> list[dict]:
        """Generiert Checklisten-Punkte für DALI-Notlicht-EVGs.

        Rückgabe: Liste von Dicts mit keys: text, category, device_name, device_address
        """
        items = []
        for dev in dali_gw.devices:
            if not dev.is_emergency:
                continue
            name = dev.name or f"EVG {dev.short_address}"
            items += [
                {
                    "text": f"DALI Notlicht {name} (Adr. {dev.short_address}): "
                             "Funktionstest – 1 h Betrieb nach Netzausfall",
                    "category": "DALI Notbeleuchtung",
                    "device_name": name,
                    "device_address": dev.short_address,
                },
                {
                    "text": f"DALI Notlicht {name} (Adr. {dev.short_address}): "
                             "Dauerbetriebstest – Vollentladungstest (≥ 3 h)",
                    "category": "DALI Notbeleuchtung",
                    "device_name": name,
                    "device_address": dev.short_address,
                },
            ]
        return items

    # ── Gruppen-Synchronisation (Hilfsmethode) ────────────────────────────────

    def sync_groups_from_devices(self, dali_gw: DaliGateway) -> None:
        """Aktualisiert DaliGroup.device_addresses aus DaliDevice.group_memberships."""
        group_map: dict[int, list[int]] = {}
        for dev in dali_gw.devices:
            for g_nr in dev.group_memberships:
                group_map.setdefault(g_nr, []).append(dev.short_address)

        for grp in dali_gw.groups:
            grp.device_addresses = sorted(group_map.get(grp.number, []))

    # ── Standard-Szenen anlegen ───────────────────────────────────────────────

    @staticmethod
    def ensure_default_scenes(dali_gw: DaliGateway) -> None:
        """Legt Szenen 0–3 an, falls noch keine Szenen vorhanden sind."""
        if dali_gw.scenes:
            return
        defaults = [
            (0, "Präsenz"),
            (1, "Putzen"),
            (2, "Nacht"),
            (3, "Aus"),
        ]
        for nr, name in defaults:
            dali_gw.scenes.append(DaliScene(number=nr, name=name))

    # ── Import-Automatisierung ────────────────────────────────────────────────

    def auto_configure_from_import(self, project) -> int:
        """
        Konfiguriert alle DALI-Gateways automatisch nach einem XLSX/knxproj-Import.

        Pro erkanntem Gateway:
        1. DaliGateway-Config anlegen (get_or_create)
        2. Broadcast-GAs verknüpfen (link_gas_from_structure)
        3. Gruppen aus LDA-GAs oder KO-Namen ableiten (_derive_groups_from_import)
        4. Standard-Szenen anlegen (ensure_default_scenes)

        Gibt die Gesamtzahl verknüpfter GAs zurück.
        """
        gateways = self.get_dali_gateways_from_topology(project)
        if not gateways:
            return 0

        # Veraltete Configs entfernen (gateway_device_id nicht mehr in Topologie)
        active_ids = {d.id for d in gateways}
        stale = [k for k in project.dali_configs if k not in active_ids]
        for k in stale:
            del project.dali_configs[k]
            logger.debug(f"DALI: veraltete Config '{k[:8]}' entfernt.")

        total_linked = 0
        for device in gateways:
            gw = self.get_or_create(
                project,
                device.id,
                name=device.product_name or device.product or "DALI-Gateway",
            )
            # Broadcast-GAs nur verknüpfen wenn noch leer
            if not (gw.ga_switch_broadcast or gw.ga_dim_broadcast):
                total_linked += self.link_gas_from_structure(gw, project)

            # Gruppen ableiten (nur wenn noch keine vorhanden)
            if not gw.groups:
                self._derive_groups_from_import(gw, device, project)

            # EVGs ableiten (nur wenn noch keine vorhanden)
            if not gw.devices:
                self._derive_evgs_from_import(gw, device, project)

            self.ensure_default_scenes(gw)

        logger.info(
            f"DALI auto_configure_from_import: {len(gateways)} Gateway(s), "
            f"{total_linked} GAs verknüpft."
        )
        return total_linked

    def _derive_groups_from_import(
        self, dali_gw: DaliGateway, device, project
    ) -> int:
        """
        Leitet DALI-Gruppen aus dem importierten Gerät ab.

        Strategie 1 – LDA-GAs (KNX-Arranger-Namenskonvention):
          Alle GAs mit Bezeichnung 'LDA_xxx_xx FUNKTION' werden nach
          (room_nr, elem_nr) gruppiert. Jede eindeutige Kombination ergibt
          eine DALI-Gruppe mit ga_switch (E/A) und ga_dim (DIM).

        Strategie 2 – KO-Namen (ETS6-Import ohne LDA-Konvention):
          KO-Namen des Gateway-Devices werden auf
          'Gruppe/Kanal X Schalten/Dimmen' geparst.
          Die verbundene GA des KOs wird der Gruppe zugeordnet.

        Gibt die Anzahl angelegter Gruppen zurück.
        """
        ga_by_addr = {
            ga.address: ga
            for ga in project.group_addresses.all_addresses()
        }

        # ── Strategie 1: LDA-GAs ──────────────────────────────────────────────
        # Alle LDA-GAs die mit diesem Gateway verbunden sind
        # (über connected_gas der KOs oder alle LDA-GAs der Linie)
        connected_gas: set[str] = set()
        for co in device.communication_objects:
            connected_gas.update(co.connected_gas)

        # LDA-GAs aus connected_gas parsen
        lda_groups: dict[tuple, dict] = {}  # (room_nr, elem_nr) → {switch, dim, value, name}
        for ga_addr in connected_gas:
            ga = ga_by_addr.get(ga_addr)
            if not ga or not ga.designation:
                continue
            m = _LDA_PREFIX_RE.match(ga.designation.strip())
            if not m:
                continue
            key = (m.group(1), m.group(2))
            func = m.group(3).strip().upper()
            if key not in lda_groups:
                lda_groups[key] = {"switch": "", "dim": "", "value": "", "name": ""}
            if func in ("E/A", "SCHALTEN", "SWITCH"):
                lda_groups[key]["switch"] = ga_addr
            elif func in ("DIM", "DIMMEN"):
                lda_groups[key]["dim"] = ga_addr
            elif func in ("WERT", "RM WERT", "HELLIGKEITSWERT", "VALUE"):
                lda_groups[key]["value"] = ga_addr

        # Falls keine connected GAs bekannt: alle LDA-GAs der GA-Struktur prüfen
        if not lda_groups:
            for ga in project.group_addresses.all_addresses():
                if not ga.designation:
                    continue
                m = _LDA_PREFIX_RE.match(ga.designation.strip())
                if not m:
                    continue
                key = (m.group(1), m.group(2))
                func = m.group(3).strip().upper()
                if key not in lda_groups:
                    lda_groups[key] = {"switch": "", "dim": "", "value": "", "name": ""}
                if func in ("E/A", "SCHALTEN", "SWITCH"):
                    lda_groups[key]["switch"] = ga.address
                elif func in ("DIM", "DIMMEN"):
                    lda_groups[key]["dim"] = ga.address
                elif func in ("WERT", "RM WERT", "HELLIGKEITSWERT", "VALUE"):
                    lda_groups[key]["value"] = ga.address

        if lda_groups:
            # Räume für Namensgebung
            room_index = {r.number: r.name for r in project.all_rooms}
            for grp_nr, ((room_nr, elem_nr), info) in enumerate(sorted(lda_groups.items())):
                room_name = room_index.get(room_nr, f"Raum {room_nr}")
                grp_name = f"{room_name}" if elem_nr == "01" else f"{room_name} {elem_nr}"
                grp = DaliGroup(
                    number=grp_nr,
                    name=grp_name,
                    ga_switch=info["switch"],
                    ga_dim=info["dim"],
                    ga_value=info["value"],
                )
                dali_gw.groups.append(grp)
            logger.info(
                f"DALI _derive_groups: {len(dali_gw.groups)} Gruppen aus LDA-GAs "
                f"für Gateway '{dali_gw.name}'."
            )
            return len(dali_gw.groups)

        # ── Strategie 2: KO-Namen parsen ─────────────────────────────────────
        ko_groups: dict[int, dict] = {}  # group_nr → {switch, dim, value}
        for co in device.communication_objects:
            m = _KO_GROUP_RE.search(co.name or "")
            if not m:
                continue
            grp_nr = int(m.group(1))
            func_raw = m.group(2).lower()
            if grp_nr not in ko_groups:
                ko_groups[grp_nr] = {"switch": "", "dim": "", "value": ""}
            # Erste verbundene GA verwenden
            ga_addr = co.connected_gas[0] if co.connected_gas else ""
            if not ga_addr:
                continue
            if any(k in func_raw for k in ("schalten", "switch", "on")):
                ko_groups[grp_nr]["switch"] = ga_addr
            elif any(k in func_raw for k in ("dimmen", "dim")):
                ko_groups[grp_nr]["dim"] = ga_addr
            elif any(k in func_raw for k in ("wert", "value", "helligkeit")):
                ko_groups[grp_nr]["value"] = ga_addr

        for grp_nr in sorted(ko_groups):
            info = ko_groups[grp_nr]
            dali_gw.groups.append(DaliGroup(
                number=grp_nr - 1,  # KNX-Gruppe 1 = DALI-Gruppe 0
                name=f"Gruppe {grp_nr}",
                ga_switch=info["switch"],
                ga_dim=info["dim"],
                ga_value=info["value"],
            ))

        if ko_groups:
            logger.info(
                f"DALI _derive_groups: {len(dali_gw.groups)} Gruppen aus KO-Namen "
                f"für Gateway '{dali_gw.name}'."
            )
        return len(dali_gw.groups)

    def _derive_evgs_from_import(
        self, dali_gw: DaliGateway, device, project
    ) -> int:
        """
        Leitet individuelle DALI-EVGs aus den KOs des importierten Gateway-Devices ab.

        Erkannte KO-Muster (herstellerübergreifend):
          "EVG 5 Schalten", "Betriebsgerät 3 Dimmen", "Einzelgerät 1 - Schalten",
          "Individual 2 On/Off", "Ballast 4 Dim", "Leuchte 7 Schalten", "Gear 1 Switch"

        Pro erkannter Nummer wird ein DaliDevice angelegt:
          - short_address: die Nummer direkt (0-basiert nach DALI-Standard)
          - name: Raumname + Element-Nr. aus GA-Bezeichnung (LDA_xxx_xx) oder
                  Fallback "EVG {addr}"
          - room_id: aus LDA-GA-Bezeichnung oder device.room_id

        Nur EVGs mit mind. einer verbundenen GA werden angelegt.
        EVGs mit identischer short_address werden dedupliziert.

        Gibt Anzahl angelegter EVGs zurück.
        """
        if not device.communication_objects:
            return 0

        # GA-Index für Bezeichnungs-Lookup
        ga_by_addr = {
            ga.address: ga
            for ga in project.group_addresses.all_addresses()
        }
        # Raum-Index: room_nr → room_id
        room_id_by_nr = {r.number: r.id for r in project.all_rooms}
        room_name_by_nr = {r.number: r.name for r in project.all_rooms}

        # EVG-Daten sammeln: short_addr → {switch, dim, value, room_id, name}
        evg_data: dict[int, dict] = {}

        for co in device.communication_objects:
            m = _KO_EVG_RE.search(co.name or "")
            if not m:
                continue
            # Keine GAs verbunden → EVG nicht anlegen (wahrscheinlich nicht programmiert)
            if not co.connected_gas:
                continue

            raw_nr = int(m.group(1))
            func_raw = m.group(2).lower()

            # DALI-Adressierung: Hersteller verwenden meist 1-basierte Labels
            # (EVG 1 = short_address 0). Wenn raw_nr == 0 → 0-basiert, direkt übernehmen.
            short_addr = raw_nr - 1 if raw_nr > 0 else 0

            if short_addr not in evg_data:
                evg_data[short_addr] = {
                    "switch": "", "dim": "", "value": "",
                    "room_id": device.room_id or "",
                    "name": "",
                }

            ga_addr = co.connected_gas[0]
            if any(k in func_raw for k in ("schalten", "switch", "on")):
                evg_data[short_addr]["switch"] = ga_addr
            elif any(k in func_raw for k in ("dimmen", "dim", "relativ")):
                evg_data[short_addr]["dim"] = ga_addr
            elif any(k in func_raw for k in ("wert", "value", "helligkeit")):
                evg_data[short_addr]["value"] = ga_addr

            # Raum aus GA-Bezeichnung ableiten (LDA_xxx_xx → room_nr)
            if not evg_data[short_addr]["room_id"]:
                ga_obj = ga_by_addr.get(ga_addr)
                if ga_obj and ga_obj.designation:
                    lda_m = _LDA_PREFIX_RE.match(ga_obj.designation.strip())
                    if lda_m:
                        room_nr = lda_m.group(1)
                        evg_data[short_addr]["room_id"] = room_id_by_nr.get(room_nr, "")

            # Name aus Raumname + Element-Nr. ableiten
            if not evg_data[short_addr]["name"]:
                ga_obj = ga_by_addr.get(ga_addr)
                if ga_obj and ga_obj.designation:
                    lda_m = _LDA_PREFIX_RE.match(ga_obj.designation.strip())
                    if lda_m:
                        room_nr = lda_m.group(1)
                        elem_nr = lda_m.group(2)
                        room_name = room_name_by_nr.get(room_nr, f"Raum {room_nr}")
                        evg_data[short_addr]["name"] = (
                            room_name if elem_nr == "01"
                            else f"{room_name} {elem_nr}"
                        )

        # DaliDevice-Einträge anlegen
        existing_addrs = {d.short_address for d in dali_gw.devices}
        added = 0
        for short_addr in sorted(evg_data):
            if short_addr in existing_addrs:
                continue
            info = evg_data[short_addr]
            name = info["name"] or f"EVG {short_addr}"
            dali_gw.devices.append(DaliDevice(
                short_address=short_addr,
                name=name,
                room_id=info["room_id"],
            ))
            added += 1

        if added:
            logger.info(
                f"DALI _derive_evgs: {added} EVGs aus KO-Namen abgeleitet "
                f"für Gateway '{dali_gw.name}'."
            )
        return added
