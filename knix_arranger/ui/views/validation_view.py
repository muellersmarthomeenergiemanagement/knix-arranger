"""
Validierungsbericht-Ansicht (FA-600)

Baum statt flacher Liste: Stufe (Fehler/Warnungen/Hinweise) → Regel (mit
Titel und Anzahl) → einzelne Meldungen. Dazu Stufen-Schalter und ein
Suchfeld (Adresse, Bezeichnung, Meldung) -- bei importierten Projekten mit
über tausend Hinweisen (FA-610) sonst kaum überblickbar.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QLineEdit, QCheckBox, QAbstractItemView,
)
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtCore import Signal, Qt
from ...services.report_service import VALIDATION_RULES, _rule_sort_key
from ..styles import COLOR_ERROR, COLOR_WARNING, COLOR_INFO, COLOR_OK
from ..column_utils import fit_columns

#: (Stufe, Überschrift, Farbe) in Anzeigereihenfolge
_LEVELS = (
    ("error", "Fehler", COLOR_ERROR),
    ("warning", "Warnungen", COLOR_WARNING),
    ("info", "Hinweise", COLOR_INFO),
)

#: Regeln mit mehr Meldungen werden zugeklappt angezeigt
_EXPAND_LIMIT = 20


def _issue_fields(issue) -> dict:
    """ValidationIssue oder dict -> einheitliche Felder."""
    if hasattr(issue, "level"):
        return {
            "level": issue.level, "rule_id": issue.rule_id,
            "address": issue.address, "message": issue.message,
            "suggestion": issue.suggestion,
            "designation": getattr(issue, "designation", ""),
        }
    return {
        "level": issue.get("level", ""), "rule_id": issue.get("rule_id", ""),
        "address": issue.get("address", ""), "message": issue.get("message", ""),
        "suggestion": issue.get("suggestion", ""),
        "designation": issue.get("designation", ""),
    }


class ValidationView(QWidget):
    """Zeigt Validierungsergebnisse als Baum Stufe → Regel → Meldung."""

    revalidate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._issues: list[dict] = []

        layout = QVBoxLayout(self)

        # Titel und Button
        header = QHBoxLayout()
        title = QLabel("Validierung")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self._btn_validate = QPushButton("Erneut validieren")
        self._btn_validate.clicked.connect(self.revalidate_requested.emit)
        header.addWidget(self._btn_validate)
        layout.addLayout(header)

        # Zusammenfassung
        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        # Legende
        legend = QLabel(
            "Legende:  "
            f"<span style='color:{COLOR_ERROR}; font-weight:bold;'>Fehler</span> = muss behoben werden&nbsp;&nbsp;"
            f"<span style='color:{COLOR_WARNING}; font-weight:bold;'>Warnung</span> = sollte geprüft werden&nbsp;&nbsp;"
            f"<span style='color:{COLOR_INFO}; font-weight:bold;'>Hinweis</span> = zur Kenntnis"
        )
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet("font-size: 12px;")
        layout.addWidget(legend)

        # Filter: Stufen + Suche
        filter_row = QHBoxLayout()
        self._level_boxes: dict[str, QCheckBox] = {}
        for level, label, color in _LEVELS:
            # Ohne eigene Farbe: ein QCheckBox-Stylesheet färbt auch das
            # Häkchen ein (blau auf blau bei "Hinweise" unsichtbar)
            box = QCheckBox(label)
            box.setChecked(True)
            box.toggled.connect(self._rebuild)
            filter_row.addWidget(box)
            self._level_boxes[level] = box
        filter_row.addSpacing(16)
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Suchen: Adresse, Gerät, Bezeichnung oder Regel (z.B. 12/1/62, 1.1.51, FA-614)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._rebuild)
        filter_row.addWidget(self._search, 1)
        btn_expand = QPushButton("Alle aufklappen")
        btn_expand.clicked.connect(self._expand_all)
        filter_row.addWidget(btn_expand)
        btn_collapse = QPushButton("Alle zuklappen")
        btn_collapse.clicked.connect(self._collapse_rules)
        filter_row.addWidget(btn_collapse)
        layout.addLayout(filter_row)

        # Baum
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Stufe / Regel / Adresse", "Meldung", "Vorschlag", "Bezeichnung"])
        self._tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setUniformRowHeights(True)
        self._tree.header().setStretchLastSection(True)
        layout.addWidget(self._tree)

    def set_issues(self, issues: list):
        """Zeigt Validierungsprobleme an."""
        self._issues = [_issue_fields(i) for i in issues]
        self._update_summary()
        self._rebuild()

    # ── Aufbau ─────────────────────────────────────────────────────────────

    def _matches(self, issue: dict, needle: str) -> bool:
        if not needle:
            return True
        title = VALIDATION_RULES.get(issue["rule_id"], ("",))[0]
        haystack = " ".join((issue["rule_id"], title, issue["address"], issue["message"],
                             issue["suggestion"], issue["designation"])).lower()
        return all(part in haystack for part in needle.lower().split())

    def _rebuild(self):
        self._tree.setUpdatesEnabled(False)
        self._tree.clear()
        needle = self._search.text().strip()
        bold = QFont()
        bold.setBold(True)
        shown = 0
        for level, label, color in _LEVELS:
            if not self._level_boxes[level].isChecked():
                continue
            by_rule: dict[str, list[dict]] = {}
            for issue in self._issues:
                if issue["level"] == level and self._matches(issue, needle):
                    by_rule.setdefault(issue["rule_id"], []).append(issue)
            if not by_rule:
                continue
            count = sum(len(v) for v in by_rule.values())
            shown += count
            level_item = QTreeWidgetItem(self._tree, [f"{label}  ({count})"])
            level_item.setForeground(0, QBrush(QColor(color)))
            level_item.setFont(0, bold)
            level_item.setFirstColumnSpanned(True)
            for rule_id in sorted(by_rule, key=_rule_sort_key):
                rule_issues = by_rule[rule_id]
                title = VALIDATION_RULES.get(rule_id, ("",))[0]
                rule_item = QTreeWidgetItem(level_item, [
                    "  ".join(p for p in (rule_id, title, f"({len(rule_issues)})") if p),
                ])
                rule_item.setFont(0, bold)
                rule_item.setFirstColumnSpanned(True)
                meaning = VALIDATION_RULES.get(rule_id, ("", "", ""))[1]
                if meaning:
                    rule_item.setToolTip(0, meaning)
                for issue in rule_issues:
                    item = QTreeWidgetItem(rule_item, [
                        issue["address"] or "–", issue["message"],
                        issue["suggestion"], issue["designation"],
                    ])
                    item.setToolTip(1, issue["message"])
                    item.setForeground(0, QBrush(QColor(color)))
                # Suche aktiv oder wenige Meldungen: aufgeklappt
                rule_item.setExpanded(bool(needle) or len(rule_issues) <= _EXPAND_LIMIT)
            level_item.setExpanded(True)

        if self._issues and not shown:
            QTreeWidgetItem(self._tree, ["Keine Meldung passt zum Filter."])
        fit_columns(self._tree)
        # Meldungen sind lang: Spalte nicht über die halbe Breite wachsen lassen
        max_msg = max(300, self._tree.viewport().width() // 2)
        if self._tree.columnWidth(1) > max_msg:
            self._tree.setColumnWidth(1, max_msg)
        self._tree.setUpdatesEnabled(True)

    def _expand_all(self):
        self._tree.expandAll()

    def _collapse_rules(self):
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            level_item = root.child(i)
            level_item.setExpanded(True)
            for j in range(level_item.childCount()):
                level_item.child(j).setExpanded(False)

    def _update_summary(self):
        counts = {level: 0 for level, _l, _c in _LEVELS}
        for issue in self._issues:
            counts[issue["level"] if issue["level"] in counts else "info"] += 1
        for level, label, _color in _LEVELS:
            self._level_boxes[level].setText(f"{label} ({counts[level]})")
        if not self._issues:
            self._summary.setText("Keine Probleme gefunden.")
            self._summary.setStyleSheet(f"color: {COLOR_OK}; font-weight: bold;")
            return
        self._summary.setText(
            f"{counts['error']} Fehler, {counts['warning']} Warnungen, "
            f"{counts['info']} Hinweise"
        )
        color = (COLOR_ERROR if counts["error"] else
                 COLOR_WARNING if counts["warning"] else COLOR_INFO)
        self._summary.setStyleSheet(f"color: {color}; font-weight: bold;")
