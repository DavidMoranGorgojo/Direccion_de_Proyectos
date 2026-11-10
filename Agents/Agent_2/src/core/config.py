
"""
Configuración del Agente 2.

Centraliza los parámetros utilizados por la recuperación
híbrida, la fusión RRF y el reranker.

Los valores pueden sobrescribirse mediante variables
de entorno durante el despliegue.
"""

import math
import os


def _get_positive_int(name, default):
    """
    Obtiene un entero positivo desde una variable de entorno.

    Incluye el nombre de la variable en los errores
    para facilitar el diagnóstico de configuración.
    """

    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            f"{name} debe ser un entero mayor que cero; "
            f"valor recibido: {raw_value!r}"
        ) from error

    if value <= 0:
        raise ValueError(
            f"{name} debe ser un entero mayor que cero; "
            f"valor recibido: {raw_value!r}"
        )

    return value


def _get_threshold(name, default):
    """
    Obtiene un umbral numérico finito entre 0 y 1.
    """

    raw_value = os.getenv(name, str(default))

    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            f"{name} debe ser un número finito entre 0 y 1; "
            f"valor recibido: {raw_value!r}"
        ) from error

    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(
            f"{name} debe ser un número finito entre 0 y 1; "
            f"valor recibido: {raw_value!r}"
        )

    return value


def _get_non_empty_string(name, default):
    """
    Obtiene una cadena no vacía desde una variable de entorno.
    """

    value = os.getenv(name, default)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} debe ser una cadena de texto no vacía"
        )

    return value.strip()


RRF_K = _get_positive_int(
    "AGENT2_RRF_K",
    60,
)

RERANKER_MODEL = _get_non_empty_string(
    "AGENT2_RERANKER_MODEL",
    "BAAI/bge-reranker-v2-m3",
)

RERANK_THRESHOLD = _get_threshold(
    "AGENT2_RERANK_THRESHOLD",
    0.45,
)

SEARCH_TOP_K = _get_positive_int(
    "AGENT2_SEARCH_TOP_K",
    30,
)

# Máximo de candidatos que se envían al reranker
# después de ordenar los resultados mediante RRF.
RERANK_TOP_K = _get_positive_int(
    "AGENT2_RERANK_TOP_K",
    20,
)
