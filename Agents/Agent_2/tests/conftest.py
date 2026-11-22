"""Configuración de las pruebas autocontenidas del recuperador."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for directory in (ROOT, ROOT / 'shared'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
