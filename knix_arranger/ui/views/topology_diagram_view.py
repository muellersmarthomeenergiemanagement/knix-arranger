"""
Topologie-Prinzipschema als grafisches Diagramm (FA-212, FA-904, FA-1013)
Zeigt Bereiche, Linienkoppler, Speisegeräte und Geräteanzahlen als Kastendiagramm.
Exportierbar als PNG und (mit PyMuPDF) als PDF.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsLineItem, QFileDialog, QMessageBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPen, QBrush, QFont, QFontMetrics, QPainter, QPixmap,
)
from ...models.project import KnxProject
from ...services.cable_length_service import CableLengthService
from ..styles import COLOR_WARNING, COLOR_ERROR

# ── Farben (KNX-Designbasis, FA-1012) ────────────────────────────────────────
_C_BACKBONE    = QColor("#1A237E")   # Dunkelblau: Backbone
_C_AREA        = QColor("#1565C0")   # Blau: Bereich
_C_COUPLER     = QColor("#1565C0")   # Blau: Koppler
_C_POWER       = QColor("#2E7D32")   # Grün: Speisegerät
_C_LINE        = QColor("#37474F")   # Dunkelgrau: Linie
_C_LINE_WARN   = QColor(COLOR_WARNING)  # Orange: Leitungslänge nahe Grenzwert (FA-2603)
_C_LINE_ERROR  = QColor(COLOR_ERROR)    # Rot: Leitungslänge über Grenzwert (FA-2603)
_C_BG          = QColor("#FAFAFA")   # Hintergrund
_C_LINE_WIRE   = QColor("#78909C")   # Verbindungslinien

# ── Maße ─────────────────────────────────────────────────────────────────────
BOX_W       = 160
BOX_H_AREA  = 40
BOX_H_NODE  = 34   # BK, LK, SV
BOX_H_LINE  = 90   # Linie-Box (inkl. Gerätezähler)
GAP_COL     = 50   # Abstand zwischen Bereichen
GAP_ROW     = 18   # Abstand zwischen Zeilen innerhalb eines Bereichs
MARGIN      = 30


class _Box:
    """Hilfsobjekt: eine Kasten-Position im Diagramm."""
    def __init__(self, x: float, y: float, w: float, h: float,
                 label: str, sub: str = "", color: QColor = _C_LINE,
                 text_color: QColor = QColor("white"), tooltip: str = ""):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.label = label
        self.sub = sub
        self.color = color
        self.text_color = text_color
        self.tooltip = tooltip or label

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def top(self) -> float:
        return self.y


class TopologyDiagramView(QWidget):
    """Grafisches Topologie-Prinzipschema (FA-212, FA-904)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        title = QLabel("Topologie-Prinzipschema")
        title.setObjectName("title")
        toolbar.addWidget(title)
        toolbar.addStretch()

        btn_export_png = QPushButton("Als PNG exportieren…")
        btn_export_png.clicked.connect(self._export_png)
        toolbar.addWidget(btn_export_png)

        btn_export_pdf = QPushButton("Als PDF exportieren…")
        btn_export_pdf.clicked.connect(self._export_pdf)
        toolbar.addWidget(btn_export_pdf)

        layout.addLayout(toolbar)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        legend = QLabel(
            f"<span style='color:{_C_AREA.name()};'>&#9632;</span> Bereich/Koppler&nbsp;&nbsp;"
            f"<span style='color:{_C_POWER.name()};'>&#9632;</span> Speisegerät&nbsp;&nbsp;"
            f"<span style='color:{_C_LINE.name()};'>&#9632;</span> Linie (OK)&nbsp;&nbsp;"
            f"<span style='color:{_C_LINE_WARN.name()};'>&#9632;</span> Leitungslänge nahe Grenzwert&nbsp;&nbsp;"
            f"<span style='color:{_C_LINE_ERROR.name()};'>&#9632;</span> Leitungslänge überschritten (FA-2603)&nbsp;&nbsp;"
            f"<span style='color:{_C_BACKBONE.name()};'>&#9632;</span> Backbone&nbsp;&nbsp;&nbsp;"
            "▶ Aktor(en)&nbsp;&nbsp;⏺ Sensor(en)&nbsp;&nbsp;◆ Sonstige"
        )
        legend.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(legend)

        # Zeichenfläche
        self._scene = QGraphicsScene()
        self._scene.setBackgroundBrush(QBrush(_C_BG))

        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setDragMode(QGraphicsView.ScrollHandDrag)
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._view)

    def set_project(self, project: KnxProject):
        self._project = project
        self._rebuild()

    def _rebuild(self):
        self._scene.clear()
        if not self._project or not self._project.topology.areas:
            self._info.setText("Keine Topologie vorhanden.")
            return
        self._draw_topology()
        self._view.fitInView(self._scene.sceneRect().adjusted(-20, -20, 20, 20),
                             Qt.KeepAspectRatio)

    # ── Zeichnen ──────────────────────────────────────────────────────────────

    def _draw_topology(self):
        areas = self._project.topology.areas
        multi_area = len(areas) > 1

        # FA-2603: Leitungslängen-Warnungen/-Fehler pro Linie (dieselbe Prüfung
        # wie in der separaten Kabellängen-Ansicht, hier zusätzlich direkt im
        # grafischen Prinzipschema sichtbar statt nur in einer separaten Liste).
        cable_validations = {
            v.line_id: v for v in CableLengthService().validate_project(self._project)
        }

        col_x = MARGIN
        area_cols: list[dict] = []   # {"area": Area, "x": float, "boxes": [_Box]}

        # ── Berechnung der Spaltenbreiten ──
        for area in areas:
            boxes: list[_Box] = []
            y = MARGIN

            # Bereichskoppler (nur bei >1 Bereich)
            if multi_area:
                boxes.append(_Box(col_x, y, BOX_W, BOX_H_NODE,
                                  "Bereichskoppler",
                                  f"{area.coupler_address}",
                                  _C_COUPLER))
                y += BOX_H_NODE + GAP_ROW

                if area.backbone_power_supply is not None:
                    sv = area.backbone_power_supply
                    label = sv.product_name or sv.product or "SV Bereichslinie"
                    sub = f"{area.area_number}.0.-"
                    if sv.manufacturer:
                        sub += f"  {sv.manufacturer}"
                    boxes.append(_Box(col_x, y, BOX_W, BOX_H_NODE,
                                      label, sub, _C_POWER))
                    y += BOX_H_NODE + GAP_ROW

            # Linien
            for line in area.lines:
                actors  = sum(1 for d in line.devices if d.device_type == "actor")
                sensors = sum(1 for d in line.devices if d.device_type == "sensor")
                others  = sum(1 for d in line.devices
                               if d.device_type not in ("actor", "sensor",
                                                         "coupler", "power_supply"))
                lk_addr = line.coupler_address or f"{area.area_number}.{line.line_number}.0"
                sv_addr = f"{area.area_number}.{line.line_number}.-"
                sub_parts = [f"LK {lk_addr}", f"SV {sv_addr}"]
                if actors:
                    sub_parts.append(f"▶ {actors} Aktor(en)")
                if sensors:
                    sub_parts.append(f"⏺ {sensors} Sensor(en)")
                if others:
                    sub_parts.append(f"◆ {others} Sonstige")
                sub = "\n".join(sub_parts)
                line_name = f"{lk_addr}  {line.name}" if line.name else lk_addr

                line_color = _C_LINE
                line_tooltip = line_name
                validation = cable_validations.get(line.id)
                if validation and validation.status != "OK":
                    line_color = (
                        _C_LINE_ERROR if validation.status == "Fehler" else _C_LINE_WARN
                    )
                    line_tooltip = line_name + "\n\n⚠ " + "\n⚠ ".join(validation.messages)
                    sub_parts.append(f"⚠ Leitungslänge: {validation.status}")
                    sub = "\n".join(sub_parts)

                boxes.append(_Box(col_x, y, BOX_W, BOX_H_LINE,
                                  line_name, sub, line_color, tooltip=line_tooltip))
                y += BOX_H_LINE + GAP_ROW

            area_cols.append({"area": area, "x": col_x, "boxes": boxes,
                              "col_h": y})
            col_x += BOX_W + GAP_COL

        # ── Backbone-Linie oben (bei >1 Bereich) ──
        if multi_area:
            x0 = MARGIN + BOX_W / 2
            x1 = col_x - GAP_COL - BOX_W / 2
            backbone_y = MARGIN - 20
            self._draw_wire(x0, backbone_y, x1, backbone_y, thick=True,
                            color=_C_BACKBONE)
            self._add_label_item(
                (x0 + x1) / 2 - 60, backbone_y - 16,
                "KNX Backbone", bold=True, color=_C_BACKBONE)

        # ── Jede Spalte zeichnen ──
        for col in area_cols:
            area = col["area"]
            boxes = col["boxes"]
            x = col["x"]

            # Bereichs-Header
            area_label = f"Bereich {area.area_number}"
            if area.name:
                area_label += f": {area.name}"
            hdr_y = MARGIN - BOX_H_AREA - 10
            self._draw_box(_Box(x, hdr_y, BOX_W, BOX_H_AREA,
                                area_label, "", _C_AREA))

            # Verbindung Backbone → BK (bei multi_area)
            if multi_area:
                self._draw_wire(x + BOX_W / 2, MARGIN - 20,
                                x + BOX_W / 2, MARGIN - 2)

            # Boxes + vertikale Verbindungslinien
            prev_cx = x + BOX_W / 2
            prev_bottom = hdr_y + BOX_H_AREA
            for box in boxes:
                self._draw_box(box)
                self._draw_wire(prev_cx, prev_bottom, box.cx, box.top)
                prev_cx = box.cx
                prev_bottom = box.bottom

        # Statistik
        total_areas = len(areas)
        total_lines = sum(len(a.lines) for a in areas)
        total_devices = sum(len(l.devices) for a in areas for l in a.lines)
        self._info.setText(
            f"{total_areas} Bereich(e)  |  {total_lines} Linie(n)  |  "
            f"{total_devices} Gerät(e) in der Topologie"
        )

    def _draw_box(self, box: _Box):
        rect = QGraphicsRectItem(box.x, box.y, box.w, box.h)
        rect.setBrush(QBrush(box.color))
        rect.setPen(QPen(box.color.darker(130), 1))
        rect.setToolTip(box.tooltip)
        self._scene.addItem(rect)

        # Titelzeile
        title = QGraphicsTextItem(box.label)
        font = QFont("Segoe UI", 8, QFont.Bold)
        title.setFont(font)
        title.setDefaultTextColor(box.text_color)
        title.setPos(box.x + 6, box.y + 4)
        title.setTextWidth(box.w - 12)
        self._scene.addItem(title)

        # Unterzeilen
        if box.sub:
            sub = QGraphicsTextItem(box.sub)
            sfont = QFont("Segoe UI", 7)
            sub.setFont(sfont)
            sub.setDefaultTextColor(box.text_color.lighter(160)
                                    if box.text_color == QColor("white")
                                    else box.text_color.lighter(120))
            title_h = 18
            sub.setPos(box.x + 6, box.y + title_h)
            sub.setTextWidth(box.w - 12)
            self._scene.addItem(sub)

    def _draw_wire(self, x1: float, y1: float, x2: float, y2: float,
                   thick: bool = False, color: QColor = _C_LINE_WIRE):
        pen = QPen(color, 2 if thick else 1.5, Qt.SolidLine)
        pen.setCapStyle(Qt.RoundCap)
        # Orthogonale Verbindung (vertikal → horizontal → vertikal)
        if abs(x1 - x2) < 2:
            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(pen)
            self._scene.addItem(line)
        else:
            mid_y = (y1 + y2) / 2
            for pts in [(x1, y1, x1, mid_y), (x1, mid_y, x2, mid_y),
                        (x2, mid_y, x2, y2)]:
                seg = QGraphicsLineItem(*pts)
                seg.setPen(pen)
                self._scene.addItem(seg)

    def _add_label_item(self, x: float, y: float, text: str,
                        bold: bool = False, color: QColor = QColor("#333")):
        item = QGraphicsTextItem(text)
        font = QFont("Segoe UI", 8, QFont.Bold if bold else QFont.Normal)
        item.setFont(font)
        item.setDefaultTextColor(color)
        item.setPos(x, y)
        self._scene.addItem(item)

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_png(self):
        if not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Topologie-Diagramm exportieren", "Topologie.png",
            "PNG-Bilder (*.png);;Alle Dateien (*.*)",
        )
        if not path:
            return
        rect = self._scene.sceneRect().adjusted(-10, -10, 10, 10)
        pix = QPixmap(int(rect.width()), int(rect.height()))
        pix.fill(QColor("white"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter, source=rect)
        painter.end()
        pix.save(path, "PNG")
        QMessageBox.information(self, "Export", f"Diagramm gespeichert:\n{path}")

    def _export_pdf(self):
        if not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Topologie-Diagramm als PDF exportieren", "Topologie.pdf",
            "PDF-Dokumente (*.pdf);;Alle Dateien (*.*)",
        )
        if not path:
            return
        try:
            import fitz
        except ImportError:
            QMessageBox.warning(
                self, "PyMuPDF fehlt",
                "PDF-Export benötigt PyMuPDF.\n"
                "Installation: pip install pymupdf\n\n"
                "Alternativ: PNG-Export verwenden.",
            )
            return

        # Erst als PNG rendern, dann in PDF einbetten
        rect = self._scene.sceneRect().adjusted(-10, -10, 10, 10)
        scale = 2.0   # Höhere Auflösung
        pix = QPixmap(int(rect.width() * scale), int(rect.height() * scale))
        pix.fill(QColor("white"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(scale, scale)
        self._scene.render(painter, source=rect)
        painter.end()

        # PNG in temporäre Datei schreiben
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        pix.save(tmp.name, "PNG")

        try:
            doc = fitz.open()
            # A4 quer wenn das Diagramm breiter als hoch ist
            w, h = pix.width() / scale, pix.height() / scale
            page_w = max(595, w + 80)
            page_h = max(420, h + 100)
            page = doc.new_page(width=page_w, height=page_h)

            # Titel
            page.insert_text(fitz.Point(30, 30),
                             f"KNX-Topologie: {self._project.name}",
                             fontsize=14, fontname="helv-bo")
            page.insert_text(fitz.Point(30, 48),
                             f"Bereiche: {len(self._project.topology.areas)}  |  "
                             f"Linien: {sum(len(a.lines) for a in self._project.topology.areas)}",
                             fontsize=9, fontname="helv")

            # Diagramm-Bild
            img_rect = fitz.Rect(30, 60, 30 + w, 60 + h)
            page.insert_image(img_rect, filename=tmp.name)

            doc.save(path)
            doc.close()
            QMessageBox.information(self, "Export", f"PDF gespeichert:\n{path}")
        finally:
            os.unlink(tmp.name)
