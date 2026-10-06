"""
Dialog "Bedienungsanleitung anpassen" (FA-2005): eigene Texte, Abschnitte
ein-/ausblenden, eigene Abschnitte, Text je Raum und Foto je Taster.
Die Anpassungen gelten nur für dieses Projekt.
"""
from __future__ import annotations
import copy
import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
    QPlainTextEdit, QCheckBox, QListWidget, QListWidgetItem, QLineEdit,
    QFileDialog, QSplitter, QFormLayout, QComboBox,
)

from ...models.documentation import UserManualSettings
from ...services.ets_corrections import room_key
from ...services.manual_i18n import MANUAL_LANGUAGES, ManualLanguage, language_name
from ...services.user_manual import MANUAL_SECTIONS, MANUAL_TEXTS, photo_key

PHOTO_FOLDER = "Fotos"
_TIPS_PLACEHOLDER = ("Standard: wird aus den Funktionen des Projekts zusammengestellt "
                     "(kurz/lang drücken, Dimmen, Storen, Leuchtanzeigen …).")


def manual_rooms(project) -> list[tuple[str, str, object]]:
    """Räume in Gebäudereihenfolge: (Raumschlüssel, Anzeige, Raum)."""
    result = []
    for building in project.areal.buildings:
        for floor in building.all_floors:
            for room in floor.all_rooms:
                label = " ".join(p for p in (floor.short_code or floor.name,
                                             room.number, room.name) if p)
                result.append((room_key(floor, room), label, room))
    return result


def manual_buttons(project) -> list[tuple[str, str]]:
    """Taster der Anleitung: (Foto-Schlüssel, Anzeige)."""
    imported = project.topology.is_imported
    result = []
    for rkey, label, room in manual_rooms(project):
        for be in room.bedienelemente:
            if not (be.is_shown(imported) and be.is_operable):
                continue
            name = {"Tastereinheit": "Taster"}.get(be.element_type, be.element_type)
            detail = be.participant_number or f"Nr. {be.taster_index}"
            result.append((photo_key(rkey, be), f"{label} – {name} ({detail})"))
    return list(dict(result).items())


class UserManualSettingsDialog(QDialog):
    """Bearbeitet eine Kopie von project.manual_settings; übernimmt bei OK."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self._project = project
        self.settings: UserManualSettings = copy.deepcopy(project.manual_settings)
        self.setWindowTitle("Bedienungsanleitung anpassen")
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        intro = QLabel("Anpassungen gelten nur für dieses Projekt. Leere Textfelder "
                       "verwenden den Standardtext.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tabs = QTabWidget()
        tabs.addTab(self._texts_tab(), "Texte")
        tabs.addTab(self._sections_tab(), "Abschnitte")
        tabs.addTab(self._custom_tab(), "Eigene Abschnitte")
        tabs.addTab(self._rooms_tab(), "Räume")
        tabs.addTab(self._photos_tab(), "Taster-Fotos")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("Übernehmen")
        ok.clicked.connect(self._accept)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    # ── Texte ──

    def _texts_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        # Sprache des Bauherrn (FA-2006)
        self._language = QComboBox()
        for code in MANUAL_LANGUAGES:
            self._language.addItem(language_name(code), code)
        idx = self._language.findData(self.settings.language)
        self._language.setCurrentIndex(max(idx, 0))
        self._language.setToolTip(
            "Sprache der Anleitung. Eigene Texte bitte in dieser Sprache erfassen; "
            "Raumnamen und Bezeichnungen aus dem Projekt bleiben, wie sie erfasst sind.")
        self._language.currentIndexChanged.connect(self._update_placeholders)
        form.addRow("Sprache der Anleitung:", self._language)
        self._text_edits: dict[str, QPlainTextEdit] = {}
        for key, (label, default) in MANUAL_TEXTS.items():
            edit = QPlainTextEdit(self.settings.texts.get(key, ""))
            edit.setPlaceholderText(default or _TIPS_PLACEHOLDER)
            edit.setMinimumHeight(70)
            row = QHBoxLayout()
            row.addWidget(edit)
            reset = QPushButton("Standard")
            reset.setToolTip("Eigenen Text löschen, Standardtext verwenden")
            reset.clicked.connect(edit.clear)
            row.addWidget(reset, alignment=Qt.AlignTop)
            form.addRow(f"{label}:", row)
            self._text_edits[key] = edit
        self._update_placeholders()
        return page

    def _update_placeholders(self, *_args) -> None:
        """Standardtexte der gewählten Sprache grau im leeren Feld."""
        lang = ManualLanguage(self._language.currentData() or "de")
        for key, edit in self._text_edits.items():
            edit.setPlaceholderText(lang.text(key) if key != "tipps" else _TIPS_PLACEHOLDER)

    # ── Abschnitte ──

    def _sections_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(QLabel("Angehakte Abschnitte erscheinen in der Anleitung:"))
        self._section_checks: dict[str, QCheckBox] = {}
        for key, label in MANUAL_SECTIONS.items():
            check = QCheckBox(label)
            check.setChecked(key not in self.settings.hidden)
            box.addWidget(check)
            self._section_checks[key] = check
        box.addStretch()
        return page

    # ── Eigene Abschnitte ──

    def _custom_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(QLabel("Erscheinen im Teil «Allgemeines», z.B. «Visualisierung "
                             "auf dem Tablet» oder «Alarmanlage»."))
        split = QSplitter()
        self._custom_list = QListWidget()
        split.addWidget(self._custom_list)
        editor = QWidget()
        form = QVBoxLayout(editor)
        self._custom_title = QLineEdit()
        self._custom_title.setPlaceholderText("Titel")
        self._custom_text = QPlainTextEdit()
        self._custom_text.setPlaceholderText("Text")
        form.addWidget(self._custom_title)
        form.addWidget(self._custom_text)
        split.addWidget(editor)
        split.setSizes([220, 500])
        box.addWidget(split)
        row = QHBoxLayout()
        add = QPushButton("+ Abschnitt")
        add.clicked.connect(self._add_custom)
        remove = QPushButton("Entfernen")
        remove.setObjectName("secondary")
        remove.clicked.connect(self._remove_custom)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        box.addLayout(row)

        self._custom_rows = [dict(s) for s in self.settings.custom_sections]
        for section in self._custom_rows:
            self._custom_list.addItem(section.get("title") or "(ohne Titel)")
        self._custom_list.currentRowChanged.connect(self._show_custom)
        self._custom_title.textEdited.connect(self._store_custom)
        self._custom_text.textChanged.connect(self._store_custom)
        self._custom_index = -1
        self._set_custom_enabled(False)
        if self._custom_rows:
            self._custom_list.setCurrentRow(0)
        return page

    def _set_custom_enabled(self, enabled: bool) -> None:
        self._custom_title.setEnabled(enabled)
        self._custom_text.setEnabled(enabled)

    def _show_custom(self, row: int) -> None:
        self._custom_index = -1          # Laden löst keine Speicherung aus
        valid = 0 <= row < len(self._custom_rows)
        self._custom_title.setText(self._custom_rows[row].get("title", "") if valid else "")
        self._custom_text.setPlainText(self._custom_rows[row].get("text", "") if valid else "")
        self._set_custom_enabled(valid)
        self._custom_index = row if valid else -1

    def _store_custom(self, *_args) -> None:
        if self._custom_index < 0:
            return
        section = self._custom_rows[self._custom_index]
        section["title"] = self._custom_title.text()
        section["text"] = self._custom_text.toPlainText()
        self._custom_list.item(self._custom_index).setText(section["title"] or "(ohne Titel)")

    def _add_custom(self) -> None:
        self._custom_rows.append({"title": "Neuer Abschnitt", "text": ""})
        self._custom_list.addItem("Neuer Abschnitt")
        self._custom_list.setCurrentRow(len(self._custom_rows) - 1)
        self._custom_title.setFocus()
        self._custom_title.selectAll()

    def _remove_custom(self) -> None:
        row = self._custom_list.currentRow()
        if 0 <= row < len(self._custom_rows):
            self._custom_index = -1
            del self._custom_rows[row]
            self._custom_list.takeItem(row)
            self._show_custom(self._custom_list.currentRow())

    # ── Räume ──

    def _rooms_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(QLabel("Zusatztext unter der Raumüberschrift, z.B. «Die Storen im "
                             "Wintergarten fahren bei Wind automatisch hoch.»"))
        split = QSplitter()
        self._room_list = QListWidget()
        self._room_texts = dict(self.settings.room_texts)
        for rkey, label, _room in manual_rooms(self._project):
            item = QListWidgetItem(label + ("  ✎" if self._room_texts.get(rkey) else ""))
            item.setData(Qt.UserRole, (rkey, label))
            self._room_list.addItem(item)
        split.addWidget(self._room_list)
        self._room_text = QPlainTextEdit()
        self._room_text.setEnabled(False)
        split.addWidget(self._room_text)
        split.setSizes([260, 460])
        box.addWidget(split)
        self._room_key = ""
        self._room_list.currentItemChanged.connect(self._show_room)
        self._room_text.textChanged.connect(self._store_room)
        return page

    def _show_room(self, item, _previous=None) -> None:
        self._room_key = ""
        rkey = item.data(Qt.UserRole)[0] if item else ""
        self._room_text.setPlainText(self._room_texts.get(rkey, ""))
        self._room_text.setEnabled(bool(rkey))
        self._room_key = rkey

    def _store_room(self) -> None:
        if not self._room_key:
            return
        text = self._room_text.toPlainText()
        if text.strip():
            self._room_texts[self._room_key] = text
        else:
            self._room_texts.pop(self._room_key, None)
        item = self._room_list.currentItem()
        if item:
            label = item.data(Qt.UserRole)[1]
            item.setText(label + ("  ✎" if text.strip() else ""))

    # ── Taster-Fotos ──

    def _photos_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(QLabel("Foto des montierten Tasters; steht in der Anleitung "
                             "rechts neben dem Tastenplan."))
        self._photos = dict(self.settings.photos)
        self._photo_list = QListWidget()
        for key, label in manual_buttons(self._project):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, (key, label))
            self._photo_list.addItem(item)
            self._refresh_photo_item(item)
        box.addWidget(self._photo_list)
        row = QHBoxLayout()
        choose = QPushButton("Foto wählen…")
        choose.clicked.connect(self._choose_photo)
        remove = QPushButton("Foto entfernen")
        remove.setObjectName("secondary")
        remove.clicked.connect(self._remove_photo)
        row.addWidget(choose)
        row.addWidget(remove)
        row.addStretch()
        box.addLayout(row)
        return page

    def _refresh_photo_item(self, item) -> None:
        key, label = item.data(Qt.UserRole)
        photo = self._photos.get(key, "")
        item.setText(f"{label}   →   {os.path.basename(photo)}" if photo else label)

    def _choose_photo(self) -> None:
        item = self._photo_list.currentItem()
        if not item:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Foto des Tasters wählen", "",
            "Bilder (*.jpg *.jpeg *.png);;Alle Dateien (*.*)")
        if not path:
            return
        self._photos[item.data(Qt.UserRole)[0]] = self._store_photo(path)
        self._refresh_photo_item(item)

    def _store_photo(self, path: str) -> str:
        """Kopiert das Foto in den Projektordner (Unterordner «Fotos») und gibt
        den Pfad relativ dazu zurück -- so reist es mit dem Projekt mit.
        Ohne gespeichertes Projekt bleibt der Originalpfad."""
        folder = self._project.folder_path
        if not folder:
            return path
        target_dir = os.path.join(folder, PHOTO_FOLDER)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, os.path.basename(path))
        if os.path.abspath(target) != os.path.abspath(path):
            stem, ext = os.path.splitext(target)
            n = 2
            while os.path.exists(target):
                target = f"{stem}_{n}{ext}"
                n += 1
            shutil.copy2(path, target)
        return os.path.relpath(target, folder)

    def _remove_photo(self) -> None:
        item = self._photo_list.currentItem()
        if item:
            self._photos.pop(item.data(Qt.UserRole)[0], None)
            self._refresh_photo_item(item)

    # ── Übernehmen ──

    def _accept(self) -> None:
        s = self.settings
        s.texts = {k: e.toPlainText().strip() for k, e in self._text_edits.items()
                   if e.toPlainText().strip()}
        s.hidden = [k for k, c in self._section_checks.items() if not c.isChecked()]
        s.custom_sections = [
            {"title": r.get("title", "").strip(), "text": r.get("text", "").strip()}
            for r in self._custom_rows
            if r.get("title", "").strip() or r.get("text", "").strip()]
        s.room_texts = {k: v.strip() for k, v in self._room_texts.items() if v.strip()}
        s.photos = dict(self._photos)
        s.language = self._language.currentData() or "de"
        self.accept()
