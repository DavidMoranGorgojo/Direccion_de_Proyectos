"""Parseo y validación de la respuesta léxica de CTR-002.

El Backend devuelve ``{"indice": ..., "resultados": [...]}``. Este parser
comprueba la estructura y los tipos, y conserva sin modificar el texto, los
identificadores y los códigos exactos que vienen del índice BM25.

La validación de campos es la común de CTR-002 (``services.field_parser``),
con las clases de error propias de esta etapa.
"""

from __future__ import annotations

from typing import Any

from ..models.lexical import (
    LexicalCandidate,
    LexicalIndexInfo,
    LexicalSearchResponse,
)
from .field_parser import FieldParser


class LexicalParserError(ValueError):
    """Error base del parser de respuestas léxicas."""


class LexicalContractError(LexicalParserError):
    """La respuesta no contiene la estructura obligatoria de CTR-002."""


class LexicalValidationError(LexicalParserError):
    """Un campo de la respuesta no tiene un tipo o valor válido."""


_campos = FieldParser(LexicalContractError, LexicalValidationError)


def parse_lexical_response(payload: Any) -> LexicalSearchResponse:
    """Valida una respuesta léxica ya decodificada y devuelve el modelo interno."""

    if not isinstance(payload, dict):
        raise LexicalContractError("La respuesta debe ser un objeto")

    indice = _parse_index(_campos.required(payload, "indice", "indice"))
    resultados_payload = _campos.required(payload, "resultados", "resultados")

    if not isinstance(resultados_payload, list):
        raise LexicalValidationError("El campo 'resultados' debe ser una lista")

    resultados: list[LexicalCandidate] = []
    chunk_ids: set[str] = set()

    for posicion, resultado_payload in enumerate(resultados_payload):
        candidate = _parse_candidate(resultado_payload, posicion)

        if candidate.chunk_id in chunk_ids:
            raise LexicalValidationError(
                f"El campo 'resultados[{posicion}].chunk_id' está duplicado: "
                f"'{candidate.chunk_id}'"
            )

        chunk_ids.add(candidate.chunk_id)
        resultados.append(candidate)

    return LexicalSearchResponse(indice=indice, resultados=resultados)


def _parse_index(value: Any) -> LexicalIndexInfo:
    if not isinstance(value, dict):
        raise LexicalValidationError("El campo 'indice' debe ser un objeto")

    return LexicalIndexInfo(
        version=_campos.string(value, "version", "indice.version", non_empty=True),
        modelo_embeddings=_campos.string(
            value,
            "modelo_embeddings",
            "indice.modelo_embeddings",
            non_empty=True,
        ),
    )


def _parse_candidate(value: Any, posicion: int) -> LexicalCandidate:
    if not isinstance(value, dict):
        raise LexicalContractError(
            f"El campo 'resultados[{posicion}]' debe ser un objeto"
        )

    base = f"resultados[{posicion}]"

    # El score de BM25 es crudo: solo se exige que sea finito, sin rango.
    return LexicalCandidate(
        chunk_id=_campos.string(
            value, "chunk_id", f"{base}.chunk_id", non_empty=True
        ),
        texto=_campos.string(value, "texto", f"{base}.texto", non_empty=True),
        score_lexico=_campos.finite_number(value, "score", f"{base}.score"),
        metadatos=_campos.chunk_metadata(value, base),
    )


__all__ = [
    "LexicalContractError",
    "LexicalParserError",
    "LexicalValidationError",
    "parse_lexical_response",
]
