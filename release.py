"""
KNiX Arranger – Release-Skript
Neue Version bauen, als ZIP bereitstellen und optional auf GitHub veröffentlichen.

Ausfuehren:
    python release.py 1.1.0          # nur Build + ZIP
    python release.py 1.1.0 --github # Build + ZIP + GitHub Release erstellen

Voraussetzung fuer --github:
    GitHub CLI (gh) installiert und eingeloggt: https://cli.github.com/
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
INIT_FILE = ROOT / "knix_arranger" / "__init__.py"
ISS_FILE = ROOT / "setup.iss"


def set_version(new_version: str):
    """Setzt die Version in __init__.py und setup.iss."""
    text = INIT_FILE.read_text(encoding="utf-8")
    text = re.sub(r'__version__\s*=\s*"[^"]+"', f'__version__ = "{new_version}"', text)
    INIT_FILE.write_text(text, encoding="utf-8")

    iss = ISS_FILE.read_text(encoding="utf-8")
    iss = re.sub(r'(#define AppVersion\s+")([^"]+)(")', rf'\g<1>{new_version}\g<3>', iss)
    ISS_FILE.write_text(iss, encoding="utf-8")

    print(f"Version gesetzt: {new_version}")


def build():
    print("Starte PyInstaller-Build...")
    result = subprocess.run([sys.executable, "build.py"], cwd=ROOT)
    if result.returncode != 0:
        print("FEHLER: Build fehlgeschlagen.")
        sys.exit(1)


def create_zip(version: str) -> Path:
    dist_dir = ROOT / "dist" / "KNiX_Arranger"
    zip_name = ROOT / "dist" / f"KNiX_Arranger_v{version}"
    shutil.make_archive(str(zip_name), "zip", dist_dir.parent, dist_dir.name)
    zip_path = Path(str(zip_name) + ".zip")
    print(f"ZIP erstellt: {zip_path}")
    return zip_path


def create_github_release(version: str, installer_path: Path):
    """Erstellt ein GitHub Release mit dem Installer als Asset.

    Voraussetzung: gh CLI eingeloggt (gh auth login).
    Tag-Format: v1.2.0
    """
    if not installer_path.exists():
        print(f"WARNUNG: Installer nicht gefunden: {installer_path}")
        print("  Bitte erst Inno Setup kompilieren (setup.iss), dann erneut ausfuehren.")
        return

    tag = f"v{version}"
    print(f"\nErstelle GitHub Release {tag}...")

    result = subprocess.run(
        [
            "gh", "release", "create", tag,
            str(installer_path),
            "--repo", "muellersmarthomeenergiemanagement/knix-arranger-releases",
            "--title", f"KNiX Arranger {version}",
            "--notes", f"KNiX Arranger Version {version}",
            "--latest",
        ],
        cwd=ROOT,
    )
    if result.returncode == 0:
        print(f"GitHub Release {tag} erfolgreich erstellt!")
        print(f"  Asset: {installer_path.name}")
    else:
        print("FEHLER: GitHub Release fehlgeschlagen.")
        print("  Pruefen: gh auth status")


def main():
    if len(sys.argv) < 2:
        sys.path.insert(0, str(ROOT))
        from knix_arranger import __version__
        print(f"Aktuelle Version: {__version__}")
        print(f"Aufruf: python release.py <neue-version>  (z.B. python release.py 1.1.0)")
        print(f"        python release.py <neue-version> --github  (inkl. GitHub Release)")
        sys.exit(0)

    new_version = sys.argv[1].strip()
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print("Format: Major.Minor.Patch  (z.B. 1.1.0)")
        sys.exit(1)

    publish_github = "--github" in sys.argv

    set_version(new_version)
    build()
    zip_path = create_zip(new_version)

    print()
    print(f"Release {new_version} fertig!")
    print(f"  ZIP fuer Beta-Versand:  {zip_path}")
    print(f"  Installer bauen:        Inno Setup > setup.iss > Compile")

    installer_path = ROOT / "installer" / f"KNiX_Arranger_Setup_v{new_version}.exe"

    if publish_github:
        create_github_release(new_version, installer_path)
    else:
        print()
        print(f"  GitHub Release:  python release.py {new_version} --github")
        print(f"  (nach Inno Setup Compile)")


if __name__ == "__main__":
    main()
