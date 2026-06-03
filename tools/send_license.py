"""
KNiX Arranger – Lizenz per E-Mail versenden
Generiert eine Lizenzdatei und sendet sie an den Kunden.

Konfiguration in tools/mail_config.json:
{
  "smtp_host": "mail.example.com",
  "smtp_port": 587,
  "smtp_user": "info@muellersmarthomeenergiemanagement.ch",
  "smtp_password": "...",
  "sender_name": "Mueller SmartHome & EnergieManagement"
}

Ausfuehren:
    python tools/send_license.py
"""
from __future__ import annotations
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "mail_config.json"
ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(ROOT))


def load_mail_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"FEHLER: {CONFIG_PATH} nicht gefunden.")
        print("Bitte tools/mail_config.json erstellen (siehe Kommentar in diesem Skript).")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def send_license_email(
    customer: str,
    email: str,
    license_path: str,
    config: dict,
):
    """Sendet die Lizenzdatei per E-Mail an den Kunden."""
    msg = MIMEMultipart()
    msg["From"] = f"{config['sender_name']} <{config['smtp_user']}>"
    msg["To"] = email
    msg["Subject"] = "Ihre KNiX Arranger Lizenz"

    body = f"""Guten Tag {customer}

Vielen Dank für Ihren Kauf von KNiX Arranger.

Ihre persönliche Lizenzdatei ist diesem E-Mail beigefügt.

So aktivieren Sie Ihre Lizenz:
  1. Laden Sie KNiX Arranger herunter und installieren Sie das Programm.
  2. Beim ersten Start erscheint der Lizenz-Dialog.
  3. Klicken Sie auf «Lizenzdatei auswählen» und wählen Sie die mitgelieferte
     Datei ({Path(license_path).name}) aus.
  4. Die Lizenz wird automatisch aktiviert.

Bei Fragen stehen wir Ihnen gerne zur Verfügung:
{config['smtp_user']}

Freundliche Grüsse
{config['sender_name']}
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Lizenzdatei anhängen
    with open(license_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f"attachment; filename={Path(license_path).name}",
    )
    msg.attach(part)

    with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
        server.starttls()
        server.login(config["smtp_user"], config["smtp_password"])
        server.send_message(msg)

    print(f"E-Mail gesendet an {email}")


def interactive():
    from key_generator import generate_license  # Importiert aus demselben Verzeichnis

    config = load_mail_config()

    print("=" * 55)
    print("  KNiX Arranger – Lizenz erstellen und versenden")
    print("=" * 55)

    customer = input("Kundenname:   ").strip()
    email = input("E-Mail:       ").strip()

    print("\nLizenztyp:")
    print("  1) Einzellizenz  – 100 Jahre (de facto unbegrenzt)")
    print("  2) Jahreslizenz  – 365 Tage")
    print("  3) Testlizenz    – 30 Tage")
    choice = input("Auswahl [1]: ").strip() or "1"
    type_map = {"1": "single", "2": "annual", "3": "trial"}
    days_map = {"1": 36500, "2": 365, "3": 30}
    license_type = type_map.get(choice, "single")
    expiry_days = days_map.get(choice, 36500)

    # Lizenzdatei generieren
    license_path = generate_license(customer, email, license_type, expiry_days)
    print(f"\nLizenzdatei erstellt: {license_path}")

    confirm = input(f"E-Mail an {email} senden? [J/n]: ").strip().lower()
    if confirm in ("", "j", "y", "ja", "yes"):
        send_license_email(customer, email, license_path, config)
        print("Fertig.")
    else:
        print(f"E-Mail nicht gesendet. Datei liegt unter: {license_path}")


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)  # Damit key_generator.py gefunden wird
    interactive()
