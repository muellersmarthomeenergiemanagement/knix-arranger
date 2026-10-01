"""
Korrekturen an importierten ETS-Daten (Korrekturschicht).

Bei aus der ETS importierten Projekten bleibt die ETS massgebend: KNiX
verändert die ETS-Daten nicht, sondern legt Korrekturen daneben ab, die alle
Dokumente verwenden. Sie sind an der GA-Adresse festgemacht und überleben so
jeden Re-Import und Neuaufbau. Jede Korrektur erscheint in der Validierung als
"Abweichung zur ETS" -- Nachweis und Aufgabenliste für die ETS.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class EtsCorrections:
    # GA-Adresse -> Gewerk-Code, der statt des Kürzels im ETS-Namen gilt
    # (z.B. "2/2/100": "G" -- im Chalet steht "T." für Tor, nicht Tagesvorhang)
    gewerk_by_address: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"gewerk_by_address": dict(self.gewerk_by_address)}

    @classmethod
    def from_dict(cls, data: dict | None) -> EtsCorrections:
        data = data or {}
        return cls(gewerk_by_address=dict(data.get("gewerk_by_address", {})))
