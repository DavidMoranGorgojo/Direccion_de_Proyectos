from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from models.message import Message

DEFAULT_TITLE = "Nuevo chat"


@dataclass
class Conversation:
    """`id` es el conversacion_id (CTR-001/003/006). Lo genera el Backend; mientras una
    conversación nueva no lo tenga, se usa un identificador opaco local."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = DEFAULT_TITLE
    messages: list[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    server_id: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {"conversacion_id": self.id, "titulo": self.title, "created_at": self.created_at,
                "updated_at": self.updated_at, "mensajes": [m.to_dict() for m in self.messages]}

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        """Lee un chat de CTR-006 (conversacion_id/titulo/mensajes) o del formato local antiguo."""
        return cls(id=d.get("conversacion_id") or d["id"],
                   title=d.get("titulo") or d.get("title") or DEFAULT_TITLE,
                   server_id=d.get("conversacion_id", ""),
                   created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
                   messages=[Message.from_dict(m) for m in d.get("mensajes", d.get("messages", []))])
