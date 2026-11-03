"""
Teilnehmer je Liniensegment (FA-609b).

Ein TP-Segment trägt höchstens 64 Busteilnehmer. Mehr Teilnehmer auf einer
Linie brauchen Linienverstärker (Segmentkoppler): jeder bildet ein weiteres
Segment mit eigener Spannungsversorgung, bis 4 Segmente bzw. 256 Teilnehmer.
Der Topologie-Modus TP-256 sagt nur, dass Verstärker erlaubt sind – ob sie
eingebaut sind, zeigt erst ein Verstärker in der Linie.

Gezählt werden alle Busteilnehmer der Linie (ohne Spannungsversorgungen und
Drosseln), auch der Linienkoppler und externe Geräte, die nicht im
ETS-Projekt stehen (Device.external, z.B. die TP-Schnittstelle eines
Visualisierungsservers).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from .bus_current import RESERVE_LIMIT, is_consumer

SEGMENT_DEVICES = 64
MAX_SEGMENTS = 4
_REPEATER_RE = re.compile(r"verstärker|verstaerker|repeater|segmentkoppler", re.IGNORECASE)


def is_line_repeater(device) -> bool:
    """Linienverstärker / Segmentkoppler am Produktnamen."""
    return bool(_REPEATER_RE.search(" ".join(
        (device.product_name or "", device.product or "", device.order_number or ""))))


@dataclass
class SegmentLoad:
    count: int = 0          # Busteilnehmer der Linie
    segments: int = 1       # 1 + Linienverstärker
    external: int = 0       # davon nicht im ETS-Projekt

    @property
    def capacity(self) -> int:
        return SEGMENT_DEVICES * self.segments

    @property
    def free(self) -> int:
        return self.capacity - self.count

    @property
    def overloaded(self) -> bool:
        return self.count > self.capacity

    @property
    def low_reserve(self) -> bool:
        return not self.overloaded and self.count > RESERVE_LIMIT * self.capacity

    def summary(self) -> str:
        """'63 / 64 Teilnehmer' bzw. '70 / 128 Teilnehmer (2 Segmente)'."""
        text = f"{self.count} / {self.capacity} Teilnehmer"
        if self.segments > 1:
            text += f" ({self.segments} Segmente)"
        return text


def segment_load(line) -> SegmentLoad:
    devices = [d for d in line.devices if is_consumer(d)]
    repeaters = sum(1 for d in devices if is_line_repeater(d))
    return SegmentLoad(count=len(devices),
                       segments=min(1 + repeaters, MAX_SEGMENTS),
                       external=sum(1 for d in devices if d.external))
