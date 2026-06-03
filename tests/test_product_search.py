"""Tests fuer ProductSearchService (FA-1303/1304, FA-1402/1403)."""
from knix_arranger.services.product_search_service import (
    ProductSearchService, ProductSuggestion,
)


class TestProductSearchService:
    def setup_method(self):
        self.svc = ProductSearchService()

    def test_catalog_loaded(self):
        """Produktkatalog sollte geladen werden."""
        assert len(self.svc._catalog) > 0

    def test_search_actors_schaltaktor(self):
        results = self.svc.search_actors("Schaltaktor")
        assert len(results) > 0
        for r in results:
            assert r.category == "actor"
            assert "schaltaktor" in r.actor_type.lower()

    def test_search_actors_dimmaktor(self):
        results = self.svc.search_actors("Dimmaktor")
        assert len(results) > 0
        for r in results:
            assert "dimmaktor" in r.actor_type.lower()

    def test_search_actors_min_channels(self):
        results = self.svc.search_actors("Schaltaktor", min_channels=8)
        for r in results:
            assert r.channels >= 8

    def test_search_actors_preferred_manufacturer(self):
        """Bevorzugte Hersteller werden zuerst angezeigt (FA-1304)."""
        results = self.svc.search_actors("Schaltaktor",
                                         preferred_manufacturers=["MDT"])
        if len(results) >= 2:
            # MDT-Produkte sollten vor anderen kommen
            first_mdt = next((i for i, r in enumerate(results)
                            if r.manufacturer == "MDT"), None)
            first_other = next((i for i, r in enumerate(results)
                              if r.manufacturer != "MDT"), None)
            if first_mdt is not None and first_other is not None:
                assert first_mdt < first_other

    def test_search_sensors_taster(self):
        results = self.svc.search_sensors("Taster")
        assert len(results) > 0
        for r in results:
            assert r.category == "sensor"
            assert "taster" in r.sensor_type.lower()

    def test_search_sensors_praesenzmelder(self):
        results = self.svc.search_sensors("Praesenzmelder")
        assert len(results) > 0

    def test_search_actors_empty_type_returns_all(self):
        """Leerer Aktor-Typ liefert alle Aktoren zurueck."""
        all_actors = self.svc.search_actors("")
        typed = self.svc.search_actors("Schaltaktor")
        assert len(all_actors) >= len(typed)

    def test_search_sensors_preferred_manufacturer(self):
        """Bevorzugte Hersteller werden bei Sensoren zuerst angezeigt (FA-1403)."""
        results = self.svc.search_sensors("Taster", preferred_manufacturers=["MDT"])
        if len(results) >= 2:
            first_mdt = next((i for i, r in enumerate(results) if r.manufacturer == "MDT"), None)
            first_other = next((i for i, r in enumerate(results) if r.manufacturer != "MDT"), None)
            if first_mdt is not None and first_other is not None:
                assert first_mdt < first_other

    def test_search_sensors_empty_type_returns_all_sensors(self):
        """Leerer Sensor-Typ liefert alle Sensoren zurueck."""
        all_sensors = self.svc.search_sensors("")
        assert len(all_sensors) > 0
        for r in all_sensors:
            assert r.category == "sensor"

    def test_search_online_not_implemented(self):
        import pytest
        with pytest.raises(NotImplementedError):
            self.svc.search_online("test")


class TestProductSearchInfrastructure:
    """Tests fuer search_infrastructure (FA-2303)."""

    def setup_method(self):
        self.svc = ProductSearchService()

    def test_search_infrastructure_all(self):
        results = self.svc.search_infrastructure()
        assert len(results) > 0
        for r in results:
            assert r.category == "infrastructure"

    def test_search_infrastructure_koppler(self):
        results = self.svc.search_infrastructure("Linienkoppler")
        assert len(results) > 0
        for r in results:
            assert "linienkoppler" in r.device_type.lower()

    def test_search_infrastructure_preferred_manufacturer(self):
        results = self.svc.search_infrastructure(preferred_manufacturers=["MDT"])
        if len(results) >= 2:
            first_mdt = next((i for i, r in enumerate(results) if r.manufacturer == "MDT"), None)
            first_other = next((i for i, r in enumerate(results) if r.manufacturer != "MDT"), None)
            if first_mdt is not None and first_other is not None:
                assert first_mdt < first_other

    def test_search_infrastructure_returns_product_suggestions(self):
        results = self.svc.search_infrastructure()
        for r in results:
            assert isinstance(r, ProductSuggestion)
            assert r.manufacturer != ""
            assert r.product_name != ""
            assert r.device_type != ""


class TestProductSearchAll:
    """Tests fuer search_all (FA-2303)."""

    def setup_method(self):
        self.svc = ProductSearchService()

    def test_empty_query_returns_all_products(self):
        all_results = self.svc.search_all()
        actors = self.svc.search_actors("")
        sensors = self.svc.search_sensors("")
        infra = self.svc.search_infrastructure()
        assert len(all_results) == len(actors) + len(sensors) + len(infra)

    def test_category_filter_actor(self):
        results = self.svc.search_all(category_filter="actor")
        assert len(results) > 0
        assert all(r.category == "actor" for r in results)

    def test_category_filter_sensor(self):
        results = self.svc.search_all(category_filter="sensor")
        assert len(results) > 0
        assert all(r.category == "sensor" for r in results)

    def test_category_filter_infrastructure(self):
        results = self.svc.search_all(category_filter="infrastructure")
        assert len(results) > 0
        assert all(r.category == "infrastructure" for r in results)

    def test_query_matches_manufacturer(self):
        results = self.svc.search_all(query="MDT")
        assert len(results) > 0
        for r in results:
            assert "mdt" in r.manufacturer.lower()

    def test_query_matches_product_name(self):
        results = self.svc.search_all(query="Schaltaktor")
        assert len(results) > 0

    def test_query_and_category_combined(self):
        results = self.svc.search_all(query="MDT", category_filter="actor")
        for r in results:
            assert r.category == "actor"
            assert "mdt" in r.manufacturer.lower()

    def test_unknown_query_returns_empty(self):
        results = self.svc.search_all(query="XYZNONEXISTENT123")
        assert results == []

    def test_preferred_manufacturer_sorting(self):
        results = self.svc.search_all(preferred_manufacturers=["ABB"])
        if len(results) >= 2:
            first_abb = next((i for i, r in enumerate(results) if r.manufacturer == "ABB"), None)
            first_other = next((i for i, r in enumerate(results) if r.manufacturer != "ABB"), None)
            if first_abb is not None and first_other is not None:
                assert first_abb < first_other


class TestProductSearchMetadata:
    """Tests fuer known_manufacturers und known_device_types."""

    def setup_method(self):
        self.svc = ProductSearchService()

    def test_known_manufacturers_returns_list(self):
        mfrs = self.svc.known_manufacturers()
        assert isinstance(mfrs, list)
        assert len(mfrs) > 0

    def test_known_manufacturers_sorted(self):
        mfrs = self.svc.known_manufacturers()
        assert mfrs == sorted(mfrs)

    def test_known_manufacturers_no_duplicates(self):
        mfrs = self.svc.known_manufacturers()
        assert len(mfrs) == len(set(mfrs))

    def test_known_manufacturers_no_empty_string(self):
        mfrs = self.svc.known_manufacturers()
        assert all(m != "" for m in mfrs)

    def test_known_device_types_all(self):
        types = self.svc.known_device_types()
        assert isinstance(types, list)
        assert len(types) > 0

    def test_known_device_types_filtered_actor(self):
        types = self.svc.known_device_types(category="actor")
        assert len(types) > 0
        actor_types_in_catalog = {
            p.get("actor_type", "") for p in self.svc._catalog
            if p.get("category") == "actor"
        }
        for t in types:
            assert t in actor_types_in_catalog

    def test_known_device_types_sorted(self):
        types = self.svc.known_device_types()
        assert types == sorted(types)

    def test_known_device_types_no_duplicates(self):
        types = self.svc.known_device_types()
        assert len(types) == len(set(types))


class TestProductSearchAddProduct:
    """Tests fuer add_product (Laufzeit-Erweiterung des Katalogs)."""

    def setup_method(self):
        self.svc = ProductSearchService()

    def test_add_product_increases_count(self):
        before = len(self.svc._catalog)
        self.svc.add_product({
            "category": "actor",
            "manufacturer": "TestHersteller",
            "order_number": "TEST-001",
            "product_name": "Test Schaltaktor 4-fach",
            "actor_type": "Schaltaktor",
            "channels": 4,
        })
        assert len(self.svc._catalog) == before + 1

    def test_add_actor_is_searchable(self):
        self.svc.add_product({
            "category": "actor",
            "manufacturer": "NeuHersteller",
            "order_number": "NH-8SA",
            "product_name": "NH Schaltaktor 8-fach",
            "actor_type": "Schaltaktor",
            "channels": 8,
        })
        results = self.svc.search_actors("Schaltaktor")
        assert any(r.manufacturer == "NeuHersteller" for r in results)

    def test_add_sensor_is_searchable(self):
        self.svc.add_product({
            "category": "sensor",
            "manufacturer": "SensorHersteller",
            "order_number": "SH-4T",
            "product_name": "SH Taster 4-fach",
            "sensor_type": "Taster 4-fach",
            "channels": 4,
        })
        results = self.svc.search_sensors("Taster")
        assert any(r.manufacturer == "SensorHersteller" for r in results)

    def test_add_infrastructure_is_searchable(self):
        self.svc.add_product({
            "category": "infrastructure",
            "manufacturer": "InfraHersteller",
            "order_number": "IH-LK",
            "product_name": "IH Linienkoppler TP",
            "device_type": "Linienkoppler",
            "channels": 0,
        })
        results = self.svc.search_infrastructure("Linienkoppler")
        assert any(r.manufacturer == "InfraHersteller" for r in results)


class TestProductSuggestionDisplayType:
    """Tests fuer ProductSuggestion.display_type()."""

    def test_display_type_actor(self):
        s = ProductSuggestion(category="actor", actor_type="Schaltaktor")
        assert s.display_type() == "Schaltaktor"

    def test_display_type_sensor(self):
        s = ProductSuggestion(category="sensor", sensor_type="Taster 4-fach")
        assert s.display_type() == "Taster 4-fach"

    def test_display_type_infrastructure(self):
        s = ProductSuggestion(category="infrastructure", device_type="Linienkoppler")
        assert s.display_type() == "Linienkoppler"

    def test_display_type_device_type_has_priority(self):
        """device_type hat Vorrang vor actor_type und sensor_type."""
        s = ProductSuggestion(device_type="Netzteil", actor_type="Schaltaktor")
        assert s.display_type() == "Netzteil"

    def test_display_type_empty_returns_dash(self):
        s = ProductSuggestion()
        assert s.display_type() == "\u2013"
