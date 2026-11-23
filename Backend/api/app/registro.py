"""CTR-003 · Registro de consultas.

Cada POST /consulta queda registrado (main.py llama a `registrar`). Los endpoints de búsqueda
pueden usar la misma función con tipo "vectorial" o "lexica".

  GET /consultas/mias   consultas del usuario autenticado
  GET /consultas        todas (solo admin), con filtros usuario_id, tipo, estado, desde y hasta

Cada fila incluye la valoración del usuario (util y comentario_valoracion, null si no valoró).
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from .links import connect
from .sesiones import solo_admin, usuario_actual

router = APIRouter(prefix="/consultas", tags=["Registro de consultas (CTR-003)"])
CAMPOS = """r.id, r.trace_id, r.usuario_id, r.conversacion_id, r.tipo, r.pregunta, r.estado, r.codigo_error,
r.num_fuentes, r.chunk_ids, r.latencia_ms, r.creado_en, v.util, v.comentario AS comentario_valoracion"""
# La valoración del usuario (POST /valoracion) se une al turno por trace_id (CTR-003 §5.3).
TABLAS = """aplicacion.registro_consulta r
LEFT JOIN aplicacion.valoracion v ON v.trace_id = r.trace_id AND v.usuario_id = r.usuario_id"""


def registrar(conn, *, pregunta: str, estado: str, tipo: str = "consulta", usuario_id: int | None = None,
              conversacion_id: str | None = None, trace_id: str = "", codigo_error: str = "",
              chunk_ids: list[str] | None = None, latencia_ms: float | None = None) -> None:
    chunk_ids = [str(c) for c in (chunk_ids or []) if c]
    conn.execute("""
        INSERT INTO aplicacion.registro_consulta
            (trace_id, usuario_id, conversacion_id, tipo, pregunta, estado, codigo_error, num_fuentes,
             chunk_ids, latencia_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (trace_id, usuario_id, conversacion_id, tipo, pregunta, estado, codigo_error, len(chunk_ids),
          chunk_ids, latencia_ms))


def _serializar(fila: dict) -> dict:
    return {**fila, "creado_en": fila["creado_en"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


@router.get("/mias")
def mias(usuario: Annotated[dict, Depends(usuario_actual)],
         limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    with connect() as conn:
        filas = conn.execute(f"""
            SELECT {CAMPOS} FROM {TABLAS} WHERE r.usuario_id=%s
            ORDER BY r.creado_en DESC, r.id DESC LIMIT %s OFFSET %s
        """, (usuario["id"], limit, offset)).fetchall()
    return {"consultas": [_serializar(f) for f in filas]}


@router.get("")
def todas(_: Annotated[dict, Depends(solo_admin)],
          usuario_id: int | None = None, tipo: Literal["consulta", "vectorial", "lexica"] | None = None,
          estado: str | None = None, desde: datetime | None = None, hasta: datetime | None = None,
          limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    condiciones, valores = [], []
    for columna, valor, op in (("usuario_id", usuario_id, "="), ("tipo", tipo, "="), ("estado", estado, "="),
                               ("creado_en", desde, ">="), ("creado_en", hasta, "<=")):
        if valor is not None:
            condiciones.append(f"r.{columna} {op} %s")
            valores.append(valor)
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    with connect() as conn:
        filas = conn.execute(f"""
            SELECT {CAMPOS} FROM {TABLAS} {where}
            ORDER BY r.creado_en DESC, r.id DESC LIMIT %s OFFSET %s
        """, (*valores, limit, offset)).fetchall()
    return {"consultas": [_serializar(f) for f in filas]}
