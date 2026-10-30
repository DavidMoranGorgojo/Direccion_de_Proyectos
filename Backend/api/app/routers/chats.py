"""CTR-006 · Historial de chats.

Cada usuario solo ve y modifica sus propios chats.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chat, Mensaje, Usuario, ahora
from app.schemas import ChatDetalle, ChatIn, ChatResumen, ChatUpdate, MensajeIn, MensajeOut
from app.security import usuario_actual

router = APIRouter(prefix="/chats", tags=["historial (CTR-006)"])


def _chat_propio(chat_id: int, usuario: Usuario, db: Session) -> Chat:
    chat = db.get(Chat, chat_id)
    # 404 también si es de otro usuario, para no revelar que existe
    if chat is None or chat.usuario_id != usuario.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat no encontrado")
    return chat


@router.get("", response_model=list[ChatResumen])
def listar_chats(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    q = (
        select(Chat)
        .where(Chat.usuario_id == usuario.id)
        .order_by(Chat.actualizado_en.desc(), Chat.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return db.scalars(q).all()


@router.post("", response_model=ChatResumen, status_code=status.HTTP_201_CREATED)
def crear_chat(datos: ChatIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    chat = Chat(usuario_id=usuario.id, titulo=datos.titulo or "Nuevo chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@router.get("/{chat_id}", response_model=ChatDetalle)
def ver_chat(chat_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    return _chat_propio(chat_id, usuario, db)


@router.patch("/{chat_id}", response_model=ChatResumen)
def renombrar_chat(
    chat_id: int, datos: ChatUpdate, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    chat = _chat_propio(chat_id, usuario, db)
    chat.titulo = datos.titulo
    db.commit()
    db.refresh(chat)
    return chat


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_chat(chat_id: int, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    chat = _chat_propio(chat_id, usuario, db)
    db.delete(chat)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{chat_id}/mensajes", response_model=MensajeOut, status_code=status.HTTP_201_CREATED)
def añadir_mensaje(
    chat_id: int, datos: MensajeIn, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)
):
    chat = _chat_propio(chat_id, usuario, db)
    mensaje = Mensaje(chat_id=chat.id, rol=datos.rol, contenido=datos.contenido, fuentes=datos.fuentes)
    db.add(mensaje)
    # Primer mensaje del usuario como título si el chat no tiene uno propio
    if chat.titulo == "Nuevo chat" and datos.rol == "usuario":
        chat.titulo = datos.contenido[:80]
    chat.actualizado_en = ahora()
    db.commit()
    db.refresh(mensaje)
    return mensaje
