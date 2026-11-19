"""Simulador del Agente 1 para las pruebas de contrato CTR-004 (CJ-01).

Reproduce el otro extremo del intercambio: cómo recibe el Agente 1 el mensaje
de evidencias del Agente 2 (CTR-004) y qué decide con él. La validación es la
misma que aplica el Agente 1 real y no redacta ni llama a ningún LLM: devuelve
el estado y las fuentes que acabarían en la respuesta CTR-001.

``construir_mensaje_ctr004`` es una ayuda de prueba para llevar el resultado de
A2-06 (``RetrievalResult``) a la forma CTR-004. El empaquetado definitivo de
evidencias es A2-07: esta función fija el contrato que ese paquete debe cumplir,
no lo sustituye.

Deuda conocida
--------------
El Agente 1 real considera obsoleta cualquier evidencia con ``sustituido_por``,
aunque A2-06 la marque ``vigente`` para las versiones de ``vigente_para``. El
simulador reproduce esa regla para no dar una falsa sensación de acuerdo; hay
que revisarla con el Agente 1 antes de cerrar CJ-03.
"""

from __future__ import annotations

import json

from ..core.errors import CODIGOS_ERROR

ESTADOS_CTR004 = frozenset(
    {
        "error",
        "sin_evidencia",
        "insuficiente",
        "ambiguo",
        "suficiente",
        "solo_obsoleto",
    }
)

CAMPOS_METADATOS = (
    "version",
    "versiones",
    "documento",
    "seccion",
    "pagina",
    "obsoleto",
    "sustituido_por",
    "componente",
    "tipo_documento",
    "vigente_para",
)


def _error_contrato(mensaje="Contrato de Agente 2 inválido."):
    return {
        "estado": "error",
        "evidencias": [],
        "campo_ambiguo": None,
        "mensaje_error": mensaje,
        "codigo_error": "error_verificacion",
    }


def evidencia_valida(evidencia):
    """Tipos necesarios para citar y serializar fuentes de CTR-001."""

    if (
        not isinstance(evidencia, dict)
        or not isinstance(evidencia.get("chunk_id"), str)
        or not evidencia["chunk_id"]
    ):
        return False

    if not isinstance(evidencia.get("texto"), str) or not evidencia["texto"].strip():
        return False

    metadata = evidencia.get("metadata")

    if not isinstance(metadata, dict):
        return False

    for campo in ("documento", "seccion", "version"):
        if campo in metadata and not isinstance(metadata[campo], str):
            return False

    if "pagina" in metadata and (
        type(metadata["pagina"]) is not int or metadata["pagina"] < 0
    ):
        return False

    if "versiones" in metadata and (
        not isinstance(metadata["versiones"], list)
        or any(not isinstance(version, str) for version in metadata["versiones"])
    ):
        return False

    if "obsoleto" in metadata and type(metadata["obsoleto"]) is not bool:
        return False

    if metadata.get("sustituido_por") is not None and not isinstance(
        metadata["sustituido_por"], str
    ):
        return False

    estado = evidencia.get("estado_documento", "vigente")
    return isinstance(estado, str) and estado in {
        "vigente",
        "obsoleto",
        "sustituido",
    }


def validar_respuesta_agente2(respuesta):
    """Valida el mensaje CTR-004 igual que el Agente 1 antes de decidir."""

    if not isinstance(respuesta, dict):
        return _error_contrato()

    try:
        json.dumps(respuesta, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return _error_contrato()

    estado = respuesta.get("estado")
    evidencias = respuesta.get("evidencias")

    if (
        not isinstance(estado, str)
        or estado not in ESTADOS_CTR004
        or not isinstance(evidencias, list)
        or any(not evidencia_valida(evidencia) for evidencia in evidencias)
    ):
        return _error_contrato()

    if estado in {"suficiente", "solo_obsoleto"} and not evidencias:
        return _error_contrato()

    if estado in {"sin_evidencia", "insuficiente"} and evidencias:
        return _error_contrato()

    campo = respuesta.get("campo_ambiguo")
    mensaje = respuesta.get("mensaje_error")

    if (
        campo is not None and (not isinstance(campo, str) or not campo.strip())
    ) or (mensaje is not None and not isinstance(mensaje, str)):
        return _error_contrato()

    por_id = {}

    for evidencia in evidencias:
        chunk_id = evidencia["chunk_id"]

        if chunk_id in por_id and evidencia != por_id[chunk_id]:
            return _error_contrato()

        por_id[chunk_id] = evidencia

    codigo_error = respuesta.get("codigo_error", "")

    if codigo_error not in CODIGOS_ERROR:
        codigo_error = ""

    if estado == "error" and not codigo_error:
        codigo_error = "error_verificacion"

    return {
        "estado": estado,
        "evidencias": list(por_id.values()),
        "campo_ambiguo": campo,
        "mensaje_error": mensaje,
        "codigo_error": codigo_error,
    }


def es_obsoleta(evidencia):
    """Regla de obsolescencia del Agente 1 real (ver «Deuda conocida»)."""

    metadata = evidencia.get("metadata", {})

    return (
        evidencia.get("estado_documento") in {"obsoleto", "sustituido"}
        or metadata.get("obsoleto") is True
        or bool(metadata.get("sustituido_por"))
    )


def resolver_evidencias(respuesta, version=None):
    """Decide como el Agente 1: respuesta, aclaración, sin evidencia o error."""

    normalizada = validar_respuesta_agente2(respuesta)
    estado = normalizada["estado"]
    evidencias = normalizada["evidencias"]

    if estado == "error":
        mensaje = normalizada.get("mensaje_error")

        return {
            "estado": "error",
            "texto": mensaje
            if isinstance(mensaje, str) and mensaje
            else "Error de recuperación.",
            "fuentes": [],
            "codigo_error": normalizada.get("codigo_error")
            or "indice_no_disponible",
        }

    if estado == "ambiguo":
        campo = normalizada.get("campo_ambiguo") or "version"

        return {
            "estado": "aclaracion",
            "texto": f"¿Qué {campo} necesitas consultar?",
            "fuentes": [],
            "campo_aclaracion": campo,
        }

    if estado in {"sin_evidencia", "insuficiente"} or not evidencias:
        return {
            "estado": "sin_evidencia",
            "texto": (
                "No se ha encontrado información en la documentación "
                "disponible."
            ),
            "fuentes": [],
        }

    if version:
        compatibles = [
            evidencia
            for evidencia in evidencias
            if version in evidencia["metadata"].get("versiones", [])
            or evidencia["metadata"].get("version") == version
        ]

        if not compatibles:
            return {
                "estado": "error",
                "texto": (
                    "Las evidencias no corresponden a la versión solicitada."
                ),
                "fuentes": [],
            }

        evidencias = compatibles

    vigentes = [
        evidencia for evidencia in evidencias if not es_obsoleta(evidencia)
    ]

    if estado == "solo_obsoleto" and vigentes:
        return {
            "estado": "error",
            "texto": "Estado de obsolescencia incoherente en Agente 2.",
            "fuentes": [],
        }

    seleccion = vigentes or evidencias

    return {
        "estado": "respuesta",
        "texto": "Respuesta simulada: redacta A1.",
        "fuentes": [
            {
                "chunk_id": evidencia["chunk_id"],
                "documento": evidencia["metadata"].get("documento", ""),
                "seccion": evidencia["metadata"].get("seccion", ""),
                "pagina": evidencia["metadata"].get("pagina", 0),
                "versiones": evidencia["metadata"].get("versiones", []),
                "obsoleto": es_obsoleta(evidencia),
            }
            for evidencia in seleccion
        ],
        "aviso": None
        if vigentes
        else "AVISO: La documentación disponible es OBSOLETA / SUSTITUIDA.",
    }


def _metadata(candidato):
    metadata = {
        "version": candidato.get("version_documento"),
        "versiones": list(candidato.get("versiones") or []),
        "documento": candidato.get("documento"),
        "seccion": candidato.get("seccion"),
        "pagina": candidato.get("pagina"),
        "obsoleto": candidato.get("obsoleto"),
        "sustituido_por": candidato.get("sustituido_por"),
        "componente": candidato.get("componente"),
        "tipo_documento": candidato.get("tipo_documento"),
        "vigente_para": list(candidato.get("vigente_para") or []),
    }

    return {
        campo: valor
        for campo, valor in metadata.items()
        if valor is not None
    }


def construir_mensaje_ctr004(resultado):
    """Ayuda de prueba: ``RetrievalResult`` de A2-06 → mensaje CTR-004."""

    estado = getattr(resultado, "estado", None)

    if estado not in ESTADOS_CTR004:
        raise ValueError(f"Estado de recuperación no válido: {estado!r}")

    mensaje = {
        "estado": estado,
        "evidencias": [],
        "campo_ambiguo": getattr(resultado, "campo_ambiguo", None),
        "mensaje_error": getattr(resultado, "mensaje_error", None),
        "codigo_error": getattr(resultado, "codigo_error", None)
        or "",
    }

    if estado in {"insuficiente", "error", "sin_evidencia"}:
        return mensaje

    for candidato in resultado.candidatos:
        mensaje["evidencias"].append(
            {
                "chunk_id": candidato["chunk_id"],
                "texto": candidato["texto"],
                "score_final": float(
                    candidato.get("score_final", candidato.get("score", 0.0))
                ),
                "metadata": _metadata(candidato),
                "estado_documento": candidato.get(
                    "estado_documento",
                    "vigente",
                ),
            }
        )

    return mensaje


__all__ = [
    "CAMPOS_METADATOS",
    "ESTADOS_CTR004",
    "construir_mensaje_ctr004",
    "es_obsoleta",
    "evidencia_valida",
    "resolver_evidencias",
    "validar_respuesta_agente2",
]
