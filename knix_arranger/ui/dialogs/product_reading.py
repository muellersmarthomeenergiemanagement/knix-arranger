"""
Herstellerdateien aus dem Produktordner einlesen – nur die für fehlende
Geräte nötigen, nach Rückfrage und mit Fortschritt (FA-3108f). Grosse
Sammeldateien (z.B. 160 MB) dauern über eine Netzfreigabe Minuten; nie
unangekündigt im Hauptfenster.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from ...services import missing_products as mp


def read_with_progress(parent, paths: list[str], catalog=None) -> mp.ReadResult:
    """Jede Datei im Hintergrund lesen (das Fenster bleibt bedienbar, auch bei
    einer 160-MB-Datei über die Netzfreigabe); Katalog im Hauptthread.
    «Abbrechen» wirkt nach der laufenden Datei."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    dialog = QProgressDialog("Herstellerdateien einlesen …", "Abbrechen", 0, len(paths), parent)
    dialog.setWindowTitle("Herstellerdateien")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(0)
    result = mp.ReadResult()
    products, imported = [], {}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            for number, path in enumerate(paths):
                if dialog.wasCanceled():
                    result.problems.append("abgebrochen")
                    break
                name = os.path.basename(path)
                try:
                    size = round(os.path.getsize(path) / 1_000_000)
                except OSError:
                    size = 0
                dialog.setValue(number)
                dialog.setLabelText(f"Liest {name} ({size} MB) – {number + 1} von {len(paths)}")
                future = pool.submit(mp.parse_file, path)
                while not future.done():
                    QApplication.processEvents()
                    time.sleep(0.05)
                try:
                    found, problem = future.result()
                except Exception as exc:          # unlesbare Datei: weiter mit der nächsten
                    found, problem = [], f"{name}: {exc}"
                if problem:
                    result.problems.append(problem)
                    continue
                products.extend(found)
                imported[path] = len(found)
        mp.store(products, imported, catalog, result)
    finally:
        dialog.setValue(len(paths))
        dialog.close()
    return result


def offer_pending(parent, manufacturers: set[str], catalog=None,
                  title: str = "Herstellerdateien") -> mp.ReadResult:
    """Noch nicht eingelesene Dateien dieser Hersteller anbieten und nach
    «Ja» einlesen. Ohne passende Dateien oder bei «Nein»: leeres Ergebnis."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        paths = mp.relevant_pending(manufacturers)
    finally:
        QApplication.restoreOverrideCursor()
    if not paths:
        return mp.ReadResult()
    names = ", ".join(os.path.basename(p) for p in paths[:4]) + (" …" if len(paths) > 4 else "")
    answer = QMessageBox.question(
        parent, title,
        f"Im Produktordner liegen {len(paths)} noch nicht eingelesene Herstellerdatei"
        f"{'en' if len(paths) != 1 else ''} für Geräte ohne Produkt ({mp.total_mb(paths)} MB): "
        f"{names}\n\nJetzt einlesen? Grosse Dateien brauchen über eine Netzfreigabe "
        "einige Minuten; abbrechen ist zwischen den Dateien möglich.")
    if answer != QMessageBox.Yes:
        return mp.ReadResult()
    return read_with_progress(parent, paths, catalog)
