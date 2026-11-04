
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
    value = int(os.getenv(name, str(default)))

    if value <= 0:
        raise ValueError(
            f"{name} debe ser un entero mayor que cero"
        )

    return value


def _get_threshold(name, default):
    value = float(os.getenv(name, str(default)))

    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(
            f"{name} debe ser un número finito entre 0 y 1"
        )

    return value


RRF_K = _get_positive_int("AGENT2_RRF_K", 60)

RERANKER_MODEL = os.getenv(
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
