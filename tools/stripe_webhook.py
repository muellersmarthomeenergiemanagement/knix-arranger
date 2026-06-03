"""
KNiX Arranger – Stripe Webhook Server
Empfaengt Stripe-Zahlungsbestaetigung und sendet automatisch die Lizenzdatei.

Voraussetzungen:
    pip install flask stripe

Konfiguration in tools/stripe_config.json:
{
  "stripe_secret_key":  "sk_live_...",
  "stripe_webhook_secret": "whsec_...",
  "product_name": "KNiX Arranger Einzellizenz",
  "license_type": "single",
  "expiry_days": 36500
}

Auf dem NAS starten:
    python tools/stripe_webhook.py

Stripe-Dashboard: Developers > Webhooks > Endpoint hinzufuegen
  URL: https://ihr-nas.example.com:5001/webhook
  Events: checkout.session.completed
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(Path(__file__).parent)  # Damit key_generator + send_license importierbar sind

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("stripe_webhook")

CONFIG_PATH = Path(__file__).parent / "stripe_config.json"
MAIL_CONFIG_PATH = Path(__file__).parent / "mail_config.json"


def load_config(path: Path) -> dict:
    if not path.exists():
        logger.error(f"Konfiguration fehlt: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def create_app():
    from flask import Flask, request, abort
    import stripe
    from key_generator import generate_license
    from send_license import send_license_email

    stripe_cfg = load_config(CONFIG_PATH)
    mail_cfg = load_config(MAIL_CONFIG_PATH)

    stripe.api_key = stripe_cfg["stripe_secret_key"]
    webhook_secret = stripe_cfg["stripe_webhook_secret"]

    app = Flask(__name__)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        payload = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.error.SignatureVerificationError:
            logger.warning("Ungültige Stripe-Signatur")
            abort(400)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            customer_name = session.get("customer_details", {}).get("name", "Kunde")
            customer_email = session.get("customer_details", {}).get("email", "")

            if not customer_email:
                logger.error("Keine E-Mail in Stripe-Session")
                return ("", 200)

            logger.info(f"Neue Zahlung: {customer_name} <{customer_email}>")

            try:
                license_path = generate_license(
                    customer=customer_name,
                    email=customer_email,
                    license_type=stripe_cfg.get("license_type", "single"),
                    expiry_days=stripe_cfg.get("expiry_days", 36500),
                )
                send_license_email(customer_name, customer_email, license_path, mail_cfg)
                logger.info(f"Lizenz gesendet an {customer_email}")
            except Exception as e:
                logger.error(f"Fehler beim Lizenz-Versand: {e}", exc_info=True)

        return ("", 200)

    @app.route("/health")
    def health():
        return ("OK", 200)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5001, debug=False)
