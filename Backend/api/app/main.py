"""Pasarela HTTP de ARSOFT hacia Agentes y PostgreSQL."""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import httpx
import psycopg
from arsoft_http import GENERIC_ERROR, invalid_question
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from .conocimiento import router as knowledge
from .historial import ConversacionAjena, guardar_turno, reservar_chat
from .historial import router as historial
from . import limite_consultas
from .links import connect, service_access, service_headers
from .registro import registrar
from .registro import router as registro
from .sesiones import router as sesiones
from .sesiones import usuario_actual
from .valoracion import router as valoracion
from .vectorial import crear_router as crear_router_vectorial

AGENT_TIMEOUT_SECONDS = float(os.environ.get("ARSOFT_AGENT_TIMEOUT_SECONDS", "25.0"))
CODIGOS_ERROR_CTR001 = frozenset({
    "entrada_invalida",
    "modelo_no_disponible",
    "modelo_incompatible",
    "indice_no_disponible",
    "tiempo_agotado",
    "error_verificacion",
    "servicio_no_disponible",
})
bearer = HTTPBearer(auto_error=False)
log = logging.getLogger("arsoft.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agents_client = httpx.AsyncClient(
        timeout=httpx.Timeout(AGENT_TIMEOUT_SECONDS),
        trust_env=False,
    )
    try:
        yield
    finally:
        await app.state.agents_client.aclose()


app = FastAPI(title="ARSOFT Backend API", version="0.2.0", lifespan=lifespan)
app.include_router(knowledge)
app.include_router(crear_router_vectorial(connect, service_access))  # POST /conocimiento/vectorial (CTR-002)
app.include_router(sesiones)
app.include_router(historial)
app.include_router(registro)
app.include_router(valoracion)  # POST /valoracion (CTR-001)


@app.get("/", include_in_schema=False)
def web_client():
    """Interfaz web sencilla para el prototipo del reto ARSOFT."""
    return FileResponse(Path(__file__).with_name("web_client.html"), media_type="text/html")


class Pregunta(BaseModel):
    conversacion_id: str = Field(max_length=128)
    pregunta: str


class Fuente(BaseModel):
    chunk_id: str = Field(min_length=1)
    documento: str = Field(min_length=1)
    seccion: str = Field(min_length=1)
    pagina: int = Field(ge=1, strict=True)
    versiones: list[str]
    obsoleto: bool

    @field_validator("chunk_id")
    @classmethod
    def id_fragmento_completo(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La fuente necesita un identificador de fragmento.")
        return value

    @field_validator("documento", "seccion")
    @classmethod
    def cita_texto_completo(cls, value: str) -> str:
        value = value.strip()
        if not value or value.casefold() in {"doc_desconocido", "documento sin nombre"}:
            raise ValueError("La fuente necesita documento y sección verificables.")
        return value


class RespuestaAgentes(BaseModel):
    trace_id: str = Field(min_length=1)
    estado: Literal["respuesta", "aclaracion", "sin_evidencia", "fuera_de_ambito", "error"]
    texto: str
    fuentes: list[Fuente]
    codigo_error: str

    @model_validator(mode="after")
    def contrato_estado_fuentes_y_error(self):
        if self.estado == "respuesta" and not self.texto.strip():
            raise ValueError("Una respuesta verificada necesita texto.")
        if (self.estado == "respuesta") != bool(self.fuentes):
            raise ValueError("Una respuesta necesita fuentes completas; los demás estados no llevan fuentes.")
        if self.estado == "error":
            if self.codigo_error not in CODIGOS_ERROR_CTR001:
                raise ValueError("La respuesta de error necesita un código CTR-001 reconocido.")
        elif self.codigo_error:
            raise ValueError("Los estados distintos de error no llevan codigo_error.")
        return self


class RespuestaConsulta(RespuestaAgentes):
    conversacion_id: str


def authorize_consultation(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """CTR-005: /consulta exige una sesión válida (401 sesion_caducada si no la hay)."""
    return usuario


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, error: StarletteHTTPException):
    if isinstance(error.detail, dict):
        body = error.detail
    elif error.status_code == 404:
        body = {"codigo_error": "recurso_no_encontrado", "mensaje": "El recurso solicitado no existe."}
    elif error.status_code == 405:
        body = {"codigo_error": "metodo_no_permitido", "mensaje": "El método HTTP no está permitido."}
    else:
        body = {"codigo_error": "error_interno", "mensaje": str(error.detail)}
    return JSONResponse(body, status_code=error.status_code, headers=error.headers)


@app.exception_handler(Exception)
async def internal_error(request: Request, error: Exception):
    """500 con el formato de error de la API, sin detalles internos (CTR-001: error 500)."""
    log.exception("Error no controlado en %s", request.url.path)
    return JSONResponse({"codigo_error": "error_interno", "mensaje": "Error interno del servidor."},
                        status_code=500)


@app.exception_handler(psycopg.Error)
async def postgres_error(request: Request, error: psycopg.Error):
    mensaje = "La base de datos o el índice no están disponibles."
    if request.url.path.startswith(("/conocimiento", "/catalogos/")):
        body = {"codigo": "indice_no_disponible", "mensaje": mensaje}
    else:
        body = {"codigo_error": "servicio_no_disponible", "mensaje": mensaje}
    return JSONResponse(body, status_code=503)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path == "/auth/login":  # CTR-005: 422 con el cuerpo de login
        return JSONResponse({"estado": "no_autenticado", "codigo_error": "datos_incompletos",
                             "mensaje": "Faltan datos o el formato es incorrecto."}, status_code=422)
    if request.url.path in ("/consulta", "/valoracion") and await bearer(request) is None:
        return JSONResponse({"codigo_error": "sesion_caducada", "mensaje": "Tu sesión ha caducado."},
                            status_code=401)
    return JSONResponse({"codigo_error": "entrada_invalida", "mensaje": "Faltan datos o el formato es incorrecto."},
                        status_code=422)


def agents_url() -> str:
    return os.getenv("AGENTES_URL", "http://127.0.0.1:8001").rstrip("/")


def failed(cid: str, code: str, text: str = GENERIC_ERROR) -> RespuestaConsulta:
    return RespuestaConsulta(trace_id=uuid4().hex, conversacion_id=cid, estado="error",
                             texto=text, fuentes=[], codigo_error=code)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        return JSONResponse({"status": "unavailable", "postgres": "unavailable"}, status_code=503)
    try:
        response = httpx.get(f"{agents_url()}/agentes/salud", headers=service_headers(), timeout=3,
                             trust_env=False)
        response.raise_for_status()
    except httpx.HTTPError:
        return JSONResponse({"status": "unavailable", "postgres": "ok", "agentes": "unavailable"}, status_code=503)
    return {"status": "ok", "postgres": "ok", "agentes": "ok"}


@app.post("/consulta", response_model=RespuestaConsulta)
async def consulta(data: Pregunta, request: Request,
                   usuario: Annotated[dict, Depends(authorize_consultation)]):
    cid = data.conversacion_id or uuid4().hex
    if invalid_question(data.pregunta):
        return failed(cid, "entrada_invalida", "La pregunta debe contener entre 1 y 2000 caracteres.")
    espera = limite_consultas.admitir(usuario["id"])
    if espera:  # CTR-001: 429 si el usuario encadena demasiadas consultas
        raise HTTPException(429, headers={"Retry-After": str(espera)},
                            detail={"codigo_error": "demasiadas_consultas",
                                    "mensaje": "Demasiadas consultas seguidas. Espera un momento."})
    # psycopg es síncrono: el acceso a la base va a un hilo aparte para no bloquear el event loop
    try:
        await run_in_threadpool(reservar, usuario["id"], cid, data.pregunta)
    except ConversacionAjena:  # CTR-006: cada usuario solo usa sus chats; no se reenvía a Agentes
        raise HTTPException(404, detail={"codigo_error": "conversacion_no_encontrada",
                                         "mensaje": "La conversación no existe."})
    except psycopg.Error:
        log.exception("No se pudo reservar la conversación")
        return failed(cid, "servicio_no_disponible")
    inicio = time.perf_counter()
    result = await consultar_agentes(cid, data.pregunta, request.app.state.agents_client)
    await run_in_threadpool(guardar, usuario, data.pregunta, result, (time.perf_counter() - inicio) * 1000)
    return result


def reservar(usuario_id: int, cid: str, pregunta: str) -> None:
    with connect() as conn:
        reservar_chat(conn, usuario_id=usuario_id, conversacion_id=cid, pregunta=pregunta)


async def consultar_agentes(cid: str, pregunta: str, client: httpx.AsyncClient) -> RespuestaConsulta:
    try:
        upstream = await client.post(f"{agents_url()}/agentes/consulta", headers=service_headers(),
                                     json={"conversacion_id": cid, "pregunta": pregunta})
        upstream.raise_for_status()
        result = RespuestaAgentes.model_validate(upstream.json())
    except httpx.TimeoutException:
        try:
            await client.delete(f"{agents_url()}/agentes/conversaciones/{cid}",
                                headers=service_headers(), timeout=3.0)
        except httpx.HTTPError:
            pass
        return failed(cid, "tiempo_agotado")
    except httpx.HTTPError:
        return failed(cid, "servicio_no_disponible")
    except (ValidationError, ValueError):
        return failed(cid, "error_verificacion")
    return RespuestaConsulta(**result.model_dump(), conversacion_id=cid)


def guardar(usuario: dict, pregunta: str, result: RespuestaConsulta, latencia_ms: float) -> None:
    """Historial (CTR-006) y registro (CTR-003) del turno. Si falla, la respuesta se entrega igual."""
    respuesta = result.model_dump()
    try:
        with connect() as conn:
            guardar_turno(conn, usuario_id=usuario["id"], conversacion_id=result.conversacion_id,
                          pregunta=pregunta, respuesta=respuesta)
            registrar(conn, pregunta=pregunta, estado=result.estado, usuario_id=usuario["id"],
                      conversacion_id=result.conversacion_id, trace_id=result.trace_id,
                      codigo_error=result.codigo_error, chunk_ids=[f.chunk_id for f in result.fuentes],
                      latencia_ms=round(latencia_ms, 2))
    except (psycopg.Error, ConversacionAjena):
        log.exception("No se pudo guardar el turno en el historial ni en el registro")
