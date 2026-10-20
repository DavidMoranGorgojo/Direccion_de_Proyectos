"""Inicio de sesión.

CONTRATO CTR-005 (Backend es la única autoridad que concede el acceso):

    POST {ARSOFT_API_URL}/auth/login
    Petición:  {"usuario": "...", "contrasena": "..."}
    200:  {"estado": "autenticado", "mensaje": "...", "usuario": {"id": "u-123", "nombre_usuario": "..."}}
    401:  {"estado": "no_autenticado", "mensaje": "...", "codigo_error": "credenciales_invalidas"}
    También: 422 (datos incompletos), 429 (demasiados intentos), 500.
La contraseña solo viaja en el cuerpo (nunca en la URL), no se guarda ni se registra.
El contrato aún no define token ni cookie de sesión: si la respuesta trae "token" se usará.

Sin ARSOFT_API_URL se usa un MODO LOCAL SIMULADO solo para desarrollo: los usuarios se guardan
en ~/.arsoft_asistente/users.json con la contraseña cifrada (PBKDF2 + sal), nunca en claro.
Para crear usuarios:  python tools/create_user.py
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from services import api

DATA_DIR = Path.home() / ".arsoft_asistente"

USERS_FILE = DATA_DIR / "users.json"
ITERATIONS = 200_000
DEMO_USER, DEMO_PASS = "demo", "demo1234"   # solo modo local; se crea si no hay usuarios


@dataclass
class AuthResult:
    ok: bool
    user: str = ""
    token: str | None = None
    user_id: str = ""
    error: str = ""


# ------------------------------------------------------------- usuarios locales
def _hash(password: str, salt: bytes, iters: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters).hex()


def _load_users(path: Path = USERS_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def add_user(username: str, password: str, path: Path = USERS_FILE) -> None:
    users = _load_users(path)
    salt = secrets.token_bytes(16)
    users[username.strip().lower()] = {"salt": salt.hex(), "iters": ITERATIONS,
                                       "hash": _hash(password, salt)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _local_login(username: str, password: str) -> AuthResult:
    users = _load_users()
    if not users:
        add_user(DEMO_USER, DEMO_PASS)
        users = _load_users()
    rec = users.get(username.strip().lower())
    salt = bytes.fromhex(rec["salt"]) if rec else b"\0" * 16   # mismo coste exista o no
    candidate = _hash(password, salt, rec["iters"] if rec else ITERATIONS)
    if rec and hmac.compare_digest(candidate, rec["hash"]):
        return AuthResult(True, username.strip().lower(), token=None)
    time.sleep(0.6)                                          # frena la fuerza bruta
    return AuthResult(False, error="Usuario o contraseña incorrectos")


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
    if api.is_mock():
        return _local_login(username, password)
    return _remote_login(username, password)


class LoginWorker(QThread):
    """Comprueba las credenciales fuera del hilo de la interfaz."""
    done = Signal(object)  # AuthResult

    def __init__(self, username: str, password: str):
        super().__init__()
        self._u, self._p = username, password

    def run(self) -> None:
        self.done.emit(login(self._u, self._p))
