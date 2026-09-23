"""
Release-Notes ("Was ist neu") aus config/release_notes.json.

Eine Quelle für drei Stellen:
- Dialog "Was ist neu" nach einem Update bzw. über das Hilfe-Menü
- Text des GitHub-Release (den der Update-Dialog VOR dem Download anzeigt)
- Release-Prüfung in CI/release.py: ohne Eintrag für die Version kein Release

Kommandozeile (CI):
    python -m knix_arranger.services.release_notes_service 1.1.16 --output notes.md
    → schreibt die Notes als Markdown, Exit-Code 1 wenn der Eintrag fehlt.
"""
from __future__ import annotations
import argparse
import html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

RELEASE_NOTES_PATH = Path(__file__).parent.parent / "config" / "release_notes.json"

# Anzeige-Reihenfolge und Überschriften der Kategorien
CATEGORIES = [
    ("neu", "Neu"),
    ("verbessert", "Verbessert"),
    ("behoben", "Behoben"),
]


def parse_version(version: str) -> tuple[int, ...]:
    """'1.1.16' → (1, 1, 16); ungültige Teile zählen als 0."""
    parts = []
    for part in (version or "").strip().lstrip("v").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


@dataclass
class ReleaseNotes:
    version: str
    date: str = ""
    items: dict[str, list[str]] = field(default_factory=dict)  # Kategorie → Punkte

    @classmethod
    def from_dict(cls, data: dict) -> ReleaseNotes:
        return cls(
            version=data["version"],
            date=data.get("date", ""),
            items={key: list(data.get(key) or []) for key, _ in CATEGORIES},
        )

    def to_markdown(self) -> str:
        lines: list[str] = []
        for key, title in CATEGORIES:
            if self.items.get(key):
                lines.append(f"### {title}")
                lines.extend(f"- {item}" for item in self.items[key])
                lines.append("")
        return "\n".join(lines).strip() + "\n"

    def to_html(self) -> str:
        date = f" <span style='color:#808080;'>({html.escape(self.date)})</span>" if self.date else ""
        parts = [f"<h3>Version {html.escape(self.version)}{date}</h3>"]
        for key, title in CATEGORIES:
            if self.items.get(key):
                parts.append(f"<p><b>{title}</b></p><ul>")
                parts.extend(f"<li>{html.escape(item)}</li>" for item in self.items[key])
                parts.append("</ul>")
        return "".join(parts)


def load_release_notes(path: Path = RELEASE_NOTES_PATH) -> list[ReleaseNotes]:
    """Alle Einträge, neueste Version zuerst."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    notes = [ReleaseNotes.from_dict(v) for v in data.get("versions", [])]
    return sorted(notes, key=lambda n: parse_version(n.version), reverse=True)


def notes_for(version: str, path: Path = RELEASE_NOTES_PATH) -> ReleaseNotes | None:
    target = parse_version(version)
    return next(
        (n for n in load_release_notes(path) if parse_version(n.version) == target),
        None,
    )


def notes_since(last_seen: str, current: str,
                path: Path = RELEASE_NOTES_PATH) -> list[ReleaseNotes]:
    """Einträge neuer als `last_seen` bis einschliesslich `current` (neueste
    zuerst) – deckt auch übersprungene Versionen ab."""
    lower, upper = parse_version(last_seen), parse_version(current)
    return [
        n for n in load_release_notes(path)
        if lower < parse_version(n.version) <= upper
    ]


def notes_to_html(notes: list[ReleaseNotes]) -> str:
    return "<hr>".join(n.to_html() for n in notes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-Notes als Markdown ausgeben")
    parser.add_argument("version", help="Version, z.B. 1.1.16 oder v1.1.16")
    parser.add_argument("--output", help="Zieldatei (Standard: stdout)")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    notes = notes_for(args.version)
    if notes is None:
        print(
            f"FEHLER: Kein Eintrag für Version {args.version} in {RELEASE_NOTES_PATH}.\n"
            f"Bitte die Änderungen dort ergänzen, bevor das Release erstellt wird.",
            file=sys.stderr,
        )
        return 1

    markdown = notes.to_markdown()
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
