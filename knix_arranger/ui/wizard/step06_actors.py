"""
Wizard Schritt 6: Aktor-Ermittlung (liniengerecht)
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView, QGroupBox,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ...models.project import KnxProject
from ...models.building import ActorAssignment
from ...models.material_list import MaterialEntry
from ...services.actor_service import ActorService
from ...services.topology_engine import TopologyEngine
from ..column_utils import fit_columns

logger = logging.getLogger("knix_arranger.step06_actors")


class Step06Actors(QWidget):
    """Berechnete Aktoren pro Linie anzeigen (FA-1300)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)

        info = QLabel(
            "Die benötigten Aktoren werden automatisch aus den\n"
            "Gewerk-Zuweisungen berechnet und liniengerecht verteilt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        self._btn_calculate = QPushButton("Aktoren berechnen")
        self._btn_calculate.clicked.connect(self._calculate)
        btn_layout.addWidget(self._btn_calculate)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        self._no_topology_hint = QLabel(
            "Hinweis: Keine Topologie vorhanden. "
            "Bitte zuerst in Schritt 6 die Topologie berechnen."
        )
        self._no_topology_hint.setStyleSheet("color: #E67E22; font-weight: bold;")
        self._no_topology_hint.setWordWrap(True)
        self._no_topology_hint.setVisible(False)
        layout.addWidget(self._no_topology_hint)

        # Baum: Linien > Aktoren
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels([
            "Linie / Aktor", "Typ", "Kanäle", "Gewerke", "Einbauort",
        ])
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setRootIsDecorated(True)
        layout.addWidget(self._tree)

        # Materialliste (FA-1306)
        mat_group = QGroupBox("Materialliste Aktoren")
        mat_layout = QVBoxLayout()
        self._mat_tree = QTreeWidget()
        self._mat_tree.itemExpanded.connect(lambda _: fit_columns(self._mat_tree))
        self._mat_tree.setHeaderLabels(["Typ", "Anzahl", "Hersteller", "Artikelnummer"])
        self._mat_tree.setMaximumHeight(160)
        self._mat_tree.setAlternatingRowColors(True)
        self._mat_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._mat_tree.setRootIsDecorated(False)
        mat_layout.addWidget(self._mat_tree)

        btn_mat_transfer = QPushButton("In Projekt-Materialliste übernehmen →")
        btn_mat_transfer.setToolTip(
            "Alle ermittelten Aktoren in die Projekt-Materialliste eintragen (FA-2305)"
        )
        btn_mat_transfer.clicked.connect(self._transfer_to_material_list)
        mat_layout.addWidget(btn_mat_transfer)

        mat_group.setLayout(mat_layout)
        layout.addWidget(mat_group)

    def on_enter(self):
        # Falls noch keine Topologie vorhanden, automatisch aus Gebäudestruktur ableiten
        if not self._project.topology.areas and self._project.areal.buildings:
            engine = TopologyEngine(self._project.config.topology_mode)
            self._project.topology = engine.calculate_topology(self._project.areal)

        rooms = self._project.all_rooms
        has_gewerke = any(r.gewerk_assignments for r in rooms)
        if has_gewerke:
            self._calculate()

    def _calculate(self):
        service = ActorService()
        catalog = self._project.gewerk_catalog
        topology = self._project.topology

        self._tree.clear()

        if not topology.areas:
            self._no_topology_hint.setVisible(True)
            self._summary.setText("")
            return

        self._no_topology_hint.setVisible(False)

        all_rooms = self._project.all_rooms
        try:
            line_results = service.determine_actors_per_line(
                topology, all_rooms, catalog,
            )
        except Exception:
            logger.exception("Fehler bei Aktor-Ermittlung")
            QMessageBox.warning(
                self, "Fehler bei Aktor-Ermittlung",
                "Die Aktor-Ermittlung ist fehlgeschlagen.\n"
                "Bitte prüfen Sie die Topologie und die Gewerk-Zuweisungen.",
            )
            return

        total_actors = 0
        total_lines = 0
        bold_font = QFont()
        bold_font.setBold(True)

        # Room-ID → Room Lookup für Verteiler-Zuweisung
        room_by_id = {r.id: r for r in all_rooms}

        # Line-coupler_address → Line Lookup
        line_by_address = {
            line.coupler_address: line
            for area in topology.areas
            for line in area.lines
        }

        # Verteiler-Zuweisung: vor dem Befüllen alle betroffenen VT leeren
        cleared_vt_ids: set[str] = set()

        for result in line_results:
            num_actors = len(result.actors)
            total_actors += num_actors
            total_lines += 1

            # Verteiler der Linie ermitteln (erster Raum mit Verteiler)
            line_obj = line_by_address.get(result.coupler_address)
            target_vt = None
            if line_obj:
                for rid in line_obj.assigned_room_ids:
                    room = room_by_id.get(rid)
                    if room and room.has_verteiler:
                        target_vt = room.verteiler[0]
                        break

            vt_label = (
                f"{target_vt.verteiler_type} {target_vt.name}".strip()
                if target_vt else "–"
            )

            # Linien-Knoten
            line_item = QTreeWidgetItem(self._tree, [
                f"Linie {result.coupler_address} - {result.line_name}",
                f"{result.device_count} Geräte",
                f"{num_actors} Aktoren",
                "",
                vt_label,
            ])
            line_item.setFont(0, bold_font)
            line_item.setExpanded(True)

            # Anforderungen als Unter-Knoten
            if result.requirements:
                req_item = QTreeWidgetItem(line_item, [
                    "Anforderungen", "", "", "", "",
                ])
                req_item.setFont(0, bold_font)
                for req in result.requirements:
                    QTreeWidgetItem(req_item, [
                        "",
                        req.actor_type,
                        f"{req.channels_needed} Kanäle",
                        ", ".join(req.gewerk_codes),
                        "",
                    ])
                req_item.setExpanded(True)

            # Vorgeschlagene Aktoren als Unter-Knoten
            if result.actors:
                actor_item = QTreeWidgetItem(line_item, [
                    "Vorgeschlagene Aktoren", "", "", "", "",
                ])
                actor_item.setFont(0, bold_font)
                for actor in result.actors:
                    QTreeWidgetItem(actor_item, [
                        "",
                        actor.actor_type,
                        str(actor.channels),
                        actor.product.manufacturer or "-",
                        vt_label,
                    ])
                actor_item.setExpanded(True)

            # Verteiler-Zuweisung: Aktoren in den Verteiler eintragen
            if target_vt:
                if target_vt.id not in cleared_vt_ids:
                    target_vt.actor_assignments = []
                    cleared_vt_ids.add(target_vt.id)
                for actor in result.actors:
                    target_vt.actor_assignments.append(ActorAssignment(
                        actor_type=actor.actor_type,
                        manufacturer=actor.product.manufacturer,
                        order_number=actor.product.order_number,
                        product_name=actor.product.product_name,
                    ))

        fit_columns(self._tree)

        self._summary.setText(
            f"{total_lines} Linien, "
            f"{total_actors} Aktoren insgesamt vorgeschlagen"
        )

        # Aktoren und Sensoren in die Topologie persistieren (für Views/Berichte).
        # Importierte Topologien (XLSX/knxproj) bleiben unverändert (FA-ImportGuard).
        if not topology.is_imported:
            engine = TopologyEngine(self._project.config.topology_mode)
            engine.populate_devices(
                topology, all_rooms, catalog,
                small_project=(topology.topology_mode == "TP-64"),
                preserve_manual=True,
            )

        # Materialliste aggregieren und anzeigen (FA-1306)
        all_actors = [actor for r in line_results for actor in r.actors]
        material = service.create_material_list(all_actors)
        self._mat_tree.clear()
        for entry in material:
            QTreeWidgetItem(self._mat_tree, [
                entry["actor_type"],
                str(entry["quantity"]),
                entry.get("manufacturer") or "–",
                entry.get("order_number") or "–",
            ])
        fit_columns(self._mat_tree)

    def _transfer_to_material_list(self):
        """
        Überträgt alle berechneten Aktoren in die Projekt-Materialliste (FA-2305).

        Liest direkt aus der Topologie, damit physikalische Adressen
        (B.L.T) pro Gerät übernommen werden können (FA-2309).
        """
        topology = self._project.topology
        if not topology.areas:
            QMessageBox.information(
                self, "Keine Aktoren",
                "Bitte zuerst die Aktoren berechnen.",
            )
            return

        ml = self._project.material_list
        ml.clear_auto_entries()  # vorherige Wizard-Einträge entfernen

        total_entries = 0
        for area in topology.areas:
            for line in area.lines:
                # Alle Aktor-Devices dieser Linie
                actor_devices = [d for d in line.devices if d.device_type == "actor"]
                if not actor_devices:
                    continue

                # Pro Linie nach Produkttyp gruppieren
                by_type: dict[str, list] = {}
                for device in actor_devices:
                    key = f"{device.product}|{device.manufacturer}|{device.order_number}"
                    by_type.setdefault(key, []).append(device)

                line_label = f"{line.coupler_address} {line.name}".strip()

                for devices in by_type.values():
                    addresses = [
                        d.physical_address for d in devices if d.physical_address
                    ]
                    # FA-1308: Gateways in eigener Kategorie führen
                    if devices[0].device_type == "gateway":
                        category = "Gateway / Schnittstellen"
                    else:
                        category = "Aktor"
                    entry = MaterialEntry(
                        quantity=len(devices),
                        category=category,
                        device_type=devices[0].product,
                        manufacturer=devices[0].manufacturer,
                        order_number=devices[0].order_number,
                        product_name=devices[0].product,
                        source="wizard_auto",
                        line_id=line.id,
                        line_name=line_label,
                        physical_addresses=addresses,
                    )
                    ml.entries.append(entry)
                    total_entries += 1

        QMessageBox.information(
            self, "Materialliste aktualisiert",
            f"{total_entries} Aktor-Position(en) mit physikalischen Adressen\n"
            f"in die Projekt-Materialliste übertragen.\n"
            f"Die Materialliste ist über die Sidebar zugänglich.",
        )
