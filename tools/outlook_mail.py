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


def mail_subject(formal: bool = True, renewal: bool = False) -> str:
    """Betreffzeile passend zur gewählten Anrede (und ggf. Erneuerung)."""
    if renewal:
        return ("Erneuerung Ihrer KNiX Arranger Lizenz" if formal
                else "Erneuerung Deiner KNiX Arranger Lizenz")
    return "Ihre KNiX Arranger Lizenz" if formal else "Deine KNiX Arranger Lizenz"


def _renewal_lines(
    customer: str,
    filename: str,
    link: str,
    valid_until: str | None,
    formal: bool,
) -> list[str]:
    """Mailtext bei einer Lizenzerneuerung (ohne Grussformel).

    Die Argumente werden unveraendert eingesetzt - fuer HTML muessen sie
    bereits escaped sein. valid_until=None (z.B. unbegrenzte Lizenz)
    laesst die Angabe zum Ablaufdatum weg.
    """
    if formal:
        validity = f" und gültig bis {valid_until}" if valid_until else ""
        return [
            f"Guten Tag {customer}",
            "",
            "Vielen Dank, dass Sie KNiX Arranger weiterhin nutzen. Ihre Lizenz wurde erneuert.",
            "",
            f"Die neue Lizenzdatei ist dieser E-Mail beigefügt{validity}.",
            "",
            "So aktivieren Sie die neue Lizenz:",
            "1. Starten Sie KNiX Arranger und öffnen Sie im Menü «Hilfe» den Eintrag «Lizenz…». "
            "Ist Ihre bisherige Lizenz bereits abgelaufen, erscheint der Lizenz-Dialog beim "
            "Start automatisch.",
            f"2. Klicken Sie auf «Lizenzdatei auswählen» und wählen Sie die neue Datei "
            f"({filename}) aus.",
            "3. Die neue Lizenz ersetzt die bisherige und ist sofort aktiv. Ihre Projekte und "
            "Einstellungen bleiben unverändert erhalten.",
            "",
            f"Die aktuelle Version von KNiX Arranger finden Sie jederzeit auf GitHub: {link}",
            "",
            "Bei Fragen stehen wir Ihnen gerne zur Verfügung.",
        ]
    validity = f" und gültig bis {valid_until}" if valid_until else ""
    return [
        f"Hallo {customer}",
        "",
        "Vielen Dank, dass Du KNiX Arranger weiterhin nutzt. Deine Lizenz wurde erneuert.",
        "",
        f"Die neue Lizenzdatei ist dieser E-Mail beigefügt{validity}.",
        "",
        "So aktivierst Du die neue Lizenz:",
        "1. Starte KNiX Arranger und öffne im Menü «Hilfe» den Eintrag «Lizenz…». "
        "Ist Deine bisherige Lizenz bereits abgelaufen, erscheint der Lizenz-Dialog beim "
        "Start automatisch.",
        f"2. Klicke auf «Lizenzdatei auswählen» und wähle die neue Datei ({filename}) aus.",
        "3. Die neue Lizenz ersetzt die bisherige und ist sofort aktiv. Deine Projekte und "
        "Einstellungen bleiben unverändert erhalten.",
        "",
        f"Die aktuelle Version von KNiX Arranger findest Du jederzeit auf GitHub: {link}",
        "",
        "Bei Fragen stehen wir Dir gerne zur Verfügung.",
    ]


def build_license_mail_body(
    customer: str,
    license_path: str,
    github_url: str = GITHUB_RELEASES_URL,
    formal: bool = True,
    renewal: bool = False,
    valid_until: str | None = None,
) -> str:
    """Reine Text-Variante des Mailtexts (fuer den SMTP-Versand ohne Outlook-Signatur).

    formal=True (Standard): Sie-Form. formal=False: Du-Form.
    renewal=True: Text fuer eine erneuerte Lizenz (valid_until = neues Ablaufdatum).
    """
    filename = Path(license_path).name
    if renewal:
        lines = _renewal_lines(customer, filename, github_url, valid_until, formal)
        return "\n".join(lines + ["", "Freundliche Grüsse", SENDER_NAME])
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
        "Vielen Dank für Deinen Kauf von KNiX Arranger.\n\n"
        "Deine persönliche Lizenzdatei ist dieser E-Mail beigefügt.\n\n"
        "So aktivierst Du Deine Lizenz:\n"
        "  1. Lade KNiX Arranger von GitHub herunter und installiere das Programm:\n"
        f"     {github_url}\n"
        "  2. Beim ersten Start erscheint der Lizenz-Dialog.\n"
        "  3. Klicke auf «Lizenzdatei auswählen» und wähle die mitgelieferte\n"
        f"     Datei ({filename}) aus.\n"
        "  4. Die Lizenz wird automatisch aktiviert.\n\n"
        "Bei Fragen stehen wir Dir gerne zur Verfügung.\n\n"
        "Freundliche Grüsse\n"
        f"{SENDER_NAME}"
    )


def _build_message_html(
    customer: str,
    license_path: str,
    github_url: str,
    formal: bool = True,
    renewal: bool = False,
    valid_until: str | None = None,
) -> str:
    """HTML-Variante ohne Absenderzeile (die liefert die Outlook-Signatur)."""
    customer_e = html.escape(customer)
    filename_e = html.escape(Path(license_path).name)
    link_e = html.escape(github_url)

    if renewal:
        lines = _renewal_lines(
            customer_e, filename_e, f'<a href="{github_url}">{link_e}</a>',
            html.escape(valid_until) if valid_until else None, formal,
        )
    elif formal:
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
            "Vielen Dank für Deinen Kauf von KNiX Arranger.",
            "",
            "Deine persönliche Lizenzdatei ist dieser E-Mail beigefügt.",
            "",
            "So aktivierst Du Deine Lizenz:",
            f"1. Lade KNiX Arranger von GitHub herunter und installiere das Programm: "
            f'<a href="{github_url}">{link_e}</a>',
            "2. Beim ersten Start erscheint der Lizenz-Dialog.",
            f"3. Klicke auf «Lizenzdatei auswählen» und wähle die mitgelieferte Datei "
            f"({filename_e}) aus.",
            "4. Die Lizenz wird automatisch aktiviert.",
            "",
            "Bei Fragen stehen wir Dir gerne zur Verfügung.",
        ]
    return "<br>\n".join(lines)


def create_license_draft(
    customer: str,
    email: str,
    license_path: str,
    github_url: str = GITHUB_RELEASES_URL,
    display: bool = True,
    formal: bool = True,
    renewal: bool = False,
    valid_until: str | None = None,
) -> None:
    """Erstellt eine Lizenz-E-Mail in Outlook (Entwurf oder Direktversand).

    display=True (Standard): oeffnet die Mail als Entwurf zur Kontrolle,
        Versand erfolgt manuell in Outlook.
    display=False: sendet die Mail sofort ueber das in Outlook konfigurierte
        Geschaeftskonto.
    formal=True (Standard): Anrede in der Sie-Form. formal=False: Du-Form.
    renewal=True: Text und Betreff fuer eine erneuerte Lizenz; valid_until ist
        das neue Ablaufdatum (None = ohne Angabe, z.B. bei unbegrenzter Lizenz).

    Die in Outlook fuer neue Nachrichten hinterlegte Standard-Signatur wird
    automatisch unter den Mailtext gesetzt.
    """
    import win32com.client  # Import hier, damit das Modul auch ohne pywin32 importierbar bleibt

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    mail.To = email
    mail.Subject = mail_subject(formal, renewal)

    # GetInspector (ohne das Fenster anzuzeigen) veranlasst Outlook, die
    # Standard-Signatur fuer neue Nachrichten in HTMLBody einzufuegen.
    mail.GetInspector
    signature_html = mail.HTMLBody

    message_html = _build_message_html(
        customer, license_path, github_url,
        formal=formal, renewal=renewal, valid_until=valid_until,
    )
    mail.HTMLBody = f"{message_html}<br><br>\n{signature_html}"

    mail.Attachments.Add(str(Path(license_path).resolve()))

    if display:
        mail.Display()
    else:
        mail.Send()
