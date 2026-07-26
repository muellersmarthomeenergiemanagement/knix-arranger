"""
Topologie-Ansicht (FA-200, FA-1007) – editierbar in der manuellen Phase.

Ermöglicht dem Integrator:
- Linien umbenennen / UV-Einbauort anpassen
- Geräte-Einbauort bearbeiten
- Geräte zwischen Linien verschieben

Alle Änderungen werden sofort über den ProjectBus propagiert.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLabel,
    QHBoxLayout, QMenu, QInputDialog, QMessageBox, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from ...models.topology import Topology, Area, Line, Device
from ...services.belegungsplan_service import _extract_channel_label, group_actor_rows_by_channel
from ..column_utils import fit_columns

# Farben für Infrastruktur-Knoten
_COLOR_COUPLER     = QColor("#1565C0")  # Dunkelblau: Koppler
_COLOR_POWER       = QColor("#2E7D32")  # Dunkelgrün: Speisegerät
_COLOR_PROGRAMMED  = QColor("#4527A0")  # Violett: physikalisch programmiert (Adresse fixiert)
_COLOR_SECURE_MISSING = QColor("#C62828")  # Rot: Gerät unterstützt kein KNX Secure (FA-2704)

# UserRole-Schlüssel für Baumdaten
_ROLE_DATA = Qt.UserRole


class TopologyView(QWidget):
    """Topologie-Prinzipschema als Baumansicht – editierbar."""

    topology_changed = Signal()   # nach jeder manuellen Änderung

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topology: Topology | None = None
        self._bus = None
        self._knx_secure = None  # KnxSecureConfig, siehe set_knx_secure() (FA-2704)
        self._ga_structure = None  # GroupAddressStructure, siehe set_group_addresses()
        self._belegungsplan = None  # BelegungsplanData, siehe set_project() -- Kanalanzeige Aktoren

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Topologie")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        # Toolbar
        toolbar = QHBoxLayout()
        self._btn_expand_all = QPushButton("Alle aufklappen")
        self._btn_expand_all.setToolTip("Alle Bereiche und Linien aufklappen")
        self._btn_expand_all.clicked.connect(self._expand_all)
        self._btn_collapse_all = QPushButton("Alle zuklappen")
        self._btn_collapse_all.setToolTip("Alle Linien zuklappen (Bereiche bleiben sichtbar)")
        self._btn_collapse_all.clicked.connect(self._collapse_all)
        toolbar.addWidget(self._btn_expand_all)
        toolbar.addWidget(self._btn_collapse_all)
        toolbar.addStretch()
        hint = QLabel("Doppelklick: Einbauort bearbeiten  ·  Rechtsklick: weitere Optionen")
        hint.setStyleSheet("color: #808080; font-style: italic;")
        toolbar.addWidget(hint)
        layout.addLayout(toolbar)

        self._legend = QLabel()
        self._legend.setStyleSheet("font-size: 11px; color: #666;")
        self._update_legend()
        layout.addWidget(self._legend)

        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels([
            "Element", "Adresse", "Geräte", "Einbauort", "Details",
        ])
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

    # ── API ──

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    def set_topology(self, topology: Topology):
        self._topology = topology
        self._refresh()

    def set_knx_secure(self, knx_secure_config) -> None:
        """Verbindet die View mit der KNX-Secure-Konfiguration (FA-2704).

        Bei aktiviertem KNX Secure werden Geräte, die laut KNXPROD-Daten kein
        KNX Secure unterstützen, in der Topologie-Ansicht rot markiert --
        bisher war das nur im separaten KNX-Secure-Modul sichtbar.
        """
        self._knx_secure = knx_secure_config
        self._update_legend()
        if self._topology is not None:
            self._refresh()

    def set_group_addresses(self, ga_structure) -> None:
        """Verbindet die View mit der GA-Struktur, um Kanal-Gruppenadressen
        unter Aktoren anzuzeigen (FA-1007 Kanal-Anzeige)."""
        self._ga_structure = ga_structure
        if self._topology is not None:
            self._refresh()

    def set_project(self, project) -> None:
        """Verbindet die View mit dem vollständigen Projekt (FA-1007 Kanal-Anzeige).

        Berechnet den Belegungsplan (dieselbe Datenquelle wie Verknüpfungsmatrix/
        Belegungsplan-Export), damit die Kanalknoten unter Aktoren auch in
        Wizard-Projekten (Gewerk-/GA-basiert, ohne populierte
        Device.communication_objects) korrekt gruppiert und mit Gewerk-Kontext
        beschriftet werden -- nicht nur bei ETS6-Importen mit echten COs.
        """
        from ...services.belegungsplan_service import BelegungsplanService
        self._topology = project.topology
        self._knx_secure = project.knx_secure
        self._ga_structure = project.group_addresses
        self._belegungsplan = BelegungsplanService().generate(project)
        self._update_legend()
        self._refresh()

    def _update_legend(self) -> None:
        parts = [
            f"<span style='color:{_COLOR_COUPLER.name()};'>&#9679;</span> Koppler (BK/LK)",
            f"<span style='color:{_COLOR_POWER.name()};'>&#9679;</span> Speisegerät (SV)",
            f"<span style='color:{_COLOR_PROGRAMMED.name()};'>&#9679;</span> [P] physikalisch programmiert (Adresse gesperrt)",
        ]
        if self._knx_secure and self._knx_secure.enabled:
            parts.append(
                f"<span style='color:{_COLOR_SECURE_MISSING.name()};'>&#9679;</span> "
                "kein KNX Secure (FA-2704)"
            )
        self._legend.setText("&nbsp;&nbsp;".join(parts))

    # ── Baum aufbauen ──

    def _save_tree_state(self) -> tuple[set, set, str | None]:
        """
        Gibt (expanded_area_ids, expanded_line_ids, selected_id) zurück.
        selected_id = device.id | line.id | area.id des selektierten Items.
        """
        expanded_areas: set[str] = set()
        expanded_lines: set[str] = set()
        selected_id: str | None = None

        sel = self._tree.currentItem()
        if sel:
            d = sel.data(0, _ROLE_DATA)
            if d:
                kind = d[0]
                if kind == "area":
                    selected_id = d[1].id
                elif kind == "line":
                    selected_id = d[2].id
                elif kind == "device":
                    selected_id = d[3].id

        root = self._tree.invisibleRootItem()
        for ai in range(root.childCount()):
            area_item = root.child(ai)
            d = area_item.data(0, _ROLE_DATA)
            if d and area_item.isExpanded():
                expanded_areas.add(d[1].id)
            for li in range(area_item.childCount()):
                line_item = area_item.child(li)
                ld = line_item.data(0, _ROLE_DATA)
                if ld and ld[0] == "line" and line_item.isExpanded():
                    expanded_lines.add(ld[2].id)

        return expanded_areas, expanded_lines, selected_id

    def _restore_tree_state(
        self,
        expanded_areas: set[str],
        expanded_lines: set[str],
        selected_id: str | None,
    ) -> None:
        """Stellt Expand-Zustand und Selektion nach einem Rebuild wieder her."""
        root = self._tree.invisibleRootItem()
        for ai in range(root.childCount()):
            area_item = root.child(ai)
            d = area_item.data(0, _ROLE_DATA)
            if not d:
                continue
            area_id = d[1].id
            # Bereiche: aufgeklappt wenn vorher aufgeklappt ODER noch kein State gespeichert
            should_expand = (area_id in expanded_areas) or (not expanded_areas)
            area_item.setExpanded(should_expand)
            if selected_id and area_id == selected_id:
                self._tree.setCurrentItem(area_item)

            for li in range(area_item.childCount()):
                line_item = area_item.child(li)
                ld = line_item.data(0, _ROLE_DATA)
                if not ld:
                    continue
                if ld[0] == "line":
                    line_id = ld[2].id
                    line_item.setExpanded(
                        (line_id in expanded_lines) or (not expanded_lines)
                    )
                    if selected_id and line_id == selected_id:
                        self._tree.setCurrentItem(line_item)
                    # Geräte-Selektion wiederherstellen
                    for di in range(line_item.childCount()):
                        dev_item = line_item.child(di)
                        dd = dev_item.data(0, _ROLE_DATA)
                        if dd and dd[0] == "device" and selected_id and dd[3].id == selected_id:
                            self._tree.setCurrentItem(dev_item)

    def _refresh(self):
        # ── Zustand sichern ──
        expanded_areas, expanded_lines, selected_id = self._save_tree_state()
        vscroll = self._tree.verticalScrollBar().value()

        self._tree.setUpdatesEnabled(False)
        self._tree.clear()
        if not self._topology:
            self._tree.setUpdatesEnabled(True)
            return

        total_areas   = len(self._topology.areas)
        total_lines   = sum(len(a.lines) for a in self._topology.areas)
        total_devices = sum(
            l.device_count for a in self._topology.areas for l in a.lines
        )
        self._info.setText(
            f"Modus: {self._topology.topology_mode} | "
            f"{total_areas} Bereiche, {total_lines} Linien, "
            f"{total_devices} Geräte  –  Rechtsklick zum Bearbeiten"
        )

        ga_by_address = (
            {ga.address: ga for ga in self._ga_structure.all_addresses()}
            if self._ga_structure else {}
        )

        for area in self._topology.areas:
            area_devices = sum(l.device_count for l in area.lines)
            area_item = QTreeWidgetItem(self._tree, [
                f"Bereich {area.area_number} - {area.name}",
                area.coupler_address,
                str(area_devices),
                "",
                f"{len(area.lines)} Linien, Backbone: {area.backbone_type}",
            ])
            area_item.setData(0, _ROLE_DATA, ("area", area))
            # Expand-Zustand wird in _restore_tree_state gesetzt

            # FA-1007: Bereichskoppler
            if total_areas > 1:
                bk_device = next(
                    (d for d in (area.lines[0].devices if area.lines else [])
                     if d.device_type == "coupler" and d.product == "Bereichskoppler"),
                    None,
                )
                bk_location = bk_device.installation_location if bk_device else ""
                bk_detail_parts = []
                if bk_device and bk_device.manufacturer:
                    bk_detail_parts.append(bk_device.manufacturer)
                if bk_device and bk_device.order_number:
                    bk_detail_parts.append(bk_device.order_number)
                bk_item = QTreeWidgetItem(area_item, [
                    "Bereichskoppler (BK)",
                    area.coupler_address,
                    "", bk_location,
                    " | ".join(bk_detail_parts) if bk_detail_parts
                    else "Verbindet Bereichslinie mit Backbone",
                ])
                if bk_device:
                    bk_item.setData(0, _ROLE_DATA, ("device", area, area.lines[0] if area.lines else None, bk_device))
                self._colorize(bk_item, _COLOR_COUPLER)

            # FA-1007: Speisegerät Bereichslinie
            if area.backbone_power_supply is not None:
                sv_dev = area.backbone_power_supply
                sv_detail_parts = []
                if sv_dev.manufacturer:
                    sv_detail_parts.append(sv_dev.manufacturer)
                if sv_dev.order_number:
                    sv_detail_parts.append(sv_dev.order_number)
                sv_area_item = QTreeWidgetItem(area_item, [
                    "Speisegerät Bereichslinie (SV)",
                    f"{area.area_number}.0.-",
                    "", sv_dev.installation_location,
                    " | ".join(sv_detail_parts) if sv_detail_parts
                    else "Spannungsversorgung der Bereichslinie",
                ])
                sv_area_item.setData(0, _ROLE_DATA, ("device", area, None, sv_dev))
                self._colorize(sv_area_item, _COLOR_POWER)

            for line in area.lines:
                status = ""
                if line.device_count > 100:
                    status = " [ÜBERLAST!]"
                elif line.device_count > 85:
                    status = " [Warnung]"

                line_item = QTreeWidgetItem(area_item, [
                    f"Linie {line.line_number} - {line.name}{status}",
                    line.coupler_address,
                    str(line.device_count),
                    line.uv_location or "",
                    "",
                ])
                line_item.setData(0, _ROLE_DATA, ("line", area, line))
                # Expand-Zustand wird in _restore_tree_state gesetzt

                # FA-1007: Linienkoppler
                if line.coupler_address:
                    lk_device = next(
                        (d for d in line.devices
                         if d.device_type == "coupler" and d.product == "Linienkoppler"),
                        None,
                    )
                    lk_location = lk_device.installation_location if lk_device else ""
                    lk_detail_parts = []
                    if lk_device and lk_device.manufacturer:
                        lk_detail_parts.append(lk_device.manufacturer)
                    if lk_device and lk_device.order_number:
                        lk_detail_parts.append(lk_device.order_number)
                    lk_item = QTreeWidgetItem(line_item, [
                        "Linienkoppler (LK)",
                        line.coupler_address,
                        "", lk_location,
                        " | ".join(lk_detail_parts) if lk_detail_parts
                        else "Verbindet Linie mit Bereichslinie",
                    ])
                    if lk_device:
                        lk_item.setData(0, _ROLE_DATA, ("device", area, line, lk_device))
                    self._colorize(lk_item, _COLOR_COUPLER)

                # FA-1007: Speisegerät Linie
                if line.recommended_power_supply:
                    sv_device = next(
                        (d for d in line.devices if d.device_type == "power_supply"),
                        None,
                    )
                    sv_location = sv_device.installation_location if sv_device else ""
                    sv_detail_parts = []
                    if sv_device and sv_device.manufacturer:
                        sv_detail_parts.append(sv_device.manufacturer)
                    if sv_device and sv_device.order_number:
                        sv_detail_parts.append(sv_device.order_number)
                    sv_line_item = QTreeWidgetItem(line_item, [
                        "Speisegerät (SV)",
                        f"{area.area_number}.{line.line_number}.-",
                        "", sv_location,
                        " | ".join(sv_detail_parts) if sv_detail_parts
                        else "Spannungsversorgung der Linie",
                    ])
                    if sv_device:
                        sv_line_item.setData(0, _ROLE_DATA, ("device", area, line, sv_device))
                    self._colorize(sv_line_item, _COLOR_POWER)

                # Reguläre Geräte
                for device in line.devices:
                    if device.device_type in ("coupler", "power_supply"):
                        continue
                    detail_parts = []
                    if device.manufacturer:
                        detail_parts.append(device.manufacturer)
                    if device.order_number:
                        detail_parts.append(device.order_number)
                    if device.serial_number:
                        detail_parts.append(f"SN: {device.serial_number}")

                    name = device.product or device.device_type
                    status = " | ".join(detail_parts)
                    if device.is_programmed:
                        name = f"[P] {name}"
                        if not status:
                            status = "Adresse programmiert – gesperrt"

                    dev_item = QTreeWidgetItem(line_item, [
                        name,
                        device.physical_address,
                        "",
                        device.installation_location,
                        status,
                    ])
                    dev_item.setData(0, _ROLE_DATA, ("device", area, line, device))

                    # FA-2704: Secure-inkompatible Geräte rot markieren (nur
                    # wenn KNX Secure aktiv ist und die Kompatibilität bereits
                    # geprüft wurde -- ungeprüfte Geräte werden nicht geraten).
                    secure_missing = False
                    if self._knx_secure and self._knx_secure.enabled:
                        info = self._knx_secure.device_infos.get(device.id)
                        secure_missing = bool(info and not info.secure_supported)

                    if secure_missing:
                        self._colorize(dev_item, _COLOR_SECURE_MISSING)
                        dev_item.setToolTip(
                            0, "Gerät unterstützt laut KNXPROD-Daten kein KNX Secure (FA-2704)"
                        )
                    elif device.is_programmed:
                        self._colorize(dev_item, _COLOR_PROGRAMMED)

                    # FA-1007: Kanäle unter Aktoren anzeigen -- gruppiert nach
                    # physischem Kanal (nicht nach Befehlstyp, siehe
                    # _extract_channel_label), damit z.B. Schalten/Sperren/
                    # Status desselben Ausgangs A zusammen erscheinen.
                    if device.device_type == "actor":
                        self._add_channel_items(dev_item, device, ga_by_address)

        fit_columns(self._tree)

        # ── Zustand wiederherstellen ──
        self._restore_tree_state(expanded_areas, expanded_lines, selected_id)
        self._tree.setUpdatesEnabled(True)
        self._tree.verticalScrollBar().setValue(vscroll)

    def _add_channel_items(self, dev_item: QTreeWidgetItem, device: Device,
                            ga_by_address: dict) -> None:
        """Fügt Kanal-Kindknoten mit ihren Gruppenadressen unter einem Aktor ein.

        Bevorzugt die Belegungsplan-Daten (self._belegungsplan.actor_rows): in
        Wizard-Projekten (Gewerk-/GA-basiert) ist Device.communication_objects
        meist leer -- die einzige Quelle mit korrekter Kanal-Zuordnung samt
        Gewerk-Kontext ist dort BelegungsplanService. Fällt auf die rohen COs
        zurück, wenn kein Belegungsplan vorliegt oder das Gerät dort keine
        Zeilen hat (z.B. reine ETS6-Importe ohne Gewerk-Zuordnung -- dort greift
        der CO-Fallback in belegungsplan_service._collect_actor_rows bereits,
        und dessen Zeilen erscheinen dann ebenfalls unter self._belegungsplan).
        """
        if self._belegungsplan is not None:
            rows = [r for r in self._belegungsplan.actor_rows
                    if r.physical_address == device.physical_address]
            if rows:
                self._add_channel_items_from_rows(dev_item, rows)
                return
        self._add_channel_items_from_cos(dev_item, device, ga_by_address)

    @staticmethod
    def _add_channel_items_from_rows(dev_item: QTreeWidgetItem, rows: list) -> None:
        """Kanalknoten aus BelegungsplanService.actor_rows -- inkl. Gewerk-Kontext,
        damit auch bei mehreren Gewerken auf demselben Kanal klar ist, welche
        GA wozu gehört (z.B. Jalousieaktor mit Auf/Ab UND Sperren desselben
        Gewerks am selben Ausgang)."""
        for ch_num, ch_rows in group_actor_rows_by_channel(rows):
            first = ch_rows[0]
            context = " / ".join(p for p in [first.gewerk_code, first.room_name] if p)
            label = f"Kanal {ch_num}" + (f" – {context}" if context else "")
            ch_item = QTreeWidgetItem(dev_item, [
                label, "", "", "", f"{len(ch_rows)} GA(s)",
            ])
            ch_item.setForeground(0, QColor("#616161"))
            for r in ch_rows:
                gewerk_prefix = f"{r.gewerk_code} " if r.gewerk_code else ""
                QTreeWidgetItem(ch_item, [
                    f"{gewerk_prefix}{r.function_name}: {r.ga_designation}",
                    r.ga_address,
                    "",
                    "",
                    r.dpt,
                ])

    @staticmethod
    def _add_channel_items_from_cos(dev_item: QTreeWidgetItem, device: Device,
                                     ga_by_address: dict) -> None:
        """Kanalknoten direkt aus Device.communication_objects (ETS6-Import-
        Fallback ohne Belegungsplan). Gruppierung per
        _extract_channel_label(co.name) -- fällt auf die CO-Objektnummer
        zurück, wenn kein Kanal aus dem Namen erkennbar ist.
        """
        cos_with_ga = [co for co in sorted(device.communication_objects,
                                            key=lambda c: c.object_number)
                       if co.connected_gas]
        if not cos_with_ga:
            return

        channel_groups: dict[str, list] = {}
        for co in cos_with_ga:
            label = _extract_channel_label(co.name) or f"CO {co.object_number}"
            channel_groups.setdefault(label, []).append(co)

        for label, cos in channel_groups.items():
            ga_count = sum(len(co.connected_gas) for co in cos)
            ch_item = QTreeWidgetItem(dev_item, [
                label, "", "", "", f"{ga_count} GA(s)",
            ])
            ch_item.setForeground(0, QColor("#616161"))
            for co in cos:
                for ga_addr in co.connected_gas:
                    ga_obj = ga_by_address.get(ga_addr)
                    label_text = ga_obj.designation if ga_obj else ga_addr
                    QTreeWidgetItem(ch_item, [
                        f"{co.name or co.object_function}: {label_text}",
                        ga_addr,
                        "",
                        "",
                        ga_obj.datapoint_type if ga_obj else "",
                    ])

    # ── Toolbar-Aktionen ──

    def _expand_all(self):
        self._tree.expandAll()
        fit_columns(self._tree)

    def _collapse_all(self):
        """Linien zuklappen – Bereiche bleiben aufgeklappt."""
        self._tree.setUpdatesEnabled(False)
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            area_item = root.child(i)
            area_item.setExpanded(True)
            for j in range(area_item.childCount()):
                area_item.child(j).setExpanded(False)
        self._tree.setUpdatesEnabled(True)
        fit_columns(self._tree)

    # ── Interaktion ──

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, _ROLE_DATA)
        if not data:
            return

        kind = data[0]
        menu = QMenu(self)
        global_pos = self._tree.viewport().mapToGlobal(pos)

        if kind == "area":
            _, area = data
            rename_act = menu.addAction("Bereich umbenennen…")
            action = menu.exec(global_pos)
            if action == rename_act:
                self._rename_area(area)

        elif kind == "line":
            _, area, line = data
            rename_act  = menu.addAction("Linie umbenennen…")
            uv_act      = menu.addAction("UV-Einbauort bearbeiten…")
            action = menu.exec(global_pos)
            if action == rename_act:
                self._rename_line(line)
            elif action == uv_act:
                self._edit_line_uv(line)

        elif kind == "device":
            _, area, line, device = data
            loc_act = menu.addAction("Einbauort bearbeiten…")
            addr_act = None
            move_act = None
            if device.device_type not in ("coupler", "power_supply"):
                addr_act = menu.addAction("Physikalische Adresse bearbeiten…")
                if line is not None:
                    move_act = menu.addAction("Auf andere Linie verschieben…")
            menu.addSeparator()
            if device.is_programmed:
                prog_act = menu.addAction("Programmierung aufheben…")
            else:
                prog_act = menu.addAction("Als programmiert markieren")
            action = menu.exec(global_pos)
            if action == loc_act:
                self._edit_device_location(device)
            elif addr_act and action == addr_act:
                self._edit_physical_address(device, line)
            elif move_act and action == move_act:
                self._move_device(device, line)
            elif action == prog_act:
                self._toggle_programmed(device)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Doppelklick: Einbauort bearbeiten (schnellste Aktion)."""
        data = item.data(0, _ROLE_DATA)
        if not data:
            return
        kind = data[0]
        if kind == "line":
            _, area, line = data
            self._edit_line_uv(line)
        elif kind == "device":
            _, area, line, device = data
            self._edit_device_location(device)

    # ── Editier-Aktionen ──

    def _rename_area(self, area: Area):
        name, ok = QInputDialog.getText(
            self, "Bereich umbenennen",
            "Neuer Bereichsname:", text=area.name,
        )
        if ok and name.strip():
            if self._bus:
                self._bus.begin_change(f"Bereich {area.area_number} umbenennen")
            area.name = name.strip()
            self._refresh()
            self._emit_changed()

    def _rename_line(self, line: Line):
        name, ok = QInputDialog.getText(
            self, "Linie umbenennen",
            "Neuer Linienname:", text=line.name,
        )
        if ok and name.strip():
            if self._bus:
                self._bus.begin_change(f"Linie {line.line_number} umbenennen")
            line.name = name.strip()
            self._refresh()
            self._emit_changed()

    def _edit_line_uv(self, line: Line):
        loc, ok = QInputDialog.getText(
            self, "UV-Einbauort bearbeiten",
            f"Einbauort für Linie {line.line_number} – {line.name}:",
            text=line.uv_location or "",
        )
        if ok:
            if self._bus:
                self._bus.begin_change(f"UV-Einbauort Linie {line.line_number} bearbeiten")
            line.uv_location = loc.strip()
            self._refresh()
            self._emit_changed()

    def _edit_device_location(self, device: Device):
        loc, ok = QInputDialog.getText(
            self, "Einbauort bearbeiten",
            f"Einbauort für »{device.product or device.device_type}«:",
            text=device.installation_location,
        )
        if ok:
            if self._bus:
                self._bus.begin_change(
                    f"Einbauort »{device.product or device.device_type}« bearbeiten"
                )
            device.installation_location = loc.strip()
            self._refresh()
            self._emit_changed()

    def _edit_physical_address(self, device: Device, line: Line | None):
        """Setzt die physikalische Adresse manuell und schützt sie mit is_programmed."""
        current = device.physical_address or ""
        new_addr, ok = QInputDialog.getText(
            self, "Physikalische Adresse bearbeiten",
            f"Physikalische Adresse für »{device.product or device.device_type}«\n"
            f"Format: Bereich.Linie.Teilnehmer  (z.B. 1.1.5)\n"
            f"Die Adresse wird als programmiert markiert und bei\n"
            f"Neuberechnungen nicht mehr automatisch geändert.",
            text=current,
        )
        if not ok:
            return

        new_addr = new_addr.strip()
        # Format-Validierung
        parts = new_addr.split(".")
        if len(parts) != 3:
            QMessageBox.warning(self, "Ungültiges Format",
                                "Bitte im Format B.L.T eingeben, z.B. 1.1.5")
            return
        try:
            b, l, t = int(parts[0]), int(parts[1]), int(parts[2])
            if not (0 <= b <= 15 and 0 <= l <= 15 and 1 <= t <= 255):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Ungültige Adresse",
                                "Bereich 0–15, Linie 0–15, Teilnehmer 1–255")
            return

        # Konflikt-Prüfung: Adresse bereits auf dieser Linie vergeben?
        if line is not None:
            conflict = next(
                (d for d in line.devices
                 if d is not device and d.physical_address == new_addr),
                None,
            )
            if conflict:
                answer = QMessageBox.question(
                    self,
                    "Adresskollision",
                    f"Die Adresse {new_addr} ist bereits vergeben:\n"
                    f"»{conflict.product or conflict.device_type}«\n\n"
                    f"Trotzdem übernehmen?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return

        if self._bus:
            self._bus.begin_change(
                f"Physikalische Adresse »{device.product or device.device_type}« setzen"
            )
        device.physical_address = new_addr
        device.is_programmed = True
        device.manually_added = True   # Präfix-Update bei Linienwechsel aktivieren
        self._refresh()
        self._emit_changed()

    def _toggle_programmed(self, device: Device):
        """Wechselt den is_programmed-Status eines Geräts."""
        if device.is_programmed:
            answer = QMessageBox.question(
                self,
                "Programmierung aufheben",
                f"Programmierungs-Schutz für »{device.product or device.device_type}«\n"
                f"(Adresse {device.physical_address}) aufheben?\n\n"
                f"Das Gerät muss danach manuell neu programmiert werden,\n"
                f"wenn die Adresse vom Programm geändert wird.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            device.is_programmed = False
        else:
            device.is_programmed = True
        self._refresh()
        self._emit_changed()

    def _move_device(self, device: Device, from_line: Line):
        """Verschiebt ein Gerät auf eine andere Linie."""
        if device.is_programmed:
            QMessageBox.warning(
                self,
                "Verschieben nicht möglich",
                f"»{device.product or device.device_type}« (Adresse {device.physical_address})\n"
                f"ist als programmiert markiert.\n\n"
                f"Programmierte Geräte können nicht auf eine andere Linie verschoben\n"
                f"werden, da ihre physikalische Adresse fix im Gerät gespeichert ist.\n\n"
                f"Heben Sie zuerst die Programmierung über das Kontextmenü auf.",
            )
            return
        if not self._topology:
            return

        # Alle Linien außer der aktuellen als Auswahl aufbauen
        choices: list[tuple[str, Line]] = []
        for area in self._topology.areas:
            for line in area.lines:
                if line is from_line:
                    continue
                label = f"Bereich {area.area_number} / Linie {line.line_number} – {line.name}"
                choices.append((label, line))

        if not choices:
            return

        labels = [c[0] for c in choices]
        label, ok = QInputDialog.getItem(
            self, "Gerät verschieben",
            f"»{device.product or device.device_type}« verschieben nach:",
            labels, 0, False,
        )
        if not ok:
            return

        target_line = choices[labels.index(label)][1]

        if self._bus:
            self._bus.begin_change(
                f"»{device.product or device.device_type}« nach "
                f"Linie {target_line.line_number} – {target_line.name} verschieben"
            )

        # Gerät aus Quelllinie entfernen und in Ziellinie einfügen
        if device in from_line.devices:
            from_line.devices.remove(device)
        target_line.devices.append(device)

        self._refresh()
        self._emit_changed()

    def _emit_changed(self):
        self.topology_changed.emit()
        if self._bus:
            self._bus.emit_topology_changed()

    @staticmethod
    def _colorize(item: QTreeWidgetItem, color: QColor) -> None:
        """Setzt die Vordergrundfarbe aller Spalten eines Knotens."""
        for col in range(item.columnCount()):
            item.setForeground(col, color)
