"""CTR-003 · Registro de consultas.

Dos formas de registrar:
  1. Desde otro endpoint del backend (p. ej. la búsqueda vectorial/BM25 de Jaime),
     llamando a `registrar_consulta(...)` directamente.
  2. Por HTTP con POST /consultas (si el registro lo hace otro servicio, p. ej. Agentes).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chat, RegistroConsulta, Usuario
from app.schemas import ConsultaIn, ConsultaOut
from app.security import solo_admin, usuario_actual

router = APIRouter(prefix="/consultas", tags=["registro de consultas (CTR-003)"])


def registrar_consulta(
    db: Session,
    *,
    consulta: str,
    tipo_busqueda: str,
    usuario_id: int | None = None,
    chat_id: int | None = None,
    num_resultados: int = 0,
    resultados: list | None = None,
    latencia_ms: float | None = None,
    estado: str = "ok",
    error: str | None = None,
) -> RegistroConsulta:
    """Guarda una consulta. Pensado para llamarlo desde los endpoints de búsqueda.

    Ejemplo en el endpoint de búsqueda:
        t0 = time.perf_counter()
        resultados = buscar(...)
        registrar_consulta(db, consulta=q, tipo_busqueda="vectorial", usuario_id=usuario.id,
                           num_resultados=len(resultados), resultados=[r.id for r in resultados],
                           latencia_ms=(time.perf_counter() - t0) * 1000)
    """
    registro = RegistroConsulta(
        usuario_id=usuario_id,
        chat_id=chat_id,
        consulta=consulta,
        tipo_busqueda=tipo_busqueda,
        num_resultados=num_resultados,
        resultados=resultados,
        latencia_ms=latencia_ms,
        estado=estado,
        error=error,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


@router.post("", response_model=ConsultaOut, status_code=status.HTTP_201_CREATED)
def crear_registro(datos: ConsultaIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    if datos.chat_id is not None:
        chat = db.get(Chat, datos.chat_id)
        if chat is None or chat.usuario_id != usuario.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat no encontrado")
    return registrar_consulta(db, usuario_id=usuario.id, **datos.model_dump())


@router.get("/mias", response_model=list[ConsultaOut])
def mis_consultas(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    q = (
        select(RegistroConsulta)
        .where(RegistroConsulta.usuario_id == usuario.id)
        .order_by(RegistroConsulta.creado_en.desc(), RegistroConsulta.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return db.scalars(q).all()


@router.get("", response_model=list[ConsultaOut])
def todas_las_consultas(
    usuario_id: int | None = None,
    tipo_busqueda: str | None = None,
    estado: str | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(solo_admin),
    db: Session = Depends(get_db),
):
    q = select(RegistroConsulta)
    if usuario_id is not None:
        q = q.where(RegistroConsulta.usuario_id == usuario_id)
    if tipo_busqueda:
        q = q.where(RegistroConsulta.tipo_busqueda == tipo_busqueda)
    if estado:
        q = q.where(RegistroConsulta.estado == estado)
    if desde:
        q = q.where(RegistroConsulta.creado_en >= desde)
    if hasta:
        q = q.where(RegistroConsulta.creado_en <= hasta)
    q = q.order_by(RegistroConsulta.creado_en.desc(), RegistroConsulta.id.desc()).limit(limit).offset(offset)
    return db.scalars(q).all()
