"""
KNiX Arranger - Starter-Skript
(c) Michael Mueller SmartHome&EnergieManagement
"""
import sys
import os

# Projektverzeichnis zum Pfad hinzufuegen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from knix_arranger.main import main

if __name__ == "__main__":
    sys.exit(main())
