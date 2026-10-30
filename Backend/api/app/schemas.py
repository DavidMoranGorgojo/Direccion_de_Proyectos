"""Esquemas de entrada/salida de la API (Pydantic).

Revisar contra los contratos CTR-003, CTR-005 y CTR-006 definitivos.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- CTR-005: login ----------
# Contrato tal y como lo consume Frontend/services/auth.py:
#   Petición: {"usuario": "...", "contrasena": "..."}
#   200: {"estado": "autenticado", "mensaje": "...", "usuario": {"id": "...", "nombre_usuario": "..."}}
#   401: {"estado": "no_autenticado", "mensaje": "...", "codigo_error": "credenciales_invalidas"}
#   422 datos incompletos · 429 demasiados intentos · 500
# El contrato aún no define sesión; se añade "token" (Frontend lo usa si viene).
class LoginIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    contrasena: str = Field(min_length=1, max_length=128)


class UsuarioOut(BaseModel):
    id: str
    nombre_usuario: str
    nombre: str
    rol: str

    @classmethod
    def de_modelo(cls, u) -> "UsuarioOut":
        return cls(id=str(u.id), nombre_usuario=u.username, nombre=u.nombre, rol=u.rol)


class LoginOut(BaseModel):
    estado: Literal["autenticado"] = "autenticado"
    mensaje: str = "Sesión iniciada"
    usuario: UsuarioOut
    token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class ErrorAuth(BaseModel):
    estado: Literal["no_autenticado"] = "no_autenticado"
    mensaje: str
    codigo_error: str


# ---------- CTR-006: historial de chats ----------
class ChatIn(BaseModel):
    titulo: str | None = Field(default=None, max_length=200)


class ChatUpdate(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)


class MensajeIn(BaseModel):
    rol: Literal["usuario", "asistente"]
    contenido: str = Field(min_length=1)
    fuentes: list | None = None


class MensajeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rol: str
    contenido: str
    fuentes: list | None
    creado_en: datetime


class ChatResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    titulo: str
    creado_en: datetime
    actualizado_en: datetime


class ChatDetalle(ChatResumen):
    mensajes: list[MensajeOut]


# ---------- CTR-003: registro de consultas ----------
class ConsultaIn(BaseModel):
    consulta: str = Field(min_length=1)
    tipo_busqueda: Literal["vectorial", "bm25", "otro"]
    chat_id: int | None = None
    num_resultados: int = 0
    resultados: list | None = None
    latencia_ms: float | None = None
    estado: Literal["ok", "error"] = "ok"
    error: str | None = None


class ConsultaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usuario_id: int | None
    chat_id: int | None
    consulta: str
    tipo_busqueda: str
    num_resultados: int
    resultados: list | None
    latencia_ms: float | None
    estado: str
    error: str | None
    creado_en: datetime
