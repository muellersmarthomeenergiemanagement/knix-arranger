"""
Bestandteile und Revisionsstände des Revisionspakets (FA-2102, FA-2105,
FA-2106) sowie die Produktdatenblätter als Anhang (FA-1204).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import os
import re
import shutil

# Bestandteile in der Reihenfolge des Pakets: (Schlüssel, Bezeichnung).
# Bestandteile ohne Daten (z.B. Szenen, DALI) entfallen automatisch.
REVISION_PARTS: list[tuple[str, str]] = [
    ("zusammenfassung", "Projektzusammenfassung"),
    ("ga_uebersicht", "Gruppenadress-Übersicht"),
    ("topologie", "Topologie-Bericht"),
    ("bedienelemente", "Bedienelemente und Sensoren"),
    ("aktoren", "Aktoren und Gateways"),
    ("raeume", "Räume nach Gewerken"),
    ("belegungsplan", "Belegungsplan (Verknüpfungsmatrix)"),
    ("szenen", "Szenenreport"),
    ("validierung", "Validierungsbericht Gruppenadressen"),
    ("checklisten", "Inbetriebnahme-Checklisten"),
    ("abnahme", "Abnahmeprotokoll"),
    ("anleitung", "Bedienungsanleitung"),
    ("materialliste", "Materialliste"),
    ("ga_csv", "GA-Export (CSV)"),
    ("dali", "DALI-Gerätekonfiguration"),
    ("zeitprogramme", "Zeitsteuerungsplan"),
    ("secure", "KNX Secure Archivbericht"),
    ("datenblaetter", "Produktdatenblätter"),
    ("offerte", "Kundenofferte (akzeptiert)"),
]
ALL_PARTS = frozenset(key for key, _ in REVISION_PARTS)
PART_LABELS = dict(REVISION_PARTS)

DATASHEET_FOLDER = "Datenblaetter"


def next_revision_number(project) -> str:
    """Nächste Revisionsbezeichnung: A, B, … Z, dann AA, AB, …"""
    used = {r.number for r in project.revisions}
    n = 0
    while True:
        label, i = "", n
        while True:
            label = chr(ord("A") + i % 26) + label
            i = i // 26 - 1
            if i < 0:
                break
        if label not in used:
            return label
        n += 1


def revision_folder_name(number: str) -> str:
    """Unterordner einer Revision, z.B. "Rev_A"."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", number.strip()) or "0"
    return f"Rev_{safe}"


def accepted_quotes(project) -> list:
    return [q for q in project.customer_quotes if q.status == "Akzeptiert"]


@dataclass
class Datasheet:
    path: str                      # lokaler Pfad oder URL
    products: list[str] = field(default_factory=list)

    @property
    def is_url(self) -> bool:
        return self.path.startswith(("http://", "https://"))


def collect_datasheets(project) -> list[Datasheet]:
    """Alle hinterlegten Datenblätter (Geräte, Bedienelemente, Gewerke),
    je Datei einmal, mit den Produkten, zu denen sie gehören."""
    by_path: dict[str, Datasheet] = {}

    def add(paths, product: str) -> None:
        for path in paths:
            if not path:
                continue
            ds = by_path.setdefault(path, Datasheet(path))
            if product and product not in ds.products:
                ds.products.append(product)

    for area in project.topology.areas:
        devices = [d for line in area.lines for d in line.devices]
        if area.backbone_power_supply is not None:
            devices.append(area.backbone_power_supply)
        for d in devices:
            add(d.datasheets, d.product_name or d.product or d.order_number)
    for room in project.all_rooms:
        for be in room.bedienelemente:
            if not be.suppressed:
                add(be.datasheets, be.product_name or be.element_type)
        for ga in room.gewerk_assignments:
            add(ga.datasheets, f"Gewerk {ga.gewerk_code}")
    return list(by_path.values())


def copy_datasheets(datasheets: list[Datasheet], output_dir: str, base_dir: str = ""
                    ) -> tuple[list[tuple[Datasheet, str]], list[Datasheet]]:
    """Kopiert lokale Datenblätter in den Unterordner "Datenblaetter".
    Relative Pfade gelten ab `base_dir` (Projektordner).
    Gibt (kopiert mit Zieldatei, nicht gefunden) zurück; URLs bleiben Links."""
    copied: list[tuple[Datasheet, str]] = []
    missing: list[Datasheet] = []
    target_dir = os.path.join(output_dir, DATASHEET_FOLDER)
    used_names: set[str] = set()
    for ds in datasheets:
        if ds.is_url:
            continue
        source = ds.path if os.path.isabs(ds.path) or not base_dir             else os.path.join(base_dir, ds.path)
        if not os.path.isfile(source):
            missing.append(ds)
            continue
        os.makedirs(target_dir, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(source))
        name, n = f"{stem}{ext}", 2
        while name.lower() in used_names:
            name, n = f"{stem}_{n}{ext}", n + 1
        used_names.add(name.lower())
        target = os.path.join(target_dir, name)
        shutil.copy2(source, target)
        copied.append((ds, target))
    return copied, missing
