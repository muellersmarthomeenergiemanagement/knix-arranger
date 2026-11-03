"""
Umbau-Variante einer Linie (FA-609c): Linie aufteilen oder Hauptlinie einführen.

Die Variante steht neben dem Ist-Stand und verändert die Topologie nicht --
die ETS bleibt die Referenz, bis der Umbau dort umgesetzt und neu eingelesen
ist. Auswertung in services/line_plan_service.
"""
from __future__ import annotations
from dataclasses import dataclass, field

# Ziel eines Geräts (LinePlan.targets); ohne Eintrag bleibt es in der Linie
TARGET_NEW = "new"      # neue Linie bzw. neues Segment
TARGET_MAIN = "main"    # Hauptlinie


@dataclass
class LinePlan:
    source: str = ""            # bestehende Linie "B.L", z.B. "1.1"
    mode: str = "line"          # "line": neue Linie mit Linienkoppler,
                                # "segment": Linienverstärker in derselben Linie
    new_line: int = 0           # Liniennummer der neuen Linie (mode "line")
    new_name: str = ""
    # Linienkoppler B.L.0 für die bestehende Linie einbauen: sie hängt dann
    # nicht mehr direkt an der Hauptlinie (Chalet: Linie 1.1 ohne Koppler)
    main_line: bool = False
    targets: dict[str, str] = field(default_factory=dict)   # Device.id -> Ziel

    def to_dict(self) -> dict:
        return {"source": self.source, "mode": self.mode, "new_line": self.new_line,
                "new_name": self.new_name, "main_line": self.main_line,
                "targets": dict(self.targets)}

    @classmethod
    def from_dict(cls, data: dict) -> LinePlan:
        return cls(source=data.get("source", ""), mode=data.get("mode", "line"),
                   new_line=int(data.get("new_line", 0) or 0),
                   new_name=data.get("new_name", ""),
                   main_line=bool(data.get("main_line", False)),
                   targets=dict(data.get("targets") or {}))
