"""Modelos de usuarios, chats, mensajes y registro de consultas.

ESQUEMA PROVISIONAL: hay que alinearlo con el esquema unificado de
Roberto y Daniel (nombres de tablas/columnas y tipos) cuando esté cerrado.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(128))
    rol: Mapped[str] = mapped_column(String(16), default="usuario")  # usuario | admin
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chats: Mapped[list["Chat"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    titulo: Mapped[str] = mapped_column(String(200), default="Nuevo chat")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)

    usuario: Mapped[Usuario] = relationship(back_populates="chats")
    mensajes: Mapped[list["Mensaje"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Mensaje.id"
    )


class Mensaje(Base):
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    rol: Mapped[str] = mapped_column(String(16))  # usuario | asistente
    contenido: Mapped[str] = mapped_column(Text)
    fuentes: Mapped[list | None] = mapped_column(JSON, nullable=True)  # documentos/fragmentos citados
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    chat: Mapped[Chat] = relationship(back_populates="mensajes")


class RegistroConsulta(Base):
    __tablename__ = "registro_consultas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), index=True, nullable=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"), nullable=True)
    consulta: Mapped[str] = mapped_column(Text)
    tipo_busqueda: Mapped[str] = mapped_column(String(16))  # vectorial | bm25 | agentes | otro
    num_resultados: Mapped[int] = mapped_column(Integer, default=0)
    resultados: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ids de fragmentos devueltos
    latencia_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    estado: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, index=True)
