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
import json
import sys
from pathlib import Path

# Für den Lizenzschlüssel wird der Lizenzdienst der App verwendet (gleiches
# Format beim Codieren und Einfügen) -- Projektwurzel dafür importierbar machen
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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


def license_key_for(license_path: str) -> str | None:
    """Lizenzschlüssel zum Kopieren (siehe license_service.encode_license_key);
    None, wenn die Datei fehlt oder unlesbar ist."""
    from knix_arranger.services.license_service import encode_license_key
    try:
        with open(license_path, "r", encoding="utf-8") as f:
            return encode_license_key(json.load(f))
    except (OSError, ValueError):
        return None


def _insert_key_block(lines: list[str], license_path: str, formal: bool, as_html: bool) -> None:
    """Fügt vor "Bei Fragen …" (letzte Zeile) einen Block mit dem
    Lizenzschlüssel ein -- zum Einfügen in der App statt der Datei."""
    key = license_key_for(license_path)
    if not key:
        return
    intro = (
        "Alternativ zur Datei können Sie diesen Lizenzschlüssel kopieren und in KNiX Arranger "
        "unter «Lizenzschlüssel einfügen…» einfügen (ab Version 1.1.18):"
        if formal else
        "Alternativ zur Datei kannst Du diesen Lizenzschlüssel kopieren und in KNiX Arranger "
        "unter «Lizenzschlüssel einfügen…» einfügen (ab Version 1.1.18):"
    )
    chunks = [key[i:i + 64] for i in range(0, len(key), 64)]
    if as_html:
        block = [
            "", intro,
            '<span style="font-family: Consolas, \'Courier New\', monospace; font-size: 12px;">'
            + "<br>".join(chunks) + "</span>",
        ]
    else:
        block = ["", intro] + chunks
    lines[-2:-2] = block


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
    elif formal:
        lines = [
            f"Guten Tag {customer}",
            "",
            "Vielen Dank für Ihren Kauf von KNiX Arranger.",
            "",
            "Ihre persönliche Lizenzdatei ist dieser E-Mail beigefügt.",
            "",
            "So aktivieren Sie Ihre Lizenz:",
            "  1. Laden Sie KNiX Arranger von GitHub herunter und installieren Sie das Programm:",
            f"     {github_url}",
            "  2. Beim ersten Start erscheint der Lizenz-Dialog.",
            "  3. Klicken Sie auf «Lizenzdatei auswählen» und wählen Sie die mitgelieferte",
            f"     Datei ({filename}) aus.",
            "  4. Die Lizenz wird automatisch aktiviert.",
            "",
            "Bei Fragen stehen wir Ihnen gerne zur Verfügung.",
        ]
    else:
        lines = [
            f"Hallo {customer}",
            "",
            "Vielen Dank für Deinen Kauf von KNiX Arranger.",
            "",
            "Deine persönliche Lizenzdatei ist dieser E-Mail beigefügt.",
            "",
            "So aktivierst Du Deine Lizenz:",
            "  1. Lade KNiX Arranger von GitHub herunter und installiere das Programm:",
            f"     {github_url}",
            "  2. Beim ersten Start erscheint der Lizenz-Dialog.",
            "  3. Klicke auf «Lizenzdatei auswählen» und wähle die mitgelieferte",
            f"     Datei ({filename}) aus.",
            "  4. Die Lizenz wird automatisch aktiviert.",
            "",
            "Bei Fragen stehen wir Dir gerne zur Verfügung.",
        ]
    _insert_key_block(lines, license_path, formal, as_html=False)
    return "\n".join(lines + ["", "Freundliche Grüsse", SENDER_NAME])


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
    _insert_key_block(lines, license_path, formal, as_html=True)
    return "<br>\n".join(lines)


def _attach_license(mail, license_path: str, attempts: int = 6, pause: float = 0.5) -> None:
    """Hängt die Lizenzdatei an und prüft, dass sie wirklich in der Mail ist.

    Eine frisch erzeugte Datei kann kurz gesperrt sein (z.B. durch einen
    Virenscanner) -- daher mehrere Versuche. Schlägt es endgültig fehl, gibt
    es einen RuntimeError mit verständlicher Meldung.
    """
    import time
    path = Path(license_path).resolve()
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            mail.Attachments.Add(str(path))
            break
        except Exception as e:  # COM-Fehler, Datei gesperrt o.ä.
            last_error = e
            time.sleep(pause)
    names = [mail.Attachments.Item(i).FileName for i in range(1, mail.Attachments.Count + 1)]
    if path.name not in names:
        raise RuntimeError(
            f"Die Lizenzdatei {path.name} konnte nicht an die E-Mail angehängt werden"
            + (f" ({last_error})" if last_error else "")
            + ". Es wurde kein Entwurf gespeichert."
        )


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
    try:
        # Lizenz ZUERST anhängen: schlägt das fehl, wird die Mail verworfen,
        # bevor Outlook einen unvollständigen Entwurf ohne Lizenz speichert
        # (am 24.09.2026 lag so ein Entwurf nur mit Signaturbildern vor).
        _attach_license(mail, license_path)

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
    except Exception:
        mail.Close(1)  # olDiscard: nichts speichern
        raise

    if display:
        # Entwurf immer auch in "Entwürfe" ablegen und das Fenster nach vorne
        # holen -- sonst öffnet Outlook es teils unbemerkt hinter dem
        # Lizenz-Manager und es sieht aus, als wäre nichts passiert.
        mail.Save()
        mail.Display()
        try:
            mail.GetInspector.Activate()
        except Exception:
            pass  # Aktivieren ist nur Komfort; der Entwurf existiert trotzdem
    else:
        mail.Send()


# ── Versandstatus ────────────────────────────────────────────────────────────
# Der Lizenz-Manager startet Outlook classic per COM unsichtbar (ohne
# Hauptfenster). Nach "Senden" schliesst sich das Entwurfsfenster, den
# Postausgang sieht man nie -- eine hängende Mail fällt so nicht auf
# (am 23.09.2026 lag eine Lizenz-Mail einen Tag unbemerkt im Postausgang).

_LICENSE_SUBJECT_MARKER = "KNiX Arranger Lizenz"


def _is_license_mail(item) -> bool:
    try:
        return _LICENSE_SUBJECT_MARKER in (item.Subject or "")
    except Exception:
        return False


def license_mail_status(since) -> dict:
    """Stand der Lizenz-Mails in Outlook classic seit `since` (datetime, lokal).

    Rückgabe: {"outbox": [Betreff, ...], "sent": [(Betreff, Zeit), ...]}
    Nur lesend. Wirft eine Exception, wenn Outlook nicht erreichbar ist.
    """
    import win32com.client
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")

    outbox = [it.Subject for it in ns.GetDefaultFolder(4).Items if _is_license_mail(it)]

    sent = []
    items = ns.GetDefaultFolder(5).Items
    items.Sort("[SentOn]", True)
    for i, it in enumerate(items):
        if i >= 30:
            break
        try:
            sent_on = it.SentOn.replace(tzinfo=None)
        except Exception:
            continue
        if sent_on < since:
            break
        if _is_license_mail(it):
            sent.append((it.Subject, sent_on))
    return {"outbox": outbox, "sent": sent}


def trigger_send_receive() -> None:
    """Stösst "Senden/Empfangen" in Outlook classic an (verschickt, was im
    Postausgang zum Senden bereitliegt)."""
    import win32com.client
    win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI").SendAndReceive(False)
