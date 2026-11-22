"""Serialización pública de evidencias según CTR-004.

Los campos de compatibilidad de A1 son adicionales al formato firmado.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Evidence:
    chunk_id: str
    score_final: float
    texto: str
    metadatos: dict[str, Any]

    @classmethod
    def from_internal(cls, evidence):
        metadata = deepcopy(evidence['metadata'])
        # Alias interno de la edición documental, ausente en CTR-002.
        metadata.pop('version', None)
        return cls(evidence['chunk_id'], evidence['score_final'], evidence['texto'], metadata)


def public_response(response):
    """Incluye resultados incluso en abstenciones y errores controlados.

    Conserva evidencias/metadata para el consumidor A1 existente. Los dos
    formatos no comparten objetos mutables.
    """
    return {
        **response,
        'resultados': [asdict(Evidence.from_internal(item))
                       for item in response.get('evidencias', [])],
    }
