"""
Wizard Schritt 8: Aktor-Ermittlung (liniengerecht)
"""
from __future__ import annotations
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView, QGroupBox,
    QMessageBox, QComboBox, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from ...models.project import KnxProject
from ...models.building import ActorAssignment
from ...models.material_list import MaterialEntry
from ...services.actor_service import ActorService
from ...services.topology_engine import TopologyEngine
from ...services.verteiler_service import (
    VerteilerPlacement, apply_device_locations, verteiler_label,
)
from .recompute_guard import RecomputeGuard, KEY_DEVICES
from ..column_utils import fit_columns

logger = logging.getLogger("knix_arranger.step06_actors")


class Step06Actors(QWidget):
    """Berechnete Aktoren pro Linie anzeigen (FA-1300)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        # Vom WizardController durch eine gemeinsame Instanz ersetzt
        self._guard = RecomputeGuard()

        layout = QVBoxLayout(self)

        info = QLabel(
            "Die benötigten Aktoren werden automatisch aus den "
            "Gewerk-Zuweisungen berechnet und liniengerecht verteilt.\n"
            "Einbauort: je Linie einen Verteiler wählen (Verteiler aus Schritt 4), "
            "einzelne Aktortypen können in einem anderen Verteiler sitzen – "
            "z.B. Jalousieaktoren in der UV des Stockwerks für kurze Leitungen."
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
            "Bitte zuerst in Schritt 7 die Topologie berechnen."
        )
        self._no_topology_hint.setStyleSheet("color: #E67E22; font-weight: bold;")
        self._no_topology_hint.setWordWrap(True)
        self._no_topology_hint.setVisible(False)
        layout.addWidget(self._no_topology_hint)

        self._offer_ready_hint = QLabel(
            "Tipp: Ab hier ist die Geräteliste vollständig genug für eine "
            "Kundenofferte. Materialliste und Kundenofferte finden Sie nach "
            "„Fertig“ im Hauptfenster (Seitenleiste)."
        )
        self._offer_ready_hint.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self._offer_ready_hint.setWordWrap(True)
        self._offer_ready_hint.setVisible(False)
        layout.addWidget(self._offer_ready_hint)

        # Gateways: gemeinsam für das Projekt oder je Linie (FA-1307)
        self._gateway_group = QGroupBox("Gateways")
        self._gateway_grid = QGridLayout(self._gateway_group)
        self._gateway_group.setVisible(False)
        layout.addWidget(self._gateway_group)

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
            "Alle ermittelten Aktoren in die Projekt-Materialliste eintragen"
        )
        btn_mat_transfer.clicked.connect(self._transfer_to_material_list)
        mat_layout.addWidget(btn_mat_transfer)

        mat_group.setLayout(mat_layout)
        layout.addWidget(mat_group)

    def on_enter(self):
        # Die Topologie entsteht ausschliesslich in Schritt 7 – fehlt sie,
        # zeigt _calculate() einen Hinweis statt still eine eigene zu berechnen.
        rooms = self._project.all_rooms
        has_gewerke = any(r.gewerk_assignments for r in rooms)
        if has_gewerke or not self._project.topology.areas:
            self._calculate()

    def _calculate(self):
        service = ActorService()
        catalog = self._project.gewerk_catalog
        topology = self._project.topology

        self._tree.clear()

        if not topology.areas:
            self._no_topology_hint.setVisible(True)
            self._offer_ready_hint.setVisible(False)
            self._summary.setText("")
            return

        self._no_topology_hint.setVisible(False)
        self._build_gateway_choices()

        all_rooms = self._project.all_rooms
        try:
            line_results = service.determine_actors_per_line(
                topology, all_rooms, catalog,
                shared=self._project.shared_gateways(),
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

        # Line-coupler_address → Line Lookup
        line_by_address = {
            line.coupler_address: line
            for area in topology.areas
            for line in area.lines
        }

        # Verteiler-Zuweisung: gewählter Verteiler je Linie bzw. Aktortyp
        placement = VerteilerPlacement(all_rooms)
        if not topology.is_imported:
            for vt, _room in placement.refs:
                vt.actor_assignments = []
        cleared_vt_ids: set[str] = {vt.id for vt, _room in placement.refs} \
            if not topology.is_imported else set()

        for result in line_results:
            num_actors = len(result.actors)
            total_actors += num_actors
            total_lines += 1

            line_obj = line_by_address.get(result.coupler_address)
            line_ref = placement.for_line(line_obj) if line_obj else None
            vt_label = verteiler_label(*line_ref) if line_ref else "–"

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
            if line_obj is not None and placement.refs and not topology.is_imported:
                default = placement.default_for_line(line_obj)
                self._tree.setItemWidget(line_item, 4, self._verteiler_combo(
                    placement, line_obj.verteiler_id,
                    f"automatisch: {verteiler_label(*default) if default else '–'}",
                    lambda vt_id, line=line_obj: self._set_line_verteiler(line, vt_id),
                ))

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
                    ref = (placement.for_actor(line_obj, actor.actor_type)
                           if line_obj else None)
                    row = QTreeWidgetItem(actor_item, [
                        "",
                        actor.actor_type,
                        str(actor.channels),
                        actor.product.manufacturer or "-",
                        verteiler_label(*ref) if ref else "–",
                    ])
                    if line_obj is not None and placement.refs and not topology.is_imported:
                        self._tree.setItemWidget(row, 4, self._verteiler_combo(
                            placement, line_obj.actor_verteiler.get(actor.actor_type, ""),
                            "wie Linie",
                            lambda vt_id, line=line_obj, t=actor.actor_type:
                                self._set_actor_verteiler(line, t, vt_id),
                        ))
                actor_item.setExpanded(True)

            # Verteiler-Zuweisung: Aktoren in ihren Verteiler eintragen
            for actor in result.actors:
                ref = placement.for_actor(line_obj, actor.actor_type) if line_obj else None
                if ref is None:
                    continue
                target_vt = ref[0]
                if target_vt.id not in cleared_vt_ids:
                    target_vt.actor_assignments = []
                    cleared_vt_ids.add(target_vt.id)
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
        self._offer_ready_hint.setVisible(total_actors > 0)

        # Aktoren und Sensoren in die Topologie persistieren (für Views/Berichte).
        # Importierte Topologien (XLSX/knxproj) bleiben unverändert (FA-ImportGuard).
        # Nur wenn sich Räume/Aktoren/Topologie seit dem letzten Lauf geändert haben.
        if not topology.is_imported and self._guard.is_stale(self._project, KEY_DEVICES):
            engine = TopologyEngine(self._project.config.topology_mode)
            engine.populate_devices(
                topology, all_rooms, catalog,
                small_project=(topology.topology_mode == "TP-64"),
                preserve_manual=True,
                shared_gateways=self._project.shared_gateways(),
            )
            self._guard.mark_done(self._project, KEY_DEVICES)
        apply_device_locations(topology, all_rooms)
        if not placement.refs and not topology.is_imported:
            self._summary.setText(
                self._summary.text() + " – keine Verteiler erfasst: Einbauort "
                "in Schritt 4 (Elektroverteilungen) festlegen")

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

    # ── Gateways: gemeinsam oder je Linie (FA-1307) ──

    def _build_gateway_choices(self) -> None:
        """Je Gateway-Gewerk im Projekt: gemeinsames Gateway für das Projekt
        (z.B. Revox, das die Zonen selbst einteilt) oder je Linie, und die
        Linie des gemeinsamen Gateways."""
        from ...models.device import GEWERK_TO_ACTOR_TYPE, GATEWAY_ACTOR_TYPES
        while self._gateway_grid.count():
            widget = self._gateway_grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        project = self._project
        imported = project.topology.is_imported
        rooms = project.all_rooms
        codes = sorted({a.gewerk_code for r in rooms for a in r.gewerk_assignments
                        if GEWERK_TO_ACTOR_TYPE.get(a.gewerk_code) in GATEWAY_ACTOR_TYPES})
        self._gateway_group.setVisible(bool(codes) and not imported)
        if not codes or imported:
            return
        lines = [(area, line) for area in project.topology.areas for line in area.lines
                 if line.assigned_room_ids]
        catalog = project.gewerk_catalog
        for row, code in enumerate(codes):
            gewerk = catalog.get(code)
            n_rooms = sum(1 for r in rooms if any(a.gewerk_code == code
                                                  for a in r.gewerk_assignments))
            self._gateway_grid.addWidget(QLabel(
                f"{code} – {gewerk.name if gewerk else code} ({n_rooms} Räume)"), row, 0)

            scope = QComboBox()
            scope.addItem("gemeinsam für das Projekt", "project")
            scope.addItem("je Linie", "line")
            shared = project.config.gateway_shared(code)
            scope.setCurrentIndex(0 if shared else 1)
            scope.setToolTip("Gemeinsam: ein Gateway für alle Räume dieses Gewerks, "
                             "z.B. Revox teilt die Zonen selbst ein. Je Linie: ein "
                             "Gateway auf jeder Linie mit Räumen dieses Gewerks.")
            scope.currentIndexChanged.connect(
                lambda _i, c=code, combo=scope: self._set_gateway_scope(c, combo.currentData()))
            self._gateway_grid.addWidget(scope, row, 1)

            line_combo = QComboBox()
            auto = ActorService.shared_gateway_line(project.topology, rooms, code)
            auto_text = (f"automatisch: Linie {auto[1].coupler_address} {auto[1].name}"
                         if auto else "automatisch")
            line_combo.addItem(auto_text, "")
            for _area, line in lines:
                line_combo.addItem(f"Linie {line.coupler_address} {line.name}", line.id)
            line_combo.setCurrentIndex(max(0, line_combo.findData(
                project.config.gateway_line.get(code, ""))))
            line_combo.setEnabled(shared)
            line_combo.setToolTip("Linie, auf der das gemeinsame Gateway sitzt "
                                  "(automatisch: Linie mit der HV)")
            line_combo.currentIndexChanged.connect(
                lambda _i, c=code, combo=line_combo: self._set_gateway_line(c, combo.currentData()))
            self._gateway_grid.addWidget(line_combo, row, 2)
        self._gateway_grid.setColumnStretch(3, 1)

    def _set_gateway_scope(self, code: str, scope: str) -> None:
        from ...models.project import SHARED_GATEWAY_DEFAULTS
        default = "project" if code in SHARED_GATEWAY_DEFAULTS else "line"
        if scope == default:
            self._project.config.gateway_scope.pop(code, None)
        else:
            self._project.config.gateway_scope[code] = scope
        QTimer.singleShot(0, self._calculate)

    def _set_gateway_line(self, code: str, line_id: str) -> None:
        if line_id:
            self._project.config.gateway_line[code] = line_id
        else:
            self._project.config.gateway_line.pop(code, None)
        QTimer.singleShot(0, self._calculate)

    def _verteiler_combo(self, placement: VerteilerPlacement, current_id: str,
                         auto_text: str, on_change) -> QComboBox:
        """Auswahl des Verteilers (erster Eintrag = automatisch / wie Linie)."""
        combo = QComboBox()
        combo.addItem(auto_text, "")
        for vt, room in placement.refs:
            combo.addItem(verteiler_label(vt, room), vt.id)
        combo.setCurrentIndex(max(0, combo.findData(current_id)))
        combo.currentIndexChanged.connect(lambda _i: on_change(combo.currentData() or ""))
        return combo

    def _set_line_verteiler(self, line, vt_id: str) -> None:
        line.verteiler_id = vt_id
        # Neu aufbauen erst nach dem Signal: _calculate() löscht die Auswahl selbst
        QTimer.singleShot(0, self._calculate)

    def _set_actor_verteiler(self, line, actor_type: str, vt_id: str) -> None:
        if vt_id:
            line.actor_verteiler[actor_type] = vt_id
        else:
            line.actor_verteiler.pop(actor_type, None)
        QTimer.singleShot(0, self._calculate)

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
