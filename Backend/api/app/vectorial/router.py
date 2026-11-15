"""POST /conocimiento/vectorial (ARSOFT-CTR-002 ed. 1.1, Agentes → Backend)."""

from typing import Callable, ContextManager, Optional

import psycopg
from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError

from .busqueda import buscar_vectorial
from .errores import ErrorContrato, indice_no_disponible, peticion_invalida
from .esquemas import PeticionVectorial, RespuestaBusqueda


def crear_router(abrir_conexion: Callable[[], ContextManager[psycopg.Connection]],
                 acceso: Optional[Callable] = None) -> APIRouter:
    """abrir_conexion: devuelve una conexión usable en `with` (p. ej. links.connect).
    acceso: dependencia de FastAPI que protege la ruta (p. ej. links.service_access); None = sin protección.

    Los errores del contrato se devuelven desde aquí, así que no dependen de los manejadores
    de errores de la aplicación que monte este router.
    """
    router = APIRouter(prefix="/conocimiento", tags=["conocimiento"],
                       dependencies=[Depends(acceso)] if acceso else [])

    @router.post("/vectorial", response_model=RespuestaBusqueda)
    def vectorial(cuerpo: dict = Body(...)):
        try:
            peticion = PeticionVectorial.model_validate(cuerpo)
        except ValidationError as exc:
            return peticion_invalida(exc.errors(include_input=False, include_url=False)).respuesta()
        try:
            with abrir_conexion() as conn:
                return buscar_vectorial(conn, peticion)
        except ErrorContrato as exc:
            return exc.respuesta()
        except psycopg.Error:
            return indice_no_disponible("La base de datos no está disponible.").respuesta()

    return router
