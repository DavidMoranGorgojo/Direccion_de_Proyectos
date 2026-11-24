
"""
Carga y reutilización del modelo de reranking del Agente 2.

El modelo se inicializa una sola vez por proceso para cada
configuración activa y se reutiliza en consultas posteriores.

La inicialización está protegida frente a llamadas concurrentes.
"""

import threading
from functools import lru_cache

from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.clients.reranker_model import RerankerModel


# Evita inicializaciones simultáneas del modelo.
_bloqueo_carga = threading.Lock()


@lru_cache(maxsize=1)
def _load_reranker(model_name):
    """
    Carga el modelo real y crea su adaptador.

    La caché permite reutilizar la instancia del modelo.
    Los errores de inicialización se propagan y no se almacenan.
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

    El bloqueo garantiza que solo un hilo pueda acceder
    a la carga del modelo cada vez.

    Una vez inicializado, las llamadas posteriores
    reutilizan la instancia almacenada en caché.
    """
    with _bloqueo_carga:
        return _load_reranker(config.RERANKER_MODEL)
