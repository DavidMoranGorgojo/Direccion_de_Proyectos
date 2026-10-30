"""CTR-005 · Login.

Respuestas con el formato que espera Frontend/services/auth.py.
"""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import JWT_EXPIRE_MINUTES
from app.db import get_db
from app.models import Usuario, ahora
from app.schemas import ErrorAuth, LoginIn, LoginOut, UsuarioOut
from app.security import crear_token, usuario_actual, verificar_password

router = APIRouter(prefix="/auth", tags=["login (CTR-005)"])

# Límite de intentos fallidos (en memoria, por usuario + IP).
# Si se levantan varias réplicas de la API habría que moverlo a la base de datos.
MAX_FALLOS = 5
VENTANA_S = 300
_fallos: dict[tuple[str, str], deque] = defaultdict(deque)


def _clave(request: Request, usuario: str) -> tuple[str, str]:
    ip = request.client.host if request.client else "?"
    return usuario.strip().lower(), ip


def _bloqueado(clave) -> bool:
    q = _fallos[clave]
    limite = time.monotonic() - VENTANA_S
    while q and q[0] < limite:
        q.popleft()
    return len(q) >= MAX_FALLOS


def _error(status: int, mensaje: str, codigo: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorAuth(mensaje=mensaje, codigo_error=codigo).model_dump())


@router.post(
    "/login",
    response_model=LoginOut,
    responses={401: {"model": ErrorAuth}, 422: {"model": ErrorAuth}, 429: {"model": ErrorAuth}},
)
def login(datos: LoginIn, request: Request, db: Session = Depends(get_db)):
    clave = _clave(request, datos.usuario)
    if _bloqueado(clave):
        return _error(429, "Demasiados intentos. Espera unos minutos antes de reintentar.", "demasiados_intentos")

    usuario = db.scalar(select(Usuario).where(Usuario.username == datos.usuario.strip().lower()))
    # Mismo mensaje para usuario inexistente, inactivo o contraseña incorrecta
    if usuario is None or not usuario.activo or not verificar_password(datos.contrasena, usuario.password_hash):
        _fallos[clave].append(time.monotonic())
        return _error(401, "Usuario o contraseña incorrectos", "credenciales_invalidas")

    _fallos.pop(clave, None)
    usuario.ultimo_login = ahora()
    db.commit()
    return LoginOut(
        usuario=UsuarioOut.de_modelo(usuario),
        token=crear_token(usuario),
        expires_in=JWT_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(usuario_actual)):
    return UsuarioOut.de_modelo(usuario)
