"""Configuración de la API del Backend (por variables de entorno)."""

import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/thermodrive")

# CTR-002 §3: el vector de la consulta tiene exactamente 1024 floats (BAAI/bge-m3).
DIMENSIONES = 1024

# CTR-002 §3: k es obligatorio y su valor inicial es 30. El tope evita peticiones desmesuradas.
K_MAX = int(os.getenv("BUSQUEDA_K_MAX", "200"))

POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
POOL_MAX = int(os.getenv("DB_POOL_MAX", "5"))
