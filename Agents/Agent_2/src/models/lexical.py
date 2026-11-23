"""Modelos internos de la respuesta léxica de CTR-002.

La respuesta de ``POST /conocimiento/lexica`` comparte estructura con la
vectorial (``indice`` + ``resultados``), pero el score es el valor crudo de
BM25. Este módulo no normaliza ningún texto ni código: los valores se
conservan exactamente como los devuelve el Backend.

Los metadatos usan ``ChunkMetadata`` (``models.ctr_002``), el modelo único de
metadatos CTR-002 del Agente 2, compartido con el parser vectorial y el
empaquetado de evidencias.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ctr_002 import ChunkMetadata


@dataclass
class LexicalIndexInfo:
    """Información del índice devuelta por el Backend."""

    version: str
    modelo_embeddings: str


@dataclass
class LexicalCandidate:
    """Candidato léxico normalizado para las etapas posteriores."""

    chunk_id: str
    texto: str
    score_lexico: float
    metadatos: ChunkMetadata

    def to_rrf_dict(self) -> dict:
        """Convierte el candidato a un diccionario plano compatible con RRF."""
        meta = self.metadatos
        return {
            "chunk_id": self.chunk_id,
            "texto": self.texto,
            "score_bm25": self.score_lexico,
            "documento": meta.documento,
            "seccion": meta.seccion,
            "pagina": meta.pagina,
            "versiones": list(meta.versiones),
            "componente": meta.componente,
            "tipo_documento": meta.tipo_documento,
            "obsoleto": meta.obsoleto,
            "sustituido_por": meta.sustituido_por,
            "vigente_para": list(meta.vigente_para),
            "fecha_revision": meta.fecha_revision,
            "orden_en_seccion": meta.orden_en_seccion,
            "version_documento": meta.version_documento,
            "afectado_por": list(meta.afectado_por),
            "ids_referenciados": list(meta.ids_referenciados),
        }


@dataclass
class LexicalSearchResponse:
    """Respuesta validada del endpoint de búsqueda léxica."""

    indice: LexicalIndexInfo
    resultados: list[LexicalCandidate]

    def as_rrf_input(self) -> list[dict]:
        """Devuelve todos los candidatos como lista de diccionarios planos para RRF."""
        return [candidate.to_rrf_dict() for candidate in self.resultados]


__all__ = [
    "LexicalCandidate",
    "LexicalIndexInfo",
    "LexicalSearchResponse",
]
