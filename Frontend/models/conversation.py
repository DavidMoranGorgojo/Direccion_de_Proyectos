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

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        """Lee un chat de CTR-006 (conversacion_id/titulo/mensajes)."""
        return cls(id=d["conversacion_id"],
                   title=d.get("titulo") or DEFAULT_TITLE,
                   created_at=d.get("created_at", ""), updated_at=d.get("updated_at", ""),
                   messages=[Message.from_dict(m) for m in d.get("mensajes", [])])
