"""Comprobación explícita del camino real A2, independiente del servicio A1."""

from ..clients.backend import BackendAPIClient
from ..clients.bge_m3 import get_bge_m3_client
from ..clients.reranker_loader import get_reranker
from ..core import config
from ..core.errors import BackendRequestError
from .filter_inference import load_catalogs_from_backend


def check_readiness(backend_client=None, *, load_models=True):
    """Sin simuladores: valida índice, catálogos y opcionalmente inferencia.

    load_models=False verifica solo Backend y lo identifica como comprobación
    parcial. La comprobación completa puede cargar pesos; no es un liveness.
    """
    client = backend_client if backend_client is not None else BackendAPIClient(
        config.BACKEND_BASE_URL, config.EMBEDDINGS_MODEL, timeout=config.REQUEST_TIMEOUT,
        connect_timeout=config.CONNECT_TIMEOUT,
    )
    try:
        info = client.get_info()
        catalogs = load_catalogs_from_backend(client, force_reload=True)
        if load_models:
            vector = get_bge_m3_client().encode_query("comprobacion del servicio")
            if len(vector) != config.EMBEDDING_DIMENSION:
                raise BackendRequestError("modelo_incompatible", "Dimensión BGE-M3 incorrecta.")
            scores = get_reranker().predict([["comprobacion", "comprobacion del servicio"]])
            from math import isfinite
            if len(scores) != 1 or not isfinite(float(scores[0])) or not 0 <= float(scores[0]) <= 1:
                raise BackendRequestError("modelo_no_disponible", "Reranker no operativo.")
        return {"status": "ok" if load_models else "partial", "modo": "real",
                "indice": info["version"], "modelos_verificados": load_models, "codigo_error": ""}
    except BackendRequestError as error:
        return {"status": "unavailable", "modo": "real", "modelos_verificados": False,
                "codigo_error": error.codigo_error}
    except Exception:
        return {"status": "unavailable", "modo": "real", "modelos_verificados": False,
                "codigo_error": "modelo_no_disponible"}
