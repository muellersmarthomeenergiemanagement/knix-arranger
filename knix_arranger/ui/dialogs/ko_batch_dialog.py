"""
KOs aller Geräte zuordnen (Materialliste): Ergebnis des Sammelvorschlags mit
Prüfliste, «nicht benötigte Funktionen weglassen» und Übernahme mit OK.
Siehe services/ko_batch.
"""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.ko_batch import REPLACED, UNNEEDED, BatchPlan

_GREY = QColor("#777777")
_WARN = QColor("#b26a00")


class KoBatchDialog(QDialog):
    def __init__(self, project, batch: BatchPlan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KOs aller Geräte zuordnen")
        self.setMinimumSize(860, 520)
        self._project = project
        self._batch = batch

        layout = QVBoxLayout(self)
        replaced = [i for i in batch.issues if i.problem.startswith(REPLACED)]
        problems = [i for i in batch.issues
                    if i.problem != UNNEEDED and not i.problem.startswith(REPLACED)]
        kept = (f" {len(batch.kept)} Geräte mit eigener Zuordnung bleiben unverändert."
                if batch.kept else "")
        summary = QLabel(
            f"<b>{len(batch.plans)} Geräte</b> zugeordnet, {batch.links} GAs mit KO.{kept}<br>"
            + (f"<span style='color:#b26a00'>{len(replaced)} bisherige Zuordnungen "
               "ersetzt</span>: das KO passte nicht zur Funktion (Rückmeldung auf "
               "Eingangs-KO, Datentyp, andere Taste).<br>" if replaced else "")
            + (f"<span style='color:#b26a00'>{len(problems)} GAs prüfen</span> "
               "(kein passender KO oder DPT passt nicht) – im Dialog «Kanäle und KOs "
               "zuordnen…» von Hand wählen." if problems else
               "Keine unsicheren Zuordnungen.")
            + ("<br>Gemerkte Zuordnungen gleicher Produkte haben Vorrang vor dem Vorschlag."))
        summary.setWordWrap(True)
        layout.addWidget(summary)

        rows = sorted(batch.issues, key=lambda i: (i.problem == UNNEEDED,
                                                   i.device.physical_address, i.where))
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["Gerät", "Stromkreis / Taste", "Funktion", "GA",
                                         "Prüfung"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for row, issue in enumerate(rows):
            device = issue.device
            texts = [f"{device.physical_address} {device.product_name or device.product}",
                     issue.where, issue.function, issue.ga_address,
                     "nicht benötigt – kann weggelassen werden" if issue.problem == UNNEEDED
                     else issue.problem]
            for col, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if issue.problem == UNNEEDED:
                    item.setForeground(QBrush(_GREY))
                elif col == 4:
                    item.setForeground(QBrush(_WARN))
                table.setItem(row, col, item)
        table.setColumnWidth(0, 200)
        table.setColumnWidth(2, 120)
        table.setColumnWidth(3, 70)
        layout.addWidget(table, 1)
        if not rows:
            table.setVisible(False)

        self._omit_check = QCheckBox(
            f"Nicht benötigte Funktionen weglassen: {batch.unneeded_count} GAs entfallen, "
            "Plätze bleiben Reserve")
        self._omit_check.setToolTip(
            "Funktionen, für die der Aktorkanal keinen KO hat (z.B. DIM/WERT eines\n"
            "Lichtkreises an einem Schaltaktor), erhalten keine GA. Die übrigen\n"
            "Adressen ändern sich nicht.")
        self._omit_check.setVisible(bool(batch.unneeded_count) and not project.addresses_fixed)
        layout.addWidget(self._omit_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(batch.plans))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def omit(self) -> bool:
        return not self._omit_check.isHidden() and self._omit_check.isChecked()
