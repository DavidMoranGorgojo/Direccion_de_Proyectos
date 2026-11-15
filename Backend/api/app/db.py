"""Pool de conexiones a PostgreSQL + pgvector."""

from typing import Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from . import config

_pool: Optional[ConnectionPool] = None


def abrir_pool() -> None:
    global _pool
    _pool = ConnectionPool(config.DATABASE_URL, min_size=config.POOL_MIN, max_size=config.POOL_MAX,
                           timeout=2, open=False, kwargs={"autocommit": True})
    _pool.open(wait=False)


def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_conn() -> Iterator[psycopg.Connection]:
    """Dependencia de FastAPI. Sin pool o sin base de datos, los handlers de errores devuelven 503."""
    if _pool is None:
        raise psycopg.OperationalError("pool sin abrir")
    with _pool.connection() as conn:
        yield conn
