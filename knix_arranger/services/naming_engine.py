"""
KNX Swiss Bezeichnungskonzept (FA-401, FA-402, FA-403)
Format: [Gewerk]_[Stockwerk]_[Raum]_[Nr] [Funktion] ([Klartext])

Das Stockwerk steht nur bei reinen Nummern: Raumnummern je Stockwerk ("04")
sind erst mit dem Stockwerk eindeutig ("J_DG_04_02"); Nummern mit Buchstaben
tragen Stockwerk bzw. Zone schon ("E01", "SEG02" -> "J_E01_02").
"""


def label_floor_code(floor_code: str, room_number: str) -> str:
    """Stockwerk-Kürzel für die Bezeichnung, "" wenn die Raumnummer
    Buchstaben enthält (Stockwerk/Zone schon drin)."""
    if not floor_code or any(c.isalpha() for c in room_number or ""):
        return ""
    return floor_code


def element_code(gewerk_code: str, floor_code: str, room_number: str,
                 element_number: int) -> str:
    """"J_DG_04_02" bzw. "J_EG01_02" (floor_code wie von label_floor_code)."""
    parts = (gewerk_code, floor_code, room_number, f"{element_number:02d}")
    return "_".join(p for p in parts if p)


class NamingEngine:
    """Erzeugt GA-Bezeichnungen nach KNX Swiss Standard."""

    @staticmethod
    def create_designation(gewerk_code: str, room_number: str,
                           element_number: int, function_name: str,
                           description: str = "", floor_code: str = "") -> str:
        """
        Erstellt eine GA-Bezeichnung (BZ-01 bis BZ-06).

        Args:
            gewerk_code: Kürzel, z.B. "LD"
            room_number: Raumnummer, z.B. "E05"
            element_number: Fortlaufend pro Raum/Gewerk, z.B. 1
            function_name: Funktion, z.B. "E/A", "DIM", "WERT"
            description: Optionaler Klartext, z.B. "Eingang Decke"
            floor_code: Stockwerk-Kürzel, siehe label_floor_code

        Returns:
            z.B. "LD_E05_01 E/A (Eingang Decke)", "J_DG_04_02 AUF/AB (Schlafen)"
        """
        label = element_code(gewerk_code, floor_code, room_number, element_number)

        if function_name:
            label += f" {function_name}"

        if description:
            label += f" ({description})"

        return label

    @staticmethod
    def create_placeholder_designation() -> str:
        """Erstellt eine leere Platzhalter-Bezeichnung (FA-434)."""
        return "--"

    @staticmethod
    def parse_designation(designation: str) -> dict:
        """
        Parst eine GA-Bezeichnung zurück in ihre Bestandteile.

        Returns:
            {"gewerk_code": "LD", "floor_code": "", "room_number": "E05",
             "element_number": 1, "function_name": "E/A",
             "description": "Eingang Decke"}
        """
        result = {
            "gewerk_code": "",
            "floor_code": "",
            "room_number": "",
            "element_number": 0,
            "function_name": "",
            "description": "",
        }

        if designation == "--" or not designation:
            return result

        # Klartext in Klammern extrahieren
        desc = ""
        if "(" in designation and designation.endswith(")"):
            idx = designation.index("(")
            desc = designation[idx + 1:-1].strip()
            designation = designation[:idx].strip()

        # Label und Funktion trennen
        parts = designation.split(" ", 1)
        label = parts[0]
        function_name = parts[1] if len(parts) > 1 else ""

        # Label parsen: GEWERK_[STOCKWERK_]RAUM_NR
        label_parts = label.split("_")
        if len(label_parts) >= 3:
            result["gewerk_code"] = label_parts[0]
            if len(label_parts) >= 4:
                result["floor_code"] = label_parts[1]
                result["room_number"] = label_parts[2]
                number = label_parts[3]
            else:
                result["room_number"] = label_parts[1]
                number = label_parts[2]
            try:
                result["element_number"] = int(number)
            except ValueError:
                pass

        result["function_name"] = function_name
        result["description"] = desc
        return result
