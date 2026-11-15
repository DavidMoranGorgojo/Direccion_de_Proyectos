"""Configuración leída de variables de entorno."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://arsoft:arsoft@localhost:5432/arsoft",
)
JWT_SECRET = os.getenv("JWT_SECRET", "solo-para-desarrollo-cambiar-en-produccion-0000")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

# ---------- Pasarela hacia Agentes ----------
# AGENTES_MODO: "simulado" (respuestas de prueba con la forma del contrato) o "real".
# Si no se indica, es "real" cuando hay AGENTES_URL y "simulado" cuando no.
AGENTES_URL = os.getenv("AGENTES_URL", "").rstrip("/")
AGENTES_RUTA = os.getenv("AGENTES_RUTA", "/consulta")
AGENTES_MODO = os.getenv("AGENTES_MODO", "real" if AGENTES_URL else "simulado")
AGENTES_TIMEOUT_S = float(os.getenv("AGENTES_TIMEOUT_S", "60"))
