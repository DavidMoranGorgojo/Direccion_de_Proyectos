from __future__ import annotations

from typing import Any

from ..models.ctr_002 import (
    IndexInfo,
    VectorCandidate,
    VectorSearchResponse,
)
from .field_parser import FieldParser


class VectorParserError(ValueError):
    """Error base del parser de respuestas vectoriales."""


class VectorContractError(VectorParserError):
    """La respuesta no contiene la estructura obligatoria de CTR-002."""


class VectorValidationError(VectorParserError):
    """Un campo de la respuesta no tiene un tipo o valor válido."""


_campos = FieldParser(VectorContractError, VectorValidationError)


def parse_vector_response(payload: Any) -> VectorSearchResponse:
    """Valida una respuesta CTR-002 ya decodificada y devuelve el modelo interno."""

    if not isinstance(payload, dict):
        raise VectorContractError("La respuesta debe ser un objeto")

    indice = _parse_index(_campos.required(payload, "indice", "indice"))
    resultados_payload = _campos.required(payload, "resultados", "resultados")

    if not isinstance(resultados_payload, list):
        raise VectorValidationError("El campo 'resultados' debe ser una lista")

    resultados: list[VectorCandidate] = []
    chunk_ids: set[str] = set()

    for posicion, resultado_payload in enumerate(resultados_payload):
        candidate = _parse_candidate(resultado_payload, posicion)

        if candidate.chunk_id in chunk_ids:
            raise VectorValidationError(
                f"El campo 'resultados[{posicion}].chunk_id' está duplicado: "
                f"'{candidate.chunk_id}'"
            )

        chunk_ids.add(candidate.chunk_id)
        resultados.append(candidate)

    return VectorSearchResponse(indice=indice, resultados=resultados)


def _parse_index(value: Any) -> IndexInfo:
    if not isinstance(value, dict):
        raise VectorValidationError("El campo 'indice' debe ser un objeto")

    return IndexInfo(
        version=_campos.string(
            value, "version", "indice.version", non_empty=True
        ),
        modelo_embeddings=_campos.string(
            value,
            "modelo_embeddings",
            "indice.modelo_embeddings",
            non_empty=True,
        ),
    )


def _parse_candidate(value: Any, posicion: int) -> VectorCandidate:
    if not isinstance(value, dict):
        raise VectorContractError(
            f"El campo 'resultados[{posicion}]' debe ser un objeto"
        )

    base = f"resultados[{posicion}]"
    metadatos = _campos.chunk_metadata(value, base)

    return VectorCandidate(
        chunk_id=_campos.string(
            value, "chunk_id", f"{base}.chunk_id", non_empty=True
        ),
        texto=_campos.string(value, "texto", f"{base}.texto", non_empty=True),
        score_vectorial=_campos.finite_number(value, "score", f"{base}.score"),
        metadatos=metadatos,
    )


__all__ = [
    "VectorContractError",
    "VectorParserError",
    "VectorValidationError",
    "parse_vector_response",
]
