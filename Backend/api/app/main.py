"""Pasarela HTTP de ARSOFT hacia Agentes y PostgreSQL."""

import os
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

import httpx
import psycopg
from arsoft_http import GENERIC_ERROR, invalid_question
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .conocimiento import router as knowledge
from .links import connect, service_headers

AGENT_TIMEOUT_SECONDS = 25.0
bearer = HTTPBearer(auto_error=False)


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


class Pregunta(BaseModel):
    conversacion_id: str = Field(max_length=128)
    pregunta: str


class Fuente(BaseModel):
    chunk_id: str = Field(min_length=1)
    documento: str
    seccion: str
    pagina: int = Field(ge=0, strict=True)
    versiones: list[str]
    obsoleto: bool


class RespuestaAgentes(BaseModel):
    trace_id: str = Field(min_length=1)
    estado: Literal["respuesta", "aclaracion", "sin_evidencia", "fuera_de_ambito", "error"]
    texto: str
    fuentes: list[Fuente]
    codigo_error: str


class RespuestaConsulta(RespuestaAgentes):
    conversacion_id: str


def authorize_consultation(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Punto de conexión para CTR-005 cuando exista el verificador de sesiones."""
    if credentials is None:
        raise HTTPException(401, detail={"codigo_error": "sesion_caducada", "mensaje": "Tu sesión ha caducado."})
    raise HTTPException(503, detail={"codigo_error": "servicio_no_disponible",
                                     "mensaje": "La validación de sesión aún no está disponible."})


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


@app.exception_handler(psycopg.Error)
async def postgres_error(request: Request, error: psycopg.Error):
    return JSONResponse({"codigo": "indice_no_disponible"}, status_code=503)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    if request.url.path == "/consulta" and await bearer(request) is None:
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


@app.post("/consulta", response_model=RespuestaConsulta, dependencies=[Depends(authorize_consultation)])
async def consulta(data: Pregunta, request: Request):
    cid = data.conversacion_id or uuid4().hex
    if invalid_question(data.pregunta):
        return failed(cid, "entrada_invalida", "La pregunta debe contener entre 1 y 2000 caracteres.")
    client: httpx.AsyncClient = request.app.state.agents_client
    try:
        upstream = await client.post(f"{agents_url()}/agentes/consulta", headers=service_headers(),
                                     json={"conversacion_id": cid, "pregunta": data.pregunta})
        upstream.raise_for_status()
        result = RespuestaAgentes.model_validate(upstream.json())
        if (result.estado == "respuesta") != bool(result.fuentes):
            raise ValueError("Fuentes incompatibles con el estado")
    except httpx.TimeoutException:
        try:
            await client.delete(f"{agents_url()}/agentes/conversaciones/{cid}",
                                headers=service_headers(), timeout=3.0)
        except httpx.HTTPError:
            pass
        return failed(cid, "tiempo_agotado")
    except (httpx.HTTPError, ValueError):
        return failed(cid, "servicio_no_disponible")
    return RespuestaConsulta(**result.model_dump(), conversacion_id=cid)
