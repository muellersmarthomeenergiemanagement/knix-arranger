"""
Fehlende Herstellerdateien (FA-3108f): Geräte aus «Teilnehmer suchen», deren
Applikation nicht im Produktkatalog steht. Ohne Qt.

- missing(project): je Hersteller und Applikation die Geräte, mit
  Bestellnummer und Applikation samt Version – damit lädt man gezielt die
  richtige .knxprod.
- read_files(paths): .knxprod einlesen (Katalog), in den Produktordner legen.
- from_knxproj(path): die Produktdaten eines ETS-Projekts herauslösen; jede
  .knxproj enthält die ihrer Geräte. Bestehende Dateien im Produktordner
  bleiben unberührt (eine .knxproj enthält nur die verwendeten Produkte).
- complete(project, catalog): «Nachführen» – Produkt und KOs zuordnen, die
  gelesenen Verknüpfungen behalten, die Bedeutung der GAs dieser Geräte neu
  ergänzen, solange sie noch nach der Geräteadresse heissen.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger("knix_arranger.missing_products")

_PROGRAM = re.compile(r"Applikation ([0-9A-Fa-f]{4}-[0-9A-Fa-f]{2})")


@dataclass
class MissingProduct:
    """Eine fehlende Applikation eines Herstellers und ihre Geräte."""
    manufacturer_id: str
    manufacturer: str
    program: str                      # "4701-11"
    order_numbers: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)

    @property
    def application_text(self) -> str:
        """«4701 Version 1.1» (Applikationsnummer, Version hex: Haupt/Neben)."""
        number, _sep, version = self.program.partition("-")
        try:
            value = int(version, 16)
        except ValueError:
            return self.program
        return f"{number} Version {value >> 4}.{value & 0x0F}"


def device_program(device) -> str:
    """Gelesene Applikation eines Geräts ohne Katalogprodukt ("" sonst)."""
    if getattr(device, "hw2prog_id", ""):
        return ""
    match = _PROGRAM.search(getattr(device, "application_program", "") or "")
    return match.group(1).upper() if match else ""


def _devices_without_product(project) -> list:
    from .device_scan import project_devices
    return [d for d in project_devices(project) if device_program(d)]


def missing(project) -> list[MissingProduct]:
    """Fehlende Herstellerdateien je Hersteller und Applikation."""
    from .device_scan import _address_key, _manufacturer_name
    groups: dict[tuple[str, str], MissingProduct] = {}
    for device in _devices_without_product(project):
        mfr = (device.manufacturer_id or "").upper()
        key = (mfr, device_program(device))
        entry = groups.get(key)
        if entry is None:
            entry = groups[key] = MissingProduct(
                mfr, device.manufacturer or _manufacturer_name(mfr) or mfr or "unbekannt",
                key[1])
        order = (device.order_number or "").strip()
        if order and order not in entry.order_numbers and not re.fullmatch(
                r"[0-9A-F]{16,}", order):
            entry.order_numbers.append(order)
        entry.addresses.append(device.physical_address)
    for entry in groups.values():
        entry.addresses.sort(key=_address_key)
    return sorted(groups.values(), key=lambda e: (e.manufacturer.lower(), e.program))


def device_count(project) -> int:
    return len(_devices_without_product(project))


# ── Dateien einlesen ──────────────────────────────────────────────────────

@dataclass
class ReadResult:
    products: int = 0
    files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def file_manufacturers(path: str) -> set[str]:
    """Hersteller-IDs einer .knxprod aus dem Inhaltsverzeichnis des Archivs
    (Ordner «M-0002/…») – liest nur das Verzeichnis am Dateiende, nicht die
    ganze Datei."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as archive:
            return {name.split("/", 1)[0].upper() for name in archive.namelist()
                    if name.upper().startswith("M-") and "/" in name}
    except (zipfile.BadZipFile, OSError):
        return set()


def needed_manufacturers(findings, catalog) -> set[str]:
    """Hersteller der Geräte, deren Applikation nicht im Katalog steht."""
    from . import device_scan as ds
    index = ds.catalog_index(catalog)
    needed = set()
    for finding in findings:
        if not getattr(finding, "program", ""):
            continue
        if ds.match_product(index, finding)[0] is None:
            mfr = (finding.program_manufacturer or finding.manufacturer_id or "").upper()
            if mfr:
                needed.add(mfr)
    return needed


def findings_of_devices(project) -> list:
    """Geräte ohne Produkt als ScanFinding (für match_product)."""
    from . import device_scan as ds
    return [ds.ScanFinding(address=d.physical_address, answered=True,
                           manufacturer_id=d.manufacturer_id or "",
                           program=device_program(d), order_info=d.order_number or "")
            for d in _devices_without_product(project)]


def relevant_pending(manufacturers: set[str]) -> list[str]:
    """Noch nicht eingelesene Dateien im Produktordner, die einen der
    Hersteller enthalten (die grossen Sammeldateien nur, wenn nötig)."""
    from .product_folder import pending_files
    if not manufacturers:
        return []
    return [path for path in pending_files()
            if file_manufacturers(path) & manufacturers]


def total_mb(paths: list[str]) -> int:
    size = 0
    for path in paths:
        try:
            size += os.path.getsize(path)
        except OSError:
            pass
    return round(size / 1_000_000)


def read_files(paths: list[str], catalog=None, progress=None) -> ReadResult:
    """.knxprod in den Produktkatalog einlesen und im Produktordner ablegen
    (wie die Produktauswahl). progress(index, total, name) -> False bricht ab
    (vor der nächsten Datei)."""
    result = ReadResult()
    products, imported = [], {}
    for number, path in enumerate(paths):
        name = os.path.basename(path)
        if progress is not None and progress(number, len(paths), name) is False:
            result.problems.append("abgebrochen")
            break
        found, problem = parse_file(path)
        if problem:
            result.problems.append(problem)
            continue
        products.extend(found)
        imported[path] = len(found)
    store(products, imported, catalog, result)
    return result


def parse_file(path: str) -> tuple[list, str]:
    """Eine .knxprod lesen (ohne Katalog, darf im Hintergrund laufen):
    (Produkte, Problem oder "")."""
    from .knxprod_catalog_service import KnxprodCatalogService
    name = os.path.basename(path)
    try:
        found = KnxprodCatalogService().import_file(path)
    except ValueError as exc:
        return [], f"{name}: {exc}"
    if not found:
        return [], f"{name}: keine Produktdaten gefunden"
    return found, ""


def store(products: list, imported: dict[str, int], catalog, result: ReadResult) -> None:
    """Gelesene Produkte in den Katalog, Dateien in den Produktordner und als
    eingelesen vermerken (im Hauptthread)."""
    from .product_folder import add_to_folder, mark_imported
    if products:
        if catalog is None:
            from .product_sync import shared_catalog
            catalog = shared_catalog()
        catalog.add_products([p.to_catalog_dict() for p in products])
        sources = list(imported)
        copies = add_to_folder(sources)
        mark_imported(copies, {copy: imported[src] for src, copy in zip(sources, copies)})
        result.files = copies
    result.products = len(products)




def from_knxproj(path: str, catalog=None) -> ReadResult:
    """Produktdaten aus einem ETS-Projekt herauslösen und einlesen. Eine
    Datei je Hersteller, die eine gleichnamige im Produktordner nicht
    ersetzt (sie enthielte nur die Produkte dieses Projekts)."""
    from .knxproj_import_service import KnxprojImportService
    from .product_folder import products_folder
    with tempfile.TemporaryDirectory(prefix="knix_prod_") as temp:
        written = KnxprojImportService().extract_product_libraries(path, temp)
        if not written:
            result = ReadResult()
            result.problems.append(f"{os.path.basename(path)}: keine Produktdaten gefunden")
            return result
        folder = products_folder()
        stem = os.path.splitext(os.path.basename(path))[0]
        renamed = []
        for source in written:
            base = os.path.splitext(os.path.basename(source))[0]
            target_name = f"{base} aus {stem}.knxprod"
            if folder and not os.path.exists(os.path.join(folder, os.path.basename(source))):
                target_name = os.path.basename(source)
            target = os.path.join(temp, "out", target_name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(source, target)
            renamed.append(target)
        return read_files(renamed, catalog)


# ── Nachführen ────────────────────────────────────────────────────────────

@dataclass
class CompleteResult:
    completed: list[str] = field(default_factory=list)    # Geräte mit Produkt
    still_missing: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    renamed: int = 0

    def text(self) -> str:
        from .device_scan import _short_list
        if not self.completed:
            lines = ["Für keines der Geräte steht die Applikation im Produktkatalog."]
        else:
            lines = [f"{len(self.completed)} Geräte mit Produkt und Kommunikationsobjekten "
                     f"nachgeführt: {_short_list(self.completed)}."]
            if self.renamed:
                lines.append(f"{self.renamed} GAs neu benannt (Bedeutung ergänzt).")
        if self.ambiguous:
            lines.append("Produkt unsicher (Bestellnummer nicht eindeutig): "
                         f"{_short_list(self.ambiguous)} – in der Materialliste prüfen.")
        if self.still_missing:
            lines.append(f"Weiterhin ohne Herstellerdatei: {_short_list(self.still_missing)}.")
        return "\n".join(lines)


def complete(project, catalog=None) -> CompleteResult:
    """Geräte ohne Produkt nachführen, deren Applikation inzwischen im Katalog
    steht. Verknüpfungen bleiben; GAs, die noch vorläufig oder nach der
    Geräteadresse heissen (nicht von Hand und nicht im Rundgang benannt),
    bekommen die Bedeutung neu."""
    from . import device_scan as ds
    from . import ga_meaning
    if catalog is None:
        from .product_sync import shared_catalog
        catalog = shared_catalog()
    result = CompleteResult()
    index = ds.catalog_index(catalog)
    devices = []
    for device in _devices_without_product(project):
        finding = ds.ScanFinding(address=device.physical_address, answered=True,
                                 manufacturer_id=device.manufacturer_id or "",
                                 program=device_program(device),
                                 order_info=device.order_number or "")
        prod, ambiguous = ds.match_product(index, finding)
        if prod is None:
            result.still_missing.append(device.physical_address)
            continue
        ds._apply_product_keeping_links(project, device, prod)
        if device.device_type in ("", "other", "unknown"):
            device.device_type = ds._kind(prod, device.physical_address)
        devices.append(device)
        result.completed.append(device.physical_address)
        if ambiguous:
            result.ambiguous.append(device.physical_address)
    if devices:
        refresh = _gas_to_refresh(project, devices)
        proposals = [m for m in ga_meaning.propose(project, refresh=refresh)
                     if m.designation and m.address in refresh]
        if proposals:
            result.renamed = ga_meaning.apply(project, proposals).named
    return result


def _gas_to_refresh(project, devices) -> set[str]:
    """GAs dieser Geräte, deren Name noch von KNiX stammt: vorläufig oder
    mit der Geräteadresse an Stelle des Raums (Bedeutung ergänzt, Raum noch
    nicht zugeordnet)."""
    from .ga_meaning import is_provisional
    addresses = {d.physical_address for d in devices}
    linked: dict[str, set[str]] = {}
    for device in devices:
        for co in device.communication_objects:
            for ga in co.connected_gas:
                linked.setdefault(ga, set()).add(device.physical_address)
    result = set()
    for ga in project.group_addresses.all_addresses():
        owners = linked.get(ga.address)
        if not owners:
            continue
        name = ga.designation or ""
        if is_provisional(ga) or any(f"_{a}_" in name for a in owners & addresses):
            result.add(ga.address)
    return result
