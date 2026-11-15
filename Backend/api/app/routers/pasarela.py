"""Pasarela hacia Agentes · CTR-001 → Agentes, con registro CTR-003.

Flujo de POST /consulta:
  1. Frontend envía la consulta (CTR-001) con su token.
  2. Backend valida lo mínimo (que haya pregunta y, si viene chat_id, que el chat sea del usuario).
  3. Reenvía a Agentes los MISMOS bytes que recibió (no toca el cuerpo); solo añade
     las cabeceras X-Trace-Id y X-Usuario-Id. El token del usuario no se reenvía.
  4. Devuelve a Frontend la respuesta de Agentes tal cual, con la cabecera X-Trace-Id.
  5. Registra la consulta con registrar_consulta (CTR-003), haya ido bien o mal.

Mientras Agentes no esté listo, AGENTES_MODO=simulado devuelve respuestas de prueba.
"""
import time

from fastapi import APIRouter, Depends, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import agentes
from app.db import get_db
from app.models import Chat, Usuario
from app.routers.consultas import registrar_consulta
from app.schemas import ConsultaFrontendIn, ErrorPasarela
from app.security import usuario_actual

router = APIRouter(tags=["pasarela hacia Agentes (CTR-001)"])


def _ids_fuentes(datos: dict) -> list:
    """Ids de los fragmentos citados en la respuesta de Agentes (tolerante con la forma)."""
    fuentes = datos.get("fuentes") or datos.get("resultados") or []
    if not isinstance(fuentes, list):
        return []
    ids = []
    for f in fuentes:
        if isinstance(f, dict):
            ident = f.get("id_fragmento") or f.get("fragmento_id") or f.get("id") or f.get("chunk_id") or f.get("documento")
            if ident is not None:
                ids.append(ident)
        elif isinstance(f, (str, int)):
            ids.append(f)
    return ids


def _error(http: int, mensaje: str, codigo: str, trace_id: str | None) -> JSONResponse:
    cabeceras = {"X-Trace-Id": trace_id} if trace_id else None
    return JSONResponse(
        status_code=http,
        content=ErrorPasarela(mensaje=mensaje, codigo_error=codigo, trace_id=trace_id).model_dump(),
        headers=cabeceras,
    )


def _procesar(cuerpo: bytes, datos: ConsultaFrontendIn, usuario: Usuario, db: Session) -> JSONResponse:
    if datos.chat_id is not None:
        chat = db.get(Chat, datos.chat_id)
        if chat is None or chat.usuario_id != usuario.id:
            return _error(status.HTTP_404_NOT_FOUND, "Chat no encontrado", "chat_no_encontrado", None)

    trace_id = agentes.nuevo_trace_id()
    registro = {"consulta": datos.pregunta, "tipo_busqueda": "agentes",
                "usuario_id": usuario.id, "chat_id": datos.chat_id}
    t0 = time.perf_counter()

    def latencia() -> float:
        return round((time.perf_counter() - t0) * 1000, 2)

    try:
        resp = agentes.reenviar(cuerpo, trace_id=trace_id, usuario_id=usuario.id)
    except agentes.AgentesTiempoAgotado:
        registrar_consulta(db, **registro, latencia_ms=latencia(), estado="error",
                           error=f"[{trace_id}] tiempo agotado esperando a Agentes")
        return _error(status.HTTP_504_GATEWAY_TIMEOUT, "Agentes no respondió a tiempo. Inténtalo de nuevo.",
                      "agentes_tiempo_agotado", trace_id)
    except agentes.AgentesNoDisponible as e:
        registrar_consulta(db, **registro, latencia_ms=latencia(), estado="error",
                           error=f"[{trace_id}] Agentes no disponible: {e}")
        return _error(status.HTTP_502_BAD_GATEWAY, "El servicio de Agentes no está disponible.",
                      "agentes_no_disponible", trace_id)
    except agentes.AgentesRespuestaInvalida as e:
        registrar_consulta(db, **registro, latencia_ms=latencia(), estado="error", error=f"[{trace_id}] {e}")
        return _error(status.HTTP_502_BAD_GATEWAY, "El servicio de Agentes devolvió una respuesta no válida.",
                      "agentes_respuesta_invalida", trace_id)

    ids = _ids_fuentes(resp.datos)
    registrar_consulta(db, **registro, num_resultados=len(ids), resultados=ids or None, latencia_ms=latencia())
    return JSONResponse(status_code=200, content=resp.datos,
                        headers={"X-Trace-Id": trace_id, "X-Agentes-Modo": agentes.modo()})


@router.post(
    "/consulta",
    responses={
        200: {"description": "Respuesta de Agentes, sin modificar"},
        404: {"model": ErrorPasarela}, 502: {"model": ErrorPasarela}, 504: {"model": ErrorPasarela},
    },
)
async def consulta(
    datos: ConsultaFrontendIn,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """CTR-001: consulta de Frontend. Se reenvía a Agentes sin tocarla y se registra (CTR-003)."""
    cuerpo = await request.body()  # bytes originales, los que se reenvían
    return await run_in_threadpool(_procesar, cuerpo, datos, usuario, db)


@router.get("/consulta/estado")
def estado_pasarela(_: Usuario = Depends(usuario_actual)):
    """Indica a Frontend si la pasarela está en modo real o simulado."""
    return {"modo": agentes.modo()}

