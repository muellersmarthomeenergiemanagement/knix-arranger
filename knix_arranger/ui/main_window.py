"""
KNiX Arranger Hauptfenster (NFA-020, NFA-021)
"""
from __future__ import annotations
import logging
import os
import subprocess
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QStackedWidget,
    QMenuBar, QMenu, QFileDialog, QMessageBox, QProgressDialog, QApplication,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence

from .styles import get_main_stylesheet
from .widgets.sidebar import Sidebar
from .widgets.status_bar import KnxStatusBar
from .views.project_overview import ProjectOverview
from .views.building_view import BuildingView
from .views.topology_view import TopologyView
from .views.address_tree_view import AddressTreeView
from .views.address_table_view import AddressTableView
from .views.validation_view import ValidationView
from .views.gewerk_view import GewerkView
from .views.scene_view import SceneView
from .views.quotation_view import QuotationView
from .views.customer_quote_view import CustomerQuoteView
from .views.datasheet_view import DatasheetView
from .views.topology_report_view import TopologyReportView
from .views.help_view import HelpView
from .views.material_list_view import MaterialListView
from .views.co_linking_view import CoLinkingView
from .views.topology_diagram_view import TopologyDiagramView
from .views.linking_matrix_view import LinkingMatrixView
from .views.cable_length_view import CableLengthView
from .views.dali_config_view import DaliConfigView
from .views.knx_secure_view import KnxSecureView
from .views.commissioning_view import CommissioningView
from .views.time_program_view import TimeProgramView
from .views.bauherr_form_view import BauherrFormView
from .views.changelog_view import ChangelogView
from .dialogs.new_project_dialog import NewProjectDialog
from .dialogs.about_dialog import AboutDialog
from .dialogs.import_dialog import ImportDialog
from .dialogs.export_dialog import ExportDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.reports_dialog import ReportsDialog
from .dialogs.license_dialog import LicenseDialog
from .dialogs.welcome_dialog import WelcomeDialog, ACTION_NEW, ACTION_OPEN
from .dialogs.workspace_setup_dialog import WorkspaceSetupDialog
from .dialogs.project_properties_dialog import ProjectPropertiesDialog
from .dialogs.update_dialog import UpdateDialog
from .dialogs.onboarding_tour_dialog import OnboardingTourDialog
from .dialogs.knxproj_password_dialog import KnxprojPasswordDialog
from .export_worker import run_import

from ..models.project import KnxProject
from ..services.building_service import BuildingService
from ..services.address_generator import AddressGenerator
from ..services.topology_engine import TopologyEngine
from ..services.validation_engine import ValidationEngine
from ..services.sensor_service import SensorService
from ..services.csv_import_service import CsvImportService
from ..services.csv_export_service import CsvExportService
from ..services.xlsx_import_service import XlsxImportService
from ..services.knxproj_import_service import (
    KnxprojImportService, KnxprojImportError,
    KnxprojPasswordRequired, KnxprojPasswordWrong,
)
from ..services.project_reconcile_service import reconcile_reimport
from ..services.undo_manager import UndoManager, ObjectStateCommand
from ..services.project_bus import ProjectBus
from ..services.recalc_service import RecalcService
from ..services.dali_service import DaliService
from ..services.gewerk_service import GewerkService
from .. import APP_NAME, __version__

logger = logging.getLogger("knix_arranger.main_window")


class MainWindow(QMainWindow):
    """Hauptfenster des KNiX Arranger."""

    # Signal fuer asynchronen Update-Check (NFA-111)
    _update_available = Signal(object)   # UpdateInfo

    def __init__(self, app=None):
        super().__init__()
        self._app = app
        self._update_available.connect(self._on_update_available)
        self._project: KnxProject | None = None
        self._building_service = BuildingService()
        self._undo_manager = UndoManager()
        self._bus = ProjectBus()
        self._recalc = RecalcService()
        self._dirty = False
        self._pending_undo_cmd: ObjectStateCommand | None = None
        self._ga_report_path: str = ""   # Pfad zum zuletzt importierten GA-Report
        self._topology_xlsx_path: str = ""  # Pfad zum zuletzt importierten Topologie-XLSX
        self._building_report_path: str = ""  # Pfad zum zuletzt importierten Gebäude-Report
        self._import_worker_ref: list = [None]  # GC-Schutz für laufenden Import-Worker (run_import)

        # Auto-Save: 30 Sekunden nach letzter Änderung
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(30_000)
        self._autosave_timer.timeout.connect(self._autosave)

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.setMinimumSize(1100, 680)
        self.showMaximized()
        self.setStyleSheet(get_main_stylesheet())

        self._create_menu()
        self._create_ui()
        self._create_status_bar()

        # Startansicht
        self._sidebar.select("overview")
        self._navigate("overview")

        # Startdialoge nacheinander: erst "Was ist neu" (nach Update), dann
        # Willkommensbildschirm. Bewusst EIN Timer – ein modaler Dialog startet
        # eine eigene Ereignisschleife, ein zweiter Timer würde darüber aufgehen.
        QTimer.singleShot(0, self._show_startup_dialogs)

        # Automatischer Update-Check nach 4 Sekunden (NFA-111, blockiert nicht)
        QTimer.singleShot(4000, self._auto_check_updates)

    def _create_menu(self):
        """Erstellt die Menueleiste."""
        menubar = self.menuBar()

        # Datei
        file_menu = menubar.addMenu("&Datei")

        new_action = QAction("&Neues Projekt", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Oeffnen...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Speichern", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Speichern &unter...", self)
        save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        save_close_action = QAction("Speichern und &Schliessen", self)
        save_close_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        save_close_action.triggered.connect(self._save_and_close)
        file_menu.addAction(save_close_action)

        file_menu.addSeparator()

        props_action = QAction("&Projekteigenschaften...", self)
        props_action.setShortcut(QKeySequence("Ctrl+P"))
        props_action.triggered.connect(self._show_project_properties)
        file_menu.addAction(props_action)

        file_menu.addSeparator()

        import_action = QAction("ETS6 &Import... (CSV / XLSX / KNXPROJ)", self)
        import_action.setShortcut(QKeySequence("Ctrl+I"))
        import_action.triggered.connect(self._import_file)
        file_menu.addAction(import_action)

        knxprod_action = QAction("Produkt&katalog KNXPROD importieren...", self)
        knxprod_action.setToolTip(
            "Herstellerdatei (.knxprod) importieren und Produkte dem Katalog hinzufügen"
        )
        knxprod_action.triggered.connect(self._import_knxprod_catalog)
        file_menu.addAction(knxprod_action)

        export_action = QAction("CSV &Export...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_csv)
        file_menu.addAction(export_action)

        knxproj_export_action = QAction("KNXPROJ &Export... (.knxproj)", self)
        knxproj_export_action.setToolTip(
            "Exportiert das Projekt als natives ETS6-Projektformat (.knxproj)"
        )
        knxproj_export_action.triggered.connect(self._export_knxproj)
        file_menu.addAction(knxproj_export_action)

        file_menu.addSeparator()

        quit_action = QAction("&Beenden", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Bearbeiten
        edit_menu = menubar.addMenu("&Bearbeiten")

        self._undo_action = QAction("&Rückgängig", self)
        self._undo_action.setShortcut(QKeySequence.Undo)
        self._undo_action.triggered.connect(self._undo)
        self._undo_action.setEnabled(False)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("&Wiederholen", self)
        self._redo_action.setShortcut(QKeySequence.Redo)
        self._redo_action.triggered.connect(self._redo)
        self._redo_action.setEnabled(False)
        edit_menu.addAction(self._redo_action)

        edit_menu.addSeparator()

        settings_action = QAction("&Einstellungen...", self)
        settings_action.triggered.connect(self._show_settings)
        edit_menu.addAction(settings_action)

        # Ansicht
        view_menu = menubar.addMenu("&Ansicht")

        wizard_action = QAction("&Wizard starten", self)
        wizard_action.setShortcut(QKeySequence("Ctrl+W"))
        wizard_action.triggered.connect(self._start_wizard)
        view_menu.addAction(wizard_action)

        validate_action = QAction("&Validieren", self)
        validate_action.setShortcut(QKeySequence("Ctrl+V"))
        validate_action.triggered.connect(self._validate)
        view_menu.addAction(validate_action)

        # Hilfe
        help_menu = menubar.addMenu("&Hilfe")

        help_action = QAction("&Hilfe anzeigen", self)
        help_action.setShortcut(QKeySequence("F1"))
        help_action.triggered.connect(self._show_help)
        help_menu.addAction(help_action)

        tour_action = QAction("&Erste Schritte (Tour)...", self)
        tour_action.triggered.connect(self._show_onboarding_tour)
        help_menu.addAction(tour_action)

        manual_action = QAction("&Benutzerhandbuch (PDF)...", self)
        manual_action.triggered.connect(self._open_manual)
        help_menu.addAction(manual_action)

        help_menu.addSeparator()

        whats_new_action = QAction("&Was ist neu…", self)
        whats_new_action.triggered.connect(self._show_whats_new)
        help_menu.addAction(whats_new_action)

        update_action = QAction("Nach &Updates suchen...", self)
        update_action.setShortcut(QKeySequence("Ctrl+U"))
        update_action.triggered.connect(self._check_updates_manual)
        help_menu.addAction(update_action)

        help_menu.addSeparator()

        license_action = QAction("&Lizenz...", self)
        license_action.triggered.connect(self._show_license)
        help_menu.addAction(license_action)

        help_menu.addSeparator()

        about_action = QAction("&Über " + APP_NAME, self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()

        uninstall_action = QAction("&Deinstallieren...", self)
        uninstall_action.triggered.connect(self._uninstall_app)
        help_menu.addAction(uninstall_action)

    def _create_ui(self):
        """Erstellt die Benutzeroberfläche."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.navigation_changed.connect(self._navigate)
        main_layout.addWidget(self._sidebar)

        # Content
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack, 1)

        # Views erstellen
        self._overview = ProjectOverview()
        self._overview.project_name_changed.connect(self._on_project_name_changed)
        self._building_view = BuildingView()
        self._building_view.structure_changed.connect(self._bus.emit_building_changed)
        self._topology_view = TopologyView()
        self._topology_view.topology_changed.connect(self._bus.emit_topology_changed)
        self._address_tree = AddressTreeView()
        self._address_tree.ga_modified.connect(self._bus.emit_addresses_changed)
        self._address_table = AddressTableView()
        self._address_table.ga_modified.connect(self._bus.emit_addresses_changed)
        self._validation_view = ValidationView()
        self._validation_view.revalidate_requested.connect(self._validate)
        self._gewerk_view = GewerkView()
        self._scene_view = SceneView()
        self._scene_view.request_generate_addresses.connect(
            self._open_wizard_at_addresses_step
        )
        self._quotation_view = QuotationView()
        self._customer_quote_view = CustomerQuoteView()
        self._datasheet_view = DatasheetView()
        self._topology_report_view = TopologyReportView()
        self._help_view = HelpView()
        self._material_list_view = MaterialListView()
        self._material_list_view.list_changed.connect(self._bus.emit_material_changed)
        self._material_list_view.topology_changed.connect(self._bus.emit_topology_changed)
        self._co_linking_view = CoLinkingView()
        self._linking_matrix_view = LinkingMatrixView()
        self._cable_length_view = CableLengthView()
        self._topology_diagram_view = TopologyDiagramView()
        self._dali_config_view = DaliConfigView(self._project)
        self._knx_secure_view = KnxSecureView(self._project)
        self._time_program_view = TimeProgramView(self._project)
        self._bauherr_form_view = BauherrFormView()
        self._commissioning_view = CommissioningView(self._project)
        self._commissioning_view.checklist_changed.connect(self._set_dirty)
        self._changelog_view = ChangelogView()
        self._changelog_view.changed.connect(
            lambda: self._bus.any_change.emit("changelog")
        )

        # Wizard-Platzhalter
        self._wizard_widget = QWidget()

        self._views = {
            "overview": self._overview,
            "building": self._building_view,
            "topology": self._topology_view,
            "addresses": self._address_tree,
            "addresses_table": self._address_table,
            "validation": self._validation_view,
            "gewerke": self._gewerk_view,
            "scenes": self._scene_view,
            "quotations": self._quotation_view,
            "customer_quotes": self._customer_quote_view,
            "datasheets": self._datasheet_view,
            "topology_report": self._topology_report_view,
            "topology_diagram": self._topology_diagram_view,
            "material_list": self._material_list_view,
            "co_linking": self._co_linking_view,
            "linking_matrix": self._linking_matrix_view,
            "cable_length": self._cable_length_view,
            "dali_config": self._dali_config_view,
            "knx_secure": self._knx_secure_view,
            "time_programs": self._time_program_view,
            "bauherr_form": self._bauherr_form_view,
            "commissioning": self._commissioning_view,
            "changelog": self._changelog_view,
            "help": self._help_view,
            "wizard": self._wizard_widget,
        }

        for view in self._views.values():
            self._stack.addWidget(view)

        # Bus-Signale zu Handlern verdrahten
        self._bus.building_changed.connect(self._on_structure_changed)
        self._bus.material_changed.connect(self._on_material_list_changed)
        self._bus.topology_changed.connect(self._on_topology_changed)

        # Bus an Views übergeben
        self._building_view.set_bus(self._bus)
        self._material_list_view.set_bus(self._bus)
        self._gewerk_view.set_bus(self._bus)
        self._address_tree.set_bus(self._bus)
        self._address_table.set_bus(self._bus)
        self._topology_view.set_bus(self._bus)
        self._linking_matrix_view.set_bus(self._bus)

        # Bus-Signale zu Handlern
        self._bus.functions_changed.connect(self._on_functions_changed)
        self._bus.addresses_changed.connect(self._on_addresses_changed)

        # Bauherren-Beratung: Funktionszuweisungen lösen volle Neuberechnung aus
        self._bauherr_form_view.project_changed.connect(self._bus.emit_functions_changed)
        # Freitext-Anmerkungen/Notizen: nur Dirty-Flag/Autosave, keine Neuberechnung
        self._bauherr_form_view.notes_changed.connect(
            lambda: self._bus.any_change.emit("bauherr_notes")
        )

        # Undo + Auto-Save
        self._bus.change_started.connect(self._on_begin_change)
        self._bus.any_change.connect(self._on_any_change)

    def _create_status_bar(self):
        self._status_bar = KnxStatusBar()
        self.setStatusBar(self._status_bar)

    def _navigate(self, key: str):
        """Navigiert zu einer Ansicht."""
        if key == "new_project":
            self._new_project()
            return
        if key == "open_project":
            self._open_project()
            return
        if key == "import_csv":
            self._import_file()
            return
        if key == "export":
            self._export_csv()
            return
        if key == "reports":
            self._show_reports()
            return
        if key == "settings":
            self._show_settings()
            return
        if key == "wizard":
            self._start_wizard()
            return
        if self._project:
            if key == "overview":
                self._overview.update_from_project(self._project)
            elif key == "gewerke":
                self._gewerk_view.set_project(self._project)
            elif key == "topology_report":
                self._topology_report_view.set_project(self._project)
            elif key == "scenes":
                self._scene_view.set_project(self._project)
            elif key == "quotations":
                self._quotation_view.set_project(self._project)
            elif key == "customer_quotes":
                self._customer_quote_view.set_project(self._project)
            elif key == "material_list":
                self._material_list_view.set_project(self._project)
            elif key == "co_linking":
                self._co_linking_view.set_project(self._project)
            elif key == "linking_matrix":
                self._linking_matrix_view.set_project(self._project)
            elif key == "cable_length":
                self._cable_length_view.set_project(self._project)
            elif key == "dali_config":
                self._dali_config_view.set_project(self._project)
            elif key == "knx_secure":
                self._knx_secure_view.set_project(self._project)
            elif key == "time_programs":
                self._time_program_view.set_project(self._project)
            elif key == "bauherr_form":
                self._bauherr_form_view.set_project(self._project)
            elif key == "commissioning":
                self._commissioning_view.set_project(self._project)
            elif key == "changelog":
                self._changelog_view.set_project(self._project)
            elif key == "datasheets":
                self._datasheet_view.set_project(self._project)
            elif key == "topology_diagram":
                self._topology_diagram_view.set_project(self._project)

        view = self._views.get(key)
        if view:
            self._stack.setCurrentWidget(view)

    def _update_views(self):
        """Aktualisiert alle Ansichten nach Projektänderung."""
        if not self._project:
            return

        self._overview.update_from_project(self._project)
        self._building_view.set_areal(self._project.areal)
        self._building_view.set_topology(self._project.topology)
        self._building_view.set_group_addresses(self._project.group_addresses)
        self._topology_view.set_project(self._project)
        self._address_tree.set_structure(self._project.group_addresses)
        self._address_table.set_structure(self._project.group_addresses)
        self._gewerk_view.set_project(self._project)
        self._scene_view.set_project(self._project)
        self._quotation_view.set_project(self._project)
        self._customer_quote_view.set_project(self._project)
        self._datasheet_view.set_project(self._project)
        self._topology_report_view.set_project(self._project)
        self._material_list_view.set_project(self._project)
        self._co_linking_view.set_project(self._project)
        self._linking_matrix_view.set_project(self._project)
        self._cable_length_view.set_project(self._project)
        self._topology_diagram_view.set_project(self._project)
        self._dali_config_view.set_project(self._project)
        self._knx_secure_view.set_project(self._project)
        self._time_program_view.set_project(self._project)
        self._commissioning_view.set_project(self._project)
        self._changelog_view.set_project(self._project)

        ga_count = len(self._project.group_addresses.all_addresses())
        self._status_bar.set_project_name(self._project.name)
        self._status_bar.set_variant(self._project.config.mg_variant)
        self._status_bar.set_ga_count(ga_count)

    def _on_structure_changed(self):
        """Reagiert auf Änderungen an der Gebäudestruktur.

        Aktoren und GAs werden automatisch neu berechnet, da Gewerk-Zuweisungen
        an Räumen die Gerätebelegung und Adressstruktur beeinflussen.
        Die Topologie-Struktur (Linien) bleibt dabei erhalten.
        """
        if not self._project:
            return
        result = self._recalc.recalc_actors_and_addresses(self._project)
        self._update_views()
        if result["ok"]:
            self._status_bar.set_status(
                f"Gebäude geändert – Aktoren/Sensoren und GAs neu berechnet "
                f"({result['actor_count']} Geräte, {result['ga_count']} GAs)."
            )

    def _on_project_name_changed(self, name: str):
        """Aktualisiert Statusleiste und Fenstertitel wenn Projektname geändert wurde."""
        self._status_bar.set_project_name(name)
        self._update_window_title()

    def _on_material_list_changed(self):
        """Reagiert auf Änderungen an der Materialliste (Produktzuweisung etc.)."""
        if self._project:
            self._project.touch()
            # Produktdatenblätter-Ansicht mitaktualisieren, damit neu
            # zugewiesene Produkte sofort sichtbar sind (FA-1205)
            self._datasheet_view.set_project(self._project)

    def _on_topology_changed(self):
        """Reagiert auf Topologie-Änderungen aus der Materiallisten-Ansicht.

        Wird ausgelöst wenn Geräte über die Materialliste in die Topologie
        eingefügt oder aufgeteilt wurden (z.B. kanalbasierter Aktor-Split).
        Aktualisiert alle topologie-abhängigen Views, ohne die Materialliste
        selbst neu aufzubauen (diese wurde bereits vom Aufrufer aktualisiert).
        """
        if not self._project:
            return
        self._topology_view.set_project(self._project)
        self._topology_report_view.set_project(self._project)
        self._overview.update_from_project(self._project)
        self._building_view.set_topology(self._project.topology)
        self._building_view.set_group_addresses(self._project.group_addresses)
        self._co_linking_view.set_project(self._project)
        self._linking_matrix_view.set_project(self._project)

    def _on_addresses_changed(self):
        """Reagiert auf GA-Änderungen (Umbenennen, DPT, etc.) aus beiden Address-Views.

        Die bearbeitende View hat sich bereits selbst aktualisiert.
        Hier wird die jeweils andere Address-View synchronisiert.
        Zusätzlich werden function_assignments aller Bedienelemente neu berechnet,
        damit Verknüpfungsmatrix und Gebäudeansicht stets aktuelle GA-Daten zeigen.
        """
        if not self._project:
            return
        # function_assignments aus aktueller GA-Struktur neu ableiten
        SensorService().auto_assign_functions(
            self._project.all_rooms, self._project.group_addresses
        )
        # Beide Views zeigen dieselbe Struktur – beide neu laden
        self._address_tree.set_structure(self._project.group_addresses)
        self._address_table.set_structure(self._project.group_addresses)
        ga_count = len(self._project.group_addresses.all_addresses())
        self._status_bar.set_ga_count(ga_count)
        # Gebäudeansicht: Bedienelement-Zeilen mit aktualisierten function_assignments neu bauen
        self._building_view.set_areal(self._project.areal)
        self._building_view.set_topology(self._project.topology)
        self._building_view.set_group_addresses(self._project.group_addresses)
        # GA-Bezeichnungen werden in Verknüpfungsmatrix, CO-Linking und den
        # Aktor-Kanalknoten der Topologie-Ansicht angezeigt
        self._co_linking_view.set_project(self._project)
        self._linking_matrix_view.set_project(self._project)
        self._topology_view.set_project(self._project)

    def _on_functions_changed(self):
        """Reagiert auf Gewerk-Änderungen aus der manuellen Bearbeitungsphase.

        Aktoren/Sensoren in der bestehenden Topologie werden automatisch neu
        berechnet, ebenso die Gruppenadress-Struktur. Manuelle GAs und
        Produktzuweisungen bleiben erhalten.
        """
        if not self._project:
            return
        result = self._recalc.recalc_actors_and_addresses(self._project)
        self._update_views()
        if result["ok"]:
            self._status_bar.set_status(
                f"Gewerke geändert – Aktoren/Sensoren und GAs neu berechnet "
                f"({result['actor_count']} Geräte, {result['ga_count']} GAs)."
            )

    # -- Phase D: Auto-Save, Dirty-Flag, Undo-Integration --

    def _on_begin_change(self, description: str):
        """Snapshot VOR der Änderung aufnehmen – setzt einen Undo-Punkt.

        Wird von Views über bus.begin_change() ausgelöst, bevor sie Daten
        modifizieren. Der Snapshot wird als ObjectStateCommand im Undo-Stack
        abgelegt, sobald any_change feuert.
        """
        if not self._project:
            return
        import copy
        snapshot = copy.deepcopy(self._project)
        self._pending_undo_cmd = ObjectStateCommand(
            target=self._project,
            snapshot=snapshot,
            description=description,
            # Laufzeit-Felder nicht wiederherstellen
            preserve_attrs=("_file_path", "_gewerk_catalog"),
        )

    def _on_any_change(self, ctx: str):
        """Nach jeder Änderung: Undo-Command abschliessen, Dirty-Flag setzen,
        Auto-Save-Timer starten.
        """
        # Undo-Command in Stack aufnehmen (falls begin_change aufgerufen wurde)
        if self._pending_undo_cmd is not None:
            self._undo_manager._undo_stack.append(self._pending_undo_cmd)
            if len(self._undo_manager._undo_stack) > self._undo_manager.MAX_HISTORY:
                self._undo_manager._undo_stack.pop(0)
            self._undo_manager._redo_stack.clear()
            self._pending_undo_cmd = None
            self._update_undo_actions()

        # Dirty-Flag und Auto-Save
        self._set_dirty(True)
        if self._project and self._project._file_path:
            self._autosave_timer.start()  # Timer neu starten (30s Inaktivität)

    def _autosave(self):
        """Automatisch speichern nach 30 Sekunden Inaktivität."""
        if not self._project or not self._project._file_path:
            return
        try:
            self._project.save(self._project._file_path)
            self._set_dirty(False)
            self._status_bar.set_status("Automatisch gespeichert.")
            logger.info("Auto-Save erfolgreich.")
        except Exception as e:
            logger.warning(f"Auto-Save fehlgeschlagen: {e}")

    def _set_dirty(self, dirty: bool):
        """Setzt den Änderungs-Status und aktualisiert den Fenstertitel."""
        self._dirty = dirty
        self._autosave_timer.stop() if not dirty else None
        self._update_window_title()

    def _update_window_title(self):
        """Aktualisiert den Fenstertitel mit Projektname und Dirty-Indikator."""
        name = self._project.name if self._project else ""
        prefix = "● " if self._dirty else ""
        suffix = f" – {name}" if name else ""
        self.setWindowTitle(f"{prefix}{APP_NAME} v{__version__}{suffix}")

    # -- Projekt-Aktionen --

    def _new_project(self):
        from ..services.project_service import ProjectService

        # Neue Projekte werden verbindlich im Workspace abgelegt (FA-1601):
        # {Workspace}/{Projektname}/{Projektname}.knxarr + Revisionen/ + Berichte/
        workspace = self._ensure_workspace()
        project_service = ProjectService()

        dialog = NewProjectDialog(self, workspace_root=workspace, project_service=project_service)
        if not dialog.exec():
            return

        try:
            file_path = project_service.prepare_workspace_project_folder(
                workspace, dialog.project_name
            )
        except FileExistsError as e:
            QMessageBox.warning(
                self, "Projekt existiert bereits",
                f"Im Arbeitsverzeichnis existiert bereits ein Projekt mit diesem Namen:\n"
                f"{e.args[0]}\n\nBitte wählen Sie einen anderen Projektnamen.",
            )
            return

        project = KnxProject(
            name=dialog.project_name,
            project_number=dialog.project_number,
        )
        project.config.mg_variant = dialog.variant

        # Vorlage laden
        if dialog.template_key != "empty":
            areal = self._building_service.load_template(dialog.template_key)
            if areal:
                project.areal = areal
                self._building_service.assign_main_groups(project.areal)

        project.add_changelog_entry("Projekt", f"Projekt '{project.name}' erstellt.")

        try:
            project.save(file_path)
        except Exception as e:
            logger.exception("Projekt konnte nicht gespeichert werden: %s", e)
            QMessageBox.critical(
                self, "Projekt konnte nicht erstellt werden",
                f"Die Projektdatei konnte nicht gespeichert werden:\n{file_path}\n\nUrsache: {e}",
            )
            return

        project_service.add_to_recent(file_path)

        self._project = project
        self._undo_manager.clear()
        self._set_dirty(False)
        self._update_views()
        self._status_bar.set_status(
            f"Neues Projekt '{project.name}' erstellt unter: {file_path}"
        )
        self._sidebar.select("overview")
        self._navigate("overview")

    def open_file(self, path: str):
        """Öffnet eine .knxarr-Datei direkt (z.B. per Doppelklick im Explorer)."""
        try:
            self._project = KnxProject.load(path)
            from ..services.project_service import ProjectService
            ProjectService().add_to_recent(path)
            self._undo_manager.clear()
            self._set_dirty(False)
            # GA-Metadaten (Gewerk, Raum) aus Bezeichnung anreichern
            self._enrich_ga_metadata()
            # DALI-Gruppen/EVGs nachträglich ableiten (für Dateien, die vor
            # der Auto-Konfiguration gespeichert wurden); überschreibt keine
            # bestehenden Gruppen/EVGs (guard in auto_configure_from_import)
            self._auto_configure_dali()
            # function_assignments aus aktueller GA-Struktur frisch berechnen,
            # da gespeicherte Werte veraltet sein können (z.B. GAs wurden nach
            # letztem Speichern umbenannt oder neu generiert).
            SensorService().auto_assign_functions(
                self._project.all_rooms, self._project.group_addresses
            )
            self._update_views()
            self._status_bar.set_status(f"Projekt '{self._project.name}' geladen.")
            self._sidebar.select("overview")
            self._navigate("overview")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"Projekt konnte nicht geladen werden:\n{e}")

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Projekt öffnen", "",
            "KNiX Arranger Projekte (*.knxarr);;Alle Dateien (*.*)",
        )
        if path:
            self.open_file(path)

    def _save_project(self):
        if not self._project:
            self._status_bar.set_status("Kein Projekt zum Speichern.")
            return
        if self._project._file_path:
            self._project.save(self._project._file_path)
            self._set_dirty(False)
            self._status_bar.set_status("Projekt gespeichert.")
        else:
            self._save_project_as()

    def _save_project_as(self):
        if not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Projekt speichern", f"{self._project.name}.knxarr",
            "KNiX Arranger Projekte (*.knxarr);;Alle Dateien (*.*)",
        )
        if path:
            self._project.save(path)
            self._set_dirty(False)
            self._status_bar.set_status(f"Projekt gespeichert: {path}")

    def _import_file(self):
        """Importiert ETS6-Dateien: KNXPROJ, XLSX (Topologie/GA-Report) oder CSV."""
        dialog = ImportDialog(self)
        if not dialog.exec():
            return

        filepath = dialog.filepath
        file_type = dialog.file_type

        if not self._project:
            self._project = KnxProject(name="Importiertes Projekt")

        try:
            if file_type == "knxproj":
                self._import_knxproj(filepath)
            elif file_type == "xlsx":
                self._import_xlsx(filepath)
            else:
                self._import_csv(filepath)
        except Exception as e:
            logger.exception("Import-Fehler: %s", e)
            import os
            QMessageBox.critical(
                self, "Import fehlgeschlagen",
                f"Die Datei konnte nicht importiert werden:\n"
                f"{os.path.basename(filepath)}\n\n"
                f"Ursache: {e}\n\n"
                "Mögliche Gründe:\n"
                "• Die Datei ist beschädigt oder hat ein unbekanntes Format\n"
                "• Die Datei wird noch von einem anderen Programm verwendet\n"
                "• Fehlende Leserechte auf die Datei",
            )

    def _import_csv(self, filepath: str):
        """Importiert einen ETS6 GA-Export (CSV)."""
        def do_import():
            importer = CsvImportService()
            structure = importer.import_csv(filepath)
            self._project.group_addresses = structure
            return structure

        def on_success(structure):
            self._update_views()
            ga_count = len(structure.all_addresses())
            self._status_bar.set_status(f"CSV importiert: {ga_count} Gruppenadressen.")
            self._sidebar.select("addresses")
            self._navigate("addresses")

        run_import(
            self, "Gruppenadressen werden importiert…", do_import, on_success,
            self._import_worker_ref,
        )

    def _warn_if_building_structure_empty(self, areal):
        """Macht sichtbar, wenn aus dem XLSX-Import keine Gebäudestruktur
        abgeleitet werden konnte (FA-519).

        `derive_building_structure()` scheitert lautlos (nur Log-Warning),
        wenn keine GA-Bezeichnung dem erwarteten Namensmuster
        'GEWERK.STOCKWERK.RAUM.ELEMENT' entspricht -- z.B. weil der
        Integrator die GAs frei/uneinheitlich beschriftet hat. Ohne diesen
        Hinweis bleibt unbemerkt, dass Stockwerke, Räume und
        Gewerk-Zuweisungen manuell im Wizard nachgetragen werden müssen.
        """
        if areal.all_floors:
            return
        QMessageBox.warning(
            self, "Keine Gebäudestruktur erkannt",
            "Aus den Gruppenadress-Bezeichnungen konnte keine Gebäudestruktur "
            "abgeleitet werden.\n\n"
            "Das deutet darauf hin, dass die GAs nicht nach dem erwarteten Muster "
            "'GEWERK.STOCKWERK.RAUM.ELEMENT' benannt sind. Gruppenadressen, "
            "Topologie und Geräte wurden trotzdem vollständig importiert -- "
            "Stockwerke, Räume und Gewerk-Zuweisungen müssen jedoch manuell im "
            "Wizard (Schritt 2/3/5) nachgetragen werden."
        )

    def _collect_device_locations(self, importer) -> dict | None:
        """Kombiniert Einbauort-Daten aus GA-Report und Gebäude-Report (je
        nachdem, was bereits importiert wurde) zu einem gemeinsamen
        device_locations-Dict für link_rooms_to_lines().

        Der Gebäude-Report hat Vorrang: er bildet die tatsächliche ETS6-
        Raumzuordnung ab, während die 'Gebäude'-Spalte des GA-Reports
        dieselbe Information nur als Freitext trägt.
        """
        device_locations: dict = {}
        if self._ga_report_path:
            try:
                device_locations.update(
                    importer.extract_device_locations(self._ga_report_path)
                )
            except Exception as e:
                logger.warning(f"Einbauort-Extraktion (GA-Report) fehlgeschlagen: {e}")
        if self._building_report_path:
            try:
                device_locations.update(
                    importer.extract_device_locations_from_building_report(
                        self._building_report_path
                    )
                )
            except Exception as e:
                logger.warning(f"Einbauort-Extraktion (Gebäude-Report) fehlgeschlagen: {e}")
        return device_locations or None

    def _apply_button_configuration(self, importer) -> int:
        """Reichert Device.button_configuration mit der Tastenbelegung aus
        Topologie- und/oder Gebäude-Report an (rein informativ -- siehe
        XlsxImportService.extract_button_configuration: keine automatische
        Gewerk-/Funktionsableitung, nur als lesbare Referenz z.B. per
        Tooltip). Beide Quellen liefern für dasselbe Gerät i.d.R. denselben
        Text; falls beide vorhanden sind, hat der Gebäude-Report Vorrang.

        Gibt die Anzahl aktualisierter Geräte zurück.
        """
        texts: dict[str, str] = {}
        if self._topology_xlsx_path:
            try:
                texts.update(importer.extract_button_configuration(self._topology_xlsx_path))
            except Exception as e:
                logger.warning(f"Tastenbelegung-Extraktion (Topologie) fehlgeschlagen: {e}")
        if self._building_report_path:
            try:
                texts.update(
                    importer.extract_button_configuration(self._building_report_path)
                )
            except Exception as e:
                logger.warning(f"Tastenbelegung-Extraktion (Gebäude-Report) fehlgeschlagen: {e}")
        if not texts:
            return 0

        updated = 0
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    text = texts.get(device.physical_address)
                    if text and device.button_configuration != text:
                        device.button_configuration = text
                        updated += 1
        return updated

    def _apply_scene_values(self, importer) -> int:
        """Reichert Device.scene_values mit den konfigurierten Szenen-
        Schaltwerten aus Topologie- und/oder Gebäude-Report an (FA-1809,
        siehe XlsxImportService.extract_scene_values). Falls beide Quellen
        vorhanden sind, hat der Gebäude-Report Vorrang (analog
        _apply_button_configuration).

        Gibt die Anzahl aktualisierter Geräte zurück.
        """
        entries: dict[str, list] = {}
        if self._topology_xlsx_path:
            try:
                entries.update(importer.extract_scene_values(self._topology_xlsx_path))
            except Exception as e:
                logger.warning(f"Szenen-Schaltwerte-Extraktion (Topologie) fehlgeschlagen: {e}")
        if self._building_report_path:
            try:
                entries.update(importer.extract_scene_values(self._building_report_path))
            except Exception as e:
                logger.warning(f"Szenen-Schaltwerte-Extraktion (Gebäude-Report) fehlgeschlagen: {e}")
        if not entries:
            return 0

        updated = 0
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    values = entries.get(device.physical_address)
                    if values and device.scene_values != values:
                        device.scene_values = values
                        updated += 1
        return updated

    def _apply_scene_triggers(self, importer) -> int:
        """Reichert Device.scene_triggers mit den konfigurierten Szenen-
        Ausloesern (Taste -> Szenennummer) aus Topologie- und/oder Gebäude-
        Report an (FA-1810, siehe XlsxImportService.extract_scene_triggers).
        Falls beide Quellen vorhanden sind, hat der Gebäude-Report Vorrang
        (analog _apply_button_configuration).

        Gibt die Anzahl aktualisierter Geräte zurück.
        """
        entries: dict[str, list] = {}
        if self._topology_xlsx_path:
            try:
                entries.update(importer.extract_scene_triggers(self._topology_xlsx_path))
            except Exception as e:
                logger.warning(f"Szenen-Ausloeser-Extraktion (Topologie) fehlgeschlagen: {e}")
        if self._building_report_path:
            try:
                entries.update(importer.extract_scene_triggers(self._building_report_path))
            except Exception as e:
                logger.warning(f"Szenen-Ausloeser-Extraktion (Gebäude-Report) fehlgeschlagen: {e}")
        if not entries:
            return 0

        updated = 0
        for area in self._project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    triggers = entries.get(device.physical_address)
                    if triggers and device.scene_triggers != triggers:
                        device.scene_triggers = triggers
                        updated += 1
        return updated

    def _import_xlsx(self, filepath: str):
        """Importiert einen ETS6 Topologie-Report oder GA-Report (XLSX) (FA-511, FA-519b).

        Die eigentliche Verarbeitung läuft in do_import() im Hintergrund-
        Thread (run_import) -- deshalb darf do_import() KEINE Qt-Widgets
        berühren, nur self._project und andere reine Python-Objekte. Alle
        UI-Aktionen (Dialoge, Statusleiste, Navigation) laufen erst danach
        in on_success(), zurück im UI-Thread.
        """
        importer = XlsxImportService()

        report_type = importer.detect_report_type(filepath)
        if report_type == "ga_report":
            self._import_ga_report_xlsx(filepath, importer)
            return
        if report_type == "building_report":
            self._import_building_report_xlsx(filepath, importer)
            return

        def do_import():
            # Snapshot fürs Re-Import-Abgleich (siehe Ende der Methode): die
            # Objekte selbst werden unten nur ersetzt, nicht mutiert, daher bleibt
            # diese Referenz gültig auf dem alten Stand.
            old_snapshot = KnxProject(name="")
            old_snapshot.topology = self._project.topology
            old_snapshot.areal = self._project.areal

            topology = importer.import_xlsx(filepath)
            topology.is_imported = True
            self._project.topology = topology
            self._topology_xlsx_path = filepath

            # Projektname aus Metadaten uebernehmen, falls noch leer
            meta = getattr(topology, "metadata", {})
            if meta.get("project_name") and self._project.name == "Importiertes Projekt":
                self._project.name = meta["project_name"]

            # Gruppenadressen aus XLSX extrahieren — nur wenn noch kein GA-Report geladen (FA-519)
            # GA-Report hat Vorrang: er liefert echte Gruppen-Namen und mehr GAs
            if self._project.group_addresses.source != "ga_report":
                try:
                    ga_structure = importer.extract_group_addresses(filepath)
                    self._project.group_addresses = ga_structure
                except Exception as e:
                    logger.warning(f"Gruppenadressen konnten nicht extrahiert werden: {e}")

            # Gebäudestruktur aus GA-Namen ableiten (FA-506 analog). Die bereits
            # bekannte GA-Struktur wird mitgegeben, damit bei Projekten ohne
            # Stockwerk-Buchstaben-Konvention die echten Hauptgruppen-Namen
            # (z.B. "Erdgeschoss") als Stockwerksname uebernommen werden koennen.
            warn_empty_areal = None
            try:
                # Gebäude-Report hat Vorrang (FA-511b): er liefert die
                # tatsächliche ETS6-Raumzuordnung statt einer aus GA-Namen
                # abgeleiteten Vermutung (siehe _collect_device_locations).
                if self._building_report_path:
                    areal = importer.derive_building_structure_from_building_report(
                        self._building_report_path
                    )
                else:
                    areal = importer.derive_building_structure(
                        filepath, ga_structure=self._project.group_addresses
                    )
                if meta.get("project_name"):
                    areal.name = meta["project_name"]
                    # Gebäude-Name NICHT mit dem Projektnamen überschreiben (FA-511c):
                    # building_view.py zeigt areal.name bereits als Wurzelknoten an;
                    # der Gebäude-Knoten soll seinen eigenen (generischen "Gebäude"
                    # oder aus dem Gebäude-Report abgeleiteten) Namen behalten, sonst
                    # stünde derselbe lange Projektname redundant in beiden Zeilen --
                    # und bei Re-Import nach einem Gebäude-Report würde dessen saubere
                    # Darstellung dadurch wieder zerstört.
                self._project.areal = areal
                self._building_service.assign_main_groups(self._project.areal)
                warn_empty_areal = areal
            except Exception as e:
                logger.warning(f"Gebäudestruktur konnte nicht abgeleitet werden: {e}")

            # Einbauort-Daten aus GA-Report und/oder Gebäude-Report laden
            # (beide optional bereits importiert)
            device_locations = self._collect_device_locations(importer)

            # Installations-Hinweise aus dem Topologie-Report laden (FA-519c)
            device_notes = None
            try:
                device_notes = importer.extract_device_notes(filepath)
            except Exception as e:
                logger.warning(f"Installations-Hinweise-Extraktion fehlgeschlagen: {e}")

            # Tastenbelegung als lesbare Referenz laden (rein informativ)
            self._apply_button_configuration(importer)

            # Szenen-Schaltwerte aus Geräteparametern laden (FA-1809)
            self._apply_scene_values(importer)

            # Szenen-Ausloeser aus Tastenkonfiguration laden (FA-1810)
            self._apply_scene_triggers(importer)

            # Verteiler-Räume (HV/UV/NV/TV) aus Einbauort ableiten (FA-521b) --
            # Pendant zur DistributionBoard-Erkennung beim .knxproj-Import, für
            # Projekte, die nur per XLSX importiert werden können (z.B. KNX Secure).
            # Muss VOR link_rooms_to_lines laufen: die dortige physische
            # Einbauort-Zuordnung braucht die Verteiler-Räume bereits angelegt,
            # um Geräte im Verteiler dorthin (statt in einen Funktionsraum) zu
            # verknüpfen (FA-ImportGuard-Folgefix: Aktoren im Verteiler).
            try:
                importer.create_verteiler_rooms(self._project.topology, self._project.areal)
            except Exception as e:
                logger.warning(f"Verteiler-Raum-Ableitung fehlgeschlagen: {e}")

            # Zuvor manuell zugeordnete Verteiler (Schritt 4) wieder in ihren
            # echten Raum verschieben, bevor create_verteiler_rooms' frischer
            # Pseudo-Raum den Geräten zugeordnet wird -- sonst würde jeder
            # Re-Import die manuelle Zuordnung rückgängig machen.
            try:
                importer.apply_verteiler_room_overrides(
                    self._project.topology, self._project.areal,
                    self._project.verteiler_room_overrides,
                )
            except Exception as e:
                logger.warning(f"Verteiler-Raum-Zuordnung fehlgeschlagen: {e}")

            # Räume mit Topologie-Linien verknüpfen (assigned_room_ids / device.room_id)
            try:
                linked = importer.link_rooms_to_lines(
                    self._project.topology,
                    self._project.group_addresses,
                    self._project.areal,
                    device_locations=device_locations,
                    device_notes=device_notes,
                )
                logger.info(f"Raum-Linien-Verknüpfung: {linked} Paare hergestellt.")
            except Exception as e:
                logger.warning(f"Raum-Linien-Verknüpfung fehlgeschlagen: {e}")

            # Bedienelemente aus Topologie ableiten (FA-1404) – setzt participant_number
            try:
                KnxprojImportService._create_bedienelemente_from_topology(
                    self._project.topology, self._project.areal
                )
            except Exception as e:
                logger.warning(f"Bedienelemente-Ableitung aus Topologie fehlgeschlagen: {e}")

            # KO-Verbindungen aus GA-Report anreichern (falls bereits importiert)
            if self._ga_report_path:
                try:
                    enriched, added = importer.enrich_device_ko_connections(
                        self._project.topology, self._ga_report_path
                    )
                    if enriched:
                        logger.info(f"KO-Anreicherung: {enriched} Geräte, {added} neue KOs.")
                except Exception as e:
                    logger.warning(f"KO-Anreicherung fehlgeschlagen: {e}")

            # Funktionszuordnungen direkt aus KO-GA-Verknüpfungen übernehmen (FA-521c) --
            # auto_assign_functions() allein bleibt für importierte Projekte leer, siehe
            # XlsxImportService.backfill_function_assignments-Docstring.
            try:
                importer.backfill_function_assignments(
                    self._project.topology, self._project.areal, self._project.group_addresses
                )
            except Exception as e:
                logger.warning(f"Funktionszuordnungs-Backfill fehlgeschlagen: {e}")

            # Gewerk-Zuweisungen aus GA-Bezeichnungen ableiten (FA-519b)
            self._derive_gewerke_from_gas()

            # GA-Metadaten (Gewerk, Raum) aus Bezeichnung anreichern
            self._enrich_ga_metadata()

            # DALI-Gateways automatisch konfigurieren (GA-Verknüpfung + Gruppen)
            self._auto_configure_dali()

            # Re-Import-Abgleich (siehe _import_knxproj): alte IDs + KNiX-
            # Zusatzdaten anhand physischer Adresse/Raumnummer übernehmen, bevor
            # der Nutzer die Änderungen zu Gesicht bekommt.
            reconcile_diff = reconcile_reimport(old_snapshot, self._project)
            is_reimport = reconcile_diff.devices_matched > 0 or reconcile_diff.rooms_matched > 0
            # GAs, die durch den Abgleich wieder zu einer bestehenden Gewerk-Zuweisung
            # gehören, mit deren assignment_id verknüpfen (verhindert Duplikat-Blöcke
            # bei der nächsten Neugenerierung, FA-521e).
            self._relink_ga_assignment_ids()
            self._project.add_changelog_entry(
                "Re-Import" if is_reimport else "Import",
                f"{os.path.basename(filepath)}: {reconcile_diff.summary_line()}",
            )

            return {
                "topology": topology,
                "warn_empty_areal": warn_empty_areal,
                "reconcile_diff": reconcile_diff,
                "is_reimport": is_reimport,
            }

        def on_success(result: dict):
            topology = result["topology"]
            reconcile_diff = result["reconcile_diff"]
            is_reimport = result["is_reimport"]

            if result["warn_empty_areal"] is not None:
                self._warn_if_building_structure_empty(result["warn_empty_areal"])
            if is_reimport and (reconcile_diff.has_removed or reconcile_diff.has_ga_conflicts):
                QMessageBox.warning(
                    self, "Re-Import: Abgleich-Hinweise",
                    "Beim Abgleich mit dem bisherigen Projektstand wurden folgende "
                    "Geräte/Räume nicht mehr gefunden. Falls sie in Excel nur "
                    "umbenannt statt gelöscht wurden, sind ihre KNiX-Planungsdaten "
                    "(Gewerk-Zuweisungen, Bedienelemente, Materialliste, ...) jetzt "
                    "verwaist:\n\n" + reconcile_diff.details_text(),
                )
            self._warn_if_channel_conflicts()

            self._update_views()

            total_devices = sum(
                len(line.devices)
                for area in topology.areas
                for line in area.lines
            )
            kos = sum(
                len(d.communication_objects)
                for area in topology.areas
                for line in area.lines
                for d in line.devices
            )
            total_floors = len(self._project.areal.all_floors)
            total_rooms = len(self._project.areal.all_rooms)
            ga_count = len(self._project.group_addresses.all_addresses())
            ga_source = self._project.group_addresses.source
            ga_hint = " (GA-Report)" if ga_source == "ga_report" else ""
            ga_tipp = (
                " | Tipp: Gruppenadress-Report (XLSX) importieren für vollständige GA-Daten."
                if not self._ga_report_path else ""
            )
            self._status_bar.set_status(
                f"Topologie importiert: {len(topology.areas)} Bereiche, "
                f"{sum(len(a.lines) for a in topology.areas)} Linien, "
                f"{total_devices} Geräte, {kos} KOs, {ga_count} GAs{ga_hint} | "
                f"Gebäude: {total_floors} Stockwerke, {total_rooms} Räume.{ga_tipp} | "
                f"{reconcile_diff.summary_line()}."
            )
            self._sidebar.select("topology_report")
            self._navigate("topology_report")

        run_import(
            self, "Topologie wird importiert…", do_import, on_success,
            self._import_worker_ref,
        )

    def _import_ga_report_xlsx(self, filepath: str, importer):
        """Importiert einen ETS6 Gruppenadress-Report (XLSX) (FA-519b).

        Siehe _import_xlsx(): do_import() läuft im Hintergrund-Thread und
        darf keine Qt-Widgets berühren, on_success() danach im UI-Thread.
        """
        def do_import():
            # Snapshot fürs Re-Import-Abgleich (siehe Ende der Methode). Topologie
            # ändert sich hier nicht, nur ggf. areal (Gebäudestruktur-Re-Ableitung
            # unten) -- alter Stand bleibt gültig, da nur ersetzt, nicht mutiert.
            old_snapshot = KnxProject(name="")
            old_snapshot.topology = self._project.topology
            old_snapshot.areal = self._project.areal

            self._ga_report_path = filepath
            ga_structure = importer.import_ga_report(filepath)
            self._project.group_addresses = ga_structure

            warn_empty_areal = None
            # Falls Topologie bereits geladen: Einbauort + KO-Anreicherung nachziehen
            if self._project.topology.areas:
                # Gebäudestruktur erneut ableiten: war die Topologie vor diesem
                # GA-Report importiert worden, standen die echten Hauptgruppen-
                # Namen (z.B. "Erdgeschoss") noch nicht zur Verfügung. Gebäude-
                # Report hat Vorrang (siehe _import_xlsx / _collect_device_locations).
                if self._building_report_path or self._topology_xlsx_path:
                    try:
                        if self._building_report_path:
                            areal = importer.derive_building_structure_from_building_report(
                                self._building_report_path
                            )
                        else:
                            areal = importer.derive_building_structure(
                                self._topology_xlsx_path, ga_structure=ga_structure
                            )
                        if self._project.areal and self._project.areal.name:
                            areal.name = self._project.areal.name
                            if areal.buildings and self._project.areal.buildings:
                                areal.buildings[0].name = self._project.areal.buildings[0].name
                        self._project.areal = areal
                        self._building_service.assign_main_groups(self._project.areal)
                        warn_empty_areal = areal
                    except Exception as e:
                        logger.warning(f"Gebäudestruktur-Ableitung nach GA-Import fehlgeschlagen: {e}")

                device_locations = self._collect_device_locations(importer)

                device_notes = None
                if self._topology_xlsx_path:
                    try:
                        device_notes = importer.extract_device_notes(self._topology_xlsx_path)
                    except Exception as e:
                        logger.warning(f"Installations-Hinweise-Extraktion fehlgeschlagen: {e}")

                self._apply_button_configuration(importer)
                self._apply_scene_values(importer)
                self._apply_scene_triggers(importer)

                try:
                    importer.create_verteiler_rooms(self._project.topology, self._project.areal)
                except Exception as e:
                    logger.warning(f"Verteiler-Raum-Ableitung fehlgeschlagen: {e}")

                # Zuvor manuell zugeordnete Verteiler (Schritt 4) wieder in
                # ihren echten Raum verschieben (siehe _import_xlsx).
                try:
                    importer.apply_verteiler_room_overrides(
                        self._project.topology, self._project.areal,
                        self._project.verteiler_room_overrides,
                    )
                except Exception as e:
                    logger.warning(f"Verteiler-Raum-Zuordnung fehlgeschlagen: {e}")

                try:
                    importer.link_rooms_to_lines(
                        self._project.topology,
                        ga_structure,
                        self._project.areal,
                        device_locations=device_locations,
                        device_notes=device_notes,
                    )
                except Exception as e:
                    logger.warning(f"Raum-Linien-Verknüpfung fehlgeschlagen: {e}")

                try:
                    importer.enrich_device_ko_connections(
                        self._project.topology, filepath
                    )
                except Exception as e:
                    logger.warning(f"KO-Anreicherung fehlgeschlagen: {e}")

                # Bedienelemente aus neu verlinkten Devices ableiten (FA-1404)
                try:
                    KnxprojImportService._create_bedienelemente_from_topology(
                        self._project.topology, self._project.areal
                    )
                except Exception as e:
                    logger.warning(f"Bedienelemente-Ableitung nach GA-Import fehlgeschlagen: {e}")

                # Funktionszuordnungen direkt aus KO-GA-Verknüpfungen übernehmen (FA-521c)
                try:
                    importer.backfill_function_assignments(
                        self._project.topology, self._project.areal, ga_structure
                    )
                except Exception as e:
                    logger.warning(f"Funktionszuordnungs-Backfill fehlgeschlagen: {e}")

            # Gewerk-Zuweisungen aus GA-Bezeichnungen ableiten (FA-519b)
            assigned = self._derive_gewerke_from_gas()

            # GA-Metadaten (Gewerk, Raum) aus Bezeichnung anreichern
            self._enrich_ga_metadata()

            # DALI-Gateways automatisch konfigurieren (GA-Verknüpfung + Gruppen)
            self._auto_configure_dali()

            # Re-Import-Abgleich (siehe _import_knxproj): alte IDs + KNiX-
            # Zusatzdaten anhand physischer Adresse/Raumnummer übernehmen.
            reconcile_diff = reconcile_reimport(old_snapshot, self._project)
            is_reimport = reconcile_diff.devices_matched > 0 or reconcile_diff.rooms_matched > 0
            # GAs, die durch den Abgleich wieder zu einer bestehenden Gewerk-Zuweisung
            # gehören, mit deren assignment_id verknüpfen (verhindert Duplikat-Blöcke
            # bei der nächsten Neugenerierung, FA-521e).
            self._relink_ga_assignment_ids()
            self._project.add_changelog_entry(
                "Re-Import" if is_reimport else "Import",
                f"{os.path.basename(filepath)}: {reconcile_diff.summary_line()}",
            )

            return {
                "ga_structure": ga_structure,
                "assigned": assigned,
                "warn_empty_areal": warn_empty_areal,
                "reconcile_diff": reconcile_diff,
                "is_reimport": is_reimport,
            }

        def on_success(result: dict):
            ga_structure = result["ga_structure"]
            assigned = result["assigned"]
            reconcile_diff = result["reconcile_diff"]
            is_reimport = result["is_reimport"]

            if result["warn_empty_areal"] is not None:
                self._warn_if_building_structure_empty(result["warn_empty_areal"])
            if is_reimport and (reconcile_diff.has_removed or reconcile_diff.has_ga_conflicts):
                QMessageBox.warning(
                    self, "Re-Import: Abgleich-Hinweise",
                    "Beim Abgleich mit dem bisherigen Projektstand wurden folgende "
                    "Geräte/Räume nicht mehr gefunden. Falls sie in Excel nur "
                    "umbenannt statt gelöscht wurden, sind ihre KNiX-Planungsdaten "
                    "(Gewerk-Zuweisungen, Bedienelemente, Materialliste, ...) jetzt "
                    "verwaist:\n\n" + reconcile_diff.details_text(),
                )
            self._warn_if_channel_conflicts()

            self._update_views()
            ga_count = len(ga_structure.all_addresses())
            hg_count = len(ga_structure.main_groups)
            gewerk_hint = f", {assigned} Gewerk-Zuweisungen" if assigned else ""
            self._status_bar.set_status(
                f"GA-Report importiert: {hg_count} Hauptgruppen, "
                f"{ga_count} Gruppenadressen{gewerk_hint} | {reconcile_diff.summary_line()}."
            )
            self._sidebar.select("addresses")
            self._navigate("addresses")

        run_import(
            self, "Gruppenadressen werden importiert…", do_import, on_success,
            self._import_worker_ref,
        )

    def _import_building_report_xlsx(self, filepath: str, importer):
        """Importiert einen ETS6 'Gebäude'-Report (XLSX) (FA-511b).

        Liefert die tatsächliche ETS6-Stockwerk/Raum-Zuordnung -- zuverlässiger
        als die aus GA-Namen abgeleitete Heuristik in `derive_building_structure`,
        da unabhängig von der GA-Benennungskonvention des Installateurs.
        Reihenfolge relativ zu Topologie-/GA-Report-Import spielt keine Rolle:
        jeder der drei Import-Handler leitet die Gebäudestruktur bei jedem
        Aufruf neu ab und bevorzugt dabei stets den Gebäude-Report, falls
        vorhanden (siehe _collect_device_locations).

        Siehe _import_xlsx(): do_import() läuft im Hintergrund-Thread und
        darf keine Qt-Widgets berühren, on_success() danach im UI-Thread.
        """
        def do_import():
            old_snapshot = KnxProject(name="")
            old_snapshot.topology = self._project.topology
            old_snapshot.areal = self._project.areal

            self._building_report_path = filepath
            areal = importer.derive_building_structure_from_building_report(filepath)
            if self._project.areal and self._project.areal.name:
                areal.name = self._project.areal.name
                if areal.buildings and self._project.areal.buildings:
                    areal.buildings[0].name = self._project.areal.buildings[0].name
            self._project.areal = areal
            self._building_service.assign_main_groups(self._project.areal)
            warn_empty_areal = areal

            # Falls Topologie bereits geladen: Verteiler-Räume, Raum-Linien-
            # Verknüpfung und abgeleitete Bedienelemente/Funktionen nachziehen
            # (analog zu _import_ga_report_xlsx).
            if self._project.topology.areas:
                device_locations = self._collect_device_locations(importer)

                device_notes = None
                if self._topology_xlsx_path:
                    try:
                        device_notes = importer.extract_device_notes(self._topology_xlsx_path)
                    except Exception as e:
                        logger.warning(f"Installations-Hinweise-Extraktion fehlgeschlagen: {e}")

                self._apply_button_configuration(importer)
                self._apply_scene_values(importer)
                self._apply_scene_triggers(importer)

                try:
                    importer.create_verteiler_rooms(self._project.topology, self._project.areal)
                except Exception as e:
                    logger.warning(f"Verteiler-Raum-Ableitung fehlgeschlagen: {e}")

                try:
                    importer.apply_verteiler_room_overrides(
                        self._project.topology, self._project.areal,
                        self._project.verteiler_room_overrides,
                    )
                except Exception as e:
                    logger.warning(f"Verteiler-Raum-Zuordnung fehlgeschlagen: {e}")

                try:
                    importer.link_rooms_to_lines(
                        self._project.topology, self._project.group_addresses,
                        self._project.areal,
                        device_locations=device_locations, device_notes=device_notes,
                    )
                except Exception as e:
                    logger.warning(f"Raum-Linien-Verknüpfung fehlgeschlagen: {e}")

                try:
                    KnxprojImportService._create_bedienelemente_from_topology(
                        self._project.topology, self._project.areal
                    )
                except Exception as e:
                    logger.warning(f"Bedienelemente-Ableitung fehlgeschlagen: {e}")

                if self._ga_report_path:
                    try:
                        importer.enrich_device_ko_connections(
                            self._project.topology, self._ga_report_path
                        )
                    except Exception as e:
                        logger.warning(f"KO-Anreicherung fehlgeschlagen: {e}")

                try:
                    importer.backfill_function_assignments(
                        self._project.topology, self._project.areal, self._project.group_addresses
                    )
                except Exception as e:
                    logger.warning(f"Funktionszuordnungs-Backfill fehlgeschlagen: {e}")

            assigned = self._derive_gewerke_from_gas()
            self._enrich_ga_metadata()
            self._auto_configure_dali()

            reconcile_diff = reconcile_reimport(old_snapshot, self._project)
            is_reimport = reconcile_diff.devices_matched > 0 or reconcile_diff.rooms_matched > 0
            self._relink_ga_assignment_ids()
            self._project.add_changelog_entry(
                "Re-Import" if is_reimport else "Import",
                f"{os.path.basename(filepath)}: {reconcile_diff.summary_line()}",
            )

            return {
                "areal": areal,
                "assigned": assigned,
                "warn_empty_areal": warn_empty_areal,
                "reconcile_diff": reconcile_diff,
                "is_reimport": is_reimport,
            }

        def on_success(result: dict):
            areal = result["areal"]
            assigned = result["assigned"]
            reconcile_diff = result["reconcile_diff"]
            is_reimport = result["is_reimport"]

            if result["warn_empty_areal"] is not None:
                self._warn_if_building_structure_empty(result["warn_empty_areal"])
            if is_reimport and (reconcile_diff.has_removed or reconcile_diff.has_ga_conflicts):
                QMessageBox.warning(
                    self, "Re-Import: Abgleich-Hinweise",
                    "Beim Abgleich mit dem bisherigen Projektstand wurden folgende "
                    "Geräte/Räume nicht mehr gefunden. Falls sie in Excel nur "
                    "umbenannt statt gelöscht wurden, sind ihre KNiX-Planungsdaten "
                    "(Gewerk-Zuweisungen, Bedienelemente, Materialliste, ...) jetzt "
                    "verwaist:\n\n" + reconcile_diff.details_text(),
                )
            self._warn_if_channel_conflicts()

            self._update_views()
            total_floors = len(areal.all_floors)
            total_rooms = len(areal.all_rooms)
            gewerk_hint = f", {assigned} Gewerk-Zuweisungen" if assigned else ""
            self._status_bar.set_status(
                f"Gebäude-Report importiert: {total_floors} Stockwerke, "
                f"{total_rooms} Räume{gewerk_hint} | {reconcile_diff.summary_line()}."
            )
            self._sidebar.select("building")
            self._navigate("building")

        run_import(
            self, "Gebäudestruktur wird importiert…", do_import, on_success,
            self._import_worker_ref,
        )

    def _relink_ga_assignment_ids(self) -> int:
        """
        Verknüpft importierte GAs nachträglich mit ihrer GewerkAssignment
        (FA-521e). Muss NACH reconcile_reimport() aufgerufen werden, wenn
        room.gewerk_assignments seinen finalen (ggf. reimportierten) Stand hat --
        sonst fehlt der stabilen Neugenerierung (AddressGenerator, existing=)
        die Grundlage, importierte GAs statt Duplikat-Blöcken wiederzuverwenden.
        """
        if not self._project:
            return 0
        try:
            svc = GewerkService(self._project.gewerk_catalog)
            relinked = svc.relink_assignment_ids(
                self._project.group_addresses, self._project.areal
            )
            if relinked:
                logger.info(f"GA-Reimport: {relinked} GAs mit Gewerk-Zuweisung verknüpft.")
            return relinked
        except Exception as e:
            logger.warning(f"assignment_id-Verknüpfung nach Reimport fehlgeschlagen: {e}")
            return 0

    def _derive_gewerke_from_gas(self) -> int:
        """
        Leitet Gewerk-Zuweisungen aus GA-Bezeichnungen ab (FA-519b).

        Wird nach jedem GA-Import aufgerufen. Befüllt nur Räume ohne bestehende
        Zuweisungen (overwrite=False). Gibt die Anzahl neuer Zuweisungen zurück.

        Sammelt zusätzlich Kanal-/Gewerk-Mehrdeutigkeiten (Zentraladressen,
        kombinierte Adressierung, mehrere Gewerke auf einem Kanal) in
        self._last_channel_conflicts für eine Warnmeldung des Aufrufers --
        siehe GewerkService.derive_gewerk_assignments/.detect_channel_gewerk_conflicts.
        """
        self._last_channel_conflicts: list[str] = []
        if not self._project:
            return 0
        ga_structure = self._project.group_addresses
        if not ga_structure.all_addresses():
            return 0
        if not self._project.areal.all_rooms:
            return 0
        try:
            svc = GewerkService(self._project.gewerk_catalog)
            assigned = svc.derive_gewerk_assignments(
                ga_structure, self._project.areal, overwrite=False
            )
            if self._project.topology.areas:
                self._last_channel_conflicts = svc.detect_channel_gewerk_conflicts(
                    self._project.topology, ga_structure
                )
            return assigned
        except Exception as e:
            logger.warning(f"Gewerk-Ableitung aus GAs fehlgeschlagen: {e}")
            return 0

    def _warn_if_channel_conflicts(self):
        """Zeigt eine Warnung, wenn detect_channel_gewerk_conflicts Kanäle mit
        mehreren Gewerken auf derselben GA-Verbindung gefunden hat (FA-521d).

        Solche Kanäle werden bewusst NICHT automatisch einem Gewerk zugeordnet --
        die Zuordnung muss hier manuell (Schritt 5 Gewerke) geprüft werden.
        """
        conflicts = getattr(self, "_last_channel_conflicts", [])
        if not conflicts:
            return
        shown = conflicts[:30]
        more = f"\n… und {len(conflicts) - 30} weitere" if len(conflicts) > 30 else ""
        QMessageBox.warning(
            self, "Mehrere Gewerke auf einem Kanal",
            f"{len(conflicts)} Kommunikationsobjekte haben Gruppenadressen "
            "unterschiedlicher Gewerke verbunden. Das kann nicht automatisch "
            "korrekt einem einzelnen Gewerk zugeordnet werden -- bitte in "
            "Schritt 5 (Gewerke) manuell prüfen:\n\n"
            + "\n".join(shown) + more,
        )

    def _enrich_ga_metadata(self) -> int:
        """
        Befüllt leere gewerk_code und room_number in importierten GAs aus der Bezeichnung.

        Parst das Muster 'GEWERK.STOCKWERK.RAUM.ELEM_FUNKTION  ( Raumname )':
          - gewerk_code: Erster Teil vor dem Punkt (z.B. "L", "J", "LDA")
          - room_number: Raumname aus den Klammern (z.B. "Technikraum")
            Fallback: STOCKWERK.RAUM (z.B. "UG.01")

        Überschreibt nur leere Felder (keine manuellen Einträge verloren).
        Gibt Anzahl angereichter GAs zurück.
        """
        import re
        if not self._project:
            return 0
        # Gewerk-Code: erstes Segment vor "." oder "_", unabhaengig von der
        # Anzahl folgender Segmente -- deckt sowohl die 4-Segment-Konvention
        # ("LDA.OG.00.01_ea") als auch die 3-Segment-EFH-Konvention
        # ("L.002.1_ea") ab. Analog zu xlsx_import_service._parse_xlsx_designation,
        # damit .knxproj- und XLSX-Import gleich robust sind.
        _GEWERK_PREFIX_RE = re.compile(r"^([A-Z]{1,4})[._]", re.IGNORECASE)
        _FLOOR_ROOM_RE = re.compile(
            r"^([A-Z]{1,4})\.([A-Z0-9]{2,5})\.(\d{1,2})\.",
            re.IGNORECASE,
        )
        _ROOM_NAME_RE = re.compile(r"\(\s*(.+?)\s*\)")
        enriched = 0
        for ga in self._project.group_addresses.all_addresses():
            desig = ga.designation or ""
            if not desig:
                continue
            changed = False
            if not ga.gewerk_code:
                m = _GEWERK_PREFIX_RE.match(desig)
                if m:
                    ga.gewerk_code = m.group(1).upper()
                    changed = True
            if not ga.room_number:
                # Bevorzuge Raumname aus Klammern
                mn = _ROOM_NAME_RE.search(desig)
                if mn:
                    ga.room_number = mn.group(1).strip()
                    changed = True
                else:
                    mf = _FLOOR_ROOM_RE.match(desig)
                    if mf:
                        ga.room_number = f"{mf.group(2)}.{mf.group(3)}"
                        changed = True
            if changed:
                enriched += 1
        if enriched:
            logger.debug(f"GA-Metadata angereichert: {enriched} GAs.")
        return enriched

    def _detect_scenes(self) -> int:
        """Erkennt Szenen in importierten GAs und haengt sie an project.scenes (FA-1808)."""
        if not self._project:
            return 0
        try:
            from ..services.scene_detection_service import detect_scenes
            added = detect_scenes(self._project)
            if added:
                self._project.scenes.extend(added)
                logger.info(f"Szenen-Erkennung: {len(added)} Szenen aus Import übernommen.")
            return len(added)
        except Exception as e:
            logger.warning(f"Szenen-Erkennung fehlgeschlagen: {e}")
            return 0

    def _auto_configure_dali(self) -> int:
        """
        Konfiguriert DALI-Gateways automatisch nach einem Import.

        Legt DaliGateway-Configs an, verknüpft Broadcast-GAs und leitet
        Gruppen aus LDA-GAs oder KO-Namen ab. Wird nach XLSX-, GA-Report-
        und KNXPROJ-Importen aufgerufen.
        """
        if not self._project:
            return 0
        if not self._project.topology.areas:
            return 0
        try:
            svc = DaliService()
            linked = svc.auto_configure_from_import(self._project)
            if linked:
                logger.info(f"DALI-Auto-Konfiguration: {linked} GAs verknüpft.")
            return linked
        except Exception as e:
            logger.warning(f"DALI-Auto-Konfiguration fehlgeschlagen: {e}")
            return 0

    def _import_knxprod_catalog(self):
        """Importiert eine oder mehrere KNXPROD-Dateien und fügt Produkte dem Katalog hinzu (FA-2304)."""
        import os
        from PySide6.QtWidgets import QFileDialog
        from ..services.knxprod_catalog_service import KnxprodCatalogService
        from ..services.product_search_service import ProductSearchService

        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "KNXPROD-Dateien importieren (Mehrfachauswahl möglich)", "",
            "KNX Produktdatenbankdateien (*.knxprod);;Alle Dateien (*.*)",
        )
        if not filepaths:
            return

        svc = KnxprodCatalogService()
        all_products = []
        errors: list[tuple[str, str]] = []
        empty: list[str] = []
        for filepath in filepaths:
            name = os.path.basename(filepath)
            try:
                products = svc.import_file(filepath)
            except ValueError as e:
                errors.append((name, str(e)))
                continue
            if not products:
                empty.append(name)
                continue
            all_products.extend(products)

        total_products = len(all_products)
        ok_count = len(filepaths) - len(errors) - len(empty)

        # In den Katalog aufnehmen -- ein Schreibvorgang, persistiert dauerhaft
        # (%APPDATA%/KNiX Arranger/), projekt- und session-übergreifend verfügbar
        if all_products:
            ProductSearchService().add_products([p.to_catalog_dict() for p in all_products])

        if total_products == 0 and (errors or empty):
            details = "\n".join(f"• {n}: {e}" for n, e in errors)
            if empty:
                details += ("\n" if details else "") + "\n".join(
                    f"• {n}: keine Produktdaten gefunden" for n in empty
                )
            QMessageBox.critical(
                self, "KNXPROD-Import fehlgeschlagen",
                f"Keine der {len(filepaths)} ausgewählten Datei(en) konnte importiert werden:\n\n"
                f"{details}\n\n"
                "Stellen Sie sicher, dass es sich um gültige .knxprod-Dateien handelt\n"
                "(Export aus ETS6: Katalog → Hersteller → Exportieren).",
            )
            return

        summary = (
            f"{total_products} Produkte aus {ok_count} von {len(filepaths)} Datei(en) eingelesen.\n"
            f"Die Produkte stehen ab sofort in der Produktauswahl zur Verfügung."
        )
        if errors or empty:
            problems = [f"• {n}: {e}" for n, e in errors] + [f"• {n}: keine Produktdaten gefunden" for n in empty]
            summary += "\n\nÜbersprungen:\n" + "\n".join(problems)
        QMessageBox.information(self, "Import abgeschlossen", summary)
        self._status_bar.set_status(
            f"KNXPROD-Import: {total_products} Produkte aus {ok_count} von {len(filepaths)} Datei(en)."
        )

    def _sync_knxprod_files_to_catalog(self, filepaths: list[str]) -> int:
        """Liest eine Liste von .knxprod-Dateien ein und übernimmt alle
        gefundenen Produkte in einem Rutsch in den persistenten Produkt-
        katalog (%APPDATA%) -- Kern von _import_knxprod_catalog(), hier
        ohne Dialoge, da es als stiller Folgeschritt nach dem KNXPROJ-Import
        laeuft (fehlerhafte Einzeldateien werden geloggt, nicht gemeldet).
        Gibt die Anzahl uebernommener Produkte zurueck."""
        from ..services.knxprod_catalog_service import KnxprodCatalogService
        from ..services.product_search_service import ProductSearchService

        svc = KnxprodCatalogService()
        all_products = []
        for path in filepaths:
            try:
                all_products.extend(svc.import_file(path))
            except ValueError as e:
                logger.warning(f"KNXPROD-Auto-Katalogisierung: {path} übersprungen ({e}).")
        if all_products:
            ProductSearchService().add_products([p.to_catalog_dict() for p in all_products])
        return len(all_products)

    def _import_knxproj(self, filepath: str):
        """Importiert ein natives ETS6-Projekt (.knxproj) (FA-521 bis FA-526, FA-525c).

        Die Passwort-Abfrage ist interaktiv (zeigt ggf. mehrfach einen
        Dialog) und läuft deshalb bewusst NICHT im Hintergrund-Thread wie
        bei XLSX/CSV (siehe run_import in _import_xlsx) -- ein modaler
        Fortschrittsdialog macht aber sichtbar, dass das eigentliche
        Parsen der (teils grossen) .knxproj-Datei noch läuft, statt dass
        die Oberfläche kommentarlos einfriert.
        """
        from ..services.project_service import ProjectService

        importer = KnxprojImportService()
        project_service = ProjectService()
        password = None
        project_id = None
        dialog = None

        progress = QProgressDialog("KNXPROJ wird importiert…", None, 0, 0, self)
        progress.setWindowTitle("Import läuft…")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            while True:
                try:
                    QApplication.processEvents()
                    project = importer.import_knxproj(filepath, password=password)
                    break
                except KnxprojPasswordRequired as exc:
                    progress.hide()
                    project_id = exc.project_id
                    stored = project_service.get_knxproj_password(project_id)
                    if stored and password != stored:
                        password = stored
                        progress.show()
                        continue
                    dialog = KnxprojPasswordDialog(project_id, os.path.basename(filepath), self)
                    if not dialog.exec():
                        self._status_bar.set_status(
                            "KNXPROJ-Import abgebrochen: Passwort erforderlich."
                        )
                        return
                    password = dialog.password
                    progress.show()
                except KnxprojPasswordWrong:
                    progress.hide()
                    if dialog is None:
                        dialog = KnxprojPasswordDialog(project_id, os.path.basename(filepath), self)
                    dialog.show_wrong_password()
                    if not dialog.exec():
                        self._status_bar.set_status(
                            "KNXPROJ-Import abgebrochen: falsches Passwort."
                        )
                        return
                    password = dialog.password
                    progress.show()
        finally:
            progress.close()

        if dialog is not None and project_id and dialog.save_password:
            project_service.save_knxproj_password(project_id, password)

        # Re-Import-Abgleich: alte IDs + KNiX-Zusatzdaten (Materialliste,
        # KNX Secure, DALI, Gewerk-Zuweisungen, Bedienelemente, ...) anhand
        # physischer Adresse/Raumnummer in den frischen Import übernehmen,
        # bevor er das laufende Projekt ersetzt (verhindert verwaiste
        # Verknüpfungen bei Export → ETS-Anpassung → Re-Import-Zyklen).
        reconcile_diff = reconcile_reimport(self._project, project)
        is_reimport = reconcile_diff.devices_matched > 0 or reconcile_diff.rooms_matched > 0

        # Projektdaten ins laufende Projekt uebernehmen
        self._project.name = project.name or self._project.name
        self._project.modified = project.modified
        self._project.group_addresses = project.group_addresses
        self._project.topology = project.topology
        self._project.areal = project.areal

        # GAs, die durch den Abgleich wieder zu einer bestehenden Gewerk-Zuweisung
        # gehören, mit deren assignment_id verknüpfen (verhindert Duplikat-Blöcke
        # bei der nächsten Neugenerierung, FA-521e).
        self._relink_ga_assignment_ids()

        # Änderungsprotokoll: Re-Import-Zusammenfassung festhalten
        self._project.add_changelog_entry(
            "Re-Import" if is_reimport else "Import",
            f"{os.path.basename(filepath)}: {reconcile_diff.summary_line()}",
        )

        # GA-Metadaten (Gewerk, Raum) aus Bezeichnung anreichern
        self._enrich_ga_metadata()

        # Szenen aus importierten GAs erkennen (FA-1808) -- muss NACH der
        # Metadaten-Anreicherung laufen, da die Raumcluster-Erkennung auf
        # ga.room_number aufbaut.
        n_scenes_detected = self._detect_scenes()

        # DALI-Gateways automatisch konfigurieren (GA-Verknüpfung + Gruppen)
        self._auto_configure_dali()

        self._update_views()

        # Im KNXPROJ eingebettete Hersteller-Produktdaten als .knxprod in die
        # workspace-weite "Produkte KNX"-Bibliothek extrahieren und direkt in
        # den Produktkatalog übernehmen (FA-...) -- nur wenn ein Workspace
        # konfiguriert ist (kein Setup-Dialog erzwingen, rein lesender Check
        # wie _default_products_folder()).
        n_products_extracted = 0
        n_products_cataloged = 0
        workspace = self._load_app_setting("workspace_root_path", "")
        if workspace:
            products_folder = os.path.join(workspace, "Produkte KNX")
            if os.path.isdir(products_folder):
                written = importer.extract_product_libraries(filepath, products_folder)
                n_products_extracted = len(written)
                if written:
                    n_products_cataloged = self._sync_knxprod_files_to_catalog(written)

        ga_count = len(project.group_addresses.all_addresses())
        n_areas = len(project.topology.areas)
        n_lines = sum(len(a.lines) for a in project.topology.areas)
        n_dev = sum(len(l.devices) for a in project.topology.areas for l in a.lines)
        n_rooms = len(project.areal.all_rooms)
        scenes_suffix = f" | {n_scenes_detected} Szenen erkannt" if n_scenes_detected else ""
        products_suffix = (
            f" | {n_products_extracted} Produktbibliothek(en) ergänzt, "
            f"{n_products_cataloged} Produkte im Katalog aktualisiert"
            if n_products_extracted else ""
        )
        self._status_bar.set_status(
            f"KNXPROJ importiert: {ga_count} GAs | "
            f"{n_areas} Bereiche, {n_lines} Linien, {n_dev} Geräte | "
            f"{n_rooms} Räume | {reconcile_diff.summary_line()}"
            f"{scenes_suffix}{products_suffix}."
        )

        # Warnung wenn Geräte/Räume aus dem bisherigen Projekt nicht mehr
        # gefunden wurden -- deren KNiX-Planungsdaten (Gewerke, Bedienelemente,
        # Materialliste, ...) sind jetzt verwaist (Umbenennung/Löschung in ETS?).
        if is_reimport and reconcile_diff.has_removed:
            # Das Parsen der .knxproj-Datei lief hier synchron im UI-Thread
            # (nur per processEvents() am Leben gehalten, siehe oben) und
            # kann bei grossen Dateien laenger dauern -- ohne explizites
            # Aktivieren bleibt das Hauptfenster (und damit dieser modale
            # Dialog) im Hintergrund, falls der Nutzer zwischenzeitlich in
            # ein anderes Fenster gewechselt hat (Windows-Foreground-Lock,
            # siehe export_worker.run_export._on_finished fuer denselben
            # Fix beim Hintergrundthread-Pfad).
            self.raise_()
            self.activateWindow()
            QMessageBox.warning(
                self, "Re-Import: Geräte/Räume nicht mehr gefunden",
                "Beim Abgleich mit dem bisherigen Projektstand wurden folgende "
                "Geräte/Räume nicht mehr gefunden. Falls sie in ETS nur "
                "umbenannt statt gelöscht wurden, sind ihre KNiX-Planungsdaten "
                "(Gewerk-Zuweisungen, Bedienelemente, Materialliste, ...) jetzt "
                "verwaist:\n\n" + reconcile_diff.details_text(),
            )
        self._sidebar.select("addresses")
        self._navigate("addresses")

    def _export_csv(self):
        if not self._project:
            self._status_bar.set_status("Kein Projekt zum Exportieren.")
            return

        ga_count = len(self._project.group_addresses.all_addresses())
        dialog = ExportDialog(ga_count, self)
        if dialog.exec():
            try:
                exporter = CsvExportService()
                exporter.export_csv(
                    self._project.group_addresses,
                    dialog.filepath,
                    overwrite=dialog.overwrite,
                )
                self._status_bar.set_status(f"CSV exportiert: {dialog.filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Export-Fehler", str(e))

    def _export_knxproj(self):
        if not self._project:
            self._status_bar.set_status("Kein Projekt zum Exportieren.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "KNXPROJ exportieren",
            f"{self._project.name or 'projekt'}.knxproj",
            "ETS6-Projekt (*.knxproj)",
        )
        if not path:
            return
        try:
            from ..services.knxproj_export_service import KnxprojExportService
            summary = KnxprojExportService().export(self._project, path)
            self._status_bar.set_status(f"KNXPROJ exportiert: {path}")
            QMessageBox.information(
                self, "KNXPROJ-Export abgeschlossen",
                summary.as_text() + f"\n\nDatei: {path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export-Fehler", str(e))

    def _validate(self):
        if not self._project:
            self._status_bar.set_status("Kein Projekt zum Validieren.")
            return

        validator = ValidationEngine(self._project.gewerk_catalog)
        issues = validator.validate(self._project.group_addresses)
        self._validation_view.set_issues(issues)

        self._overview.update_from_project(self._project)
        self._sidebar.select("validation")
        self._navigate("validation")
        self._status_bar.set_status(f"Validierung: {len(issues)} Probleme gefunden.")

    def _start_wizard(self, start_step: int = 0):
        if not self._project:
            self._new_project()
            if not self._project:
                return

        import json
        from .wizard.wizard_controller import WizardController

        def _state() -> str:
            return json.dumps(self._project.to_dict(), sort_keys=True, default=repr)

        # Ein Undo-Punkt für die gesamte Wizard-Sitzung: der Wizard schreibt
        # direkt ins Projekt, "Rückgängig" stellt den Stand davor wieder her.
        before = _state()
        self._on_begin_change("Projektassistent")
        wizard = WizardController(self._project, self, start_step=start_step)
        completed = wizard.exec()
        if _state() != before:
            self._on_any_change("wizard")  # Undo-Punkt ablegen, Dirty-Flag setzen
        else:
            self._pending_undo_cmd = None
        # Immer alle Views aktualisieren: der Wizard schreibt Aenderungen
        # Schritt fuer Schritt direkt in das Projektobjekt, auch bei Abbruch.
        self._update_views()
        if completed:
            self._status_bar.set_status("Wizard abgeschlossen.")
            self._sidebar.select("overview")
            self._navigate("overview")

    def _open_wizard_at_addresses_step(self):
        """Deep-Link aus der Szenen-Ansicht (Veraltet-Banner) direkt zu
        Wizard-Schritt 10 "Gruppenadressen generieren"."""
        from .wizard.wizard_controller import STEP_INDEX_ADDRESSES
        self._start_wizard(start_step=STEP_INDEX_ADDRESSES)

    def _undo(self):
        if self._undo_manager.undo():
            self._update_views()
            self._status_bar.set_status(
                f"Rückgängig: {self._undo_manager.redo_description}"
            )
        self._update_undo_actions()

    def _redo(self):
        if self._undo_manager.redo():
            self._update_views()
            self._status_bar.set_status(
                f"Wiederholt: {self._undo_manager.undo_description}"
            )
        self._update_undo_actions()

    def _update_undo_actions(self):
        """Aktualisiert den Enabled-Status der Undo/Redo-Aktionen."""
        self._undo_action.setEnabled(self._undo_manager.can_undo())
        self._redo_action.setEnabled(self._undo_manager.can_redo())
        if self._undo_manager.can_undo():
            self._undo_action.setText(
                f"Rückgängig: {self._undo_manager.undo_description}"
            )
        else:
            self._undo_action.setText("Rückgängig")
        if self._undo_manager.can_redo():
            self._redo_action.setText(
                f"Wiederholen: {self._undo_manager.redo_description}"
            )
        else:
            self._redo_action.setText("Wiederholen")

    def _show_reports(self):
        if not self._project:
            self._status_bar.set_status("Kein Projekt für Berichte vorhanden.")
            return
        profile = self._app.project_service.load_company_profile() if self._app else None
        dialog = ReportsDialog(self._project, self, company_profile=profile)
        dialog.exec()

    def _show_settings(self):
        profile = self._app.project_service.load_company_profile()
        workspace = self._load_app_setting("workspace_root_path", "")
        dialog = SettingsDialog(profile=profile, parent=self, workspace_root_path=workspace)
        if dialog.exec():
            updated = dialog.get_profile()
            self._app.project_service.save_company_profile(updated)
            new_workspace = dialog.workspace_root_path
            if new_workspace != workspace:
                os.makedirs(new_workspace, exist_ok=True)
                self._save_app_setting("workspace_root_path", new_workspace)

    def _show_help(self):
        """Zeigt das Hilfesystem kontextsensitiv (FA-1101, FA-1102)."""
        # Aktuelle Ansicht ermitteln für kontextsensitive Hilfe
        current_widget = self._stack.currentWidget()
        context_key = "getting_started"
        for key, view in self._views.items():
            if view == current_widget:
                context_key = key
                break
        self._help_view.show_topic(context_key)
        self._sidebar.select("help")
        self._navigate("help")

    def show_help_topic(self, topic_key: str):
        """Zeigt ein bestimmtes Hilfethema direkt (FA-1101, aufrufbar von Wizard-Schritten)."""
        self._help_view.show_topic(topic_key)
        self._sidebar.select("help")
        self._navigate("help")

    def _show_onboarding_tour(self):
        """Zeigt die Onboarding-Tour (FA-1106)."""
        dlg = OnboardingTourDialog(self)
        dlg.exec()
        if dlg.suppress_on_next_start:
            self._save_app_setting("onboarding_shown", True)

    def _open_manual(self):
        """Oeffnet das Benutzerhandbuch als PDF (FA-1105)."""
        import os, sys
        from pathlib import Path
        pdf_path = Path(__file__).parent.parent / "data" / "KNiX_Arranger_Handbuch.pdf"
        if pdf_path.exists():
            if sys.platform == "win32":
                os.startfile(str(pdf_path))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(pdf_path)])
        else:
            QMessageBox.information(
                self, "Benutzerhandbuch",
                "Das Benutzerhandbuch steht noch nicht als PDF zur Verfügung.\n\n"
                "Nutzen Sie das integrierte Hilfesystem (F1) für Unterstützung.",
            )

    # ── Update-Mechanismus (NFA-111–115) ──────────────────────────────────────

    def _auto_check_updates(self):
        """Prueft im Hintergrund auf Updates (NFA-111, blockiert UI nicht)."""
        import threading
        from ..services.update_service import UpdateService

        # Setting prüfen (NFA-115: deaktivierbar)
        if not self._load_app_setting("auto_update_check", True):
            return

        def _check():
            svc = UpdateService()
            info = svc.check_for_updates(__version__, timeout=5.0)
            if info.available:
                ignored = self._load_app_setting("ignored_update_version", "")
                if info.latest_version != ignored:
                    self._update_available.emit(info)

        t = threading.Thread(target=_check, daemon=True)
        t.start()

    def _check_updates_manual(self):
        """Manuelle Update-Pruefung mit Rueckmeldung (NFA-112, NFA-115)."""
        from ..services.update_service import UpdateService
        # Spinner-Cursor kurz zeigen
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import Qt as QtCore_Qt
        self.setCursor(QCursor(QtCore_Qt.WaitCursor))
        try:
            svc = UpdateService()
            info = svc.check_for_updates(__version__, timeout=8.0)
        finally:
            self.unsetCursor()

        if info.error:
            QMessageBox.warning(
                self, "Update-Prüfung fehlgeschlagen",
                f"Es konnte keine Verbindung zum Update-Server hergestellt werden.\n\n"
                f"Details: {info.error}\n\n"
                f"Bitte prüfen Sie Ihre Internetverbindung.",
            )
        elif info.available:
            dlg = UpdateDialog(info, self)
            dlg.exec()
            self._apply_update_dialog_result(dlg)
        else:
            QMessageBox.information(
                self, "Kein Update verfügbar",
                f"Sie verwenden die aktuellste Version ({__version__}).",
            )

    def _on_update_available(self, update_info):
        """Callback wenn Auto-Check ein Update gefunden hat (NFA-111).

        Läuft mehrere Sekunden nach dem Start über einen Hintergrund-Thread,
        völlig unabhängig von einer Nutzeraktion -- ohne explizites Aktivieren
        bleibt das Fenster (und damit der modale Dialog) unsichtbar im
        Hintergrund, falls der Nutzer inzwischen in ein anderes Programm
        gewechselt hat (Windows-Foreground-Lock). Wirkt dann wie ein
        eingefrorenes Programm, da der modale Dialog die Bedienung blockiert.
        """
        self.raise_()
        self.activateWindow()
        dlg = UpdateDialog(update_info, self)
        dlg.exec()
        self._apply_update_dialog_result(dlg)

    def _apply_update_dialog_result(self, dlg: UpdateDialog):
        """Wertet die Benutzerentscheidung im UpdateDialog aus."""
        self._save_app_setting("auto_update_check", dlg.auto_check_enabled)
        if dlg.ignored_version:
            self._save_app_setting("ignored_update_version", dlg.ignored_version)

    # ── App-Settings (einfaches JSON, plattformunabhaengig) ───────────────────

    def _app_settings_path(self):
        from pathlib import Path
        import os
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path.home() / ".config"
        return base / "KNiXArranger" / "app_settings.json"

    def _load_app_settings(self) -> dict:
        path = self._app_settings_path()
        if path.exists():
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_app_settings(self, settings: dict):
        path = self._app_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

    def _load_app_setting(self, key: str, default=None):
        return self._load_app_settings().get(key, default)

    def _save_app_setting(self, key: str, value):
        s = self._load_app_settings()
        s[key] = value
        self._save_app_settings(s)

    def _ensure_workspace(self) -> str:
        """Liefert den konfigurierten Workspace-Pfad; fragt bei Erststart danach.

        Neue Projekte werden verbindlich in diesem Ordner angelegt (FA-1601).
        """
        path = self._load_app_setting("workspace_root_path", "")
        if path and os.path.isdir(path):
            # Auch bei bereits konfiguriertem Workspace sicherstellen (z.B. für
            # Bestandsnutzer, die den Ordner vor dessen Einführung eingerichtet haben).
            os.makedirs(os.path.join(path, "Produkte KNX"), exist_ok=True)
            return path
        while True:
            dialog = WorkspaceSetupDialog(self)
            if dialog.exec():
                path = dialog.workspace_path
                self._save_app_setting("workspace_root_path", path)
                return path

    def _show_startup_dialogs(self):
        self._show_whats_new_after_update()
        self._show_welcome()

    def _show_whats_new_after_update(self):
        """Zeigt nach einem Update einmalig die Änderungen seit der zuletzt
        gesehenen Version – auch übersprungene Versionen."""
        from ..services.release_notes_service import notes_since
        from .dialogs.whats_new_dialog import WhatsNewDialog

        settings = self._load_app_settings()
        last_seen = settings.get("last_seen_version", "")
        if last_seen == __version__:
            return
        self._save_app_setting("last_seen_version", __version__)
        try:
            if last_seen:
                notes = notes_since(last_seen, __version__)
            elif settings:
                # Bestandsnutzer, dessen Version diese Funktion noch nicht kannte
                # (App-Einstellungen existieren bereits): aktuelle Version zeigen.
                notes = notes_since("0", __version__)[:1]
            else:
                return  # Neuinstallation: keine Änderungsliste
        except Exception:
            logger.exception("Release-Notes konnten nicht geladen werden")
            return
        if notes:
            WhatsNewDialog(
                notes, f"KNiX Arranger wurde auf Version {__version__} aktualisiert",
                self,
            ).exec()

    def _show_whats_new(self):
        """Hilfe → Was ist neu: alle Versionen (neueste zuerst)."""
        from ..services.release_notes_service import load_release_notes
        from .dialogs.whats_new_dialog import WhatsNewDialog
        try:
            notes = load_release_notes()
        except Exception:
            logger.exception("Release-Notes konnten nicht geladen werden")
            QMessageBox.warning(self, "Was ist neu", "Die Änderungsliste konnte nicht geladen werden.")
            return
        WhatsNewDialog(notes, f"Was ist neu – Version {__version__}", self).exec()

    def _show_welcome(self):
        """Zeigt den Willkommensbildschirm beim Start (kein Projekt geladen)."""
        if self._project:
            return
        self._ensure_workspace()
        from ..services.project_service import ProjectService
        recent = ProjectService().get_recent_projects()
        dialog = WelcomeDialog(self, recent_projects=recent)
        if dialog.exec():
            if dialog.action == ACTION_NEW:
                self._new_project()
            elif dialog.action == ACTION_OPEN:
                if dialog.selected_path:
                    self.open_file(dialog.selected_path)
                else:
                    self._open_project()

        # Onboarding-Tour beim Erststart (FA-1106)
        if not self._load_app_setting("onboarding_shown", False):
            QTimer.singleShot(200, self._show_onboarding_tour_first_time)

    def _show_onboarding_tour_first_time(self):
        """Zeigt die Onboarding-Tour beim allerersten Start."""
        dlg = OnboardingTourDialog(self)
        dlg.exec()
        # Immer als "gesehen" markieren, damit sie nicht wieder automatisch erscheint
        self._save_app_setting("onboarding_shown", True)

    def _save_and_close(self):
        """Speichert das aktuelle Projekt und schliesst die Anwendung."""
        if self._project:
            self._save_project()
        self.close()

    def _show_project_properties(self):
        """Öffnet den Projekteigenschaften-Dialog."""
        if not self._project:
            self._status_bar.set_status("Kein Projekt geöffnet.")
            return
        old_name = self._project.name
        dialog = ProjectPropertiesDialog(self._project, self)
        if dialog.exec():
            self._update_views()
            if self._project.name != old_name:
                self._update_window_title()
            self._status_bar.set_status("Projekteigenschaften gespeichert.")

    def _show_license(self):
        dialog = LicenseDialog(self)
        dialog.exec()

    def _show_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def _uninstall_app(self):
        uninstaller = os.path.join(os.path.dirname(sys.executable), "unins000.exe")
        if not os.path.isfile(uninstaller):
            QMessageBox.information(
                self, "Deinstallieren",
                "Diese Installation kann nur über den Windows-Installer deinstalliert werden.\n\n"
                "Gehen Sie zu: Einstellungen → Apps → KNiX Arranger → Deinstallieren"
            )
            return
        reply = QMessageBox.question(
            self, "Deinstallieren",
            f"Möchten Sie {APP_NAME} wirklich deinstallieren?\n\n"
            "Das Programm wird geschlossen und der Deinstallations-Assistent gestartet.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            subprocess.Popen([uninstaller])
            self.close()

    def closeEvent(self, event):
        """Fragt vor dem Schliessen nach Speichern."""
        if self._project:
            reply = QMessageBox.question(
                self, "Beenden",
                "Möchten Sie das Projekt vor dem Beenden speichern?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Save:
                self._save_project()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
