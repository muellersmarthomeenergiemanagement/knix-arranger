"""
Validierungsbericht-Ansicht (FA-600)

Baum statt flacher Liste: Stufe (Fehler/Warnungen/Hinweise) → Regel (mit
Titel und Anzahl) → einzelne Meldungen. Dazu Stufen-Schalter und ein
Suchfeld (Adresse, Bezeichnung, Meldung) -- bei importierten Projekten mit
über tausend Hinweisen (FA-610) sonst kaum überblickbar.

Lange Texte brechen um, die Spalten teilen sich die Breite (FA-615a).
Doppelklick oder Enter auf eine Meldung springt dorthin, wo man sie
korrigiert; weitere Ziele im Kontextmenü (services/validation_targets).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QLineEdit, QCheckBox, QAbstractItemView, QMenu,
    QHeaderView, QStyledItemDelegate,
)
from PySide6.QtGui import QColor, QBrush, QFont, QKeySequence, QShortcut
from PySide6.QtCore import Signal, Qt, QTimer, QRect, QSize
from ...services.report_service import VALIDATION_RULES, _rule_sort_key
from ..styles import COLOR_ERROR, COLOR_WARNING, COLOR_INFO, COLOR_OK

#: (Stufe, Überschrift, Farbe) in Anzeigereihenfolge
_LEVELS = (
    ("error", "Fehler", COLOR_ERROR),
    ("warning", "Warnungen", COLOR_WARNING),
    ("info", "Hinweise", COLOR_INFO),
)

#: Regeln mit mehr Meldungen werden zugeklappt angezeigt
_EXPAND_LIMIT = 20

#: Anteile der Textspalten Meldung, Vorschlag, Bezeichnung an der Restbreite
_TEXT_SHARES = (0.45, 0.33, 0.22)
#: Adress-Spalte höchstens so breit (Regel-Titel überspannen alle Spalten)
_MAX_ADDRESS_WIDTH = 220
_ISSUE_ROLE = Qt.UserRole


class _WrapDelegate(QStyledItemDelegate):
    """Zeilenhöhe aus der aktuellen Spaltenbreite: QTreeView bricht mit
    setWordWrap um, berechnet die Höhe aber nicht danach."""

    _PADDING = 8

    def __init__(self, tree):
        super().__init__(tree)
        self._tree = tree

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        text = index.data(Qt.DisplayRole)
        if index.column() == 0 or not text:
            return size
        width = self._tree.columnWidth(index.column()) - self._PADDING
        if width <= 20:
            return size
        rect = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 100000), Qt.TextWordWrap, str(text))
        return QSize(size.width(), max(size.height(), rect.height() + self._PADDING // 2))


def _issue_fields(issue) -> dict:
    """ValidationIssue oder dict -> einheitliche Felder."""
    if hasattr(issue, "level"):
        return {
            "level": issue.level, "rule_id": issue.rule_id,
            "address": issue.address, "message": issue.message,
            "suggestion": issue.suggestion,
            "designation": getattr(issue, "designation", ""),
            "details": dict(getattr(issue, "details", None) or {}),
        }
    return {
        "level": issue.get("level", ""), "rule_id": issue.get("rule_id", ""),
        "address": issue.get("address", ""), "message": issue.get("message", ""),
        "suggestion": issue.get("suggestion", ""),
        "designation": issue.get("designation", ""),
        "details": dict(issue.get("details") or {}),
    }


class ValidationView(QWidget):
    """Zeigt Validierungsergebnisse als Baum Stufe → Regel → Meldung."""

    revalidate_requested = Signal()
    worklist_requested = Signal()     # ETS-Arbeitsliste erstellen (FA-618)
    # Sprung zur Korrektur (FA-615a): validation_targets.Target
    jump_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._issues: list[dict] = []
        # Meldung -> Sprungziele, vom Hauptfenster gesetzt (braucht das Projekt)
        self._targets_for = None

        layout = QVBoxLayout(self)

        # Titel und Button
        header = QHBoxLayout()
        title = QLabel("Validierung")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self._btn_worklist = QPushButton("ETS-Arbeitsliste…")
        self._btn_worklist.setToolTip(
            "Was in der ETS zu korrigieren ist – mit Anleitung, als PDF oder Excel. "
            "Nach dem Re-Import zeigt KNiX, was erledigt ist.")
        self._btn_worklist.clicked.connect(self.worklist_requested.emit)
        header.addWidget(self._btn_worklist)
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
        # Lange Meldungen umbrechen statt abschneiden
        self._tree.setWordWrap(True)
        self._tree.setUniformRowHeights(False)
        self._tree.setTextElideMode(Qt.ElideNone)
        self._tree.setItemDelegate(_WrapDelegate(self._tree))
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        header = self._tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        # Breite von Hand gezogen: Zeilenhöhen neu berechnen
        header.sectionResized.connect(lambda *_a: self._relayout_timer.start())
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(50)
        self._relayout_timer.timeout.connect(self._tree.doItemsLayout)
        self._tree.itemDoubleClicked.connect(lambda item, _c: self._jump(item))
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        for key in (Qt.Key_Return, Qt.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self._tree)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(lambda: self._jump(self._tree.currentItem()))
        layout.addWidget(self._tree)

        hint = QLabel("Doppelklick oder Enter auf eine Meldung: zur Stelle springen, an der "
                      "sie korrigiert wird  ·  Rechtsklick: weitere Ziele")
        hint.setStyleSheet("color: #666666; font-style: italic;")
        layout.addWidget(hint)

    def set_target_provider(self, provider) -> None:
        """provider(issue_dict) -> list[validation_targets.Target]."""
        self._targets_for = provider

    def _targets(self, item) -> list:
        issue = item.data(0, _ISSUE_ROLE) if item is not None else None
        if not isinstance(issue, dict) or self._targets_for is None:
            return []
        try:
            return self._targets_for(issue)
        except Exception:   # Projekt seit der Validierung geändert
            return []

    def _jump(self, item) -> None:
        targets = self._targets(item)
        if targets:
            self.jump_requested.emit(targets[0])

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        targets = self._targets(item)
        if not targets:
            return
        menu = QMenu(self)
        actions = {menu.addAction(t.label): t for t in targets}
        menu.setDefaultAction(next(iter(actions)))
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen in actions:
            self.jump_requested.emit(actions[chosen])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Adresse nach Inhalt (begrenzt), Restbreite anteilig auf die
        Textspalten; die Zeilen werden dafür höher (Umbruch)."""
        width = self._tree.viewport().width()
        if width <= 0:
            return
        self._tree.resizeColumnToContents(0)
        address = min(self._tree.columnWidth(0), _MAX_ADDRESS_WIDTH)
        self._tree.setColumnWidth(0, address)
        rest = max(width - address, 300)
        for col, share in enumerate(_TEXT_SHARES[:-1], start=1):
            self._tree.setColumnWidth(col, int(rest * share))
        self._relayout_timer.start()

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
                    item.setData(0, _ISSUE_ROLE, issue)
                    for col, text in ((1, issue["message"]), (2, issue["suggestion"])):
                        if text:
                            item.setToolTip(col, text)
                    item.setForeground(0, QBrush(QColor(color)))
                # Suche aktiv oder wenige Meldungen: aufgeklappt
                rule_item.setExpanded(bool(needle) or len(rule_issues) <= _EXPAND_LIMIT)
            level_item.setExpanded(True)

        if self._issues and not shown:
            QTreeWidgetItem(self._tree, ["Keine Meldung passt zum Filter."])
        self._fit_columns()
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
