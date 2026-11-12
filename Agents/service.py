"""Adaptador HTTP del Agente 1 existente y su recuperador simulado."""

import hmac
import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agente1.core import Agente1, MODELO_LLM, OLLAMA_URL, consultar_asistente

@dataclass
class Session:
    agent: Agente1
    lock: Lock = field(default_factory=Lock)
    touched: float = field(default_factory=time.monotonic)
    requests: int = 0


sessions: dict[str, Session] = {}
lock = Lock()
GENERIC = "El asistente no está disponible, inténtalo de nuevo."


def service_access(authorization: Annotated[str, Header()] = "") -> None:
    token = os.getenv("ARSOFT_SERVICE_TOKEN")
    if not token:
        raise HTTPException(503)
    if not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401)


app = FastAPI(title="ARSOFT Agentes", dependencies=[Depends(service_access)])


class Query(BaseModel):
    conversacion_id: str = Field(min_length=1, max_length=128)
    pregunta: str


@app.post("/agentes/consulta")
def query(data: Query):
    if not data.pregunta.strip() or len(data.pregunta) > 2000:
        return {"trace_id": uuid4().hex, "estado": "error", "texto": "La pregunta no es válida.",
                "fuentes": [], "codigo_error": "entrada_invalida"}
    with lock:
        cutoff = time.monotonic() - 1800
        for cid, session in list(sessions.items()):
            if not session.requests and session.touched < cutoff:
                del sessions[cid]
        current = sessions.get(data.conversacion_id)
        if current is None:
            current = Session(Agente1(conversacion_id=data.conversacion_id))
            sessions[data.conversacion_id] = current
        current.requests += 1
    try:
        with current.lock:
            result = consultar_asistente(data.pregunta, current.agent)
    finally:
        with lock:
            current.touched = time.monotonic()
            current.requests -= 1
    if result["estado"] == "error":
        result["texto"] = GENERIC
        if result["codigo_error"] == "error":
            result["codigo_error"] = "modelo_no_disponible"
    return result


@app.delete("/agentes/conversaciones/{conversacion_id}", status_code=204)
def close(conversacion_id: str):
    with lock:
        current = sessions.get(conversacion_id)
        if current and current.requests:
            raise HTTPException(409, "La conversación tiene un turno en curso.")
        sessions.pop(conversacion_id, None)
    return Response(status_code=204)


@app.get("/agentes/salud")
def health():
    try:
        response = httpx.get(f"{OLLAMA_URL.rstrip('/')}/models", timeout=3, trust_env=False)
        response.raise_for_status()
        if MODELO_LLM not in {item["id"] for item in response.json()["data"]}:
            raise ValueError("Modelo no encontrado")
    except (httpx.HTTPError, ValueError, KeyError):
        return JSONResponse({"status": "unavailable", "recuperacion": "mock"}, status_code=503)
    return {"status": "ok", "recuperacion": "mock"}
