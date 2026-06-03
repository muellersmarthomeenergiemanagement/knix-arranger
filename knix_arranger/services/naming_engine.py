"""
KNX Swiss Bezeichnungskonzept (FA-401, FA-402, FA-403)
Format: [Gewerk]_[Raum]_[Nr] [Funktion] ([Klartext])
"""


class NamingEngine:
    """Erzeugt GA-Bezeichnungen nach KNX Swiss Standard."""

    @staticmethod
    def create_designation(gewerk_code: str, room_number: str,
                           element_number: int, function_name: str,
                           description: str = "") -> str:
        """
        Erstellt eine GA-Bezeichnung (BZ-01 bis BZ-06).

        Args:
            gewerk_code: Kürzel, z.B. "LD"
            room_number: Raumnummer, z.B. "E05"
            element_number: Fortlaufend pro Raum/Gewerk, z.B. 1
            function_name: Funktion, z.B. "E/A", "DIM", "WERT"
            description: Optionaler Klartext, z.B. "Eingang Decke"

        Returns:
            z.B. "LD_E05_01 E/A (Eingang Decke)"
        """
        label = f"{gewerk_code}_{room_number}_{element_number:02d}"

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
            {"gewerk_code": "LD", "room_number": "E05",
             "element_number": 1, "function_name": "E/A",
             "description": "Eingang Decke"}
        """
        result = {
            "gewerk_code": "",
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

        # Label parsen: GEWERK_RAUM_NR
        label_parts = label.split("_")
        if len(label_parts) >= 3:
            result["gewerk_code"] = label_parts[0]
            result["room_number"] = label_parts[1]
            try:
                result["element_number"] = int(label_parts[2])
            except ValueError:
                pass

        result["function_name"] = function_name
        result["description"] = desc
        return result
