"""CTR-006 · Historial de chats, con la forma que lee Frontend (services/api.py y models/):

  GET /chats -> {"chats": [{"conversacion_id", "titulo", "created_at", "updated_at",
                            "mensajes": [{"message_id", "trace_id", "role", "contenido", "estado",
                                          "codigo_error", "timestamp", "fuentes"}]}],
                 "total": n}

Los chats se crean y se rellenan desde POST /consulta (main.py): el conversacion_id de CTR-001 es la
clave del chat. Cada usuario solo ve los suyos; un chat ajeno responde 404 para no revelar que existe.
"""

from datetime import timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .links import connect, service_headers
from .sesiones import usuario_actual

router = APIRouter(prefix="/chats", tags=["Historial (CTR-006)"])
TITULO_POR_DEFECTO = "Nuevo chat"
CHAT_NO_ENCONTRADO = {"codigo_error": "conversacion_no_encontrada", "mensaje": "La conversación no existe."}


def _iso(fecha) -> str:
    """ISO 8601 en UTC con sufijo Z, como espera Frontend (models/dates.py)."""
    return fecha.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _chat(fila: dict, mensajes: list[dict]) -> dict:
    return {
        "conversacion_id": fila["conversacion_id"],
        "titulo": fila["titulo"],
        "created_at": _iso(fila["created_at"]),
        "updated_at": _iso(fila["updated_at"]),
        "mensajes": [
            {"message_id": m["message_id"], "trace_id": m["trace_id"], "role": m["role"],
             "contenido": m["contenido"], "estado": m["estado"], "codigo_error": m["codigo_error"],
             "timestamp": _iso(m["timestamp"]), "fuentes": m["fuentes"]}
            for m in mensajes
        ],
    }


def _mensajes(conn, ids: list[str]) -> dict[str, list[dict]]:
    por_chat: dict[str, list[dict]] = {cid: [] for cid in ids}
    if ids:
        filas = conn.execute(
            'SELECT conversacion_id, message_id, trace_id, role, contenido, estado, codigo_error, fuentes, "timestamp" '
            "FROM aplicacion.mensaje WHERE conversacion_id = ANY(%s) ORDER BY orden", (ids,)).fetchall()
        for m in filas:
            por_chat[m["conversacion_id"]].append(m)
    return por_chat


def propietario(conn, conversacion_id: str) -> int | None:
    """Id del usuario dueño del chat, o None si no existe."""
    fila = conn.execute("SELECT usuario_id FROM aplicacion.chat WHERE conversacion_id=%s",
                        (conversacion_id,)).fetchone()
    return fila["usuario_id"] if fila else None


def guardar_turno(conn, *, usuario_id: int, conversacion_id: str, pregunta: str, respuesta: dict) -> None:
    """Guarda la pregunta y la respuesta de un turno de /consulta. Crea el chat si es nuevo."""
    conn.execute("""
        INSERT INTO aplicacion.chat (conversacion_id, usuario_id, titulo) VALUES (%s, %s, %s)
        ON CONFLICT (conversacion_id) DO UPDATE SET updated_at = now()
    """, (conversacion_id, usuario_id, pregunta.strip()[:80] or TITULO_POR_DEFECTO))
    trace = respuesta.get("trace_id", "")
    conn.execute("""
        INSERT INTO aplicacion.mensaje (conversacion_id, trace_id, role, contenido, estado)
        VALUES (%s, %s, 'user', %s, %s)
    """, (conversacion_id, trace, pregunta, respuesta.get("estado", "")))
    conn.execute("""
        INSERT INTO aplicacion.mensaje (conversacion_id, trace_id, role, contenido, estado, codigo_error, fuentes)
        VALUES (%s, %s, 'assistant', %s, %s, %s, %s)
    """, (conversacion_id, trace, respuesta.get("texto", ""), respuesta.get("estado", ""),
          respuesta.get("codigo_error", ""), Jsonb(respuesta.get("fuentes") or [])))


def _chat_propio(conn, conversacion_id: str, usuario: dict) -> dict:
    fila = conn.execute("SELECT * FROM aplicacion.chat WHERE conversacion_id=%s AND usuario_id=%s",
                        (conversacion_id, usuario["id"])).fetchone()
    if not fila:
        raise HTTPException(404, detail=CHAT_NO_ENCONTRADO)
    return fila


@router.get("")
def listar(usuario: Annotated[dict, Depends(usuario_actual)],
           limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with connect() as conn:
        total = conn.execute("SELECT count(*) AS n FROM aplicacion.chat WHERE usuario_id=%s",
                             (usuario["id"],)).fetchone()["n"]
        chats = conn.execute("""
            SELECT * FROM aplicacion.chat WHERE usuario_id=%s
            ORDER BY updated_at DESC, conversacion_id LIMIT %s OFFSET %s
        """, (usuario["id"], limit, offset)).fetchall()
        mensajes = _mensajes(conn, [c["conversacion_id"] for c in chats])
    return {"chats": [_chat(c, mensajes[c["conversacion_id"]]) for c in chats], "total": total}


@router.get("/{conversacion_id}")
def ver(conversacion_id: str, usuario: Annotated[dict, Depends(usuario_actual)]):
    with connect() as conn:
        chat = _chat_propio(conn, conversacion_id, usuario)
        return _chat(chat, _mensajes(conn, [conversacion_id])[conversacion_id])


class Renombrar(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)


@router.patch("/{conversacion_id}")
def renombrar(conversacion_id: str, datos: Renombrar, usuario: Annotated[dict, Depends(usuario_actual)]):
    with connect() as conn:
        _chat_propio(conn, conversacion_id, usuario)
        conn.execute("UPDATE aplicacion.chat SET titulo=%s, updated_at=now() WHERE conversacion_id=%s",
                     (datos.titulo.strip(), conversacion_id))
        chat = _chat_propio(conn, conversacion_id, usuario)
        return _chat(chat, _mensajes(conn, [conversacion_id])[conversacion_id])


@router.delete("/{conversacion_id}", status_code=204)
def borrar(conversacion_id: str, usuario: Annotated[dict, Depends(usuario_actual)]):
    with connect() as conn:
        _chat_propio(conn, conversacion_id, usuario)
        conn.execute("DELETE FROM aplicacion.chat WHERE conversacion_id=%s", (conversacion_id,))
    _olvidar_en_agentes(conversacion_id)
    return Response(status_code=204)


def _olvidar_en_agentes(conversacion_id: str) -> None:
    """Pide a Agentes que descarte la memoria del chat borrado. Si no responde, no bloquea el borrado."""
    from .main import agents_url  # import diferido: main importa este módulo
    try:
        httpx.delete(f"{agents_url()}/agentes/conversaciones/{conversacion_id}", headers=service_headers(),
                     timeout=3, trust_env=False)
    except httpx.HTTPError:
        pass
