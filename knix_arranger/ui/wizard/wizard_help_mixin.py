"""
Mixin fuer kontextsensitive Hilfe-Buttons in Wizard-Schritten (FA-1101).

Verwendung in einem Wizard-Schritt:
    class Step01Building(QWidget, WizardHelpMixin):
        _help_topic_key = "step01"

        def __init__(self, project, parent=None):
            super().__init__(parent)
            ...
            # Am Ende des Headers:
            help_btn = self._create_help_button()
            header_layout.addWidget(help_btn)
"""
from __future__ import annotations
from PySide6.QtWidgets import QPushButton, QWidget
from PySide6.QtCore import Qt


class WizardHelpMixin:
    """
    Fuegt einem Wizard-Schritt einen Kontext-Hilfe-Button (?) hinzu (FA-1101).

    Der Button navigiert in der Hauptansicht zum passenden Hilfethema.
    Subklassen setzen `_help_topic_key` auf den entsprechenden Key in help_contents.json.
    """
    _help_topic_key: str = "wizard"

    def _create_help_button(self) -> QPushButton:
        """Erstellt den ?-Button. Muss im Layout der Subklasse platziert werden."""
        btn = QPushButton("?")
        btn.setFixedSize(28, 28)
        btn.setToolTip(f"Hilfe zu diesem Schritt anzeigen (F1)")
        btn.setObjectName("secondary")
        btn.setStyleSheet(
            "QPushButton { border-radius: 14px; font-weight: bold; font-size: 14px; }"
        )
        btn.clicked.connect(self._show_step_help)
        return btn

    def _show_step_help(self):
        """Navigiert zum passenden Hilfethema im Hauptfenster."""
        # Elternfenster traversieren bis zum MainWindow
        widget: QWidget | None = self if isinstance(self, QWidget) else None
        while widget is not None:
            if hasattr(widget, "show_help_topic"):
                widget.show_help_topic(self._help_topic_key)
                return
            widget = widget.parent()
        # Fallback: Eltern-Dialog (WizardController) fragen
        parent = getattr(self, "parent", lambda: None)()
        while parent is not None:
            if hasattr(parent, "show_help_topic"):
                parent.show_help_topic(self._help_topic_key)
                return
            parent = parent.parent() if hasattr(parent, "parent") else None
