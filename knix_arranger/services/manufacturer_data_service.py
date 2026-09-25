"""
Herstellerdaten-Bibliothek fuer den KNXPROJ-Export mit Produktreferenz.

Ein Geraet im ETS-Projekt verweist per ProductRefId/Hardware2ProgramRefId auf
Herstellerdaten (M-XXXX/Hardware.xml, Catalog.xml, Applikationsprogramme), die
im selben Archiv liegen muessen -- samt Signaturdatei M-XXXX.signature. Die
Dateien sind signiert und werden deshalb nur unveraendert und vollstaendig je
Hersteller aus einer Quelle kopiert, nie zusammengestellt.

Quellen sind die .knxprod-Dateien im Ordner "Produkte KNX" des Arbeitsbereichs:
Produktdatenbanken der Hersteller (Format project/20) und aus ETS6-Projekten
extrahierte Bibliotheken (project/23, siehe KnxprojImportService.
extract_product_libraries). Bevorzugt wird das ETS6-Format, dann die kleinste
Datei, die alle benoetigten Geraete abdeckt (signierte Quellen zuerst).
"""
from __future__ import annotations
import glob
import logging
import os
import re
import zipfile
from dataclasses import dataclass

logger = logging.getLogger("knix_arranger.manufacturer_data")

ETS6_NAMESPACE = "http://knx.org/xml/project/23"
ETS5_NAMESPACE = "http://knx.org/xml/project/20"

_HW2PROG_ID = re.compile(rb'<Hardware2Program\s[^>]*?\bId="([^"]+)"')
_NAMESPACE = re.compile(rb'xmlns="([^"]+)"')
_MASTER_VERSION = re.compile(rb'<MasterData\s[^>]*?\bVersion="(\d+)"')


@dataclass(frozen=True)
class ManufacturerSource:
    """Herstellerdaten eines Herstellers in einer .knxprod-Datei."""
    path: str
    mfr_id: str
    size: int                    # komprimierte Groesse des Herstellerordners
    namespace: str
    signed: bool                 # M-XXXX.signature vorhanden
    hw2prog_ids: frozenset[str]

    @property
    def is_ets6(self) -> bool:
        return self.namespace == ETS6_NAMESPACE


def manufacturer_of(ets_id: str) -> str:
    """Hersteller-ID aus einer ETS-Kennung ("M-0083_H-..." -> "M-0083")."""
    return ets_id.split("_", 1)[0] if ets_id.startswith("M-") else ""


# Index je Datei (Pfad, Aenderungszeit, Groesse) -> Quellen; grosse
# Herstellerdatenbanken (ABB ~150 MB) nur einmal pro Programmlauf lesen.
_index_cache: dict[tuple[str, float, int], list[ManufacturerSource]] = {}


class ManufacturerDataLibrary:
    def __init__(self, folder: str):
        self._folder = folder

    def sources(self) -> list[ManufacturerSource]:
        result: list[ManufacturerSource] = []
        if not self._folder or not os.path.isdir(self._folder):
            return result
        for path in sorted(glob.glob(os.path.join(self._folder, "*.knxprod"))):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            key = (path, stat.st_mtime, stat.st_size)
            if key not in _index_cache:
                _index_cache[key] = self._scan(path)
            result.extend(_index_cache[key])
        return result

    @staticmethod
    def _scan(path: str) -> list[ManufacturerSource]:
        try:
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                names = {i.filename for i in infos}
                folders = {
                    n.split("/", 1)[0] for n in names
                    if n.startswith("M-") and "/" in n
                }
                found = []
                for mfr in sorted(folders):
                    hw_path = f"{mfr}/Hardware.xml"
                    if hw_path not in names:
                        continue
                    data = zf.read(hw_path)
                    ns = _NAMESPACE.search(data[:2000])
                    found.append(ManufacturerSource(
                        path=path,
                        mfr_id=mfr,
                        size=sum(i.compress_size for i in infos
                                 if i.filename.startswith(f"{mfr}/")),
                        namespace=ns.group(1).decode() if ns else "",
                        signed=f"{mfr}.signature" in names,
                        hw2prog_ids=frozenset(
                            m.decode() for m in _HW2PROG_ID.findall(data)
                        ),
                    ))
                return found
        except (zipfile.BadZipFile, OSError) as e:
            logger.warning(f"Herstellerdaten in {path} nicht lesbar: {e}")
            return []

    def choose(
        self, needed: dict[str, set[str]], only_namespace: str = "",
    ) -> dict[str, ManufacturerSource]:
        """Je Hersteller die beste Quelle fuer die benoetigten
        Hardware2Program-Kennungen: vollstaendige Abdeckung vor teilweiser,
        signiert vor unsigniert (aeltere Extraktionen ohne Signatur), ETS6-
        Format vor aelterem, kleiner vor groesser. only_namespace beschraenkt
        auf ein Format (ETS5-Export: nur project/20)."""
        by_mfr: dict[str, list[ManufacturerSource]] = {}
        for src in self.sources():
            if only_namespace and src.namespace != only_namespace:
                continue
            by_mfr.setdefault(src.mfr_id, []).append(src)
        chosen: dict[str, ManufacturerSource] = {}
        for mfr, ids in needed.items():
            candidates = [s for s in by_mfr.get(mfr, []) if s.hw2prog_ids & ids]
            if not candidates:
                continue
            chosen[mfr] = min(candidates, key=lambda s: (
                -len(s.hw2prog_ids & ids), not s.signed, not s.is_ets6, s.size,
            ))
        return chosen

    @staticmethod
    def write(zf_out: zipfile.ZipFile, chosen: dict[str, ManufacturerSource],
              existing: set[str]) -> None:
        """Kopiert je Hersteller den Ordner M-XXXX/ und M-XXXX.signature
        unveraendert ins Archiv, dazu die knx_master.xml mit der hoechsten
        MasterData-Version (ETS6-Format bevorzugt). Namen in existing (z.B. aus
        einem Basis-Projekt) werden nicht doppelt geschrieben."""
        master: tuple[tuple[bool, int], bytes] | None = None
        for src in chosen.values():
            with zipfile.ZipFile(src.path) as zf_in:
                for item in zf_in.infolist():
                    name = item.filename
                    if not (name.startswith(f"{src.mfr_id}/")
                            or name == f"{src.mfr_id}.signature"):
                        continue
                    if name in existing or (name.endswith("/") and item.file_size == 0):
                        continue
                    zf_out.writestr(item, zf_in.read(name))
                    existing.add(name)
                if "knx_master.xml" in zf_in.namelist():
                    data = zf_in.read("knx_master.xml")
                    version = _MASTER_VERSION.search(data)
                    rank = (src.is_ets6, int(version.group(1)) if version else 0)
                    if master is None or rank > master[0]:
                        master = (rank, data)
        if master and "knx_master.xml" not in existing:
            zf_out.writestr("knx_master.xml", master[1])
            existing.add("knx_master.xml")
