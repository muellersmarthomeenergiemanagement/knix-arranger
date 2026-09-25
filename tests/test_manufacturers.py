"""Tests fuer die Hersteller-Vereinheitlichung (Hersteller-ID als Schluessel)."""
import json
import os

from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.project import ProjectConfig
from knix_arranger.models.topology import Device
from knix_arranger.services.product_search_service import (
    ProductSearchService, _user_catalog_path,
)
from knix_arranger.utils.manufacturers import (
    canonical_manufacturer, manufacturer_display_name, manufacturer_id,
    normalize_order_number, product_key,
)


class TestManufacturerLookup:
    def test_id_to_display_name(self):
        assert manufacturer_display_name("M-0002") == "ABB"
        assert manufacturer_display_name("m-0083") == "MDT"

    def test_name_variants_resolve_to_same_id(self):
        for name in ("ABB", "ABB AG - STOTZ-KONTAKT", "abb ag -  stotz-kontakt"):
            assert manufacturer_id(name) == "M-0002"
        for name in ("Busch-Jaeger Elektro", "ABB AG - BUSCH-JAEGER", "Busch-Jaeger"):
            assert manufacturer_id(name) == "M-0007"

    def test_brands_of_same_group_stay_separate(self):
        assert manufacturer_id("Theben AG") == "M-0048"
        assert manufacturer_id("Theben HTS AG") == "M-00E8"

    def test_registry_name_without_short_name(self):
        assert manufacturer_display_name("RTS Automation") == "RTS Automation"
        assert manufacturer_id("RTS Automation") == "M-0069"

    def test_umlaut_name(self):
        assert manufacturer_display_name("Hörmann KG Verkaufsgesellschaft") == "Hörmann"

    def test_unknown_name_unchanged(self):
        assert manufacturer_display_name("  Testwerk ") == "Testwerk"
        assert manufacturer_id("Testwerk") == ""

    def test_ambiguous_registry_name_has_no_id(self):
        # "Simon" steht zweimal im KNX-Register
        assert manufacturer_id("Simon") == ""

    def test_unknown_id_keeps_existing_name(self):
        assert canonical_manufacturer("Neuer Hersteller", "M-FFF0") == ("Neuer Hersteller", "M-FFF0")
        assert canonical_manufacturer("", "M-FFF0") == ("M-FFF0", "M-FFF0")

    def test_order_number_normalized(self):
        assert normalize_order_number("GH Q631 0049 R0111") == "GHQ6310049R0111"
        assert normalize_order_number("akk-0816.03") == "AKK-081603"
        assert product_key("ABB AG - STOTZ-KONTAKT", "SA/S 8.16.7.1") == product_key("ABB", "SA/S8.16.71")


class TestModelMigration:
    def test_device_from_old_project_with_raw_id(self):
        d = Device.from_dict({"manufacturer": "M-0083", "order_number": "AKS-0816.03"})
        assert d.manufacturer == "MDT"
        assert d.manufacturer_id == "M-0083"
        assert d.to_dict()["manufacturer_id"] == "M-0083"

    def test_device_constructed_with_name(self):
        d = Device(manufacturer="GIRA Giersiepen")
        assert (d.manufacturer, d.manufacturer_id) == ("Gira", "M-0008")

    def test_material_entry_name_unified(self):
        e = MaterialEntry.from_dict({"manufacturer": "Hager Electro", "order_number": "TXA208"})
        assert e.manufacturer == "Hager"

    def test_preferred_manufacturers_unified_and_deduplicated(self):
        cfg = ProjectConfig.from_dict(
            {"preferred_manufacturers": ["ABB", "ABB AG - STOTZ-KONTAKT", "MDT technologies"]}
        )
        assert cfg.preferred_manufacturers == ["ABB", "MDT"]


class TestCatalogUnification:
    def _write_user_catalog(self, products):
        with open(_user_catalog_path(), "w", encoding="utf-8") as f:
            json.dump({"products": products}, f)

    def test_variants_in_user_catalog_merge(self):
        self._write_user_catalog([
            {"category": "infrastructure", "manufacturer": "ABB",
             "order_number": "GH Q631 0049 R0111", "product_name": "SU/S30.640.1 alt"},
            {"category": "infrastructure", "manufacturer": "ABB AG - STOTZ-KONTAKT",
             "order_number": "GH Q631 0049 R0111", "product_name": "SU/S30.640.1 neu"},
        ])
        svc = ProductSearchService()
        hits = [r for r in svc.search_all(query="GHQ6310049") if r.manufacturer == "ABB"]
        assert len(hits) == 1
        assert hits[0].product_name == "SU/S30.640.1 neu"
        assert hits[0].manufacturer_id == "M-0002"

    def test_find_product_with_other_spelling(self):
        self._write_user_catalog([
            {"category": "actor", "manufacturer": "MDT technologies",
             "order_number": "AKS-0816.03", "product_name": "Schaltaktor 8-fach"},
        ])
        svc = ProductSearchService()
        assert svc.find_product("M-0083", "AKS-0816.03")["product_name"] == "Schaltaktor 8-fach"
        assert svc.find_product("MDT", "aks-081603") is not None

    def test_saved_user_catalog_uses_unified_names(self):
        svc = ProductSearchService()
        svc.add_product({"category": "actor", "manufacturer": "Theben AG",
                         "order_number": "4940210", "product_name": "RMG 8 T"})
        with open(_user_catalog_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)["products"]
        assert saved[0]["manufacturer"] == "Theben"
        assert saved[0]["manufacturer_id"] == "M-0048"
        assert os.path.exists(_user_catalog_path())

    def test_preferred_manufacturer_matches_other_spelling(self):
        svc = ProductSearchService()
        results = svc.search_actors("", preferred_manufacturers=["MDT technologies"])
        assert results and results[0].manufacturer == "MDT"

    def test_placeholder_order_numbers_stay_separate(self):
        """Feller-Dummys (GA-Filter-Hilfe der Linienkoppler) tragen dieselbe
        Platzhalter-Bestellnummer -- beide muessen erhalten bleiben."""
        self._write_user_catalog([
            {"category": "actor", "manufacturer": "Feller",
             "order_number": "Dummy", "product_name": "Dummy"},
            {"category": "infrastructure", "manufacturer": "Feller",
             "order_number": "Dummy ", "product_name": "Dummy Secure"},
        ])
        svc = ProductSearchService()
        names = {r.product_name for r in svc.search_all(query="dummy") if r.manufacturer == "Feller"}
        assert names == {"Dummy", "Dummy Secure"}
        assert svc.find_product("Feller", "Dummy", "Dummy Secure")["category"] == "infrastructure"
