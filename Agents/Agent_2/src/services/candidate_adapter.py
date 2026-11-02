from __future__ import annotations

from ..models.ctr_002 import VectorCandidate


def to_fusion_candidates(candidates: list[VectorCandidate]) -> list[dict]:
    """Convierte candidatos vectoriales en diccionarios para la fusión RRF."""

    fusion_candidates: list[dict] = []

    for candidate in candidates:
        metadatos = candidate.metadatos
        fusion_candidates.append(
            {
                "chunk_id": candidate.chunk_id,
                "texto": candidate.texto,
                "score_vectorial": candidate.score_vectorial,
                "documento": metadatos.documento,
                "seccion": metadatos.seccion,
                "pagina": metadatos.pagina,
                "versiones": list(metadatos.versiones),
                "componente": metadatos.componente,
                "tipo_documento": metadatos.tipo_documento,
                "obsoleto": metadatos.obsoleto,
                "sustituido_por": metadatos.sustituido_por,
                "fecha_revision": metadatos.fecha_revision,
                "orden_en_seccion": metadatos.orden_en_seccion,
                "version_documento": metadatos.version_documento,
                "afectado_por": list(metadatos.afectado_por),
                "ids_referenciados": list(metadatos.ids_referenciados),
            }
        )

    return fusion_candidates


__all__ = ["to_fusion_candidates"]
