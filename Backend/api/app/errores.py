"""Errores del contrato CTR-002 (§4) con cuerpo plano: {"codigo": ..., "mensaje": ..., ...}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import psycopg
import psycopg_pool


class ErrorContrato(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, **extra):
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.extra = extra

    def cuerpo(self) -> dict:
        return {"codigo": self.codigo, "mensaje": self.mensaje, **self.extra}


def indice_no_disponible(motivo: str) -> ErrorContrato:
    return ErrorContrato(503, "indice_no_disponible", motivo)


def registrar(app: FastAPI) -> None:
    @app.exception_handler(ErrorContrato)
    async def _contrato(_: Request, exc: ErrorContrato):
        return JSONResponse(status_code=exc.estado, content=exc.cuerpo())

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError):
        # No se devuelve «input»: en una petición vectorial serían 1024 floats.
        errores = [{"campo": ".".join(str(p) for p in e["loc"] if p != "body"), "motivo": e["msg"]}
                   for e in exc.errors()]
        return JSONResponse(status_code=400, content={
            "codigo": "peticion_invalida", "mensaje": "La petición no cumple el contrato CTR-002.", "errores": errores})

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(psycopg_pool.PoolTimeout)
    async def _bd(_: Request, exc: Exception):
        return JSONResponse(status_code=503, content={
            "codigo": "indice_no_disponible", "mensaje": "La base de datos no está disponible."})
