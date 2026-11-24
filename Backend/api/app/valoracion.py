"""CTR-001 · Valoración de la utilidad de una respuesta.

  POST /valoracion {"trace_id": str, "util": bool}  ->  200 {"trace_id", "util"}

Exige sesión (CTR-005). Solo se valoran respuestas del propio usuario con estado "respuesta" que consten
en el registro de consultas (CTR-003). Un trace_id inexistente, ajeno o de una respuesta que no es
"respuesta" da el mismo 404 `respuesta_no_encontrada`, para no revelar si existe. Valorar otra vez la
misma respuesta actualiza la valoración. Errores: 401 sesion_caducada, 403 acceso_denegado, 404, 422
entrada_invalida, 429 demasiadas_valoraciones (con Retry-After), 500 error_interno, 503
servicio_no_disponible.
"""

import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

from . import limite_consultas
from .links import connect
from .sesiones import NO_DISPONIBLE, usuario_actual

log = logging.getLogger("arsoft.backend")
router = APIRouter(prefix="/valoracion", tags=["Valoración (CTR-001)"])
RESPUESTA_NO_ENCONTRADA = {"codigo_error": "respuesta_no_encontrada", "mensaje": "La respuesta no existe."}
DEMASIADAS = {"codigo_error": "demasiadas_valoraciones",
              "mensaje": "Demasiadas valoraciones seguidas. Espera un momento."}


class Valoracion(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    util: StrictBool  # solo true/false: 1, "true" o null no valen


def guardar(conn, usuario_id: int, trace_id: str, util: bool) -> bool | None:
    """Inserta o actualiza la valoración si la respuesta es del usuario. None si no hay tal respuesta."""
    fila = conn.execute("""
        INSERT INTO aplicacion.valoracion (trace_id, usuario_id, util)
        SELECT %(t)s, %(u)s, %(util)s
        WHERE EXISTS (SELECT 1 FROM aplicacion.registro_consulta
                      WHERE trace_id = %(t)s AND usuario_id = %(u)s AND tipo = 'consulta' AND estado = 'respuesta')
        ON CONFLICT (usuario_id, trace_id) DO UPDATE SET util = EXCLUDED.util, actualizado_en = now()
        RETURNING util
    """, {"t": trace_id, "u": usuario_id, "util": util}).fetchone()
    return fila["util"] if fila else None


@router.post("")
def valorar(datos: Valoracion, usuario: Annotated[dict, Depends(usuario_actual)]):
    espera = limite_consultas.admitir(usuario["id"], "valoracion")
    if espera:
        raise HTTPException(429, headers={"Retry-After": str(espera)}, detail=DEMASIADAS)
    try:
        with connect() as conn:
            util = guardar(conn, usuario["id"], datos.trace_id, datos.util)
    except psycopg.Error:
        # También cubre una tabla sin migrar (UndefinedTable): el cliente ve 503, el motivo queda en el log.
        log.exception("No se pudo guardar la valoración")
        raise HTTPException(503, detail=NO_DISPONIBLE)
    if util is None:
        raise HTTPException(404, detail=RESPUESTA_NO_ENCONTRADA)
    return {"trace_id": datos.trace_id, "util": util}
