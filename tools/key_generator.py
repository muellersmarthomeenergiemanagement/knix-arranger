"""
KNiX Arranger – Lizenzschlüssel-Generator (Admin-Tool)
Erzeugt RSA-signierte Lizenzdateien (.knxlic) fuer Kunden.

Voraussetzung:
    pip install cryptography

Ausfuehren:
    python tools/key_generator.py

Die Datei tools/license_private_key.pem muss vorhanden sein.
ACHTUNG: Privaten Schluessel NIEMALS weitergeben oder ins Repository einchecken!
"""
from __future__ import annotations
import json
import base64
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
PRIVATE_KEY_PATH = Path(__file__).parent / "license_private_key.pem"


def load_private_key():
    if not PRIVATE_KEY_PATH.exists():
        print(f"FEHLER: Privater Schluessel nicht gefunden: {PRIVATE_KEY_PATH}")
        print("Fuehren Sie zuerst 'python tools/generate_keypair.py' aus.")
        sys.exit(1)
    from cryptography.hazmat.primitives import serialization
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def generate_license(
    customer: str,
    email: str,
    license_type: str = "single",
    expiry_days: int = 365,
    output_path: str | None = None,
) -> str:
    """Erstellt eine signierte Lizenzdatei und gibt den Pfad zurueck."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes

    private_key = load_private_key()

    issued = datetime.today().strftime("%Y-%m-%d")
    expiry = (datetime.today() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")

    payload = {
        "customer": customer,
        "email": email,
        "type": license_type,
        "expiry": expiry,
        "issued": issued,
    }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    sig = private_key.sign(
        canonical,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )

    license_data = {
        "payload": payload,
        "signature": base64.b64encode(sig).decode(),
    }

    if output_path is None:
        safe_name = customer.replace(" ", "_").replace("/", "-")[:30]
        output_path = f"{safe_name}_{expiry}.knxlic"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(license_data, f, indent=2, ensure_ascii=False)

    return output_path


def interactive():
    """Interaktiver Modus fuer die Kommandozeile."""
    print("=" * 55)
    print("  KNiX Arranger – Lizenzgenerator")
    print("=" * 55)

    customer = input("Kundenname:          ").strip()
    if not customer:
        print("Abgebrochen.")
        return

    email = input("E-Mail:              ").strip()

    print("Lizenztyp:")
    print("  1) Einzellizenz (single)  – unbegrenzte Laufzeit empfohlen")
    print("  2) Jahreslizenz (annual)  – 365 Tage")
    print("  3) Testlizenz   (trial)   – 30 Tage")
    choice = input("Auswahl [1]: ").strip() or "1"
    type_map = {"1": "single", "2": "annual", "3": "trial"}
    days_map = {"1": 36500, "2": 365, "3": 30}   # single = 100 Jahre
    license_type = type_map.get(choice, "single")
    expiry_days = days_map.get(choice, 365)

    custom_days = input(f"Laufzeit in Tagen [{expiry_days}]: ").strip()
    if custom_days.isdigit():
        expiry_days = int(custom_days)

    output_path = generate_license(customer, email, license_type, expiry_days)

    print()
    print(f"Lizenzdatei erstellt: {output_path}")
    print(f"  Kunde:     {customer}")
    print(f"  E-Mail:    {email}")
    print(f"  Typ:       {license_type}")
    from datetime import datetime, timedelta
    expiry = (datetime.today() + timedelta(days=expiry_days)).strftime("%Y-%m-%d")
    print(f"  Gueltig bis: {expiry}")
    print()
    print("Diese Datei per E-Mail an den Kunden senden.")


if __name__ == "__main__":
    interactive()
