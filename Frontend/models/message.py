from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from models.source import Source
from models.response import Response, STATUS_OK

ROLE_USER = "user"
ROLE_BOT = "assistant"


@dataclass
class Message:
    role: str
    text: str
    status: str = STATUS_OK                       # solo mensajes del asistente
    trace_id: str = ""                            # mismo en la pregunta y en su respuesta
    sources: list[Source] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    message_id: str = ""
    rating: bool | None = None                    # valoración del usuario (solo en memoria)

    @property
    def is_user(self) -> bool:
        return self.role == ROLE_USER

    @classmethod
    def from_response(cls, r: Response) -> "Message":
        return cls(ROLE_BOT, r.texto, r.estado, r.trace_id, list(r.fuentes))

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        """Lee un mensaje de CTR-006 (contenido/estado/fuentes)."""
        return cls(
            role=d["role"], text=d.get("contenido", ""),
            status=d.get("estado") or STATUS_OK, trace_id=d.get("trace_id", ""),
            sources=[Source.from_dict(s) for s in d.get("fuentes") or []],
            timestamp=d.get("timestamp", ""), message_id=d.get("message_id", ""),
        )
