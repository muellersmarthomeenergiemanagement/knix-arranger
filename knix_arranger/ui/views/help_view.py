"""
Hilfesystem (FA-1101 bis FA-1106)
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextBrowser, QPushButton, QLineEdit,
)
from PySide6.QtCore import Qt


def _plain_to_html(text: str) -> str:
    """Konvertiert einfachen Text (mit Markdown-ähnlichen Konventionen) in HTML."""
    # Bereits HTML? Direkt zurückgeben
    if text.strip().startswith("<"):
        return text
    lines = text.split("\n")
    html_lines = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item = stripped[2:]
            # **fett** → <b>
            item = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", item)
            html_lines.append(f"<li>{item}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if stripped == "":
                html_lines.append("<br>")
            else:
                line_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", stripped)
                html_lines.append(f"<p>{line_html}</p>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


class HelpView(QWidget):
    """Kontextsensitives Hilfesystem mit Themen-Navigation (FA-1101–FA-1106)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topics: dict[str, dict] = {}
        self._all_topic_keys: list[str] = []
        self._topic_keys: list[str] = []   # aktuell angezeigte (nach Filter)
        self._load_help_contents()

        layout = QVBoxLayout(self)

        title = QLabel("Hilfe")
        title.setObjectName("title")
        layout.addWidget(title)

        content = QHBoxLayout()

        # Themen-Liste mit Suche
        left = QVBoxLayout()

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Suche:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Thema suchen…")
        self._search_edit.textChanged.connect(self._apply_search)
        search_row.addWidget(self._search_edit)
        left.addLayout(search_row)

        left.addWidget(QLabel("Themen:"))
        self._topic_list = QListWidget()
        self._topic_list.currentRowChanged.connect(self._on_topic_changed)
        left.addWidget(self._topic_list)

        content.addLayout(left, 1)

        # Hilfe-Inhalt
        right = QVBoxLayout()

        self._help_title = QLabel("")
        self._help_title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 5px;")
        right.addWidget(self._help_title)

        self._help_content = QTextBrowser()
        self._help_content.setReadOnly(True)
        self._help_content.setOpenExternalLinks(True)
        right.addWidget(self._help_content)

        content.addLayout(right, 2)

        layout.addLayout(content)

        self._populate_list(list(self._topics.keys()))

    def _load_help_contents(self):
        config_path = Path(__file__).parent.parent.parent / "config" / "help_contents.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._topics = data.get("help_topics", {})

    def _populate_list(self, keys: list[str]):
        """Füllt die Themenliste mit den angegebenen Keys."""
        self._topic_list.blockSignals(True)
        self._topic_list.clear()
        self._topic_keys = keys
        for key in keys:
            topic = self._topics.get(key, {})
            item = QListWidgetItem(topic.get("title", key))
            item.setData(Qt.UserRole, key)
            self._topic_list.addItem(item)
        self._topic_list.blockSignals(False)
        if keys:
            self._topic_list.setCurrentRow(0)

    def _apply_search(self, text: str):
        """Filtert die Themenliste nach dem Suchtext."""
        q = text.strip().lower()
        if not q:
            self._populate_list(list(self._topics.keys()))
            return
        filtered = [
            k for k, t in self._topics.items()
            if q in t.get("title", "").lower()
            or q in t.get("content", "").lower()
            or q in t.get("content_html", "").lower()
        ]
        self._populate_list(filtered)

    def _on_topic_changed(self, row: int):
        if row < 0 or row >= len(self._topic_keys):
            return
        key = self._topic_keys[row]
        topic = self._topics.get(key, {})
        self._help_title.setText(topic.get("title", ""))
        # HTML bevorzugen; sonst Plaintext konvertieren
        html = topic.get("content_html") or _plain_to_html(topic.get("content", ""))
        self._help_content.setHtml(html)

    def show_topic(self, key: str):
        """Zeigt ein bestimmtes Hilfethema (kontextsensitiv, FA-1101)."""
        # Suche zurücksetzen damit das Thema sichtbar ist
        self._search_edit.clear()
        self._populate_list(list(self._topics.keys()))
        all_keys = list(self._topics.keys())
        if key in all_keys:
            idx = all_keys.index(key)
            self._topic_keys = all_keys
            self._topic_list.setCurrentRow(idx)
