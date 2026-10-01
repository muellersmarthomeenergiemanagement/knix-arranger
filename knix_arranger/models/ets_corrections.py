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
    # Bezeichnung einer Taste für den Bauherrn (Bedienungsanleitung), z.B.
    # "1.1.41|1|links|": "Hell" statt "Szene High". Schlüssel siehe
    # services/user_manual.button_label_key (Gerät bzw. Bedienelement + Taste).
    button_labels: dict[str, str] = field(default_factory=dict)
    # Physikalische Adresse -> {"room": Raumschlüssel in KNiX, "ets": Raum-
    # schlüssel laut ETS}, z.B. "1.2.6": {"room": "EG|08", "ets": "EG|01"}.
    # Raumschlüssel "Stockwerk|Nummer" (unnummeriert "Stockwerk|#Name") wie
    # beim Re-Import-Abgleich -- Raum-IDs überleben einen Neuaufbau nicht.
    room_by_device: dict[str, dict[str, str]] = field(default_factory=dict)
    # In KNiX getrennte KO-Verknüpfungen "1.1.51|6|12/1/62" (Gerät|KO|GA);
    # beim Re-Import wieder getrennt, solange die ETS sie noch hat.
    unlinked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"gewerk_by_address": dict(self.gewerk_by_address),
                "button_labels": dict(self.button_labels),
                "room_by_device": {k: dict(v) for k, v in self.room_by_device.items()},
                "unlinked": list(self.unlinked)}

    @classmethod
    def from_dict(cls, data: dict | None) -> EtsCorrections:
        data = data or {}
        return cls(gewerk_by_address=dict(data.get("gewerk_by_address", {})),
                   button_labels=dict(data.get("button_labels", {})),
                   room_by_device={k: dict(v) for k, v in
                                   data.get("room_by_device", {}).items()},
                   unlinked=list(data.get("unlinked", [])))
