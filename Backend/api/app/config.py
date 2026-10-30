"""Configuración leída de variables de entorno."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://arsoft:arsoft@localhost:5432/arsoft",
)
JWT_SECRET = os.getenv("JWT_SECRET", "solo-para-desarrollo-cambiar-en-produccion-0000")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
