from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

from models.source import Source
from models.response import Response, STATUS_OK

ROLE_USER = "user"
ROLE_BOT = "assistant"

# Estados del formato antiguo que pueden quedar en historiales locales ya guardados
_OLD_STATUS = {"ok": "respuesta", "ambiguous": "aclaracion", "no_evidence": "sin_evidencia"}


@dataclass
class Message:
    role: str
    text: str
    status: str = STATUS_OK                       # solo mensajes del asistente
    trace_id: str = ""                            # mismo en la pregunta y en su respuesta
    sources: list[Source] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    message_id: str = ""

    @property
    def is_user(self) -> bool:
        return self.role == ROLE_USER

    @classmethod
    def from_response(cls, r: Response) -> "Message":
        return cls(ROLE_BOT, r.texto, r.estado, r.trace_id, list(r.fuentes))

    def to_dict(self) -> dict:
        return {"message_id": self.message_id, "trace_id": self.trace_id, "role": self.role,
                "contenido": self.text, "estado": self.status, "timestamp": self.timestamp,
                "fuentes": [s.to_dict() for s in self.sources]}

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        """Lee un mensaje de CTR-006 (contenido/estado/fuentes) o del formato local antiguo."""
        status = d.get("estado") or d.get("status") or STATUS_OK
        return cls(
            role=d["role"], text=d.get("contenido", d.get("text", "")),
            status=_OLD_STATUS.get(status, status), trace_id=d.get("trace_id", ""),
            sources=[Source.from_dict(s) for s in d.get("fuentes", d.get("sources")) or []],
            timestamp=d.get("timestamp", ""), message_id=d.get("message_id", ""),
        )
