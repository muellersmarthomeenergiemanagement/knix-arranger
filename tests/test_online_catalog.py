"""Tests fuer den Online-Produktkatalog (FA-1303, FA-1402)."""
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from knix_arranger.services import online_catalog_service as ocs
from knix_arranger.services.online_catalog_service import (
    OnlineCatalogService, validate_products,
)
from knix_arranger.services.product_search_service import ProductSearchService


ONLINE_ACTOR = {
    "category": "actor", "actor_type": "Jalousieaktor", "manufacturer": "Testwerk",
    "order_number": "TW-JA-8", "product_name": "Jalousieaktor 8-fach", "channels": 8,
}
ONLINE_SENSOR = {
    "category": "sensor", "sensor_type": "Präsenzmelder", "manufacturer": "Testwerk",
    "order_number": "TW-PM-1", "product_name": "Präsenzmelder Decke", "channels": 1,
}


def _fake_urlopen(payload):
    """Ersatz fuer urlopen, der payload als JSON-Antwort liefert."""
    def _open(req, timeout=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return io.BytesIO(body)
    return _open


@pytest.fixture
def online(tmp_path):
    return OnlineCatalogService(url="https://example.invalid/catalog.json",
                                cache_path=str(tmp_path / "online.json"))


class TestValidateProducts:
    def test_keeps_valid_entries(self):
        valid, skipped = validate_products([ONLINE_ACTOR, ONLINE_SENSOR])
        assert valid == [ONLINE_ACTOR, ONLINE_SENSOR]
        assert skipped == 0

    def test_drops_incomplete_entries(self):
        broken = [
            {"category": "actor", "manufacturer": "X"},             # ohne Bestellnummer
            {"category": "actor", "order_number": "1"},             # ohne Hersteller
            {"category": "lamp", "manufacturer": "X", "order_number": "1"},  # Kategorie
            "kein Produkt",
        ]
        valid, skipped = validate_products(broken + [ONLINE_ACTOR])
        assert valid == [ONLINE_ACTOR]
        assert skipped == 4

    def test_non_list_gives_nothing(self):
        assert validate_products({"x": 1}) == ([], 0)


class TestOnlineCatalogService:
    def test_fetch_writes_cache(self, online, monkeypatch):
        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen(
            {"updated": "2026-09-23", "products": [ONLINE_ACTOR, {"category": "x"}]}))
        result = online.fetch()
        assert result.ok
        assert result.products == [ONLINE_ACTOR]
        assert result.skipped == 1
        assert result.updated == "2026-09-23"

        cached = online.load_cached()
        assert cached.products == [ONLINE_ACTOR]
        assert cached.updated == "2026-09-23"
        assert cached.fetched_at == result.fetched_at

    def test_network_error_keeps_cache(self, online, monkeypatch):
        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen({"products": [ONLINE_ACTOR]}))
        online.fetch()

        def _fail(req, timeout=None):
            raise URLError("offline")
        monkeypatch.setattr(ocs, "urlopen", _fail)
        result = online.fetch()
        assert not result.ok
        assert "nicht erreichbar" in result.error
        assert online.load_cached().products == [ONLINE_ACTOR]

    def test_missing_file_on_server(self, online, monkeypatch):
        def _404(req, timeout=None):
            raise HTTPError(req.full_url, 404, "Not Found", None, None)
        monkeypatch.setattr(ocs, "urlopen", _404)
        result = online.fetch()
        assert "nicht verfügbar (HTTP 404)" in result.error

    def test_invalid_json_is_error(self, online, monkeypatch):
        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen(b"<html>404</html>"))
        result = online.fetch()
        assert not result.ok
        assert online.load_cached().products == []

    def test_load_cached_without_file(self, online):
        assert online.load_cached().products == []


class TestProductSearchWithOnlineCatalog:
    def _service(self, online, monkeypatch, products):
        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen({"products": products}))
        return ProductSearchService(online_service=online)

    def test_search_online_returns_only_online_products(self, online, monkeypatch):
        svc = self._service(online, monkeypatch, [ONLINE_ACTOR, ONLINE_SENSOR])
        results = svc.search_online(category_filter="actor")
        assert [(r.manufacturer, r.order_number) for r in results] == [("Testwerk", "TW-JA-8")]
        assert results[0].online

    def test_online_products_appear_in_normal_search(self, online, monkeypatch):
        svc = self._service(online, monkeypatch, [ONLINE_ACTOR])
        svc.update_online_catalog()
        hits = svc.search_all(query="TW-JA-8")
        assert len(hits) == 1 and hits[0].online
        # Mitgelieferte Produkte bleiben erhalten und sind nicht als online markiert
        assert any(not r.online for r in svc.search_all(category_filter="actor"))

    def test_cached_online_products_loaded_on_start(self, online, monkeypatch):
        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen({"products": [ONLINE_SENSOR]}))
        online.fetch()
        svc = ProductSearchService(online_service=online)
        hits = svc.search_sensors("Präsenzmelder")
        assert any(r.order_number == "TW-PM-1" and r.online for r in hits)

    def test_preferred_manufacturer_first(self, online, monkeypatch):
        other = dict(ONLINE_ACTOR, manufacturer="Aaa", order_number="A-1")
        svc = self._service(online, monkeypatch, [other, ONLINE_ACTOR])
        results = svc.search_online(preferred_manufacturers=["Testwerk"])
        assert results[0].manufacturer == "Testwerk"

    def test_user_import_wins_over_online(self, online, monkeypatch):
        svc = self._service(online, monkeypatch, [])
        own = dict(ONLINE_ACTOR, product_name="Eigener Import")
        svc.add_product(own)

        monkeypatch.setattr(ocs, "urlopen", _fake_urlopen({"products": [ONLINE_ACTOR]}))
        svc.update_online_catalog()
        hit = svc.find_product("Testwerk", "TW-JA-8")
        assert hit["product_name"] == "Eigener Import"
        assert not svc.search_all(query="TW-JA-8")[0].online

    def test_offline_search_uses_cache(self, online, monkeypatch):
        svc = self._service(online, monkeypatch, [ONLINE_ACTOR])
        svc.update_online_catalog()

        def _fail(req, timeout=None):
            raise URLError("offline")
        monkeypatch.setattr(ocs, "urlopen", _fail)
        results = ProductSearchService(online_service=online).search_online()
        assert [r.order_number for r in results] == ["TW-JA-8"]
