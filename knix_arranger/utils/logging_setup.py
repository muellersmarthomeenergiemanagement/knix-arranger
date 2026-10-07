"""
Logging-Konfiguration (NFA-141 bis NFA-146)
Logdateien in %APPDATA%/KNiX Arranger/logs/
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def get_log_dir() -> str:
    """Gibt das Log-Verzeichnis zurück."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    log_dir = os.path.join(appdata, "KNiX Arranger", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def setup_logging(level: str = "INFO") -> logging.Logger:
    """
    Konfiguriert das Logging-System.
    NFA-142: DEBUG, INFO, WARNING, ERROR, CRITICAL
    NFA-145: Max. 10 MB pro Datei, max. 5 Dateien
    """
    log_dir = get_log_dir()
    log_file = os.path.join(log_dir, "knix_arranger.log")

    logger = logging.getLogger("knix_arranger")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Datei-Handler mit Rotation (NFA-145)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    # Konsolen-Handler (für Entwicklung)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(message)s")
    )
    console_handler.setLevel(logging.WARNING)
    logger.addHandler(console_handler)

    return logger


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def set_log_level(level: str) -> None:
    """Ändert die Protokollstufe im laufenden Betrieb (NFA-142)."""
    logging.getLogger("knix_arranger").setLevel(
        getattr(logging, str(level).upper(), logging.INFO))


_last_action = ""


def set_last_action(text: str) -> None:
    """Merkt sich die letzte Benutzeraktion für den Crash-Report (NFA-143)."""
    global _last_action
    _last_action = text


def _ram_text() -> str:
    """Arbeitsspeicher gesamt/frei (Windows), sonst leer."""
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return ""
        gb = 1024 ** 3
        return f"{status.ullTotalPhys / gb:.1f} GB, frei {status.ullAvailPhys / gb:.1f} GB"
    except Exception:
        return ""


def _screen_text() -> str:
    """Auflösung des Hauptbildschirms, sonst leer."""
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen() if QGuiApplication.instance() else None
        if screen is None:
            return ""
        size = screen.size()
        return f"{size.width()} x {size.height()} (Skalierung {screen.devicePixelRatio():g})"
    except Exception:
        return ""


def create_crash_report(error: BaseException) -> str:
    """
    Erstellt einen Crash-Report (NFA-143): Fehlermeldung, Stack-Trace,
    Systemumgebung (OS, RAM, Bildschirm), Softwareversion, letzte Aktion.
    Gibt den Dateipfad des Reports zurück.
    """
    import traceback
    import platform
    from datetime import datetime
    from knix_arranger import __version__

    log_dir = get_log_dir()
    now = datetime.now()
    report_path = os.path.join(log_dir, f"crash_report_{now.strftime('%Y%m%d_%H%M%S')}.txt")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("KNiX Arranger - Crash Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Datum/Zeit: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Software-Version: {__version__}\n")
        f.write(f"Betriebssystem: {platform.system()} {platform.version()}\n")
        f.write(f"Python: {platform.python_version()}\n")
        f.write(f"Architektur: {platform.machine()}\n")
        f.write(f"Arbeitsspeicher: {_ram_text() or '-'}\n")
        f.write(f"Bildschirm: {_screen_text() or '-'}\n")
        f.write(f"Letzte Aktion: {_last_action or '-'}\n\n")
        f.write("Fehlermeldung:\n")
        f.write(f"  {type(error).__name__}: {error}\n\n")
        f.write("Stack-Trace:\n")
        f.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
        f.write("\n")

    return report_path


_handling = False


def handle_unexpected_error(error: BaseException) -> str:
    """Unerwarteter Fehler im laufenden Betrieb (NFA-041, NFA-143):
    protokollieren, Crash-Report schreiben und dem Benutzer melden.
    Das Programm bleibt offen. Gibt den Pfad des Reports zurück."""
    global _handling
    logger = logging.getLogger("knix_arranger")
    logger.critical(f"Unerwarteter Fehler: {error}",
                    exc_info=(type(error), error, error.__traceback__))
    try:
        report_path = create_crash_report(error)
    except Exception:
        logger.exception("Crash-Report konnte nicht geschrieben werden")
        report_path = ""
    if _handling:                       # Fehler in der Meldung selbst
        return report_path
    _handling = True
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            text = ("Bei dieser Aktion ist ein unerwarteter Fehler aufgetreten. "
                    "Die Aktion wurde nicht oder nur teilweise ausgeführt.\n\n"
                    f"{type(error).__name__}: {error}\n\n"
                    "Bitte das Projekt speichern und den Fehlerbericht an den "
                    "Support senden:")
            box = QMessageBox(QMessageBox.Critical, "Unerwarteter Fehler", text,
                              QMessageBox.Ok, QApplication.activeWindow())
            box.setInformativeText(report_path or get_log_dir())
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.exec()
    except Exception:
        logger.exception("Fehlermeldung konnte nicht angezeigt werden")
    finally:
        _handling = False
    return report_path


def install_exception_hook() -> None:
    """Fängt Fehler ab, die sonst ungesehen verloren gingen (NFA-041):
    in Qt-Slots, Timern und Hintergrund-Threads. Im installierten Programm
    gibt es keine Konsole – ohne Hook fehlte jede Spur."""
    import threading

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        if exc.__traceback__ is None:
            exc.__traceback__ = tb
        handle_unexpected_error(exc)

    def _thread_hook(args):
        if args.exc_value is None or issubclass(args.exc_type, SystemExit):
            return
        # Nur protokollieren: Qt-Dialoge dürfen nicht aus Threads geöffnet werden.
        logging.getLogger("knix_arranger").critical(
            f"Unerwarteter Fehler im Hintergrund ({args.thread.name if args.thread else '?'})",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        try:
            create_crash_report(args.exc_value)
        except Exception:
            pass

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
