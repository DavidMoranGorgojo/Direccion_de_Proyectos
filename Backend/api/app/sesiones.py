"""CTR-005 · Login y verificación de sesiones.

Respuestas de /auth/login con el formato que consume Frontend/services/auth.py:
  200 {"estado": "autenticado", "mensaje", "usuario": {"id", "nombre_usuario", "nombre", "rol"},
       "token", "token_type", "expires_in"}
  401 {"estado": "no_autenticado", "mensaje", "codigo_error": "credenciales_invalidas"}
  422 datos_incompletos · 429 demasiados_intentos · 503 servicio_no_disponible
Los errores llevan siempre "codigo_error" y "mensaje", como el resto de la API.

La sesión es un JWT firmado con ARSOFT_JWT_SECRET. Si no está configurado se deriva de
ARSOFT_SERVICE_TOKEN, que el despliegue ya exige; sin ninguno de los dos el login no se habilita.
"""

import hashlib
import hmac
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .links import connect

JWT_ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/auth", tags=["Login (CTR-005)"])

SESION_CADUCADA = {"codigo_error": "sesion_caducada", "mensaje": "Tu sesión ha caducado."}
NO_DISPONIBLE = {"codigo_error": "servicio_no_disponible",
                 "mensaje": "El servicio no está disponible. Inténtalo más tarde."}


# ------------------------------------------------------------------ claves y contraseñas
def _secreto() -> str:
    propio = os.getenv("ARSOFT_JWT_SECRET", "").strip()
    if propio:
        return propio
    servicio = os.getenv("ARSOFT_SERVICE_TOKEN", "").strip()
    if servicio:
        return hmac.new(servicio.encode(), b"arsoft-jwt-ctr-005", hashlib.sha256).hexdigest()
    return ""


def _minutos_sesion() -> int:
    return int(os.getenv("ARSOFT_SESSION_MINUTES", "480"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# Hash fijo para comparar cuando el usuario no existe y que el tiempo de respuesta no lo delate
_HASH_FICTICIO = hash_password("arsoft-usuario-inexistente")


def crear_token(usuario: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=_minutos_sesion())
    datos = {"sub": str(usuario["id"]), "usuario": usuario["nombre_usuario"], "rol": usuario["rol"], "exp": exp}
    return jwt.encode(datos, _secreto(), algorithm=JWT_ALGORITHM)


def usuario_publico(u: dict) -> dict:
    return {"id": str(u["id"]), "nombre_usuario": u["nombre_usuario"], "nombre": u["nombre"], "rol": u["rol"]}


# ------------------------------------------------------------------ verificación de sesiones
def usuario_actual(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict:
    """Dependencia para las rutas de usuario: devuelve {id, nombre_usuario, nombre, rol} o 401."""
    if credentials is None:
        raise HTTPException(401, detail=SESION_CADUCADA, headers={"WWW-Authenticate": "Bearer"})
    secreto = _secreto()
    if not secreto:
        raise HTTPException(503, detail=NO_DISPONIBLE)
    try:
        datos = jwt.decode(credentials.credentials, secreto, algorithms=[JWT_ALGORITHM])
        usuario_id = int(datos["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(401, detail=SESION_CADUCADA, headers={"WWW-Authenticate": "Bearer"})
    try:
        with connect() as conn:
            usuario = conn.execute(
                "SELECT id, nombre_usuario, nombre, rol, activo FROM aplicacion.usuario WHERE id=%s",
                (usuario_id,)).fetchone()
    except psycopg.Error:
        raise HTTPException(503, detail=NO_DISPONIBLE)
    if not usuario or not usuario["activo"]:
        raise HTTPException(401, detail=SESION_CADUCADA, headers={"WWW-Authenticate": "Bearer"})
    return usuario


def solo_admin(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    if usuario["rol"] != "admin":
        raise HTTPException(403, detail={"codigo_error": "acceso_denegado", "mensaje": "Solo administradores."})
    return usuario


# ------------------------------------------------------------------ login
# Límite de intentos fallidos en memoria, por usuario e IP. Con varias réplicas habría que llevarlo a la base.
MAX_FALLOS = 5
VENTANA_S = 300
_fallos: dict[tuple[str, str], deque] = defaultdict(deque)


class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    contrasena: str = Field(min_length=1, max_length=128)


def _no_autenticado(status: int, mensaje: str, codigo: str) -> JSONResponse:
    return JSONResponse({"estado": "no_autenticado", "mensaje": mensaje, "codigo_error": codigo}, status_code=status)


def _bloqueado(clave: tuple[str, str]) -> bool:
    intentos = _fallos[clave]
    limite = time.monotonic() - VENTANA_S
    while intentos and intentos[0] < limite:
        intentos.popleft()
    return len(intentos) >= MAX_FALLOS


@router.post("/login")
def login(datos: Login, request: Request):
    if not _secreto():
        return _no_autenticado(503, NO_DISPONIBLE["mensaje"], "servicio_no_disponible")
    nombre = datos.usuario.strip().lower()
    clave = (nombre, request.client.host if request.client else "?")
    if _bloqueado(clave):
        return _no_autenticado(429, "Demasiados intentos. Espera unos minutos antes de reintentar.",
                               "demasiados_intentos")
    try:
        with connect() as conn:
            usuario = conn.execute(
                "SELECT id, nombre_usuario, nombre, rol, activo, password_hash FROM aplicacion.usuario "
                "WHERE nombre_usuario=%s", (nombre,)).fetchone()
            valido = verificar_password(datos.contrasena, usuario["password_hash"] if usuario else _HASH_FICTICIO)
            if not usuario or not usuario["activo"] or not valido:
                _fallos[clave].append(time.monotonic())
                return _no_autenticado(401, "Usuario o contraseña incorrectos.", "credenciales_invalidas")
            conn.execute("UPDATE aplicacion.usuario SET ultimo_login=now() WHERE id=%s", (usuario["id"],))
    except psycopg.Error:
        return _no_autenticado(503, NO_DISPONIBLE["mensaje"], "servicio_no_disponible")
    _fallos.pop(clave, None)
    return {
        "estado": "autenticado",
        "mensaje": "Inicio de sesión correcto.",
        "usuario": usuario_publico(usuario),
        "token": crear_token(usuario),
        "token_type": "bearer",
        "expires_in": _minutos_sesion() * 60,
    }


@router.get("/me")
def me(usuario: Annotated[dict, Depends(usuario_actual)]):
    return usuario_publico(usuario)
