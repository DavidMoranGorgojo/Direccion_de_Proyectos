from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from ..models.ctr_002 import (
    ChunkMetadata,
    IndexInfo,
    VectorCandidate,
    VectorSearchResponse,
)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class VectorParserError(ValueError):
    """Error base del parser de respuestas vectoriales."""


class VectorContractError(VectorParserError):
    """La respuesta no contiene la estructura obligatoria de CTR-002."""


class VectorValidationError(VectorParserError):
    """Un campo de la respuesta no tiene un tipo o valor válido."""


def parse_vector_response(payload: Any) -> VectorSearchResponse:
    """Valida una respuesta CTR-002 ya decodificada y devuelve el modelo interno."""

    if not isinstance(payload, dict):
        raise VectorContractError("La respuesta debe ser un objeto")

    indice = _parse_index(_required(payload, "indice", "indice"))
    resultados_payload = _required(payload, "resultados", "resultados")

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
        version=_parse_string(value, "version", "indice.version", non_empty=True),
        modelo_embeddings=_parse_string(
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

    metadatos = ChunkMetadata(
        documento=_parse_string(value, "documento", f"{base}.documento"),
        seccion=_parse_string(value, "seccion", f"{base}.seccion"),
        pagina=_parse_int(value, "pagina", f"{base}.pagina"),
        versiones=_parse_string_list(value, "versiones", f"{base}.versiones"),
        componente=_parse_string(value, "componente", f"{base}.componente"),
        tipo_documento=_parse_string(
            value,
            "tipo_documento",
            f"{base}.tipo_documento",
        ),
        obsoleto=_parse_bool(value, "obsoleto", f"{base}.obsoleto"),
        sustituido_por=_parse_optional_string(
            value,
            "sustituido_por",
            f"{base}.sustituido_por",
        ),
        fecha_revision=_parse_date(
            value,
            "fecha_revision",
            f"{base}.fecha_revision",
        ),
        orden_en_seccion=_parse_int(
            value,
            "orden_en_seccion",
            f"{base}.orden_en_seccion",
        ),
        version_documento=_parse_string(
            value,
            "version_documento",
            f"{base}.version_documento",
        ),
        afectado_por=_parse_string_list(
            value,
            "afectado_por",
            f"{base}.afectado_por",
        ),
        ids_referenciados=_parse_string_list(
            value,
            "ids_referenciados",
            f"{base}.ids_referenciados",
        ),
    )

    return VectorCandidate(
        chunk_id=_parse_string(
            value,
            "chunk_id",
            f"{base}.chunk_id",
            non_empty=True,
        ),
        texto=_parse_string(value, "texto", f"{base}.texto", non_empty=True),
        score_vectorial=_parse_score(value, "score", f"{base}.score"),
        metadatos=metadatos,
    )


def _required(data: dict, field: str, path: str) -> Any:
    if field not in data:
        raise VectorContractError(f"Falta el campo obligatorio '{path}'")

    return data[field]


def _parse_string(
    data: dict,
    field: str,
    path: str,
    *,
    non_empty: bool = False,
) -> str:
    value = _required(data, field, path)

    if not isinstance(value, str):
        raise VectorValidationError(f"El campo '{path}' debe ser un string")

    if non_empty and not value.strip():
        raise VectorValidationError(
            f"El campo '{path}' debe ser un string no vacío"
        )

    return value


def _parse_optional_string(data: dict, field: str, path: str) -> str | None:
    value = _required(data, field, path)

    if value is None:
        return None

    if not isinstance(value, str):
        raise VectorValidationError(
            f"El campo '{path}' debe ser un string o null"
        )

    return value


def _parse_int(data: dict, field: str, path: str) -> int:
    value = _required(data, field, path)

    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorValidationError(f"El campo '{path}' debe ser un entero")

    return value


def _parse_bool(data: dict, field: str, path: str) -> bool:
    value = _required(data, field, path)

    if not isinstance(value, bool):
        raise VectorValidationError(f"El campo '{path}' debe ser un booleano")

    return value


def _parse_string_list(data: dict, field: str, path: str) -> list[str]:
    value = _required(data, field, path)

    if not isinstance(value, list):
        raise VectorValidationError(f"El campo '{path}' debe ser una lista")

    for posicion, item in enumerate(value):
        if not isinstance(item, str):
            raise VectorValidationError(
                f"El campo '{path}[{posicion}]' debe ser un string"
            )

    return list(value)


def _parse_score(data: dict, field: str, path: str) -> float:
    value = _required(data, field, path)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VectorValidationError(f"El campo '{path}' debe ser un número finito")

    try:
        finito = math.isfinite(value)
    except OverflowError:
        finito = False

    if not finito:
        raise VectorValidationError(f"El campo '{path}' debe ser un número finito")

    return float(value)


def _parse_date(data: dict, field: str, path: str) -> str:
    value = _parse_string(data, field, path, non_empty=True)

    if not _DATE_RE.fullmatch(value):
        raise VectorValidationError(
            f"El campo '{path}' debe tener formato YYYY-MM-DD"
        )

    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise VectorValidationError(
            f"El campo '{path}' debe ser una fecha válida"
        ) from error

    return value


__all__ = [
    "VectorContractError",
    "VectorParserError",
    "VectorValidationError",
    "parse_vector_response",
]
