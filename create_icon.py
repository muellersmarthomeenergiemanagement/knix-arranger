"""
Konvertiert icon.svg → icon.ico (multi-resolution) via PySide6

Voraussetzungen:
    pip install PySide6 pillow

Ausfuehren:
    python create_icon.py
"""
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QImage, QPainter
from PIL import Image

ROOT = Path(__file__).parent
SVG_PATH = ROOT / "icon.svg"
ICO_PATH = ROOT / "icon.ico"
SIZES = [256, 128, 64, 48, 32, 16]


def convert():
    app = QApplication.instance() or QApplication(sys.argv)
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"FEHLER: {SVG_PATH} konnte nicht geladen werden.")
        sys.exit(1)

    frames = []
    for size in SIZES:
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()
        pil = Image.frombytes("RGBA", (size, size), img.bits().tobytes(), "raw", "BGRA")
        frames.append(pil)
        print(f"  {size}x{size} OK")

    frames[0].save(
        ICO_PATH,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"\nIcon gespeichert: {ICO_PATH}")


if __name__ == "__main__":
    convert()
