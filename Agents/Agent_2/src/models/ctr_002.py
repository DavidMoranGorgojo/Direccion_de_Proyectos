from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class IndexInfo:
    """Información del índice vectorial devuelta por el Backend."""

    version: str
    modelo_embeddings: str


@dataclass
class ChunkMetadata:
    """Metadatos CTR-002 asociados a un chunk recuperado.

    Es el modelo único de metadatos del Agente 2: lo usan el parser vectorial,
    el empaquetado de evidencias y puede reutilizarlo el parser léxico.
    """

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
class VectorCandidate:
    """Candidato vectorial normalizado para las etapas posteriores."""

    chunk_id: str
    texto: str
    score_vectorial: float
    metadatos: ChunkMetadata


@dataclass
class VectorSearchResponse:
    """Respuesta validada del endpoint de búsqueda vectorial."""

    indice: IndexInfo
    resultados: list[VectorCandidate]
