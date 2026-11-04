
"""
Carga y reutilización del modelo de reranking del Agente 2.

El modelo se inicializa una sola vez por proceso y se
reutiliza en las siguientes consultas.
"""

from functools import lru_cache

from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.clients.reranker_model import RerankerModel


@lru_cache(maxsize=1)
def _load_reranker(model_name):
    """
    Carga el modelo real y crea su adaptador.

    La caché evita repetir la carga del mismo modelo.
    Los errores de inicialización se propagan.
    """
    from FlagEmbedding import FlagReranker

    model = FlagReranker(
        model_name,
        use_fp16=False,
    )

    return RerankerModel(model=model)


def get_reranker():
    """
    Devuelve el reranker configurado para el Agente 2.

    En llamadas sucesivas reutiliza la misma instancia,
    evitando volver a cargar los pesos del modelo.
    """
    return _load_reranker(config.RERANKER_MODEL)
