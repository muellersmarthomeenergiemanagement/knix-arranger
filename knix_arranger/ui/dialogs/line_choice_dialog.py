"""
Linien finden (FA-3108e): gefundene Linien mit Herkunft zum Anhaken, weitere
von Hand, geschätzte Dauer der Suche.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from ...services import device_scan as ds
from ..styles import COLOR_WARNING, TEXT_MUTED


class LineChoiceDialog(QDialog):

    def __init__(self, candidates: list[ds.LineCandidate], couplers_searched: bool = True,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Linien finden")
        self.resize(620, 440)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Diese Linien kennt KNiX aus der Schnittstelle, den mitgehörten Absendern und "
            "den Kopplern, die geantwortet haben. Angehakte Linien werden nach Teilnehmern "
            "abgesucht.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        self._list = QListWidget()
        for candidate in candidates:
            self._add_item(candidate.line, candidate.origin(), candidate.preselected)
        self._list.itemChanged.connect(lambda _i: self._update_summary())
        layout.addWidget(self._list, 1)

        if couplers_searched and not any(c.coupler for c in candidates):
            hint = QLabel(
                "Kein Koppler hat geantwortet. Über manche Fernzugänge antworten Koppler "
                "nicht; dann gelten nur die Linie der Schnittstelle und die gehörten "
                "Absender. Weitere Linien unten ergänzen.")
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {COLOR_WARNING};")
            layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("Weitere Linie:"))
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("z.B. 2.1")
        self._extra.returnPressed.connect(self._add_extra)
        add = QPushButton("Hinzufügen")
        add.setObjectName("secondary")
        add.clicked.connect(self._add_extra)
        row.addWidget(self._extra, 1)
        row.addWidget(add)
        layout.addLayout(row)

        self._summary = QLabel()
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok = buttons.button(QDialogButtonBox.Ok)
        self._ok.setText("Suchen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_summary()

    def _add_item(self, line: tuple[int, int], origin: str, checked: bool) -> None:
        item = QListWidgetItem(f"{ds.line_text(line)}    {origin}")
        item.setData(Qt.UserRole, line)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._list.addItem(item)

    def _add_extra(self) -> None:
        text = self._extra.text().strip()
        if not text:
            return
        try:
            lines = ds.parse_lines(text)
        except ValueError as exc:
            QMessageBox.information(self, "Linien finden", str(exc))
            return
        known = {self._list.item(i).data(Qt.UserRole): self._list.item(i)
                 for i in range(self._list.count())}
        for line in lines:
            if line in known:
                known[line].setCheckState(Qt.Checked)
            else:
                self._add_item(line, "von Hand", True)
        self._extra.clear()
        self._update_summary()

    def selected_lines(self) -> list[tuple[int, int]]:
        lines = [self._list.item(i).data(Qt.UserRole) for i in range(self._list.count())
                 if self._list.item(i).checkState() == Qt.Checked]
        return sorted(tuple(line) for line in lines)

    def _update_summary(self) -> None:
        count = len(self.selected_lines())
        self._ok.setEnabled(count > 0)
        self._summary.setText(
            f"{count} Linie{'n' if count != 1 else ''} – Suche dauert "
            f"{ds.duration_text(count)}" if count else "Keine Linie angehakt.")
