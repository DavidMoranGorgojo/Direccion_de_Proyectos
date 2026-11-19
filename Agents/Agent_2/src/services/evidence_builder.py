from __future__ import annotations

import math
import re
from dataclasses import asdict
from datetime import date
from typing import Any

from ..models.ctr_002 import ChunkMetadata
from ..models.ctr_004 import Evidence, EvidenceResponse

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class EvidenceBuilderError(ValueError):
    """Error base del empaquetado de evidencias CTR-004."""


class EvidenceContractError(EvidenceBuilderError):
    """El candidato no contiene la estructura obligatoria de CTR-004."""


class EvidenceValidationError(EvidenceBuilderError):
    """Un campo del candidato no tiene un tipo o valor válido."""


def build_evidence_response(candidates: Any) -> dict:
    """Construye la respuesta CTR-004 a partir de candidatos post-reranking."""

    if not isinstance(candidates, list):
        raise EvidenceContractError("Los candidatos deben ser una lista")

    if not candidates:
        return {"resultados": []}

    evidencias: list[Evidence] = []
    chunk_ids: set[str] = set()

    for posicion, candidate in enumerate(candidates):
        evidencia = _build_evidence(candidate, posicion)

        if evidencia.chunk_id in chunk_ids:
            raise EvidenceValidationError(
                f"El campo 'candidatos[{posicion}].chunk_id' está duplicado: "
                f"'{evidencia.chunk_id}'"
            )

        chunk_ids.add(evidencia.chunk_id)
        evidencias.append(evidencia)

    return asdict(EvidenceResponse(resultados=evidencias))


def _build_evidence(candidate: Any, posicion: int) -> Evidence:
    if not isinstance(candidate, dict):
        raise EvidenceContractError(
            f"El campo 'candidatos[{posicion}]' debe ser un objeto"
        )

    base = f"candidatos[{posicion}]"

    return Evidence(
        chunk_id=_parse_string(
            candidate,
            "chunk_id",
            f"{base}.chunk_id",
            non_empty=True,
        ),
        score_final=_parse_rerank_score(
            candidate,
            f"{base}.rerank_score",
        ),
        texto=_parse_string(
            candidate,
            "texto",
            f"{base}.texto",
            non_empty=True,
        ),
        metadatos=_parse_metadata(candidate, base),
    )


def _parse_metadata(candidate: dict, base: str) -> ChunkMetadata:
    return ChunkMetadata(
        # CTR-004 §5: sin documento, sección y página la evidencia no es válida.
        documento=_parse_string(
            candidate,
            "documento",
            f"{base}.documento",
            non_empty=True,
        ),
        seccion=_parse_string(
            candidate,
            "seccion",
            f"{base}.seccion",
            non_empty=True,
        ),
        pagina=_parse_positive_int(candidate, "pagina", f"{base}.pagina"),
        versiones=_parse_string_list(
            candidate,
            "versiones",
            f"{base}.versiones",
        ),
        componente=_parse_string(
            candidate,
            "componente",
            f"{base}.componente",
        ),
        tipo_documento=_parse_string(
            candidate,
            "tipo_documento",
            f"{base}.tipo_documento",
        ),
        obsoleto=_parse_bool(candidate, "obsoleto", f"{base}.obsoleto"),
        sustituido_por=_parse_optional_string(
            candidate,
            "sustituido_por",
            f"{base}.sustituido_por",
        ),
        vigente_para=_parse_string_list(
            candidate,
            "vigente_para",
            f"{base}.vigente_para",
        ),
        fecha_revision=_parse_date(
            candidate,
            "fecha_revision",
            f"{base}.fecha_revision",
        ),
        orden_en_seccion=_parse_int(
            candidate,
            "orden_en_seccion",
            f"{base}.orden_en_seccion",
        ),
        version_documento=_parse_string(
            candidate,
            "version_documento",
            f"{base}.version_documento",
        ),
        afectado_por=_parse_string_list(
            candidate,
            "afectado_por",
            f"{base}.afectado_por",
        ),
        ids_referenciados=_parse_string_list(
            candidate,
            "ids_referenciados",
            f"{base}.ids_referenciados",
        ),
    )


def _required(data: dict, field: str, path: str) -> Any:
    if field not in data:
        raise EvidenceContractError(f"Falta el campo obligatorio '{path}'")

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
        raise EvidenceValidationError(f"El campo '{path}' debe ser un string")

    if non_empty and not value.strip():
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un string no vacío"
        )

    return value


def _parse_optional_string(data: dict, field: str, path: str) -> str | None:
    value = _required(data, field, path)

    if value is None:
        return None

    if not isinstance(value, str):
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un string o null"
        )

    return value


def _parse_int(data: dict, field: str, path: str) -> int:
    value = _required(data, field, path)

    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceValidationError(f"El campo '{path}' debe ser un entero")

    return value


def _parse_positive_int(data: dict, field: str, path: str) -> int:
    value = _parse_int(data, field, path)

    if value < 1:
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un entero mayor que cero"
        )

    return value


def _parse_bool(data: dict, field: str, path: str) -> bool:
    value = _required(data, field, path)

    if not isinstance(value, bool):
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un booleano"
        )

    return value


def _parse_string_list(data: dict, field: str, path: str) -> list[str]:
    value = _required(data, field, path)

    if not isinstance(value, list):
        raise EvidenceValidationError(f"El campo '{path}' debe ser una lista")

    for posicion, item in enumerate(value):
        if not isinstance(item, str):
            raise EvidenceValidationError(
                f"El campo '{path}[{posicion}]' debe ser un string"
            )

    return list(value)


def _parse_rerank_score(data: dict, path: str) -> float:
    value = data.get("rerank_score")
    if value is None:
        value = data.get("score_final")
    if value is None:
        value = _required(data, "rerank_score", path)

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un número finito entre 0 y 1"
        )

    try:
        finito = math.isfinite(value)
    except OverflowError:
        finito = False

    if not finito or not 0 <= value <= 1:
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser un número finito entre 0 y 1"
        )

    return float(value)


def _parse_date(data: dict, field: str, path: str) -> str | None:
    value = _required(data, field, path)

    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError(f"El campo '{path}' debe ser un string no vacío o null")

    if not _DATE_RE.fullmatch(value):
        raise EvidenceValidationError(
            f"El campo '{path}' debe tener formato YYYY-MM-DD"
        )

    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise EvidenceValidationError(
            f"El campo '{path}' debe ser una fecha válida"
        ) from error

    return value


__all__ = [
    "EvidenceBuilderError",
    "EvidenceContractError",
    "EvidenceValidationError",
    "build_evidence_response",
]
