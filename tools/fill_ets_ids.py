"""
KNiX Arranger – ETS-Kennungen im eigenen Produktkatalog nachtragen

Liest KNXPROD-Dateien und ergaenzt bei bereits vorhandenen Eintraegen des
eigenen Katalogs (%APPDATA%/KNiX Arranger/product_catalog_user.json) nur
manufacturer_id, product_ref_id, hw2prog_id und application_program_id.
Andere Felder (z.B. "veraltet"-Markierung) bleiben unveraendert, neue
Produkte werden nicht hinzugefuegt.

    python tools/fill_ets_ids.py <datei.knxprod> [<datei.knxprod> ...]
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService  # noqa: E402
from knix_arranger.services.product_search_service import ProductSearchService  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    logging.disable(logging.WARNING)
    products = []
    for path in sys.argv[1:]:
        found = KnxprodCatalogService().import_file(path)
        print(f"{Path(path).name}: {len(found)} Produkte gelesen")
        products.extend(p.to_catalog_dict() for p in found)
    filled = ProductSearchService().fill_ets_ids(products)
    print(f"{filled} Katalogeintraege mit ETS-Kennungen ergaenzt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
