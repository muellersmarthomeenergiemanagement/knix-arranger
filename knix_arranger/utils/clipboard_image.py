"""
Hilfsfunktion zum Einfügen von Bildern aus der Zwischenablage.
Speichert das Bild als PNG-Datei, damit es wie ein normal ausgewähltes
Bild (Pfad) weiterverwendet werden kann (z.B. für PDF-Berichte).
"""
from __future__ import annotations
import os
from datetime import datetime

from PySide6.QtGui import QGuiApplication


def get_pasted_images_dir() -> str:
    """Gibt das Verzeichnis für aus der Zwischenablage eingefügte Bilder zurück."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    img_dir = os.path.join(appdata, "KNiX Arranger", "pasted_images")
    os.makedirs(img_dir, exist_ok=True)
    return img_dir


def save_clipboard_image(prefix: str = "bild") -> str | None:
    """
    Speichert ein Bild aus der Zwischenablage als PNG-Datei und gibt den
    Dateipfad zurück. Gibt None zurück, wenn sich kein Bild in der
    Zwischenablage befindet.
    """
    image = QGuiApplication.clipboard().image()
    if image.isNull():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{prefix}_{timestamp}.png"
    filepath = os.path.join(get_pasted_images_dir(), filename)
    image.save(filepath, "PNG")
    return filepath
