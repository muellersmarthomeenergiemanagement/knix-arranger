"""
Registriert die .knxarr-Dateizuordnung in Windows,
sodass ein Doppelklick auf eine .knxarr-Datei den KNiX Arranger öffnet.

Ausführen mit: python register_file_association.py
Entfernen mit: python register_file_association.py --remove
"""
import sys
import os
import winreg


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_SCRIPT  = os.path.join(SCRIPT_DIR, "run.py")
PYTHON_EXE  = sys.executable

PROG_ID     = "KNiXArranger.Project"
EXT         = ".knxarr"
DESCRIPTION = "KNiX Arranger Projekt"
OPEN_CMD    = f'"{PYTHON_EXE}" "{RUN_SCRIPT}" "%1"'


def _set_key(root, path, value="", name=""):
    with winreg.CreateKey(root, path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def register():
    # Dateierweiterung → ProgID
    _set_key(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{EXT}", PROG_ID)

    # ProgID → Beschreibung
    _set_key(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}", DESCRIPTION)

    # Icon (optionales Icon aus Python-Installation)
    _set_key(winreg.HKEY_CURRENT_USER,
             rf"Software\Classes\{PROG_ID}\DefaultIcon",
             f'"{PYTHON_EXE}",0')

    # Öffnen-Befehl
    _set_key(winreg.HKEY_CURRENT_USER,
             rf"Software\Classes\{PROG_ID}\shell\open\command",
             OPEN_CMD)

    print(f"Dateizuordnung registriert:")
    print(f"  Erweiterung : {EXT}")
    print(f"  Befehl      : {OPEN_CMD}")
    print()
    print("Hinweis: Explorer-Fenster neu starten, damit die Änderung sichtbar wird.")


def remove():
    def _del(root, path):
        try:
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command")
    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open")
    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell")
    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\DefaultIcon")
    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}")
    _del(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{EXT}")
    print("Dateizuordnung entfernt.")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        register()
