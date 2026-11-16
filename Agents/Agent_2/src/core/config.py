"""Configuración del Agente 2 (recuperación).

Centraliza los parámetros de la parte de recuperación de Alba:
cliente HTTP del Backend, vectorización local con BGE-M3 y filtros duros.

Los valores pueden sobrescribirse mediante variables de entorno.
"""

import math
import os
from dataclasses import dataclass
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = AGENT_ROOT / "data" / "bbdd_sintetica_chunks.json"

DEFAULT_BACKEND_BASE_URL = "http://localhost:8000"
DEFAULT_EMBEDDINGS_MODEL = "BAAI/bge-m3"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_SEARCH_TOP_K = 30
DEFAULT_REQUEST_TIMEOUT = 5.0
DEFAULT_USE_QUERY_PREFIX = True

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _positive_int(env, name, default):
    raw_value = env.get(name, str(default))

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


def _positive_float(env, name, default):
    raw_value = env.get(name, str(default))

    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            f"{name} debe ser un número finito mayor que cero; "
            f"valor recibido: {raw_value!r}"
        ) from error

    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"{name} debe ser un número finito mayor que cero; "
            f"valor recibido: {raw_value!r}"
        )

    return value


def _non_empty_string(env, name, default):
    value = env.get(name, default)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} debe ser una cadena de texto no vacía"
        )

    return value.strip()


def _boolean(env, name, default):
    raw_value = env.get(name)

    if raw_value is None:
        return default

    normalized = str(raw_value).strip().casefold()

    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise ValueError(
        f"{name} debe ser un booleano (1/0, true/false); "
        f"valor recibido: {raw_value!r}"
    )


@dataclass(frozen=True)
class Agent2Settings:
    """Parámetros de configuración de la recuperación del Agente 2."""

    backend_base_url: str = DEFAULT_BACKEND_BASE_URL
    embeddings_model: str = DEFAULT_EMBEDDINGS_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    search_top_k: int = DEFAULT_SEARCH_TOP_K
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    use_query_prefix: bool = DEFAULT_USE_QUERY_PREFIX
    dataset_path: Path = DEFAULT_DATASET_PATH

    @classmethod
    def from_env(cls, env=None):
        """Construye la configuración leyendo variables de entorno."""

        env = os.environ if env is None else env

        base_url = _non_empty_string(
            env,
            "AGENT2_BACKEND_BASE_URL",
            DEFAULT_BACKEND_BASE_URL,
        ).rstrip("/")

        return cls(
            backend_base_url=base_url,
            embeddings_model=_non_empty_string(
                env,
                "AGENT2_EMBEDDINGS_MODEL",
                DEFAULT_EMBEDDINGS_MODEL,
            ),
            embedding_dimension=_positive_int(
                env,
                "AGENT2_EMBEDDING_DIMENSION",
                DEFAULT_EMBEDDING_DIMENSION,
            ),
            search_top_k=_positive_int(
                env,
                "AGENT2_SEARCH_TOP_K",
                DEFAULT_SEARCH_TOP_K,
            ),
            request_timeout=_positive_float(
                env,
                "AGENT2_REQUEST_TIMEOUT",
                DEFAULT_REQUEST_TIMEOUT,
            ),
            use_query_prefix=_boolean(
                env,
                "AGENT2_USE_QUERY_PREFIX",
                DEFAULT_USE_QUERY_PREFIX,
            ),
            dataset_path=DEFAULT_DATASET_PATH,
        )


SETTINGS = Agent2Settings.from_env()

BACKEND_BASE_URL = SETTINGS.backend_base_url
EMBEDDINGS_MODEL = SETTINGS.embeddings_model
EMBEDDING_DIMENSION = SETTINGS.embedding_dimension
SEARCH_TOP_K = SETTINGS.search_top_k
REQUEST_TIMEOUT = SETTINGS.request_timeout
USE_QUERY_PREFIX = SETTINGS.use_query_prefix
DATASET_PATH = SETTINGS.dataset_path
