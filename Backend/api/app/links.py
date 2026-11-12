"""Configuración de conexiones internas del Backend."""

import hmac
import os
from typing import Annotated

import psycopg
from fastapi import Header, HTTPException
from psycopg.rows import dict_row


def connect():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise psycopg.OperationalError("DATABASE_URL no configurada")
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3)


def service_headers() -> dict[str, str]:
    token = os.getenv("ARSOFT_SERVICE_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def service_access(authorization: Annotated[str, Header()] = "") -> None:
    expected = service_headers().get("Authorization")
    if not expected:
        raise HTTPException(503, detail={"codigo": "servicio_no_disponible"})
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, detail={"codigo": "acceso_denegado"})
