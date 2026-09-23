"""
KNiX Arranger - Lizenz-E-Mail als Outlook-Entwurf erstellen

Nutzt die lokal installierte MS-Outlook-Desktop-Anwendung per COM-Automation
(pywin32), damit keine SMTP-Zugangsdaten hinterlegt werden muessen. Die
E-Mail wird standardmaessig nur als Entwurf geoeffnet - Versand erfolgt
manuell durch Klick auf "Senden" in Outlook. Die in Outlook hinterlegte
Standard-Signatur fuer neue Nachrichten wird automatisch uebernommen.

Anrede: Pro Empfaenger waehlbar zwischen "Sie" (formal) und "Du" (informal)
ueber den Parameter `formal` (siehe build_license_mail_body / create_license_draft).

Voraussetzung:
    pip install pywin32
    MS Outlook Desktop muss installiert und mit dem Geschaeftskonto
    (info@muellersmarthomeenergiemanagement.ch) verbunden sein.
    Unter Outlook > Optionen > E-Mail > Signaturen muss eine Standard-
    signatur fuer "Neue Nachrichten" hinterlegt sein, sonst bleibt der
    Signaturbereich leer.
"""
from __future__ import annotations
import html
from pathlib import Path

GITHUB_RELEASES_URL = (
    "https://github.com/muellersmarthomeenergiemanagement/"
    "knix-arranger-releases/releases/latest"
)

SENDER_NAME = "Müller SmartHome & EnergieManagement"


def mail_subject(formal: bool = True) -> str:
    """Betreffzeile passend zur gewählten Anrede."""
    return "Ihre KNiX Arranger Lizenz" if formal else "Deine KNiX Arranger Lizenz"


def build_license_mail_body(
    customer: str,
    license_path: str,
    github_url: str = GITHUB_RELEASES_URL,
    formal: bool = True,
) -> str:
    """Reine Text-Variante des Mailtexts (fuer den SMTP-Versand ohne Outlook-Signatur).

    formal=True (Standard): Sie-Form. formal=False: Du-Form.
    """
    filename = Path(license_path).name
    if formal:
        return (
            f"Guten Tag {customer}\n\n"
            "Vielen Dank für Ihren Kauf von KNiX Arranger.\n\n"
            "Ihre persönliche Lizenzdatei ist dieser E-Mail beigefügt.\n\n"
            "So aktivieren Sie Ihre Lizenz:\n"
            "  1. Laden Sie KNiX Arranger von GitHub herunter und installieren Sie das Programm:\n"
            f"     {github_url}\n"
            "  2. Beim ersten Start erscheint der Lizenz-Dialog.\n"
            "  3. Klicken Sie auf «Lizenzdatei auswählen» und wählen Sie die mitgelieferte\n"
            f"     Datei ({filename}) aus.\n"
            "  4. Die Lizenz wird automatisch aktiviert.\n\n"
            "Bei Fragen stehen wir Ihnen gerne zur Verfügung.\n\n"
            "Freundliche Grüsse\n"
            f"{SENDER_NAME}"
        )
    return (
        f"Hallo {customer}\n\n"
        "Vielen Dank für deinen Kauf von KNiX Arranger.\n\n"
        "Deine persönliche Lizenzdatei ist dieser E-Mail beigefügt.\n\n"
        "So aktivierst du deine Lizenz:\n"
        "  1. Lade KNiX Arranger von GitHub herunter und installiere das Programm:\n"
        f"     {github_url}\n"
        "  2. Beim ersten Start erscheint der Lizenz-Dialog.\n"
        "  3. Klicke auf «Lizenzdatei auswählen» und wähle die mitgelieferte\n"
        f"     Datei ({filename}) aus.\n"
        "  4. Die Lizenz wird automatisch aktiviert.\n\n"
        "Bei Fragen stehen wir dir gerne zur Verfügung.\n\n"
        "Freundliche Grüsse\n"
        f"{SENDER_NAME}"
    )


def _build_message_html(
    customer: str,
    license_path: str,
    github_url: str,
    formal: bool = True,
) -> str:
    """HTML-Variante ohne Absenderzeile (die liefert die Outlook-Signatur)."""
    customer_e = html.escape(customer)
    filename_e = html.escape(Path(license_path).name)
    link_e = html.escape(github_url)

    if formal:
        lines = [
            f"Guten Tag {customer_e}",
            "",
            "Vielen Dank für Ihren Kauf von KNiX Arranger.",
            "",
            "Ihre persönliche Lizenzdatei ist dieser E-Mail beigefügt.",
            "",
            "So aktivieren Sie Ihre Lizenz:",
            f"1. Laden Sie KNiX Arranger von GitHub herunter und installieren Sie das Programm: "
            f'<a href="{github_url}">{link_e}</a>',
            "2. Beim ersten Start erscheint der Lizenz-Dialog.",
            f"3. Klicken Sie auf «Lizenzdatei auswählen» und wählen Sie die mitgelieferte Datei "
            f"({filename_e}) aus.",
            "4. Die Lizenz wird automatisch aktiviert.",
            "",
            "Bei Fragen stehen wir Ihnen gerne zur Verfügung.",
        ]
    else:
        lines = [
            f"Hallo {customer_e}",
            "",
            "Vielen Dank für deinen Kauf von KNiX Arranger.",
            "",
            "Deine persönliche Lizenzdatei ist dieser E-Mail beigefügt.",
            "",
            "So aktivierst du deine Lizenz:",
            f"1. Lade KNiX Arranger von GitHub herunter und installiere das Programm: "
            f'<a href="{github_url}">{link_e}</a>',
            "2. Beim ersten Start erscheint der Lizenz-Dialog.",
            f"3. Klicke auf «Lizenzdatei auswählen» und wähle die mitgelieferte Datei "
            f"({filename_e}) aus.",
            "4. Die Lizenz wird automatisch aktiviert.",
            "",
            "Bei Fragen stehen wir dir gerne zur Verfügung.",
        ]
    return "<br>\n".join(lines)


def create_license_draft(
    customer: str,
    email: str,
    license_path: str,
    github_url: str = GITHUB_RELEASES_URL,
    display: bool = True,
    formal: bool = True,
) -> None:
    """Erstellt eine Lizenz-E-Mail in Outlook (Entwurf oder Direktversand).

    display=True (Standard): oeffnet die Mail als Entwurf zur Kontrolle,
        Versand erfolgt manuell in Outlook.
    display=False: sendet die Mail sofort ueber das in Outlook konfigurierte
        Geschaeftskonto.
    formal=True (Standard): Anrede in der Sie-Form. formal=False: Du-Form.

    Die in Outlook fuer neue Nachrichten hinterlegte Standard-Signatur wird
    automatisch unter den Mailtext gesetzt.
    """
    import win32com.client  # Import hier, damit das Modul auch ohne pywin32 importierbar bleibt

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    mail.To = email
    mail.Subject = mail_subject(formal)

    # GetInspector (ohne das Fenster anzuzeigen) veranlasst Outlook, die
    # Standard-Signatur fuer neue Nachrichten in HTMLBody einzufuegen.
    mail.GetInspector
    signature_html = mail.HTMLBody

    message_html = _build_message_html(customer, license_path, github_url, formal=formal)
    mail.HTMLBody = f"{message_html}<br><br>\n{signature_html}"

    mail.Attachments.Add(str(Path(license_path).resolve()))

    if display:
        mail.Display()
    else:
        mail.Send()
