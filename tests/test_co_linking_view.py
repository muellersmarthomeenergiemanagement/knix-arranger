"""
Tests fuer CoLinkingView-Filterlogik (FA-3000).

Deckt _segment_matches() ab -- die segmentweise Adress-/GA-Filterung, die
verhindert, dass z.B. "1.1.1" faelschlich auch "1.1.10"/"1.1.12" trifft
(reiner Substring-Vergleich haette das getan).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.ui.views.co_linking_view import _segment_matches


class TestSegmentMatchesPhysicalAddress:

    def test_vollstaendiger_filter_matcht_nicht_praefix_kollision(self):
        """Regression: '1.1.1' darf NICHT auch '1.1.10'/'1.1.12' treffen."""
        assert not _segment_matches("1.1.1", "1.1.10", ".")
        assert not _segment_matches("1.1.1", "1.1.12", ".")

    def test_vollstaendiger_filter_matcht_exakte_adresse(self):
        assert _segment_matches("1.1.1", "1.1.1", ".")

    def test_kurzer_filter_zeigt_ganze_linie(self):
        assert _segment_matches("1.1", "1.1.1", ".")
        assert _segment_matches("1.1", "1.1.10", ".")
        assert _segment_matches("1.1", "1.1.12", ".")

    def test_kurzer_filter_zeigt_nicht_andere_linie(self):
        assert not _segment_matches("1.1", "1.2.5", ".")

    def test_ein_segment_filter_zeigt_ganzen_bereich(self):
        assert _segment_matches("1", "1.1.10", ".")
        assert not _segment_matches("2", "1.1.10", ".")

    def test_leerer_filter_matcht_alles(self):
        assert _segment_matches("", "1.1.10", ".")
        assert _segment_matches("   ", "1.1.10", ".")

    def test_trailing_dot_degradiert_zu_praefix(self):
        """Waehrend des Tippens ('1.1.') soll noch kein exakter 3-Segment-
        Vergleich erzwungen werden."""
        assert _segment_matches("1.1.", "1.1.10", ".")


class TestSegmentMatchesGroupAddress:

    def test_vollstaendiger_filter_matcht_nicht_praefix_kollision(self):
        """'2/0/4' darf nicht auch '2/0/40' treffen."""
        assert not _segment_matches("2/0/4", "2/0/40", "/")

    def test_vollstaendiger_filter_matcht_exakte_ga(self):
        assert _segment_matches("2/0/4", "2/0/4", "/")

    def test_kurzer_filter_zeigt_ganze_mittelgruppe(self):
        assert _segment_matches("2/0", "2/0/4", "/")
        assert _segment_matches("2/0", "2/0/40", "/")
        assert not _segment_matches("2/0", "2/1/4", "/")
