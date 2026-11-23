"""Valoración de utilidad de una respuesta (POST /valoracion).

CTR-003 §5.3 deja la valoración en manos del Backend: llega desde el Frontend y se une al registro
del turno por su trace_id. Ningún contrato fija todavía el formato (punto abierto de CTR-003), así
que se usa el mismo que el campo «feedback» del Agente 1: {"util": bool, "comentario": texto | null}.

  POST /valoracion  {"trace_id": "t-9f3a21", "util": true, "comentario": "Me ha servido"}

- Exige la sesión del usuario (CTR-005). Solo se puede valorar un turno propio: el trace_id tiene
  que estar en el registro de consultas de ese usuario; si no, 404 consulta_no_encontrada.
- Una valoración por turno y usuario. La primera devuelve 201; si se vuelve a enviar, se
  sobrescribe y devuelve 200 (idempotente, como POST /registros de CTR-003).
- El registro (GET /consultas y /consultas/mias) devuelve la valoración de cada turno.
"""

from datetime import timezone
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, field_validator

from .links import connect
from .sesiones import NO_DISPONIBLE, usuario_actual

router = APIRouter(tags=["Valoración de respuestas (CTR-003)"])

MAX_COMENTARIO = 1000
NO_ENCONTRADA = {"codigo_error": "consulta_no_encontrada", "mensaje": "La consulta no existe."}


class Valoracion(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    util: StrictBool
    comentario: str | None = Field(default=None, max_length=MAX_COMENTARIO)

    @field_validator("trace_id", mode="before")
    @classmethod
    def _sin_espacios(cls, valor):
        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("comentario")
    @classmethod
    def _vacio_es_nulo(cls, valor: str | None) -> str | None:
        valor = (valor or "").strip()
        return valor or None


class ValoracionGuardada(BaseModel):
    trace_id: str
    util: bool
    comentario: str | None
    actualizado_en: str


def guardar_valoracion(conn, *, usuario_id: int, datos: Valoracion) -> tuple[dict, bool] | None:
    """Guarda la valoración. Devuelve (fila, es_nueva), o None si el turno no es del usuario."""
    propio = conn.execute("""
        SELECT 1 FROM aplicacion.registro_consulta
        WHERE trace_id=%s AND usuario_id=%s AND tipo='consulta' LIMIT 1
    """, (datos.trace_id, usuario_id)).fetchone()
    if not propio:
        return None
    fila = conn.execute("""
        INSERT INTO aplicacion.valoracion (trace_id, usuario_id, util, comentario)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (trace_id, usuario_id) DO UPDATE
            SET util = EXCLUDED.util, comentario = EXCLUDED.comentario, actualizado_en = now()
        RETURNING trace_id, util, comentario, actualizado_en, (xmax = 0) AS nueva
    """, (datos.trace_id, usuario_id, datos.util, datos.comentario)).fetchone()
    return fila, fila.pop("nueva")


@router.post("/valoracion", response_model=ValoracionGuardada, status_code=201,
             responses={200: {"description": "Valoración actualizada (ya existía)"},
                        404: {"description": "El trace_id no es de una consulta del usuario"}})
def valorar(datos: Valoracion, usuario: Annotated[dict, Depends(usuario_actual)]):
    try:
        with connect() as conn:
            resultado = guardar_valoracion(conn, usuario_id=usuario["id"], datos=datos)
    except psycopg.Error:
        raise HTTPException(503, detail=NO_DISPONIBLE)
    if resultado is None:
        raise HTTPException(404, detail=NO_ENCONTRADA)
    fila, nueva = resultado
    fecha = fila["actualizado_en"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    cuerpo = ValoracionGuardada(**{**fila, "actualizado_en": fecha}).model_dump()
    return JSONResponse(cuerpo, status_code=201 if nueva else 200)
