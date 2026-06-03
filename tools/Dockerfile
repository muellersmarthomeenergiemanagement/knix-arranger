FROM python:3.11-slim

WORKDIR /app

# Abhängigkeiten
RUN pip install --no-cache-dir flask stripe cryptography

# App-Dateien
COPY key_generator.py .
COPY send_license.py .
COPY stripe_webhook.py .
COPY mail_config.json .
COPY stripe_config.json .
COPY license_private_key.pem .

EXPOSE 5001

CMD ["python", "stripe_webhook.py"]
