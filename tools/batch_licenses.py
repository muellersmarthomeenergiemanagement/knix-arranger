"""
KNiX Arranger – Batch-Lizenzgenerator
Liest tools/betatester.csv und erstellt fuer jeden Eintrag eine .knxlic-Datei.

CSV-Format (tools/betatester.csv):
    name,email
    Max Muster,max@muster.ch
    Anna Meier,anna@meier.ch

Ausfuehren:
    python tools/batch_licenses.py
"""
import csv
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent.parent))

from key_generator import generate_license

CSV_PATH = Path(__file__).parent / "betatester.csv"
OUT_DIR  = Path(__file__).parent / "lizenzen"

LICENSE_TYPE = "trial"
EXPIRY_DAYS  = 30


def main():
    if not CSV_PATH.exists():
        print(f"FEHLER: {CSV_PATH} nicht gefunden.")
        print("Bitte Datei mit Spalten 'name' und 'email' erstellen.")
        sys.exit(1)

    OUT_DIR.mkdir(exist_ok=True)

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        tester = list(reader)

    if not tester:
        print("Keine Eintraege in der CSV-Datei gefunden.")
        sys.exit(0)

    print(f"Generiere {len(tester)} Lizenzen -> {OUT_DIR}/")
    print()

    ok = 0
    for row in tester:
        name  = row.get("name", "").strip()
        email = row.get("email", "").strip()

        if not name or not email:
            print(f"  ÜBERSPRUNGEN: unvollständiger Eintrag {row}")
            continue

        safe = name.replace(" ", "_").replace("/", "-")[:30]
        from datetime import datetime, timedelta
        expiry = (datetime.today() + timedelta(days=EXPIRY_DAYS)).strftime("%Y-%m-%d")
        out_path = OUT_DIR / f"{safe}_{expiry}.knxlic"

        generate_license(name, email, LICENSE_TYPE, EXPIRY_DAYS, str(out_path))
        print(f"  OK  {name:<30}  {email}")
        ok += 1

    print()
    print(f"{ok} Lizenzdatei(en) erstellt in: {OUT_DIR}/")
    print()
    print("Nächste Schritte:")
    print("  1. dist\\KNiX_Arranger_v1.0.0.zip")
    print("  2. lizenzen\\<Name>.knxlic           (je Person individuell)")
    print("  3. KNiX_Arranger_Betatester_Anleitung.docx")


if __name__ == "__main__":
    main()
