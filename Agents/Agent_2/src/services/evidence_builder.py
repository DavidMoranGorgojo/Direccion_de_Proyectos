"""Empaquetado del mensaje de evidencias del Agente 2 al Agente 1 (A2-07).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Optional

from .field_parser import FieldParser

ESTADOS = ("suficiente", "solo_obsoleto", "ambiguo", "sin_evidencia", "error")
ESTADOS_CON_EVIDENCIAS = ("suficiente", "solo_obsoleto")
ESTADOS_SIN_EVIDENCIAS = ("sin_evidencia", "error")
ESTADOS_DOCUMENTO = ("vigente", "obsoleto", "sustituido")
CAMPOS_AMBIGUOS = ("version", "componente")
CODIGOS_ERROR = (
    "entrada_invalida",
    "modelo_no_disponible",
    "modelo_incompatible",
    "indice_no_disponible",
    "tiempo_agotado",
    "error_verificacion",
    "servicio_no_disponible",
)

# A2-06 llama «insuficiente» a lo que el Agente 1 trata como «sin_evidencia».
_SINONIMOS_ESTADO = {"insuficiente": "sin_evidencia"}


class EvidenceBuilderError(ValueError):
    """Error base del empaquetado de evidencias."""


class EvidenceContractError(EvidenceBuilderError):
    """El candidato no contiene la estructura obligatoria."""


class EvidenceValidationError(EvidenceBuilderError):
    """Un campo del candidato o del mensaje no tiene un tipo o valor válido."""


_campos = FieldParser(EvidenceContractError, EvidenceValidationError)


def build_evidences(candidates: Any) -> list[dict]:
    """Convierte los candidatos post-reranking en evidencias para el Agente 1.
    """

    if not isinstance(candidates, list):
        raise EvidenceContractError("Los candidatos deben ser una lista")

    evidencias: list[dict] = []
    chunk_ids: set[str] = set()

    for posicion, candidate in enumerate(candidates):
        evidencia = _build_evidence(candidate, posicion)

        if evidencia["chunk_id"] in chunk_ids:
            raise EvidenceValidationError(
                f"El campo 'candidatos[{posicion}].chunk_id' está duplicado: "
                f"'{evidencia['chunk_id']}'"
            )

        chunk_ids.add(evidencia["chunk_id"])
        evidencias.append(evidencia)

    return evidencias


def build_evidence_response(
    estado: str,
    candidates: Iterable = (),
    *,
    campo_ambiguo: Optional[str] = None,
    codigo_error: Optional[str] = None,
    mensaje_error: Optional[str] = None,
) -> dict:
    """Monta el mensaje completo para el Agente 1.

    Reglas de coherencia:

    - ``suficiente`` y ``solo_obsoleto`` llevan al menos una evidencia.
    - ``sin_evidencia`` y ``error`` no llevan evidencias: un error nunca se
      representa como una lista vacía sin estado.
    - ``error`` exige un ``codigo_error`` de CTR-001; el resto de estados no
      lleva código.
    - ``campo_ambiguo`` solo se indica con ``ambiguo``.
    """

    estado = _SINONIMOS_ESTADO.get(estado, estado)

    if estado not in ESTADOS:
        raise EvidenceValidationError(
            f"El estado debe ser uno de {', '.join(ESTADOS)}"
        )

    candidates = list(candidates)
    evidencias = build_evidences(candidates)

    if estado in ESTADOS_CON_EVIDENCIAS and not evidencias:
        raise EvidenceValidationError(
            f"El estado '{estado}' necesita al menos una evidencia"
        )

    if estado in ESTADOS_SIN_EVIDENCIAS and evidencias:
        raise EvidenceValidationError(
            f"El estado '{estado}' no puede llevar evidencias"
        )

    if estado == "error":
        if codigo_error not in CODIGOS_ERROR:
            raise EvidenceValidationError(
                "El estado 'error' necesita un codigo_error de CTR-001"
            )
    elif codigo_error is not None:
        raise EvidenceValidationError(
            "Solo el estado 'error' puede llevar codigo_error"
        )

    if campo_ambiguo is not None and (
        estado != "ambiguo" or campo_ambiguo not in CAMPOS_AMBIGUOS
    ):
        raise EvidenceValidationError(
            "campo_ambiguo solo se indica con el estado 'ambiguo' y debe ser "
            f"uno de {', '.join(CAMPOS_AMBIGUOS)}"
        )

    if mensaje_error is not None and not isinstance(mensaje_error, str):
        raise EvidenceValidationError("mensaje_error debe ser un string o null")

    return {
        "estado": estado,
        "evidencias": evidencias,
        "campo_ambiguo": campo_ambiguo,
        "codigo_error": codigo_error,
        "mensaje_error": mensaje_error,
    }


def _build_evidence(candidate: Any, posicion: int) -> dict:
    if not isinstance(candidate, dict):
        raise EvidenceContractError(
            f"El campo 'candidatos[{posicion}]' debe ser un objeto"
        )

    base = f"candidatos[{posicion}]"

    chunk_id = _campos.string(
        candidate, "chunk_id", f"{base}.chunk_id", non_empty=True
    )
    score_final = _campos.finite_number(
        candidate, "rerank_score", f"{base}.rerank_score", unit_interval=True
    )
    texto = _campos.string(candidate, "texto", f"{base}.texto", non_empty=True)
    # CTR-004 §5: sin documento, sección y página la evidencia no es válida.
    metadatos = _campos.chunk_metadata(candidate, base, citable=True)

    metadata = asdict(metadatos)
    # El Agente 1 lee la edición en ``metadata.version``.
    metadata["version"] = metadatos.version_documento

    return {
        "chunk_id": chunk_id,
        "texto": texto,
        "score_final": score_final,
        "estado_documento": _estado_documento(candidate, base, metadatos),
        "metadata": metadata,
    }


def _estado_documento(candidate: dict, base: str, metadatos) -> str:
    """Usa el estado de A2-06 si viene; si no, lo deduce de los metadatos."""

    if "estado_documento" in candidate:
        valor = candidate["estado_documento"]

        if valor not in ESTADOS_DOCUMENTO:
            raise EvidenceValidationError(
                f"El campo '{base}.estado_documento' debe ser uno de "
                f"{', '.join(ESTADOS_DOCUMENTO)}"
            )

        return valor

    if not metadatos.obsoleto:
        return "vigente"

    return "sustituido" if metadatos.sustituido_por else "obsoleto"


__all__ = [
    "CAMPOS_AMBIGUOS",
    "CODIGOS_ERROR",
    "ESTADOS",
    "ESTADOS_DOCUMENTO",
    "EvidenceBuilderError",
    "EvidenceContractError",
    "EvidenceValidationError",
    "build_evidence_response",
    "build_evidences",
]
