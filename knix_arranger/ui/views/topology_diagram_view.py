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
from ...services.topology_diagram import build_topology_diagram
from ..styles import COLOR_WARNING, COLOR_ERROR
from .. import license_gate  # NFA-066: Exporte im Lesemodus gesperrt

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
GAP_COL     = 50   # Abstand zwischen Bereichen
GAP_ROW     = 18   # Abstand zwischen Zeilen innerhalb eines Bereichs
MARGIN      = 30
BUS_INDENT  = 18   # Abzweige von der Hauptlinie (Busleitung links)
POWER_BAND_H = 18  # grünes SV-Band unten in einer Linie


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
            f"<span style='color:{_C_LINE_ERROR.name()};'>&#9632;</span> Leitungslänge überschritten&nbsp;&nbsp;"
            f"<span style='color:{_C_BACKBONE.name()};'>&#9632;</span> Backbone"
        )
        legend.setStyleSheet("font-size: 12px; color: #666;")
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
        """Bereichslinie oben mit ihrer SV, je Bereich eine Spalte: Kopf,
        Bereichskoppler, darunter die Hauptlinie als senkrechte Busleitung,
        an der die SV der Hauptlinie und die Linien abzweigen; die SV einer
        Linie als grünes Band in der Linie (T-06). Knoten aus demselben
        Service wie der Topologie-Bericht (FA-904)."""
        diagram = build_topology_diagram(self._project, include_empty_lines=True)
        backbone = diagram["backbone"]
        node_colors = {"coupler": _C_COUPLER, "power": _C_POWER}
        status_colors = {"Warnung": _C_LINE_WARN, "Fehler": _C_LINE_ERROR}
        col_w = BOX_W + BUS_INDENT

        # ── Bereichslinie mit ihrer SV ──
        y_top = MARGIN
        header_y = y_top
        backbone_y = None
        centers = [MARGIN + i * (col_w + GAP_COL) + col_w / 2
                   for i in range(len(diagram["areas"]))]
        if backbone:
            sv = diagram["backbone_power"]
            if sv is not None:
                sv_box = _Box(MARGIN, y_top, BOX_W, self._node_height(sv), sv["title"],
                              "\n".join(sv["lines"]), _C_POWER)
                self._draw_box(sv_box)
                backbone_y = sv_box.bottom + 16
                self._draw_wire(sv_box.cx, sv_box.bottom, sv_box.cx, backbone_y)
                label_x = sv_box.x + sv_box.w + 12
                centers.append(sv_box.cx)
            else:
                backbone_y = y_top + 20
                label_x = MARGIN
            self._add_label_item(label_x, backbone_y - 20, backbone, bold=True,
                                 color=_C_BACKBONE)
            self._draw_wire(min(centers), backbone_y, max(centers), backbone_y,
                            thick=True, color=_C_BACKBONE)
            header_y = backbone_y + 20

        # ── Bereiche ──
        for i, area in enumerate(diagram["areas"]):
            x = MARGIN + i * (col_w + GAP_COL)
            header = _Box(x, header_y, col_w, BOX_H_AREA, area["title"], "", _C_AREA)
            self._draw_box(header)
            if backbone_y is not None:
                self._draw_wire(header.cx, backbone_y, header.cx, header.top)
            prev = header
            nodes = list(area["nodes"])
            # Bereichskoppler zwischen Bereichs- und Hauptlinie
            if nodes and nodes[0]["kind"] == "coupler":
                node = nodes.pop(0)
                bk = _Box(x, prev.bottom + GAP_ROW, col_w, self._node_height(node),
                          node["title"], "\n".join(node["lines"]), _C_COUPLER)
                self._draw_box(bk)
                self._draw_wire(prev.cx, prev.bottom, bk.cx, bk.top)
                prev = bk

            if area["main_line"]:
                # Hauptlinie: Busleitung links, Abzweige nach rechts
                bus_x = x + BUS_INDENT / 2
                bus_top = prev.bottom
                if prev is not header:
                    self._draw_wire(prev.x + BUS_INDENT / 2, prev.bottom, bus_x, bus_top)
                self._add_label_item(bus_x + 4, bus_top + 1, area["main_line"],
                                     color=_C_BACKBONE)
                y = bus_top + GAP_ROW + 14
                last_y = bus_top
                for node in nodes:
                    box = self._node_box(node, x + BUS_INDENT, y, node_colors, status_colors)
                    self._draw_node(box, node)
                    stub_y = box.y + min(box.h / 2, 17)
                    self._draw_wire(bus_x, stub_y, box.x, stub_y)
                    last_y = stub_y
                    y = box.bottom + GAP_ROW
                self._draw_wire(bus_x, bus_top, bus_x, last_y, thick=True,
                                color=_C_BACKBONE)
            else:
                # Ohne Hauptlinie (eine Linie): direkt unter dem Bereich
                for node in nodes:
                    box = self._node_box(node, x + BUS_INDENT, prev.bottom + GAP_ROW,
                                         node_colors, status_colors)
                    self._draw_node(box, node)
                    self._draw_wire(prev.cx, prev.bottom, box.cx, box.top)
                    prev = box

        # Statistik
        areas = self._project.topology.areas
        total_areas = len(areas)
        total_lines = sum(len(a.lines) for a in areas)
        total_devices = sum(len(l.devices) for a in areas for l in a.lines)
        self._info.setText(
            f"{total_areas} Bereich(e)  |  {total_lines} Linie(n)  |  "
            f"{total_devices} Gerät(e) in der Topologie"
        )

    @staticmethod
    def _node_height(node: dict) -> float:
        if node["kind"] == "line":
            h = max(BOX_H_NODE, 22 + 12 * len(node["lines"]))
            return h + (POWER_BAND_H if node.get("power") else 0)
        return BOX_H_NODE if len(node["lines"]) <= 1 else BOX_H_NODE + 12

    def _node_box(self, node: dict, x: float, y: float, node_colors: dict,
                  status_colors: dict) -> _Box:
        if node["kind"] == "line":
            color = status_colors.get(node["status"], _C_LINE)
            tooltip = node["title"]
            if node.get("power"):
                tooltip += "\nSpannungsversorgung " + ", ".join(node["power"])
            if node["messages"]:
                tooltip += "\n\n⚠ " + "\n⚠ ".join(node["messages"])
        else:
            color, tooltip = node_colors[node["kind"]], ""
        return _Box(x, y, BOX_W, self._node_height(node), node["title"],
                    "\n".join(node["lines"]), color, tooltip=tooltip)

    def _draw_node(self, box: _Box, node: dict) -> None:
        """Knoten zeichnen; die SV einer Linie als grünes Band unten in der
        Linie -- sie speist diese Linie."""
        self._draw_box(box)
        if node["kind"] == "line" and node.get("power"):
            band = _Box(box.x + 3, box.bottom - POWER_BAND_H, box.w - 6, POWER_BAND_H - 3,
                        "SV " + ", ".join(node["power"]), "", _C_POWER,
                        tooltip="Spannungsversorgung dieser Linie")
            rect = QGraphicsRectItem(band.x, band.y, band.w, band.h)
            rect.setBrush(QBrush(_C_POWER))
            rect.setPen(QPen(_C_POWER.darker(130), 1))
            rect.setToolTip(band.tooltip)
            self._scene.addItem(rect)
            text = QGraphicsTextItem(band.label)
            text.setFont(QFont("Segoe UI", 7, QFont.Bold))
            text.setDefaultTextColor(QColor("white"))
            text.setPos(band.x + 3, band.y - 2)
            self._scene.addItem(text)

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
        path, _ = license_gate.get_save_file_name(
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
        path, _ = license_gate.get_save_file_name(
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
            from ...utils.fonts import register_fonts, font_name, finalize_pdf
            register_fonts(page)

            # Titel
            page.insert_text(fitz.Point(30, 30),
                             f"KNX-Topologie: {self._project.name}",
                             fontsize=14, fontname=font_name(bold=True))
            page.insert_text(fitz.Point(30, 48),
                             f"Bereiche: {len(self._project.topology.areas)}  |  "
                             f"Linien: {sum(len(a.lines) for a in self._project.topology.areas)}",
                             fontsize=9, fontname=font_name())

            # Diagramm-Bild
            img_rect = fitz.Rect(30, 60, 30 + w, 60 + h)
            page.insert_image(img_rect, filename=tmp.name)

            finalize_pdf(doc)
            doc.save(path)
            doc.close()
            QMessageBox.information(self, "Export", f"PDF gespeichert:\n{path}")
        finally:
            os.unlink(tmp.name)
