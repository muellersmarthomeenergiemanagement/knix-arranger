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


def create_crash_report(error: Exception) -> str:
    """
    Erstellt einen Crash-Report (NFA-143).
    Gibt den Dateipfad des Reports zurück.
    """
    import traceback
    import platform
    from datetime import datetime
    from knix_arranger import __version__

    log_dir = get_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(log_dir, f"crash_report_{timestamp}.txt")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("KNiX Arranger - Crash Report\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Datum/Zeit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Software-Version: {__version__}\n")
        f.write(f"Betriebssystem: {platform.system()} {platform.version()}\n")
        f.write(f"Python: {platform.python_version()}\n")
        f.write(f"Architektur: {platform.machine()}\n\n")
        f.write("Fehlermeldung:\n")
        f.write(f"  {type(error).__name__}: {error}\n\n")
        f.write("Stack-Trace:\n")
        f.write(traceback.format_exc())
        f.write("\n")

    return report_path
