"""
Zusammenfassung nach einem ETS-Import: ein Fenster statt einer Folge von
Meldungen (Abgleich, Kanal-Konflikte, Arbeitsliste, Secure, fehlgeschlagene
Schritte). Oben das Ergebnis, darunter die Hinweise, Warnungen zuerst.
"""
from __future__ import annotations
import html
from dataclasses import dataclass

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextBrowser, QVBoxLayout

from ..styles import COLOR_OK, COLOR_WARNING, TEXT_MUTED


@dataclass
class ImportNote:
    title: str
    text: str
    warning: bool = False


def notes_html(notes: list[ImportNote]) -> str:
    """Hinweise als HTML, Warnungen zuerst (Reihenfolge sonst unverändert)."""
    ordered = [n for n in notes if n.warning] + [n for n in notes if not n.warning]
    parts = []
    for note in ordered:
        color = COLOR_WARNING if note.warning else TEXT_MUTED
        body = html.escape(note.text).replace("\n", "<br>")
        parts.append(f"<h4 style='color:{color}; margin-bottom:2px;'>"
                     f"{html.escape(note.title)}</h4><p style='margin-top:0;'>{body}</p>")
    return "".join(parts)


class ImportSummaryDialog(QDialog):
    def __init__(self, title: str, summary: str, notes: list[ImportNote], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560 if notes else 220)
        layout = QVBoxLayout(self)

        head = QLabel(summary)
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: bold;")
        layout.addWidget(head)

        warnings = sum(1 for n in notes if n.warning)
        state = QLabel(
            f"{warnings} {'Punkt' if warnings == 1 else 'Punkte'} zu prüfen, "
            f"{len(notes) - warnings} {'Hinweis' if len(notes) - warnings == 1 else 'Hinweise'}."
            if notes else "Import ohne Auffälligkeiten.")
        state.setStyleSheet(f"color: {COLOR_WARNING if warnings else COLOR_OK};")
        layout.addWidget(state)

        if notes:
            browser = QTextBrowser()
            browser.setHtml(notes_html(notes))
            layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).setText("Schliessen")
        layout.addWidget(buttons)
