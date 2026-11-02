"""Inicio de sesión.

CONTRATO CTR-005 (Backend es la única autoridad que concede el acceso):

    POST {ARSOFT_API_URL}/auth/login
    Petición:  {"usuario": "...", "contrasena": "..."}
    200:  {"estado": "autenticado", "mensaje": "...", "usuario": {"id": "u-123", "nombre_usuario": "..."}}
    401:  {"estado": "no_autenticado", "mensaje": "...", "codigo_error": "credenciales_invalidas"}
    También: 422 (datos incompletos), 429 (demasiados intentos), 500.
La contraseña solo viaja en el cuerpo (nunca en la URL), no se guarda ni se registra.
El contrato aún no define token ni cookie de sesión: si la respuesta trae "token" se usará.
Sin ARSOFT_API_URL, api.call proporciona las respuestas del MODO SIMULADO.
"""
from __future__ import annotations
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from services import api


@dataclass
class AuthResult:
    ok: bool
    user: str = ""
    token: str | None = None
    user_id: str = ""
    error: str = ""


# --------------------------------------------------------------------- backend
BAD_CREDENTIALS = "Usuario o contraseña incorrectos"


def _remote_login(username: str, password: str) -> AuthResult:
    try:
        status, d = api.call("POST", "/auth/login", {"usuario": username, "contrasena": password})
    except api.ConnectionFailed as e:
        msg = str(e) if "HTTPS" in str(e) else "No se pudo conectar con el servidor."
        return AuthResult(False, error=msg)            # sin respuesta: nunca se concede acceso
    d = d or {}
    if status == 200 and d.get("estado") == "autenticado" and isinstance(d.get("usuario"), dict):
        u = d["usuario"]
        name = u.get("nombre_usuario") or username
        return AuthResult(True, name, d.get("token"), str(u.get("id", "")))
    if status == 401 or d.get("estado") == "no_autenticado":
        return AuthResult(False, error=d.get("mensaje") or BAD_CREDENTIALS)
    if status == 422:
        return AuthResult(False, error="Faltan datos o el formato es incorrecto.")
    if status == 429:
        return AuthResult(False, error="Demasiados intentos. Espera un momento antes de reintentar.")
    return AuthResult(False, error="El servicio no está disponible. Inténtalo más tarde.")


def login(username: str, password: str) -> AuthResult:
    return _remote_login(username, password)


class LoginWorker(QThread):
    """Comprueba las credenciales fuera del hilo de la interfaz."""
    done = Signal(object)  # AuthResult

    def __init__(self, username: str, password: str):
        super().__init__()
        self._u, self._p = username, password

    def run(self) -> None:
        self.done.emit(login(self._u, self._p))
