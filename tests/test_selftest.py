"""Selbsttest des Bundles (--selftest) läuft auch aus dem Quellcode durch."""
import pytest
from knix_arranger.utils import selftest


def test_selftest_besteht():
    assert selftest.run_selftest() == 0


def test_selftest_meldet_fehler(monkeypatch):
    def kaputt():
        raise RuntimeError("fehlt")
    monkeypatch.setattr(selftest, "CHECKS", [("Test", kaputt)])
    assert selftest.run_selftest() == 1
