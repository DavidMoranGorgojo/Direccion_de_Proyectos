"""Llamadas HTTP al servicio (API JSON sobre HTTP, FastAPI en el Backend).

En esta versión solo se usa para el inicio de sesión (CTR-005, ver services/auth.py).
La URL base del Backend se lee de la variable de entorno ARSOFT_API_URL. Si no está definida
se usa un MODO LOCAL SIMULADO solo para desarrollar la interfaz.
Fuera de entornos locales se exige HTTPS (ARSOFT_ALLOW_HTTP=1 lo desactiva, solo para pruebas).
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from services import session

API_URL = os.environ.get("ARSOFT_API_URL", "").rstrip("/")
TIMEOUT_S = 60


def is_mock() -> bool:
    return not API_URL


# ------------------------------------------------------------------- HTTP común
class ConnectionFailed(Exception):
    """No se obtuvo respuesta HTTP (sin conexión, tiempo agotado o conexión no segura)."""


def _is_local(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def _insecure() -> bool:
    u = urlparse(API_URL)
    return (u.scheme == "http" and not _is_local(u.hostname or "")
            and os.environ.get("ARSOFT_ALLOW_HTTP") != "1")


def auth_headers() -> dict:
    """Identificación del usuario. El mecanismo de sesión no está definido en CTR-005:
    si el Backend devuelve un token se envía; si no, no se envía nada."""
    return {"Authorization": f"Bearer {session.token}"} if session.token else {}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
    """Devuelve (código HTTP, JSON o None). Solo lanza ConnectionFailed si no hay respuesta."""
    if _insecure():
        raise ConnectionFailed("Conexión no segura: fuera de un entorno local se exige HTTPS.")
    headers = {"Accept": "application/json", **auth_headers()}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionFailed(str(e)) from e
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return status, parsed if isinstance(parsed, dict) else None
