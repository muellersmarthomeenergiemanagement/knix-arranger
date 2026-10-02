"""
Steigschema (FA-905a): Gebäudeschnitt mit dem Verlauf der KNX-Linien.

Stockwerke liegen übereinander (Dach oben, Keller unten), Nebengebäude
daneben auf gleicher Höhe. Je Stockwerk die Räume, links die Verteiler
(Schritt 4) und die Steigzone, in der jede Linie als eigene farbige Spur
vom Verteiler mit Linienkoppler und Aktoren zu ihren Stockwerken läuft.
Auf jedem Stockwerk zweigt die Linie unter den Räumen ab; ein Punkt
markiert jeden Raum mit Teilnehmern. Linien in ein anderes Gebäude
laufen als Erdleitung unter den Gebäuden.

Ergebnis ist ein neutrales Zeichnungsmodell in Punkten (Rechtecke,
Linienzüge, Punkte, Texte). Die App (Qt) und der Topologie-Bericht (PDF)
zeichnen es mit eigenen, schlanken Renderern -- beide zeigen so dasselbe.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from .report_sorting import room_order
from .verteiler_service import VerteilerPlacement, verteiler_label

# Gut unterscheidbare Linienfarben (auf Weiss, auch im Ausdruck)
LINE_COLORS = [
    "#1565C0", "#C62828", "#2E7D32", "#6A1B9A", "#EF6C00",
    "#00838F", "#AD1457", "#4E342E", "#558B2F", "#283593",
]
INK = "#263238"
MUTED = "#78909C"
FRAME = "#B0BEC5"
FLOOR_FILL = "#FFFFFF"
BUILDING_FILL = "#ECEFF1"
ROOM_FILL = "#F5F7F8"
VT_FILL = "#37474F"
GROUND = "#8D6E63"

# Masse in Punkten
TITLE_H = 18
FLOOR_LABEL_W = 52
VT_W = 62
VT_H = 17
LANE_PAD = 6
LANE_W = 6
ROOM_W = 46
ROOM_H = 26
ROOM_GAP = 4
ZONE_GAP = 10
ZONE_LABEL_H = 9
ROW_PAD = 5
BAND_GAP = 6
BRANCH_STEP = 4
BUILDING_GAP = 28
TRENCH_GAP = 12
TRENCH_STEP = 5
LEGEND_COL_W = 250
LEGEND_ROW_H = 13


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float
    fill: str = ""
    stroke: str = ""
    width: float = 0.6
    ref: str = ""


@dataclass
class Path:
    points: list[tuple[float, float]]
    color: str
    width: float = 1.6
    dash: bool = False
    ref: str = ""


@dataclass
class Dot:
    x: float
    y: float
    r: float
    fill: str
    ref: str = ""


@dataclass
class Label:
    x: float
    y: float            # Grundlinie
    text: str
    size: float = 7.0
    bold: bool = False
    color: str = INK
    align: str = "left"  # "left" | "center" | "right"
    ref: str = ""


@dataclass
class LegendEntry:
    ref: str
    color: str
    title: str
    detail: str


@dataclass
class RiserDiagram:
    width: float = 0.0
    height: float = 0.0
    shapes: list = field(default_factory=list)   # in Zeichenreihenfolge
    legend: list[LegendEntry] = field(default_factory=list)
    tooltips: dict[str, str] = field(default_factory=dict)  # ref -> Text

    @property
    def is_empty(self) -> bool:
        return not self.shapes


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Geschätzte Textbreite (Inter), für Kürzen und Legendenspalten."""
    return len(text) * size * (0.56 if bold else 0.52)


def fit_text(text: str, avail: float, size: float, bold: bool = False) -> str:
    """Kürzt Text mit "…" auf die verfügbare Breite."""
    if text_width(text, size, bold) <= avail:
        return text
    while text and text_width(text + "…", size, bold) > avail:
        text = text[:-1]
    return (text.rstrip() + "…") if text else ""


def blend(color: str, amount: float) -> str:
    """Mischt eine Farbe mit Weiss (amount 0 = Farbe, 1 = Weiss)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    mix = [round(c + (255 - c) * amount) for c in (r, g, b)]
    return "#" + "".join(f"{c:02X}" for c in mix)


_OG_RE = re.compile(r"^(\d+)\s*\.?\s*OG$|^OG\s*(\d+)$")
_UG_RE = re.compile(r"^(\d+)\s*\.?\s*(UG|KG)$|^(UG|KG)\s*(\d+)$")


def floor_rank(code: str) -> float | None:
    """Höhenlage eines Stockwerks aus dem Kürzel (EG = 0, OG > 0, UG < 0)."""
    c = (code or "").strip().upper()
    if c in ("EG", "E", "PT"):
        return 0
    if c in ("OG", "O", "1OG"):
        return 1
    if c in ("DG", "D", "AT", "ATTIKA", "DA"):
        return 50
    if c in ("UG", "KG", "U", "K", "SS"):
        return -1
    m = _OG_RE.match(c)
    if m:
        return int(m.group(1) or m.group(2))
    m = _UG_RE.match(c)
    if m:
        return -int(m.group(1) or m.group(4))
    return None


def _floor_ranks(floors) -> dict[str, float]:
    """floor.id -> Höhenlage; unbekannte Kürzel zwischen den Nachbarn, je
    nach Reihenfolge der Liste (oben → unten oder unten → oben)."""
    known = [(i, floor_rank(f.short_code)) for i, f in enumerate(floors)]
    pairs = [(i, r) for i, r in known if r is not None]
    descending = len(pairs) >= 2 and pairs[0][1] > pairs[-1][1]
    ranks: dict[str, float] = {}
    last = None
    for i, floor in enumerate(floors):
        r = known[i][1]
        if r is None:
            r = (last if last is not None else 0) + (-0.5 if descending else 0.5)
        ranks[floor.id] = r
        last = r
    return ranks


def _line_key(line) -> str:
    return f"line:{line.id}"


def line_short(line) -> str:
    """ "1.1" aus der Koppleradresse "1.1.0"."""
    parts = (line.coupler_address or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else str(line.line_number)


def build_riser_diagram(project, highlight: str = "") -> RiserDiagram:
    """Berechnet das Steigschema. highlight = ref einer Linie ("line:<id>"),
    die übrigen Linien werden dann blass gezeichnet."""
    diagram = RiserDiagram()
    areal = project.areal
    buildings = [b for b in areal.buildings if b.all_floors]
    if not buildings:
        return diagram

    # ── Linien, ihre Räume und Verteiler ─────────────────────────────────
    lines = [l for a in sorted(project.topology.areas, key=lambda a: a.area_number)
             for l in sorted(a.lines, key=lambda l: l.line_number)]
    devices_by_room: dict[str, int] = {}
    line_rooms: dict[str, set[str]] = {}
    for line in lines:
        rooms = set(line.assigned_room_ids)
        for d in line.devices:
            if d.room_id:
                rooms.add(d.room_id)
                devices_by_room[d.room_id] = devices_by_room.get(d.room_id, 0) + 1
        line_rooms[line.id] = rooms
    lines = [l for l in lines if line_rooms[l.id] or l.devices]
    # Angeschlossene Räume: mit Teilnehmern; solange die Linie noch keine
    # Teilnehmer mit Raum hat (frühe Planung), alle Räume ihrer Zone
    connected: dict[str, set[str]] = {}
    for line in lines:
        with_devices = {d.room_id for d in line.devices if d.room_id}
        connected[line.id] = with_devices or line_rooms[line.id]
    color_of = {l.id: LINE_COLORS[i % len(LINE_COLORS)] for i, l in enumerate(lines)}
    line_of_room = {rid: l for l in lines for rid in line_rooms[l.id]}

    def col(line_id: str, base: str | None = None) -> str:
        c = base or color_of[line_id]
        if highlight and highlight != f"line:{line_id}":
            return blend(c, 0.78)
        return c

    placement = VerteilerPlacement(project.all_rooms)
    floor_of_room: dict[str, tuple] = {}     # room.id -> (building, floor)
    for b in buildings:
        for f in b.all_floors:
            for apt in f.apartments:
                for r in apt.rooms:
                    floor_of_room[r.id] = (b, f)
    line_vt = {l.id: placement.for_line(l) for l in lines}

    # ── Zeilen (Stockwerke) über alle Gebäude auf gleicher Höhe ──────────
    rank_of: dict[str, float] = {}
    for b in buildings:
        rank_of.update(_floor_ranks(b.all_floors))
    row_ranks = sorted({rank_of[f.id] for b in buildings for f in b.all_floors}, reverse=True)
    floors_in_row = {r: [(b, f) for b in buildings for f in b.all_floors if rank_of[f.id] == r]
                     for r in row_ranks}

    order = room_order(areal)

    def floor_rooms(floor) -> list[tuple[str, list]]:
        """[(Zone, [Räume])] in Gebäude-Reihenfolge, ohne leere Pseudoräume."""
        groups = []
        for apt in floor.apartments:
            rooms = [r for r in apt.rooms if r.number or devices_by_room.get(r.id)]
            if rooms:
                groups.append((apt.name, sorted(rooms, key=lambda r: order.get(r.id, 0))))
        return groups

    def floor_lines(floor) -> list:
        ids = {line_of_room[r.id].id for _z, rs in floor_rooms(floor) for r in rs
               if r.id in line_of_room and r.id in connected[line_of_room[r.id].id]}
        return [l for l in lines if l.id in ids]

    def floor_vts(floor) -> list[tuple]:
        return [(vt, r) for apt in floor.apartments for r in apt.rooms for vt in r.verteiler]

    row_h: dict[float, float] = {}
    for r in row_ranks:
        need = ROW_PAD + ZONE_LABEL_H + ROOM_H + BAND_GAP
        need += max([len(floor_lines(f)) for _b, f in floors_in_row[r]] + [1]) * BRANCH_STEP + ROW_PAD
        n_vt = max([len(floor_vts(f)) for _b, f in floors_in_row[r]] + [0])
        need = max(need, ROW_PAD * 2 + n_vt * (VT_H + 3))
        row_h[r] = need
    row_y: dict[float, float] = {}
    y = TITLE_H
    for r in row_ranks:
        row_y[r] = y
        y += row_h[r]
    rows_bottom = y

    # ── Spalten je Gebäude ───────────────────────────────────────────────
    vt_building = {l.id: floor_of_room.get(line_vt[l.id][1].id, (None,))[0]
                   if line_vt[l.id] else None for l in lines}

    def building_lines(b) -> list:
        ids = {l.id for l in lines if vt_building[l.id] is b}
        ids |= {l.id for l in lines
                if any(floor_of_room.get(rid, (None,))[0] is b for rid in line_rooms[l.id])}
        return [l for l in lines if l.id in ids]

    def rooms_width(floor) -> float:
        groups = floor_rooms(floor)
        if not groups:
            return 0.0
        n = sum(len(rs) for _z, rs in groups)
        return n * ROOM_W + (n - len(groups)) * ROOM_GAP + (len(groups) - 1) * ZONE_GAP

    layout = []      # (building, x0, lanes{line.id: x}, rooms_x0, width)
    x = 0.0
    for b in buildings:
        b_lines = building_lines(b)
        has_vt = any(floor_vts(f) for f in b.all_floors)
        lanes_x0 = x + FLOOR_LABEL_W + (VT_W if has_vt else 0) + LANE_PAD
        lanes = {l.id: lanes_x0 + i * LANE_W + LANE_W / 2 for i, l in enumerate(b_lines)}
        rooms_x0 = lanes_x0 + max(1, len(b_lines)) * LANE_W + LANE_PAD
        width = rooms_x0 - x + max([rooms_width(f) for f in b.all_floors] + [ROOM_W]) + 6
        layout.append((b, x, lanes, rooms_x0, width))
        x += width + BUILDING_GAP
    total_w = x - BUILDING_GAP

    shapes: list = []
    room_center: dict[str, tuple[float, float]] = {}   # room.id -> (x, Unterkante)
    branch_y: dict[tuple[str, str], float] = {}         # (floor.id, line.id) -> y
    vt_anchor: dict[str, tuple[float, float]] = {}      # vt.id -> (rechte Kante, Mitte)

    # ── Gebäude, Stockwerke, Räume, Verteiler ────────────────────────────
    for b, bx, lanes, rooms_x0, bw in layout:
        b_rows = [r for r in row_ranks if any(bb is b for bb, _f in floors_in_row[r])]
        top, bottom = row_y[b_rows[0]], row_y[b_rows[-1]] + row_h[b_rows[-1]]
        shapes.append(Rect(bx, top, bw, bottom - top, fill=BUILDING_FILL, stroke=FRAME, width=0.8))
        shapes.append(Label(bx, top - 5, fit_text(b.name, bw, 9, True), 9, True))
        for r in b_rows:
            for bb, floor in floors_in_row[r]:
                if bb is not b:
                    continue
                fy, fh = row_y[r], row_h[r]
                shapes.append(Rect(bx, fy, bw, fh, fill=FLOOR_FILL, stroke=FRAME, width=0.5))
                shapes.append(Label(bx + 5, fy + 13, floor.short_code or "?", 9, True))
                shapes.append(Label(bx + 5, fy + 22, fit_text(floor.name, FLOOR_LABEL_W - 7, 5.5),
                                    5.5, color=MUTED))
                # Verteiler
                vy = fy + ROW_PAD
                for vt, vroom in floor_vts(floor):
                    vx = bx + FLOOR_LABEL_W
                    ref = f"vt:{vt.id}"
                    shapes.append(Rect(vx, vy, VT_W - 4, VT_H, fill=VT_FILL, ref=ref))
                    shapes.append(Label(vx + 3, vy + 7.5, vt.verteiler_type or "VT", 6.5, True,
                                        "#FFFFFF", ref=ref))
                    shapes.append(Label(vx + 3, vy + 14, fit_text(vt.name or vroom.name, VT_W - 10, 5),
                                        5, color="#CFD8DC", ref=ref))
                    vt_anchor[vt.id] = (vx + VT_W - 4, vy + VT_H / 2)
                    n_act = len(vt.actor_assignments)
                    diagram.tooltips[ref] = (
                        f"{verteiler_label(vt, vroom)} in {vroom.number} {vroom.name}".strip()
                        + (f"\n{n_act} Aktoren" if n_act else ""))
                    vy += VT_H + 3
                # Räume, nach Zonen gruppiert
                rx = rooms_x0
                ry = fy + ROW_PAD + ZONE_LABEL_H
                f_lines = floor_lines(floor)
                for zone, rooms in floor_rooms(floor):
                    group_w = len(rooms) * ROOM_W + (len(rooms) - 1) * ROOM_GAP
                    shapes.append(Label(rx, ry - 2.5, fit_text(zone, group_w, 5.5), 5.5, color=MUTED))
                    for room in rooms:
                        line = line_of_room.get(room.id)
                        ref = f"room:{room.id}"
                        if line is not None:
                            fill, stroke = col(line.id, blend(color_of[line.id], 0.88)), col(line.id)
                        else:
                            fill, stroke = ROOM_FILL, FRAME
                        shapes.append(Rect(rx, ry, ROOM_W, ROOM_H, fill=fill, stroke=stroke,
                                           width=0.7, ref=ref))
                        shapes.append(Label(rx + 3, ry + 8.5, fit_text(room.number, ROOM_W - 6, 6.5, True),
                                            6.5, True, ref=ref))
                        shapes.append(Label(rx + 3, ry + 16, fit_text(room.name, ROOM_W - 6, 5.5),
                                            5.5, color="#455A64", ref=ref))
                        n_dev = devices_by_room.get(room.id, 0)
                        if n_dev:
                            shapes.append(Label(rx + ROOM_W - 3, ry + ROOM_H - 3, str(n_dev), 5.5,
                                                color=MUTED, align="right", ref=ref))
                        diagram.tooltips[ref] = (
                            f"{room.number} {room.name}".strip()
                            + (f"\nLinie {line_short(line)} {line.name}" if line else "")
                            + (f"\n{n_dev} Teilnehmer" if n_dev else ""))
                        room_center[room.id] = (rx + ROOM_W / 2, ry + ROOM_H)
                        rx += ROOM_W + ROOM_GAP
                    rx += ZONE_GAP - ROOM_GAP
                band = ry + ROOM_H + BAND_GAP
                for i, line in enumerate(f_lines):
                    branch_y[(floor.id, line.id)] = band + i * BRANCH_STEP + BRANCH_STEP / 2

    # ── Linien: Steigzone, Abzweige, Erdleitungen ────────────────────────
    lane_of = {(b.id, lid): lx for b, _bx, lanes, _r, _w in layout for lid, lx in lanes.items()}
    # Mehrere Linien aus einem Verteiler: Abgänge übereinander staffeln
    by_vt: dict[str, list[str]] = {}
    for line in lines:
        if line_vt[line.id]:
            by_vt.setdefault(line_vt[line.id][0].id, []).append(line.id)

    def line_anchor(line):
        ref_ = line_vt[line.id]
        if not ref_ or ref_[0].id not in vt_anchor:
            return None
        ax, ay = vt_anchor[ref_[0].id]
        siblings = by_vt[ref_[0].id]
        step = min(3.0, (VT_H - 4) / max(1, len(siblings) - 1)) if len(siblings) > 1 else 0
        return ax, ay + (siblings.index(line.id) - (len(siblings) - 1) / 2) * step
    trench_i = 0
    line_paths, line_dots, line_labels = [], [], []
    for line in lines:
        c = col(line.id)
        ref = _line_key(line)
        vt_ref = line_vt[line.id]
        # Stockwerke mit Räumen der Linie, je Gebäude
        by_building: dict[str, list] = {}
        for b, _bx, _l, _r, _w in layout:
            for f in b.all_floors:
                if (f.id, line.id) in branch_y:
                    by_building.setdefault(b.id, []).append(f)
        home = vt_building[line.id]
        anchor = line_anchor(line)
        for b, bx, lanes, rooms_x0, bw in layout:
            if line.id not in lanes:
                continue
            lx = lanes[line.id]
            ys = [branch_y[(f.id, line.id)] for f in by_building.get(b.id, [])]
            if b is home and anchor:
                ys.append(anchor[1])
                # Verteiler → Steigzone, Linienkoppler als Quadrat
                line_paths.append(Path([anchor, (lx, anchor[1])], c, 1.6, ref=ref))
                line_dots.append(Rect(lx - 2.2, anchor[1] - 2.2, 4.4, 4.4, fill=c, ref=ref))
            entering = home is not None and b is not home
            if entering:
                ys.append(rows_bottom)
            if not ys:
                continue
            y_top, y_bot = min(ys), max(ys)
            if y_bot > y_top:
                line_paths.append(Path([(lx, y_top), (lx, y_bot)], c, 1.6, ref=ref))
            # Abzweige je Stockwerk mit Punkt je Raum
            for f in by_building.get(b.id, []):
                by = branch_y[(f.id, line.id)]
                points = [room_center[r.id] for _z, rs in floor_rooms(f) for r in rs
                          if r.id in connected[line.id] and r.id in room_center]
                if not points:
                    continue
                end_x = max(p[0] for p in points)
                line_paths.append(Path([(lx, by), (end_x, by)], c, 1.2, ref=ref))
                line_labels.append(Label(end_x + 4, by + 1.8, line_short(line), 5, True, c,
                                         ref=ref))
                for px, room_bottom in points:
                    line_paths.append(Path([(px, room_bottom), (px, by)], c, 0.6, ref=ref))
                    line_dots.append(Dot(px, by, 1.9, c, ref=ref))
        # Erdleitung vom Gebäude des Verteilers in die anderen Gebäude
        others = [b for b, *_ in layout if b is not home and b.id in by_building]
        if home is not None and others:
            ty = rows_bottom + TRENCH_GAP + trench_i * TRENCH_STEP
            trench_i += 1
            home_x = lane_of[(home.id, line.id)]
            xs = [home_x] + [lane_of[(b.id, line.id)] for b in others]
            line_paths.append(Path([(home_x, anchor[1] if anchor else rows_bottom), (home_x, ty)],
                                   c, 1.6, ref=ref))
            line_paths.append(Path([(min(xs), ty), (max(xs), ty)], c, 1.6, dash=True, ref=ref))
            for b in others:
                ox = lane_of[(b.id, line.id)]
                line_paths.append(Path([(ox, ty), (ox, rows_bottom)], c, 1.6, ref=ref))

    # Terrain (Unterkante EG) über alle Gebäude
    ground_rows = [r for r in row_ranks if r >= 0]
    has_below = any(r < 0 for r in row_ranks)
    if ground_rows and has_below:
        gy = row_y[ground_rows[-1]] + row_h[ground_rows[-1]]
        shapes.append(Path([(-8, gy), (total_w + 8, gy)], GROUND, 1.4))
        shapes.append(Label(-8, gy - 2.5, "Terrain", 5.5, color=GROUND))

    # Hervorgehobene Linie zuoberst zeichnen
    def z(item):
        return 1 if highlight and getattr(item, "ref", "") == highlight else 0
    shapes += sorted(line_paths, key=z) + sorted(line_dots, key=z) + sorted(line_labels, key=z)

    height = rows_bottom + (TRENCH_GAP + trench_i * TRENCH_STEP if trench_i else 0) + 14

    # ── Legende ──────────────────────────────────────────────────────────
    for line in lines:
        vt_ref = line_vt[line.id]
        n_dev = len(line.devices)
        parts = [f"{n_dev} Teilnehmer" if n_dev else "",
                 verteiler_label(*vt_ref) if vt_ref else "kein Verteiler",
                 f"Leitung {line.trunk_length:g} m" if line.trunk_length else ""]
        diagram.legend.append(LegendEntry(
            _line_key(line), color_of[line.id], f"{line_short(line)} {line.name}".strip(),
            " · ".join(p for p in parts if p)))
        diagram.tooltips[_line_key(line)] = (
            f"Linie {line_short(line)} {line.name}\n" + " · ".join(p for p in parts if p))
    per_row = max(1, int((total_w + 1) // LEGEND_COL_W))
    ly = height + 6
    for i, entry in enumerate(diagram.legend):
        lx = (i % per_row) * LEGEND_COL_W
        yy = ly + (i // per_row) * LEGEND_ROW_H
        shapes.append(Rect(lx, yy - 6, 12, 4, fill=col(entry.ref[5:]), ref=entry.ref))
        shapes.append(Label(lx + 16, yy - 2, fit_text(entry.title, 90, 6.5, True), 6.5, True,
                            ref=entry.ref))
        shapes.append(Label(lx + 110, yy - 2, fit_text(entry.detail, LEGEND_COL_W - 116, 6),
                            6, color="#455A64", ref=entry.ref))
    if diagram.legend:
        height = ly + ((len(diagram.legend) - 1) // per_row) * LEGEND_ROW_H + 6

    diagram.shapes = shapes
    diagram.width = max(total_w, min(len(diagram.legend), per_row) * LEGEND_COL_W)
    diagram.height = height
    return diagram

