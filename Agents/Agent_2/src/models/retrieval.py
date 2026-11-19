"""Modelos internos del estado de recuperación (A2-06).

El Agente 2 no devuelve estos objetos al Agente 1: el empaquetado CTR-004
(A2-07) los convierte en ``estado``, ``evidencias``, ``campo_ambiguo``,
``mensaje_error`` y ``codigo_error``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


ESTADOS = frozenset(
    {
        "suficiente",
        "ambiguo",
        "solo_obsoleto",
        "insuficiente",
        "error",
    }
)

CAMPOS_AMBIGUOS = frozenset({"version", "componente"})


@dataclass(frozen=True)
class RetrievalDecision:
    """Estado decidido a partir de los candidatos que superan el umbral."""

    estado: str
    campo_ambiguo: Optional[str] = None


@dataclass
class RetrievalResult:
    """Estado final con los candidatos ya ampliados con sus vecinos."""

    estado: str
    candidatos: list = field(default_factory=list)
    campo_ambiguo: Optional[str] = None
    codigo_error: Optional[str] = None
    mensaje_error: Optional[str] = None

    @property
    def es_error(self):
        return self.estado == "error"


__all__ = [
    "CAMPOS_AMBIGUOS",
    "ESTADOS",
    "RetrievalDecision",
    "RetrievalResult",
]
