"""Modelos internos de la respuesta léxica de CTR-002.

La respuesta de ``POST /conocimiento/lexica`` comparte estructura con la
vectorial (``indice`` + ``resultados``), pero el score es el valor crudo de
BM25. Este módulo no normaliza ningún texto ni código: los valores se
conservan exactamente como los devuelve el Backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LexicalIndexInfo:
    """Información del índice devuelta por el Backend."""

    version: str
    modelo_embeddings: str


@dataclass
class LexicalMetadata:
    """Metadatos CTR-002 asociados a un chunk recuperado."""

    documento: str
    seccion: str
    pagina: int
    versiones: list[str]
    componente: str
    tipo_documento: str
    obsoleto: bool
    sustituido_por: Optional[str]
    vigente_para: list[str]
    fecha_revision: Optional[str]
    orden_en_seccion: int
    version_documento: str
    afectado_por: list[str]
    ids_referenciados: list[str]


@dataclass
class LexicalCandidate:
    """Candidato léxico normalizado para las etapas posteriores."""

    chunk_id: str
    texto: str
    score_lexico: float
    metadatos: LexicalMetadata


@dataclass
class LexicalSearchResponse:
    """Respuesta validada del endpoint de búsqueda léxica."""

    indice: LexicalIndexInfo
    resultados: list[LexicalCandidate]
