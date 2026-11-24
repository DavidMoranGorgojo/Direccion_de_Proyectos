"""Configuración del Frontend: ÚNICO sitio donde se definen URL, rutas, tiempo máximo y modo.

Cada valor se toma, por orden de prioridad, de:
  1. Las variables de entorno del sistema (p. ej. las que pasa apptainer/run-frontend.sh).
  2. El archivo Frontend/.env
  3. El archivo .env de la raíz del repositorio.
  4. El valor por defecto definido aquí.

Plantilla con todas las variables: .env.example (raíz del repositorio, sección "Frontend").
Los .env reales no se suben a git.
"""
from __future__ import annotations
import os
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent
ENV_FILES = (FRONTEND_DIR / ".env", FRONTEND_DIR.parent / ".env")   # por orden de prioridad
PREFIX = "ARSOFT_"

MODO_SIMULADO = "simulado"
MODO_REAL = "real"
MODO_AUTO = ""          # sin ARSOFT_MODO: real si hay ARSOFT_API_URL, simulado si no

DEFAULTS = {
    "ARSOFT_MODO": MODO_AUTO,
    "ARSOFT_API_URL": "",
    "ARSOFT_LOGIN_PATH": "/auth/login",             # CTR-005
    "ARSOFT_HISTORIAL_PATH": "/chats",              # CTR-006
    "ARSOFT_CONSULTA_PATH": "/consulta",             # CTR-001: ruta confirmada con Backend
    "ARSOFT_VALORACION_PATH": "/valoracion",         # CTR-001: valoración de una respuesta
    "ARSOFT_TIMEOUT_S": "60",
    "ARSOFT_ALLOW_HTTP": "0",
    "ARSOFT_MOCK_EMPTY_HISTORY": "0",
}


# ----------------------------------------------------------------- lectura de .env
def parse_env_file(path: Path) -> dict[str, str]:
    """Lee un .env sencillo (CLAVE=valor). Solo devuelve las variables ARSOFT_*.

    Admite líneas en blanco, comentarios (#), el prefijo `export ` y valores entre comillas.
    """
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:                        # comentario al final de la línea
            value = value.split(" #", 1)[0].rstrip()
        if key.startswith(PREFIX):
            values[key] = value
    return values


def load_settings(environ: dict[str, str] | None = None,
                  env_files: tuple[Path, ...] = ENV_FILES) -> dict[str, str]:
    """Combina valores por defecto, archivos .env y variables de entorno (en ese orden)."""
    environ = os.environ if environ is None else environ
    settings = dict(DEFAULTS)
    for path in reversed(env_files):               # el primero de la lista gana
        settings.update(parse_env_file(path))
    settings.update({k: v for k, v in environ.items() if k.startswith(PREFIX)})
    return settings


# ------------------------------------------------------------------ normalización
def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "si", "sí", "yes")


def _path(value: str, default: str) -> str:
    value = value.strip() or default
    return value if value.startswith("/") else "/" + value


def _timeout(value: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return float(DEFAULTS["ARSOFT_TIMEOUT_S"])
    return seconds if seconds > 0 else float(DEFAULTS["ARSOFT_TIMEOUT_S"])


def _modo(value: str) -> str:
    value = value.strip().lower()
    return value if value in (MODO_SIMULADO, MODO_REAL) else MODO_AUTO


_s = load_settings()

MODO = _modo(_s["ARSOFT_MODO"])
API_URL = _s["ARSOFT_API_URL"].strip().rstrip("/")
LOGIN_PATH = _path(_s["ARSOFT_LOGIN_PATH"], DEFAULTS["ARSOFT_LOGIN_PATH"])
HISTORIAL_PATH = _path(_s["ARSOFT_HISTORIAL_PATH"], DEFAULTS["ARSOFT_HISTORIAL_PATH"])
CONSULTA_PATH = _path(_s["ARSOFT_CONSULTA_PATH"], DEFAULTS["ARSOFT_CONSULTA_PATH"])
VALORACION_PATH = _path(_s["ARSOFT_VALORACION_PATH"], DEFAULTS["ARSOFT_VALORACION_PATH"])
TIMEOUT_S = _timeout(_s["ARSOFT_TIMEOUT_S"])
ALLOW_HTTP = _flag(_s["ARSOFT_ALLOW_HTTP"])
MOCK_EMPTY_HISTORY = _flag(_s["ARSOFT_MOCK_EMPTY_HISTORY"])
