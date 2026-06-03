"""Tests fuer UpdateService (NFA-111 bis NFA-115)."""
import json
from unittest.mock import patch, MagicMock
from knix_arranger.services.update_service import UpdateService, UpdateInfo


class TestUpdateService:
    def test_is_newer_true(self):
        assert UpdateService._is_newer("1.2.0", "1.1.0") is True
        assert UpdateService._is_newer("2.0.0", "1.9.9") is True
        assert UpdateService._is_newer("1.0.1", "1.0.0") is True

    def test_is_newer_false(self):
        assert UpdateService._is_newer("1.0.0", "1.0.0") is False
        assert UpdateService._is_newer("1.0.0", "1.1.0") is False
        assert UpdateService._is_newer("0.9.0", "1.0.0") is False

    def test_is_newer_invalid(self):
        assert UpdateService._is_newer("abc", "1.0.0") is False
        assert UpdateService._is_newer("", "") is False

    def test_check_for_updates_available(self):
        svc = UpdateService(update_url="https://example.com/version.json")
        response_data = json.dumps({
            "latest_version": "2.0.0",
            "download_url": "https://example.com/download",
            "changelog": "Neue Features",
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("knix_arranger.services.update_service.urlopen", return_value=mock_resp):
            info = svc.check_for_updates("1.0.0")

        assert info.available is True
        assert info.latest_version == "2.0.0"
        assert info.download_url == "https://example.com/download"
        assert info.error == ""

    def test_check_for_updates_no_update(self):
        svc = UpdateService(update_url="https://example.com/version.json")
        response_data = json.dumps({
            "latest_version": "1.0.0",
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("knix_arranger.services.update_service.urlopen", return_value=mock_resp):
            info = svc.check_for_updates("1.0.0")

        assert info.available is False

    def test_check_for_updates_network_error(self):
        from urllib.error import URLError
        svc = UpdateService(update_url="https://example.com/version.json")

        with patch("knix_arranger.services.update_service.urlopen",
                   side_effect=URLError("Connection refused")):
            info = svc.check_for_updates("1.0.0")

        assert info.available is False
        assert "Server nicht erreichbar" in info.error
