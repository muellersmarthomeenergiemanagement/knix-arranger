"""
Gebäudestruktur-Baumansicht (FA-101 bis FA-107)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QMenu, QInputDialog, QMessageBox, QDialog,
    QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
)
from PySide6.QtCore import Signal, Qt
from ...models.building import Areal, Building, Wing, Floor, Apartment, Room, Verteiler, STANDARD_FLOOR_NAMES
from ...models.topology import Topology
from ...services.building_service import BuildingService
from ...services.belegungsplan_service import (
    build_ga_by_designation, group_cos_for_display, resolve_ga_display,
)
from ...services.structure_move import (
    can_move_apartment, can_move_room, move_apartment, move_room, room_target_on_floor,
)
from ...services.sensor_service import SENSOR_TYPE_CHOICES, sensor_assignments, set_sensor_type
from ..column_utils import fit_columns
from ..widgets.drag_drop import DragDropTree

_DEVICE_TYPE_LABELS: dict[str, str] = {
    "actor":         "Aktor",
    "sensor":        "Sensor",
    "coupler":       "Koppler",
    "power_supply":  "Spannungsversorgung",
    "gateway":       "Gateway",
    "other":         "Sonstiges",
}

# Bedienelemente vs. Sensoren: siehe OPERABLE_ELEMENT_TYPES (models/building.py)


class BuildingView(QWidget):
    """Gebäudestruktur als Baum mit Bearbeitungsfunktionen."""

    structure_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._areal: Areal | None = None
        self._topology: Topology | None = None
        self._ga_structure = None  # GroupAddressStructure, siehe set_group_addresses() -- Kanalanzeige Aktoren
        self._catalog = None  # GewerkCatalog, siehe set_gewerk_catalog() -- Namen der Gewerke

        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Gebäudestruktur")
        title.setObjectName("title")
        layout.addWidget(title)

        # Toolbar – Zeile 1: Hinzufügen
        toolbar1 = QHBoxLayout()
        self._btn_add_building  = QPushButton("+ Gebäude")
        self._btn_add_wing      = QPushButton("+ Flügel")
        self._btn_add_floor     = QPushButton("+ Stockwerk")
        self._btn_add_apartment = QPushButton("+ Wohnung/Zone")
        self._btn_add_room      = QPushButton("+ Raum")
        self._btn_add_verteiler = QPushButton("+ Verteiler")

        self._btn_add_building.clicked.connect(self._add_building)
        self._btn_add_wing.clicked.connect(self._add_wing)
        self._btn_add_floor.clicked.connect(self._add_floor)
        self._btn_add_apartment.clicked.connect(self._add_apartment)
        self._btn_add_room.clicked.connect(self._add_room)
        self._btn_add_verteiler.clicked.connect(self._add_verteiler)

        toolbar1.addWidget(self._btn_add_building)
        toolbar1.addWidget(self._btn_add_wing)
        toolbar1.addWidget(self._btn_add_floor)
        toolbar1.addWidget(self._btn_add_apartment)
        toolbar1.addWidget(self._btn_add_room)
        toolbar1.addWidget(self._btn_add_verteiler)
        toolbar1.addStretch()
        layout.addLayout(toolbar1)

        # Toolbar – Zeile 2: Bearbeiten / Löschen
        toolbar2 = QHBoxLayout()
        self._btn_rename = QPushButton("Umbenennen")
        self._btn_rename.clicked.connect(self._rename_selected)
        self._btn_delete = QPushButton("Entfernen")
        self._btn_delete.setObjectName("danger")
        self._btn_delete.clicked.connect(self._delete_selected)

        toolbar2.addWidget(self._btn_rename)
        toolbar2.addStretch()
        toolbar2.addWidget(self._btn_delete)
        layout.addLayout(toolbar2)

        # Baum; Räume lassen sich auf eine Wohnung/Zone oder ein Stockwerk
        # ziehen (FA-1015 a)
        self._tree = DragDropTree()
        self._tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._tree.drag_data = self._drag_data
        self._tree.can_drop = self._can_drop
        self._tree.on_drop = self._on_drop
        self._tree.setToolTip("Räume lassen sich auf eine Wohnung/Zone oder ein Stockwerk ziehen, "
                              "Wohnungen/Zonen auf ein Stockwerk – oder per "
                              "Rechtsklick › Verschieben nach umhängen.")
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Element", "Typ", "Adresse", "Details"])
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Baut den Baum beim Einblenden neu auf, damit Änderungen (z.B. neue
        function_assignments nach GA-Neugenerierung) sofort sichtbar sind."""
        super().showEvent(event)
        self._refresh_tree()

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus (für Phase B: manuelle Bearbeitung)."""
        self._bus = bus

    def set_areal(self, areal: Areal):
        """Setzt die anzuzeigende Gebäudestruktur."""
        self._areal = areal
        self._refresh_tree()

    def set_gewerk_catalog(self, catalog) -> None:
        """Gewerk-Katalog für die Namen der Gewerke am Raum."""
        self._catalog = catalog
        self._refresh_tree()

    def set_topology(self, topology: Topology):
        """Setzt die Topologie für die Gerätezahl-Anzeige."""
        self._topology = topology
        self._refresh_tree()

    def set_group_addresses(self, ga_structure) -> None:
        """Verbindet die View mit der GA-Struktur, um Kanal-Gruppenadressen
        unter Aktoren anzuzeigen (analog zu TopologyView, FA-1007)."""
        self._ga_structure = ga_structure
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Geräte-Hilfsmethoden
    # ------------------------------------------------------------------

    def _devices_for_building(self, building: Building) -> int:
        if not self._topology:
            return 0
        room_ids = {r.id for r in building.all_rooms}
        count = 0
        for area in self._topology.areas:
            for line in area.lines:
                if any(rid in room_ids for rid in line.assigned_room_ids):
                    count += line.device_count
        return count

    def _devices_for_room(self, room) -> list:
        """Geräte mit direkter room_id-Zuweisung (Sensoren, manuell, Import)."""
        if not self._topology:
            return []
        return [
            device
            for area in self._topology.areas
            for line in area.lines
            for device in line.devices
            if device.room_id == room.id
        ]

    @staticmethod
    def _loc_matches_vt(loc: str, vt_names: set[str]) -> bool:
        """Prüft ob eine installation_location zu einem Verteiler gehört.

        Erlaubt Abweichungen wie 'HV' vs 'HV Technik': Es reicht, wenn
        einer der Werte ein Präfix des anderen ist (case-insensitiv).
        """
        loc = loc.strip().lower()
        if not loc:
            return False
        for name in vt_names:
            if not name:
                continue
            if loc == name or loc.startswith(name) or name.startswith(loc):
                return True
        return False

    def _devices_for_verteiler(self, room, vt) -> list:
        """Geräte, die diesem Verteiler-Objekt zugeordnet sind.

        Kandidaten sind ausschließlich Geräte mit device.room_id == room.id
        (die verlässliche, bereits vom Import aufgelöste Zuordnung -- siehe
        XlsxImportService.link_rooms_to_lines), NICHT mehr alle Geräte auf
        Linien, die den Raum irgendwie berühren: ein Raum mit mehreren
        Verteilern (z.B. nach einer manuellen Zusammenführung, Step 3b) kann
        auf derselben physischen KNX-Linie liegen wie ein GANZ ANDERER Raum
        mit eigenem Verteiler -- die alte Linien-basierte Prüfung fing
        dessen Geräte fälschlich mit ein.

        Innerhalb der room.id-gefilterten Kandidaten wird nur noch gegen den
        spezifischen vt.name geprüft, NICHT gegen den bloßen Verteiler-Typ
        (vt.verteiler_type): zwei Verteiler desselben Typs im selben Raum
        (oder auf derselben Linie, wie UV1/UV2) haben sonst denselben
        Typ-Präfix ("UV") und "stehlen" sich gegenseitig Geräte, da z.B.
        "UV2 (...)" mit dem Präfix "UV" von UV1 übereinstimmt.
        """
        room_devices = self._devices_for_room(room)
        vt_name = (vt.name or "").strip().lower()
        if not vt_name:
            return []
        return [
            d for d in room_devices
            if self._loc_matches_vt(d.installation_location, {vt_name})
        ]

    # ------------------------------------------------------------------
    # Baumdarstellung
    # ------------------------------------------------------------------

    def _refresh_tree(self):
        self._tree.clear()
        if not self._areal:
            return

        # Projektweite Teilnehmernummern aller Bedienelemente (nicht nur
        # raumintern): ein importiertes Topologie-Gerät kann einer anderen
        # room_id zugeordnet sein als das daraus abgeleitete Bedienelement
        # (z.B. wenn link_rooms_to_lines und die KO-basierte Bedienelement-
        # Erzeugung unterschiedliche Räume ermitteln) -- eine nur raumlokale
        # Prüfung übersieht das und zeigt das Gerät dann ein zweites Mal als
        # leere Geräte-Zeile ohne Details (Regression: Taster 1.1.30 erschien
        # so doppelt -- einmal korrekt befüllt, einmal leer in "Eingang").
        all_be_participant_numbers = {
            be.participant_number
            for room in self._areal.all_rooms
            for be in room.bedienelemente
            if be.participant_number and not be.suppressed
        }

        # Wizard-geplante (Gewerk-basierte) function_assignments speichern in
        # function_ga nur die GA-Bezeichnung, keine Adresse (siehe
        # resolve_ga_display) -- ohne diese Auflösung fehlte die Gruppen-
        # adressnummer in der "Adresse"-Spalte bei Projekten ohne ETS-Import.
        ga_by_designation = (
            build_ga_by_designation(self._ga_structure) if self._ga_structure else {}
        )

        areal_item = QTreeWidgetItem(self._tree, [self._areal.name or "Areal", "Areal", "", ""])
        areal_item.setData(0, Qt.UserRole, ("areal", self._areal))
        areal_item.setExpanded(True)

        for building in self._areal.buildings:
            bld_devices = self._devices_for_building(building)
            bld_item = QTreeWidgetItem(
                areal_item,
                [building.name, "Gebäude", "", f"{bld_devices} Geräte"],
            )
            bld_item.setData(0, Qt.UserRole, ("building", building))
            bld_item.setExpanded(True)

            for wing in building.wings:
                wing_item = QTreeWidgetItem(bld_item, [wing.name, "Flügel", "", ""])
                wing_item.setData(0, Qt.UserRole, ("wing", wing))
                wing_item.setExpanded(True)

                for floor in wing.floors:
                    devices = floor.total_devices()
                    detail = f"HG {floor.main_group_number}, {devices} Geräte"
                    floor_item = QTreeWidgetItem(
                        wing_item,
                        [f"{floor.short_code} – {floor.name}", "Stockwerk", "", detail],
                    )
                    floor_item.setData(0, Qt.UserRole, ("floor", floor))
                    floor_item.setExpanded(True)

                    for apt in floor.apartments:
                        apt_item = QTreeWidgetItem(
                            floor_item,
                            [apt.name, "Wohnung/Zone", "", f"{len(apt.rooms)} Räume"],
                        )
                        apt_item.setData(0, Qt.UserRole, ("apartment", apt))
                        apt_item.setExpanded(True)

                        for room in apt.rooms:
                            # Geräte nach Typ getrennt sammeln
                            room_devices = self._devices_for_room(room)
                            vt_dev_map: dict[str, list] = {}
                            shown_ids: set[str] = set()
                            for vt in room.verteiler:
                                vd = self._devices_for_verteiler(room, vt)
                                vt_dev_map[vt.id] = vd
                                for d in vd:
                                    shown_ids.add(d.id)

                            active_bes = [be for be in room.bedienelemente if not be.suppressed]
                            # `room_devices` sind ALLE Geräte mit device.room_id ==
                            # room.id -- das schließt die Verteiler-Teilmenge (in
                            # `shown_ids`, s.o.) bereits mit ein, da ein Verteiler-
                            # Objekt am selben Raum hängt (z.B. ein im Raum
                            # verschachtelter Hauptverteiler). `shown_ids` steuert nur,
                            # welche Geräte in der flachen Liste NICHT nochmal gezeigt
                            # werden (sie erscheinen stattdessen unter ihrem Verteiler-
                            # Knoten) -- die Gesamtzahl darf sie daher nicht ein zweites
                            # Mal addieren, sonst zeigt die Raumzusammenfassung z.B.
                            # "21 Geräte" für einen Raum mit tatsächlich 12 Geräten
                            # (3 raumgebunden + 9 im dort verschachtelten Verteiler).
                            topo_total = len(room_devices)

                            # Geräte, die bereits als Bedienelement dargestellt werden
                            # (aus demselben importierten Gerät abgeleitet, über die
                            # Teilnehmernummer verknüpft), nicht zusätzlich als
                            # eigene Geräte-Zeile zeigen -- sonst erscheint z.B. ein
                            # Sensor doppelt: einmal roh, einmal als Bedienelement.
                            # Projektweit geprüft (all_be_participant_numbers), nicht nur
                            # raumintern, da Gerät und Bedienelement unterschiedlichen
                            # Räumen zugeordnet sein können (siehe Kommentar oben).
                            for device in room_devices:
                                if device.physical_address in all_be_participant_numbers:
                                    shown_ids.add(device.id)

                            interactive_bes = [be for be in active_bes if be.is_operable]
                            passive_bes = [be for be in active_bes if not be.is_operable]
                            dev_count = topo_total if topo_total else room.total_devices()
                            room_label   = room.name if not room.number else f"{room.number} – {room.name}"
                            # Welche Gewerke wie oft, nicht nur ihre Anzahl
                            parts = [gewerk_summary(room) or "keine Gewerke", f"{dev_count} Geräte"]
                            if interactive_bes:
                                parts.append(f"{len(interactive_bes)} Bedienelemente")
                            if passive_bes:
                                parts.append(f"{len(passive_bes)} Sensoren")
                            room_item = QTreeWidgetItem(
                                apt_item,
                                [room_label, "Raum", "", ", ".join(parts)],
                            )
                            room_item.setData(0, Qt.UserRole, ("room", room))
                            if room.gewerk_assignments:
                                room_item.setToolTip(3, self._gewerk_tooltip(room))
                                self._add_gewerk_items(room_item, room)

                            # Verteiler als Kindknoten + zugehörige Topologie-Geräte
                            for vt in room.verteiler:
                                vd = vt_dev_map.get(vt.id, [])
                                if vd:
                                    vt_detail = f"{len(vd)} Geräte"
                                else:
                                    vt_detail = (
                                        f"{len(vt.actor_assignments)} Aktoren"
                                        f", {len(vt.line_couplers)} Koppler"
                                        f", {len(vt.power_supplies)} Speisungen"
                                        f", {len(vt.interfaces)} Schnittst."
                                    )
                                vt_item = QTreeWidgetItem(
                                    room_item,
                                    [vt.name or vt.verteiler_type, vt.verteiler_type, "", vt_detail],
                                )
                                vt_item.setData(0, Qt.UserRole, ("verteiler", vt))
                                vt_item.setExpanded(True)
                                for device in vd:
                                    label = device.product_name or device.product or device.device_type
                                    addr  = device.physical_address or "–"
                                    dtype = _DEVICE_TYPE_LABELS.get(device.device_type, device.device_type)
                                    dev_item = QTreeWidgetItem(vt_item, [label, dtype, addr, ""])
                                    if device.device_type == "actor":
                                        self._add_actor_channel_items(dev_item, device)

                            # Bedienelemente aus Wizard-Funktionsdefinition
                            for be in active_bes:
                                ch_info = f"{be.channels}-Kanal"
                                row_type = (
                                    "Bedienelement" if be.is_operable else "Sensor"
                                )
                                be_item = QTreeWidgetItem(
                                    room_item,
                                    [be.element_type, row_type, be.participant_number,
                                     f"{ch_info}, {len(be.function_assignments)} Funktionen"],
                                )
                                be_item.setData(0, Qt.UserRole, ("bedienelement", (be, room)))
                                for fa in be.function_assignments:
                                    QTreeWidgetItem(
                                        be_item,
                                        [fa.button_channel, "Funktion",
                                         resolve_ga_display(fa.function_ga, ga_by_designation),
                                         fa.description],
                                    )

                            # Raumgebundene Topologie-Geräte (Sensoren, manuell, Import)
                            for device in room_devices:
                                if device.id in shown_ids:
                                    continue
                                label = device.product_name or device.product or device.device_type
                                addr  = device.physical_address or "–"
                                dtype = _DEVICE_TYPE_LABELS.get(device.device_type, device.device_type)
                                dev_item = QTreeWidgetItem(room_item, [label, dtype, addr, ""])
                                if device.device_type == "actor":
                                    self._add_actor_channel_items(dev_item, device)

        fit_columns(self._tree)

    def _gewerk_name(self, code: str) -> str:
        gewerk = self._catalog.get(code) if self._catalog else None
        return gewerk.name if gewerk else ""

    def _gewerk_tooltip(self, room: Room) -> str:
        lines = []
        for ga in room.gewerk_assignments:
            name = self._gewerk_name(ga.gewerk_code)
            head = f"{ga.gewerk_code} {name}".strip() + f" ×{ga.count}"
            labels = "; ".join(t for t in ga.element_labels if t)
            lines.append(f"{head}: {labels}" if labels else head)
        return "\n".join(lines)

    def _add_gewerk_items(self, room_item: QTreeWidgetItem, room: Room) -> None:
        """Zugeklappter Knoten "Gewerke" mit je einer Zeile pro Gewerk
        (Code, Name, Anzahl, Bezeichnung). Ohne UserRole-Daten: Umbenennen,
        Löschen und Ziehen gelten hier nicht."""
        container = QTreeWidgetItem(
            room_item, [f"Gewerke ({len(room.gewerk_assignments)})", "Gewerke", "", ""])
        container.setExpanded(False)
        for ga in room.gewerk_assignments:
            name = self._gewerk_name(ga.gewerk_code)
            labels = "; ".join(ga.element_labels[:ga.count])
            QTreeWidgetItem(container, [
                f"{ga.gewerk_code} – {name}" if name else ga.gewerk_code,
                "Gewerk", "", f"×{ga.count}: {labels}" if labels else f"×{ga.count}",
            ])

    def _add_actor_channel_items(self, dev_item: QTreeWidgetItem, device) -> None:
        """Fügt Kanal-Kindknoten mit ihren Gruppenadressen unter einem Aktor
        ein -- analog zu den Funktions-Kindknoten, die Bedienelemente hier
        schon zeigen (siehe FA-1007). Vorher fehlte diese Ebene für Aktoren
        in der Gebäude-Ansicht komplett, waehrend die Topologie-Ansicht sie
        schon hatte (dort wiederum umgekehrt fuer Sensoren, siehe
        TopologyView._add_sensor_function_items).

        Gruppiert Device.communication_objects nach physischem Kanal (siehe
        group_cos_for_display), identisch zum CO-Fallback in
        TopologyView._add_channel_items_from_cos. Zeigt nur, wenn echte COs
        vorliegen (ETS6-Import) -- für rein wizard-geplante Aktoren ohne COs
        bleibt der Aktor ein flaches Blatt, wie zuvor.
        """
        cos_with_ga = [
            co for co in sorted(device.communication_objects, key=lambda c: c.object_number)
            if co.connected_gas
        ]
        if not cos_with_ga:
            return

        ga_by_address = {}
        if self._ga_structure is not None:
            ga_by_address = {ga.address: ga for ga in self._ga_structure.all_addresses()}

        for label, cos in group_cos_for_display(cos_with_ga):
            if label:
                ga_count = sum(len(co.connected_gas) for co in cos)
                ch_item = QTreeWidgetItem(dev_item, [label, "Kanal", "", f"{ga_count} GA(s)"])
            else:
                ch_item = dev_item  # Objekte ohne Kanal direkt unter dem Geraet
            for co in cos:
                for ga_addr in co.connected_gas:
                    ga_obj = ga_by_address.get(ga_addr)
                    label_text = ga_obj.designation if ga_obj else ga_addr
                    QTreeWidgetItem(ch_item, [
                        f"{co.name or co.object_function}: {label_text}",
                        "GA",
                        ga_addr,
                        ga_obj.datapoint_type if ga_obj else "",
                    ])

    # ------------------------------------------------------------------
    # Selektion
    # ------------------------------------------------------------------

    def _get_selected_data(self) -> tuple[str, object] | None:
        item = self._tree.currentItem()
        if item:
            return item.data(0, Qt.UserRole)
        return None

    # ------------------------------------------------------------------
    # Ziehen und Ablegen (FA-1015 a)
    # ------------------------------------------------------------------

    @staticmethod
    def _drag_data(item: QTreeWidgetItem):
        data = item.data(0, Qt.UserRole)
        return data[1] if data and data[0] in ("room", "apartment") else None

    def _drop_apartment(self, room: Room, target) -> Apartment | None:
        kind, obj = target
        if kind == "apartment":
            return obj
        if kind == "floor":
            return room_target_on_floor(self._areal, room, obj)
        return None

    def _can_drop(self, rooms: list, target) -> bool:
        if not self._areal or not target:
            return False
        if any(isinstance(obj, Apartment) for obj in rooms):
            # Zonen nur auf ein Stockwerk, nicht gemischt mit Räumen
            return (target[0] == "floor"
                    and all(isinstance(obj, Apartment) for obj in rooms)
                    and any(can_move_apartment(self._areal, a, target[1]) for a in rooms))
        return any(
            can_move_room(self._areal, room, self._drop_apartment(room, target))
            for room in rooms
        )

    def _on_drop(self, rooms: list, target) -> None:
        if rooms and isinstance(rooms[0], Apartment):
            self._move_apartments(rooms, target[1])
            return
        self._move_rooms([(room, self._drop_apartment(room, target)) for room in rooms])

    def _add_apartment_move_menu(self, menu: QMenu, apt: Apartment) -> QMenu:
        """Untermenü «Verschieben nach» mit allen Stockwerken, auch anderer
        Gebäude (z.B. Gartenhaus → Nebengebäude)."""
        sub = menu.addMenu("Verschieben nach")
        multi_building = len(self._areal.buildings) > 1
        for building in self._areal.buildings:
            for floor in building.all_floors:
                label = f"{floor.name} – {building.name}" if multi_building else floor.name
                action = sub.addAction(
                    label, lambda f=floor: self._move_apartments([apt], f))
                action.setEnabled(can_move_apartment(self._areal, apt, floor))
        return sub

    def _move_apartments(self, apartments: list, floor: Floor) -> None:
        apartments = [a for a in apartments if can_move_apartment(self._areal, a, floor)]
        if not apartments:
            return
        bus = getattr(self, "_bus", None)
        if bus:
            names = ", ".join(f"»{a.name}«" for a in apartments)
            bus.begin_change(f"{names} nach »{floor.name}« verschieben")
        for apt in apartments:
            move_apartment(self._areal, apt, floor)
        self._refresh_tree()
        self.structure_changed.emit()

    def _selected_rooms(self, clicked: Room) -> list[Room]:
        """Markierte Räume; liegt der angeklickte Raum ausserhalb der
        Markierung, nur dieser."""
        rooms = [d[1] for d in (i.data(0, Qt.UserRole) for i in self._tree.selectedItems())
                 if d and d[0] == "room"]
        return rooms if clicked in rooms else [clicked]

    def _add_move_menu(self, menu: QMenu, clicked: Room) -> QMenu:
        """Untermenü «Verschieben nach» mit allen Wohnungen/Zonen – Alternative
        zum Ziehen, wenn das Ziel im Baum weit entfernt oder zugeklappt ist."""
        rooms = self._selected_rooms(clicked)
        sub = menu.addMenu("Verschieben nach" if len(rooms) == 1
                           else f"{len(rooms)} Räume verschieben nach")
        multi_building = len(self._areal.buildings) > 1
        for building in self._areal.buildings:
            for floor in building.all_floors:
                for apt in floor.apartments:
                    label = f"{apt.name}  ({floor.name})"
                    if multi_building:
                        label = f"{label} – {building.name}"
                    action = sub.addAction(
                        label, lambda a=apt: self._move_rooms([(r, a) for r in rooms]))
                    action.setEnabled(any(can_move_room(self._areal, r, apt) for r in rooms))
        sub.setEnabled(not sub.isEmpty())
        return sub

    # ------------------------------------------------------------------
    # Sensortyp (FA-1407)
    # ------------------------------------------------------------------

    def _add_sensor_type_menu(self, menu: QMenu, be, room: Room) -> QMenu | None:
        """Untermenü «Sensortyp» für Sensoren aus Gewerken, z.B. Gewerk A:
        Bewegungsmelder → Wassermelder."""
        if be.is_operable or not sensor_assignments(room, be):
            return None
        sub = menu.addMenu("Sensortyp")
        choices = list(SENSOR_TYPE_CHOICES)
        if be.element_type not in choices:
            choices.insert(0, be.element_type)
        for sensor_type in choices:
            action = sub.addAction(
                sensor_type, lambda t=sensor_type: self._set_sensor_type(room, be, t))
            action.setCheckable(True)
            action.setChecked(sensor_type == be.element_type)
        return sub

    def _set_sensor_type(self, room: Room, be, sensor_type: str) -> None:
        old = be.element_type
        if old == sensor_type:
            return
        bus = getattr(self, "_bus", None)
        if bus:
            bus.begin_change(f"Sensortyp »{old}« → »{sensor_type}« ({room.name})")
        if set_sensor_type(room, be, sensor_type):
            self._refresh_tree()
            self.structure_changed.emit()

    def _move_rooms(self, moves: list) -> None:
        moves = [(r, a) for r, a in moves if can_move_room(self._areal, r, a)]
        if not moves:
            return
        bus = getattr(self, "_bus", None)
        if bus:
            names = ", ".join(f"»{r.name}«" for r, _ in moves)
            bus.begin_change(f"{names} nach »{moves[0][1].name}« verschieben")
        for room, apt in moves:
            move_room(self._areal, room, apt)
        self._refresh_tree()
        self.structure_changed.emit()

    # ------------------------------------------------------------------
    # Hinzufügen
    # ------------------------------------------------------------------

    def _add_building(self):
        if not self._areal:
            return
        name, ok = QInputDialog.getText(self, "Gebäude hinzufügen", "Gebäudename:")
        if ok and name:
            building = Building(name=name)
            wing = Wing(name="Hauptgebäude")
            building.wings.append(wing)
            self._areal.buildings.append(building)
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_wing(self):
        data = self._get_selected_data()
        if not data or data[0] != "building":
            QMessageBox.information(self, "Hinweis", "Bitte ein Gebäude auswählen.")
            return
        building = data[1]
        name, ok = QInputDialog.getText(self, "Flügel hinzufügen", "Flügelname:")
        if ok and name:
            building.wings.append(Wing(name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_floor(self):
        data = self._get_selected_data()
        if not data or data[0] != "wing":
            QMessageBox.information(self, "Hinweis", "Bitte einen Flügel auswählen.")
            return
        wing = data[1]
        code, ok = QInputDialog.getText(self, "Stockwerk hinzufügen", "Kürzel (z.B. EG, 1.OG, UG):")
        if not (ok and code):
            return
        default_name = STANDARD_FLOOR_NAMES.get(code.upper(), code)
        name, ok2 = QInputDialog.getText(self, "Stockwerk", "Name:", text=default_name)
        if ok2 and name:
            # BuildingService legt automatisch eine Standard-Wohnung an
            BuildingService.add_floor(wing, name=name, short_code=code, areal=self._areal)
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_apartment(self):
        data = self._get_selected_data()
        if not data or data[0] != "floor":
            QMessageBox.information(self, "Hinweis", "Bitte ein Stockwerk auswählen.")
            return
        floor = data[1]
        name, ok = QInputDialog.getText(self, "Wohnung/Zone hinzufügen", "Name:")
        if ok and name:
            floor.apartments.append(Apartment(name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_room(self):
        data = self._get_selected_data()
        if not data or data[0] != "apartment":
            QMessageBox.information(self, "Hinweis", "Bitte eine Wohnung/Zone auswählen.")
            return
        apt = data[1]
        number, ok = QInputDialog.getText(self, "Raum hinzufügen", "Raumnummer (z.B. E01):")
        if not (ok and number):
            return
        name, ok2 = QInputDialog.getText(self, "Raum", "Raumname:")
        if ok2 and name:
            apt.rooms.append(Room(number=number, name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_verteiler(self):
        data = self._get_selected_data()
        if not data or data[0] != "room":
            QMessageBox.information(self, "Hinweis", "Bitte einen Raum auswählen.")
            return
        room = data[1]

        dlg = QDialog(self)
        dlg.setWindowTitle("Verteiler hinzufügen")
        form = QFormLayout(dlg)

        name_edit        = QLineEdit()
        name_edit.setPlaceholderText("z.B. UV Küche, HV")
        type_combo       = QComboBox()
        type_combo.addItems(["HV", "UV", "NV", "TV"])
        designation_edit = QLineEdit()

        form.addRow("Name:", name_edit)
        form.addRow("Typ:", type_combo)
        form.addRow("Bezeichnung:", designation_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.Accepted:
            vt = Verteiler(
                name=name_edit.text().strip() or type_combo.currentText(),
                verteiler_type=type_combo.currentText(),
                designation=designation_edit.text().strip(),
            )
            room.verteiler.append(vt)
            self._refresh_tree()
            self.structure_changed.emit()

    # ------------------------------------------------------------------
    # Umbenennen
    # ------------------------------------------------------------------

    def _on_double_click(self, _item: QTreeWidgetItem, _column: int):
        self._rename_selected()

    def _rename_selected(self):
        data = self._get_selected_data()
        if not data:
            return
        kind, obj = data

        titles = {
            "areal":     "Areal umbenennen",
            "building":  "Gebäude umbenennen",
            "wing":      "Flügel umbenennen",
            "floor":     "Stockwerk umbenennen",
            "apartment": "Wohnung/Zone umbenennen",
            "room":      "Raum umbenennen",
            "verteiler": "Verteiler umbenennen",
        }
        title = titles.get(kind)
        if not title:
            return

        new_name, ok = QInputDialog.getText(self, title, "Name:", text=getattr(obj, "name", ""))
        if not (ok and new_name):
            return
        obj.name = new_name

        if kind == "floor":
            code, ok2 = QInputDialog.getText(self, "Stockwerk", "Kürzel:", text=obj.short_code)
            if ok2 and code:
                obj.short_code = code

        self._refresh_tree()
        self.structure_changed.emit()

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def _delete_selected(self):
        data = self._get_selected_data()
        if not data:
            return
        kind, obj = data
        if kind == "bedienelement":
            be, _room = obj
            label = be.element_type or "Bedienelement"
            hint = (
                "\n\nDas Gerät wird unterdrückt und nicht neu berechnet."
                if be.is_auto else ""
            )
            reply = QMessageBox.question(
                self, "Gerät löschen",
                f"«{label}» wirklich löschen?{hint}",
                QMessageBox.Yes | QMessageBox.No,
            )
        else:
            reply = QMessageBox.question(
                self, "Löschen",
                f"'{getattr(obj, 'name', kind)}' wirklich löschen?",
                QMessageBox.Yes | QMessageBox.No,
            )
        if reply == QMessageBox.Yes:
            self._remove_from_structure(kind, obj)
            self._refresh_tree()
            self.structure_changed.emit()

    def _remove_from_structure(self, kind: str, obj):
        if kind == "bedienelement":
            from ...services.button_move import remove_bedienelement
            be, room = obj
            remove_bedienelement(room, be)
            return
        if not self._areal:
            return
        if kind == "building":
            if obj in self._areal.buildings:
                self._areal.buildings.remove(obj)
        elif kind == "wing":
            for b in self._areal.buildings:
                if obj in b.wings:
                    b.wings.remove(obj)
                    return
        elif kind == "floor":
            for b in self._areal.buildings:
                for w in b.wings:
                    if obj in w.floors:
                        w.floors.remove(obj)
                        return
        elif kind == "apartment":
            for f in self._areal.all_floors:
                if obj in f.apartments:
                    f.apartments.remove(obj)
                    return
        elif kind == "room":
            for f in self._areal.all_floors:
                for a in f.apartments:
                    if obj in a.rooms:
                        a.rooms.remove(obj)
                        return
        elif kind == "verteiler":
            for f in self._areal.all_floors:
                for a in f.apartments:
                    for r in a.rooms:
                        if obj in r.verteiler:
                            r.verteiler.remove(obj)
                            return

    # ------------------------------------------------------------------
    # Kontextmenü
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)
        kind = data[0]

        if kind == "areal":
            menu.addAction("Gebäude hinzufügen", self._add_building)
            menu.addAction("Umbenennen",          self._rename_selected)
        elif kind == "building":
            menu.addAction("Flügel hinzufügen",   self._add_wing)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "wing":
            menu.addAction("Stockwerk hinzufügen", self._add_floor)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "floor":
            menu.addAction("Wohnung/Zone hinzufügen", self._add_apartment)
            menu.addAction("Umbenennen",              self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",                 self._delete_selected)
        elif kind == "apartment":
            menu.addAction("Raum hinzufügen",      self._add_room)
            self._add_apartment_move_menu(menu, data[1])
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "room":
            menu.addAction("Verteiler hinzufügen", self._add_verteiler)
            self._add_move_menu(menu, data[1])
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "verteiler":
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "bedienelement":
            self._add_sensor_type_menu(menu, *data[1])
            menu.addAction("Löschen",              self._delete_selected)

        menu.exec(self._tree.viewport().mapToGlobal(pos))


def gewerk_summary(room: Room) -> str:
    """Kurzform der Gewerke eines Raums, z.B. "LDA ×2, J ×2, S, H"."""
    return ", ".join(
        f"{ga.gewerk_code} ×{ga.count}" if ga.count > 1 else ga.gewerk_code
        for ga in room.gewerk_assignments
    )
