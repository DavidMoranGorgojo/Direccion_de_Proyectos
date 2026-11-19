from __future__ import annotations

from dataclasses import dataclass

from .ctr_002 import ChunkMetadata


@dataclass
class Evidence:
    """Evidencia CTR-004 preparada para el Agente 1."""

    chunk_id: str
    score_final: float
    texto: str
    metadatos: ChunkMetadata


@dataclass
class EvidenceResponse:
    """Respuesta CTR-004 con las evidencias recuperadas."""

    resultados: list[Evidence]


__all__ = ["Evidence", "EvidenceResponse"]
