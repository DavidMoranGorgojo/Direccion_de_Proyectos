"""Constantes de la búsqueda vectorial."""

import os

# CTR-002 §3: el vector de la consulta tiene exactamente 1024 floats (BAAI/bge-m3).
DIMENSIONES = 1024

# CTR-002 §3: k es obligatorio y su valor inicial es 30. El tope evita peticiones desmesuradas.
K_MAX = int(os.getenv("BUSQUEDA_K_MAX", "200"))
