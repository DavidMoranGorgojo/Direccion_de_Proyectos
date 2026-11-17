from __future__ import annotations
from dataclasses import dataclass, field

from models.source import Source

# Estados de CTR-001 (se escriben exactamente así, sin tildes)
STATUS_OK = "respuesta"                  # respuesta fundamentada, con fuentes
STATUS_CLARIFY = "aclaracion"            # el texto es la repregunta
STATUS_NO_EVIDENCE = "sin_evidencia"
STATUS_OUT_OF_SCOPE = "fuera_de_ambito"
STATUS_ERROR = "error"
STATUSES = (STATUS_OK, STATUS_CLARIFY, STATUS_NO_EVIDENCE, STATUS_OUT_OF_SCOPE, STATUS_ERROR)

GENERIC_ERROR = "El asistente no está disponible, inténtalo de nuevo."


@dataclass
class Response:
    """Respuesta del asistente tal como la define CTR-001 (el Backend la reenvía sin tocarla)."""
    texto: str
    estado: str = STATUS_OK
    fuentes: list[Source] = field(default_factory=list)
    trace_id: str = ""
    codigo_error: str = ""
    conversacion_id: str = ""

    @classmethod
    def error(cls, texto: str = GENERIC_ERROR, codigo: str = "") -> "Response":
        return cls(texto, STATUS_ERROR, codigo_error=codigo)

    @classmethod
    def from_dict(cls, d: dict) -> "Response":
        estado = d.get("estado", "")
        if estado not in STATUSES:               # estado desconocido: no se inventa nada
            return cls.error(d.get("texto") or GENERIC_ERROR, "estado_desconocido")
        return cls(texto=d.get("texto", ""), estado=estado,
                   fuentes=[Source.from_dict(s) for s in d.get("fuentes") or []],
                   trace_id=d.get("trace_id", ""), codigo_error=d.get("codigo_error", ""),
                   conversacion_id=d.get("conversacion_id", ""))
