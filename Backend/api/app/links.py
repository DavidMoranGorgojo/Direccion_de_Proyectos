"""Configuración de conexiones internas del Backend."""

import os

import psycopg
from arsoft_http import service_headers, service_token_configured, valid_service_token
from fastapi import Header, HTTPException
from psycopg.rows import dict_row


def connect():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise psycopg.OperationalError("DATABASE_URL no configurada")
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=3)


def service_access(authorization: str = Header(default="")) -> None:
    if not service_token_configured():
        raise HTTPException(503, detail={"codigo": "servicio_no_disponible",
                                         "mensaje": "El token de servicio no está configurado."})
    if not valid_service_token(authorization):
        raise HTTPException(401, detail={"codigo": "acceso_denegado",
                                         "mensaje": "Se requiere un Bearer de servicio válido."})
