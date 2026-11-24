"""Servicio HTTP de Agentes con recuperación real o simulación explícita."""

import asyncio
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from threading import Lock
from typing import Annotated
from uuid import uuid4

import httpx
from arsoft_http import (GENERIC_ERROR, invalid_question, service_token_configured,
                         valid_service_token)
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agente1.core import Agente1, MODELO_LLM, OLLAMA_URL, consultar_asistente, simulador_agente_2

try:
    from .Agent_2.src.services.pipeline import recuperar_evidencias
    from .Agent_2.src.services.runtime import check_readiness
except ImportError:
    recuperar_evidencias = None

USE_REAL_AGENT2 = os.getenv("USE_REAL_AGENT2", "0").lower() in ("1", "true", "yes")

SESSION_TTL_SECONDS = 1800
MAX_SESSIONS = 1024


@dataclass
class Session:
    agent: Agente1
    lock: Lock = field(default_factory=Lock)
    touched: float = field(default_factory=time.monotonic)
    requests: int = 0
    discard_after_request: bool = False


sessions: OrderedDict[str, Session] = OrderedDict()
lock = Lock()


def service_access(authorization: Annotated[str, Header()] = "") -> None:
    if not service_token_configured():
        raise HTTPException(503)
    if not valid_service_token(authorization):
        raise HTTPException(401)


def prune_sessions() -> None:
    cutoff = time.monotonic() - SESSION_TTL_SECONDS
    with lock:
        for cid, session in list(sessions.items()):
            if session.requests == 0 and session.touched < cutoff:
                sessions.pop(cid, None)


async def cleanup_sessions() -> None:
    while True:
        await asyncio.sleep(60)
        prune_sessions()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_sessions())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="ARSOFT Agentes", dependencies=[Depends(service_access)], lifespan=lifespan)


class Query(BaseModel):
    conversacion_id: str = Field(min_length=1, max_length=128)
    pregunta: str


def get_session(cid: str) -> Session:
    now = time.monotonic()
    with lock:
        current = sessions.get(cid)
        if current is not None and current.requests == 0 and current.touched < now - SESSION_TTL_SECONDS:
            sessions.pop(cid, None)
            current = None
        if current is None:
            if len(sessions) >= MAX_SESSIONS:
                available_id = next((old_id for old_id, old_session in sessions.items()
                                     if old_session.requests == 0), None)
                if available_id is None:
                    raise HTTPException(503, "Capacidad de conversaciones ocupada.")
                sessions.pop(available_id)
            current = Session(Agente1(conversacion_id=cid))
            sessions[cid] = current
        current.requests += 1
        sessions.move_to_end(cid)
        return current

@app.get("/health")
def liveness():
    """Comprueba que el proceso HTTP de Agentes está operativo, sin probar modelos externos."""
    return {"status": "ok"}


@app.post("/agentes/consulta")
def query(data: Query):
    cid = data.conversacion_id
    if invalid_question(data.pregunta):
        return {"trace_id": uuid4().hex, "estado": "error", "texto": "La pregunta no es válida.",
                "fuentes": [], "codigo_error": "entrada_invalida"}

    current = get_session(cid)
    try:
        with current.lock:
            with lock:
                if current.discard_after_request:
                    current.agent = Agente1(conversacion_id=cid)
                    current.discard_after_request = False

            # Separación estricta entre servicio real y simulador (B11):
            if USE_REAL_AGENT2:
                if recuperar_evidencias is None:
                    return {
                        "trace_id": uuid4().hex,
                        "estado": "error",
                        "texto": GENERIC_ERROR,
                        "fuentes": [],
                        "codigo_error": "servicio_no_disponible",
                    }
                agente2_impl = recuperar_evidencias
            else:
                agente2_impl = simulador_agente_2

            result = consultar_asistente(data.pregunta, current.agent, agente2=agente2_impl)
    finally:
        with lock:
            current.touched = time.monotonic()
            current.requests -= 1
            if current.discard_after_request and current.requests == 0:
                sessions.pop(cid, None)
            elif sessions.get(cid) is current:
                sessions.move_to_end(cid)

    if result["estado"] == "error":
        result["texto"] = GENERIC_ERROR
        if not result.get("codigo_error"):
            result["codigo_error"] = "error_verificacion"
    return result


@app.delete("/agentes/conversaciones/{conversacion_id}", status_code=204)
def close(conversacion_id: str):
    with lock:
        current = sessions.get(conversacion_id)
        if current and current.requests:
            current.discard_after_request = True
        else:
            sessions.pop(conversacion_id, None)
    return Response(status_code=204)


@app.get("/agentes/salud")
def health():
    if USE_REAL_AGENT2:
        if recuperar_evidencias is None:
            return JSONResponse({"status": "unavailable", "recuperacion": "agente2_no_disponible"}, status_code=503)
        recuperacion_modo = "agente2"
    else:
        recuperacion_modo = "mock"

    try:
        response = httpx.get(f"{OLLAMA_URL.rstrip('/')}/models", timeout=3, trust_env=False)
        response.raise_for_status()
        if MODELO_LLM not in {item["id"] for item in response.json()["data"]}:
            raise ValueError("Modelo no encontrado")
    except (httpx.HTTPError, ValueError, KeyError):
        return JSONResponse({"status": "unavailable", "recuperacion": recuperacion_modo}, status_code=503)
    if USE_REAL_AGENT2:
        readiness = check_readiness()
        if readiness["status"] != "ok":
            return JSONResponse({**readiness, "recuperacion": recuperacion_modo}, status_code=503)
    return {"status": "ok", "recuperacion": recuperacion_modo}
