"""
Vollständigkeitsprüfung der Revisionsunterlagen (FA-2104).

Prüft vor dem Erstellen des Revisionspakets, welche Bestandteile nach
FA-2102 noch fehlen oder unvollständig sind, z.B. "Abnahmeprotokoll fehlt
noch" oder "Produktdatenblatt für Gerät X fehlt". Das Paket wird trotzdem
erstellt; die offenen Punkte stehen im Inhaltsverzeichnis.
"""
from __future__ import annotations
from dataclasses import dataclass

# Busgeräte mit Produkt und Datenblatt (keine Koppler/Spannungsversorgungen)
_PRODUCT_DEVICE_TYPES = ("actor", "sensor", "gateway")
# So viele Einzelnennungen je Befund, der Rest wird zusammengefasst
_MAX_NAMED = 5


@dataclass
class RevisionFinding:
    part: str        # Bestandteil nach FA-2102, z.B. "Produktdatenblätter"
    message: str


def _named(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_NAMED])
    rest = len(items) - _MAX_NAMED
    return shown + (f" und {rest} weitere" if rest > 0 else "")


def _bus_devices(project) -> list:
    return [d for area in project.topology.areas for line in area.lines
            for d in line.devices if d.device_type in _PRODUCT_DEVICE_TYPES]


def _device_label(device) -> str:
    name = device.product_name or device.product or device.order_number or "Gerät"
    return f"{device.physical_address} {name}".strip()


def check_revision_completeness(project, company_profile=None) -> list[RevisionFinding]:
    """Offene Punkte der Revisionsunterlagen; leere Liste = vollständig."""
    findings: list[RevisionFinding] = []

    def add(part: str, message: str) -> None:
        findings.append(RevisionFinding(part, message))

    if company_profile is None or not company_profile.company_name:
        add("Deckblatt", "Firmenprofil ohne Firmenname (Deckblatt, Kopfzeilen).")

    if not project.topology.areas:
        add("Topologie", "Keine Topologie vorhanden.")

    if not any(not ga.is_placeholder for ga in project.group_addresses.all_addresses()):
        add("Gruppenadressen", "Keine Gruppenadressen vorhanden.")

    devices = _bus_devices(project)
    if not devices:
        add("Geräteliste", "Keine Aktoren, Sensoren oder Gateways in der Topologie.")
    without_product = [_device_label(d) for d in devices if not d.order_number]
    if without_product:
        add("Geräteliste", f"{len(without_product)} Gerät(e) ohne Produkt "
            f"(Bestellnummer): {_named(without_product)}.")

    # Datenblatt je Produkt: fehlt es bei allen Geräten dieses Produkts
    by_product: dict[tuple, list] = {}
    for d in devices:
        if d.order_number:
            by_product.setdefault((d.manufacturer, d.order_number), []).append(d)
    missing_ds = [
        f"{items[0].product_name or order} ({' '.join(p for p in (manufacturer, order) if p)})"
        for (manufacturer, order), items in sorted(by_product.items())
        if not any(d.datasheets for d in items)
    ]
    for product in missing_ds[:_MAX_NAMED]:
        add("Produktdatenblätter", f"Produktdatenblatt für {product} fehlt.")
    if len(missing_ds) > _MAX_NAMED:
        add("Produktdatenblätter",
            f"Bei {len(missing_ds) - _MAX_NAMED} weiteren Produkten fehlt das Datenblatt.")

    imported = project.topology.is_imported
    without_function = [
        f"{room.number} {room.name} ({be.element_type})".strip()
        for room in project.all_rooms for be in room.bedienelemente
        if be.is_shown(imported) and be.is_operable and not be.funktionen
    ]
    if without_function:
        add("Funktionszuordnung", f"{len(without_function)} Bedienelement(e) ohne "
            f"Funktion: {_named(without_function)}.")

    protocol = project.acceptance_protocol
    if protocol is None or not protocol.result:
        add("Abnahmeprotokoll", "Abnahmeprotokoll fehlt noch (kein Abnahmeentscheid).")
    else:
        open_defects = [d for d in protocol.defects if d.status != "behoben"]
        if open_defects:
            add("Abnahmeprotokoll", f"{len(open_defects)} Mangel/Mängel noch nicht behoben.")

    items = [i for cl in project.checklists for i in cl.items]
    if not items:
        add("Inbetriebnahme-Checkliste", "Inbetriebnahme-Checkliste noch nicht ausgefüllt.")
    else:
        open_items = sum(1 for i in items if not i.result)
        if open_items:
            add("Inbetriebnahme-Checkliste",
                f"{open_items} von {len(items)} Prüfpunkten noch offen.")

    if not project.material_list.entries:
        add("Materialliste", "Materialliste ist leer.")

    return findings
