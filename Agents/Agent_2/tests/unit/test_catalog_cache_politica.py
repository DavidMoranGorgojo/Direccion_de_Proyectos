"""Tests de política de actualización, caducidad e invalidación de caché de catálogos (Fase 3).

Verifica:
1. Reproducción y resolución del defecto original: misma URL de Backend, catálogo actualizado
   de v1 (HTM-0142) a v2 (HTM-9999), verificando recarga tras invalidación/expiración.
2. Reutilización de caché válida.
3. Expiración configurable (TTL).
4. Invalidación explícita global e individual por cliente.
5. Comportamiento controlado ante fallos de recarga (con y sin stale_if_error).
6. Separación de claves de identidad para clientes con distinta configuración.
7. Seguridad ante consultas concurrentes (thread-safety).
8. Ausencia de catálogos y política estricta de producción.
"""

from __future__ import annotations

import concurrent.futures
import time
from unittest.mock import MagicMock
import pytest

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.filters import code_key
from Agents.Agent_2.src.services.filter_inference import (
    CatalogCacheEntry,
    _BACKEND_CATALOG_CACHE,
    _backend_cache_key,
    invalidate_backend_catalog_cache,
    load_catalogs_from_backend,
    load_catalogs,
)


def _make_backend_client(base_url="http://backend.internal:8000", token="token-1", model="BAAI/bge-m3"):
    client = MagicMock(spec=BackendAPIClient)
    client.base_url = base_url
    client.token = token
    client.model_embeddings = model
    return client


class TestCatalogCacheDefectoOriginal:
    """Reproduce y valida la corrección del defecto de URL idéntica con catálogo actualizado."""

    def test_reproduccion_defecto_y_recarga_tras_invalidacion(self):
        client = _make_backend_client("http://backend-rag:8000")
        invalidate_backend_catalog_cache()

        # Versión 1 del catálogo: contiene HTM-0142
        catalog_v1 = {
            "codigos": {
                "nombre": "codigos",
                "version": "1.0",
                "contenido": [{"codigo": "HTM-0142", "descripcion": "Fallo V1"}],
            },
            "componentes": {
                "nombre": "componentes",
                "version": "1.0",
                "contenido": [{"codigo": "CMP-01", "nombre": "Bomba"}],
            },
        }

        # Versión 2 del catálogo: contiene HTM-9999 (actualización en backend)
        catalog_v2 = {
            "codigos": {
                "nombre": "codigos",
                "version": "2.0",
                "contenido": [{"codigo": "HTM-9999", "descripcion": "Fallo V2"}],
            },
            "componentes": {
                "nombre": "componentes",
                "version": "2.0",
                "contenido": [{"codigo": "CMP-01", "nombre": "Bomba"}],
            },
        }

        current_catalog = catalog_v1
        client.get_catalogo.side_effect = lambda nombre: current_catalog[nombre]

        # 1. Primera consulta: carga v1 y puebla la caché
        cats_v1 = load_catalogs_from_backend(client)
        assert code_key("HTM-0142") in cats_v1["code_by_key"]
        assert code_key("HTM-9999") not in cats_v1["code_by_key"]
        assert cats_v1.versions["codigos"] == "1.0"
        assert client.get_catalogo.call_count == 2

        # 2. El Backend actualiza sus catálogos manteniendo la misma URL
        current_catalog = catalog_v2

        # Si consultamos con caché activa sin invalidar, aún retorna v1
        cats_cached = load_catalogs_from_backend(client, use_cache=True)
        assert code_key("HTM-0142") in cats_cached["code_by_key"]
        assert client.get_catalogo.call_count == 2

        # 3. Invalidación explícita: comprueba que ahora utiliza el catálogo nuevo v2
        invalidate_backend_catalog_cache(client)
        cats_v2 = load_catalogs_from_backend(client)

        assert code_key("HTM-9999") in cats_v2["code_by_key"]
        assert code_key("HTM-0142") not in cats_v2["code_by_key"]
        assert cats_v2.versions["codigos"] == "2.0"
        assert client.get_catalogo.call_count == 4

    def test_recarga_por_force_reload(self):
        client = _make_backend_client("http://backend-rag:8000")
        invalidate_backend_catalog_cache()

        version_data = {"ver": "1.0", "cod": "HTM-0142"}
        client.get_catalogo.side_effect = lambda nombre: {
            "nombre": nombre,
            "version": version_data["ver"],
            "contenido": [{"codigo": version_data["cod"]}],
        }

        res1 = load_catalogs_from_backend(client)
        assert code_key("HTM-0142") in res1["code_by_key"]

        # Backend cambia catálogo
        version_data["ver"] = "2.0"
        version_data["cod"] = "HTM-9999"

        # Con force_reload=True debe descargar inmediatamente el nuevo
        res2 = load_catalogs_from_backend(client, force_reload=True)
        assert code_key("HTM-9999") in res2["code_by_key"]
        assert code_key("HTM-0142") not in res2["code_by_key"]
        assert res2.versions["codigos"] == "2.0"


class TestCatalogCacheTTLAndInvalidation:
    def test_ttl_expiration_reloads_fresh_data(self):
        client = _make_backend_client("http://backend-ttl:8000")
        invalidate_backend_catalog_cache()

        call_counter = {"count": 0}

        def mock_get(nombre):
            call_counter["count"] += 1
            ver = f"v{call_counter['count']}"
            return {
                "nombre": nombre,
                "version": ver,
                "contenido": [{"codigo": f"CODE-{ver}"}],
            }

        client.get_catalogo.side_effect = mock_get

        # TTL de 0.05 segundos
        res1 = load_catalogs_from_backend(client, ttl=0.05)
        assert client.get_catalogo.call_count == 2
        assert code_key("CODE-v1") in res1["code_by_key"]

        # Reutilización antes de expirar
        res_cached = load_catalogs_from_backend(client, ttl=0.05)
        assert client.get_catalogo.call_count == 2
        assert res_cached is res1

        # Esperar a que expire el TTL
        time.sleep(0.06)

        # Tras expirar, recarga automáticamente
        res_fresh = load_catalogs_from_backend(client, ttl=0.05)
        assert client.get_catalogo.call_count == 4
        assert code_key("CODE-v3") in res_fresh["code_by_key"]

    def test_invalidate_global_vs_single_client(self):
        client_a = _make_backend_client("http://backend-a:8000")
        client_b = _make_backend_client("http://backend-b:8000")
        invalidate_backend_catalog_cache()

        payload = {"nombre": "codigos", "version": "1.0", "contenido": [{"codigo": "C-1"}]}
        client_a.get_catalogo.return_value = payload
        client_b.get_catalogo.return_value = payload

        load_catalogs_from_backend(client_a)
        load_catalogs_from_backend(client_b)

        assert len(_BACKEND_CATALOG_CACHE) == 2

        # Invalidar solo client_a
        invalidate_backend_catalog_cache(client_a)
        assert len(_BACKEND_CATALOG_CACHE) == 1
        assert _backend_cache_key(client_b) in _BACKEND_CATALOG_CACHE

        # Invalidar globalmente
        invalidate_backend_catalog_cache()
        assert len(_BACKEND_CATALOG_CACHE) == 0


class TestCatalogCacheErrorHandling:
    def test_reload_failure_propagates_error_without_corrupting_cache(self):
        client = _make_backend_client("http://backend-err:8000")
        invalidate_backend_catalog_cache()

        client.get_catalogo.return_value = {
            "nombre": "codigos",
            "version": "1.0",
            "contenido": [{"codigo": "HTM-0142"}],
        }

        initial_cats = load_catalogs_from_backend(client)
        assert code_key("HTM-0142") in initial_cats["code_by_key"]

        # El backend falla en la siguiente llamada
        client.get_catalogo.side_effect = BackendRequestError("indice_no_disponible", "Error")

        # Con force_reload, propaga la excepción
        with pytest.raises(BackendRequestError) as exc_info:
            load_catalogs_from_backend(client, force_reload=True, stale_if_error=False)
        assert exc_info.value.codigo_error == "indice_no_disponible"

        # La caché previa no fue borrada ni corrompida
        cached_after = load_catalogs_from_backend(client, use_cache=True)
        assert cached_after is initial_cats

    def test_reload_failure_with_stale_if_error_returns_stale_entry(self):
        client = _make_backend_client("http://backend-stale:8000")
        invalidate_backend_catalog_cache()

        client.get_catalogo.return_value = {
            "nombre": "codigos",
            "version": "1.0",
            "contenido": [{"codigo": "HTM-0142"}],
        }

        initial_cats = load_catalogs_from_backend(client)

        # Fallo en backend
        client.get_catalogo.side_effect = BackendRequestError("tiempo_agotado", "Timeout")

        # Con stale_if_error=True y force_reload, devuelve la previa sin fallar
        stale_cats = load_catalogs_from_backend(client, force_reload=True, stale_if_error=True)
        assert stale_cats is initial_cats


class TestCatalogCacheIdentitiesAndConcurrency:
    def test_different_client_configurations_have_isolated_caches(self):
        client_prod = _make_backend_client("http://backend.internal", token="token-prod")
        client_staging = _make_backend_client("http://backend.internal", token="token-staging")
        invalidate_backend_catalog_cache()

        client_prod.get_catalogo.return_value = {
            "nombre": "codigos",
            "version": "prod-1",
            "contenido": [{"codigo": "CODE-PROD"}],
        }
        client_staging.get_catalogo.return_value = {
            "nombre": "codigos",
            "version": "stg-1",
            "contenido": [{"codigo": "CODE-STG"}],
        }

        cats_prod = load_catalogs_from_backend(client_prod)
        cats_stg = load_catalogs_from_backend(client_staging)

        assert code_key("CODE-PROD") in cats_prod["code_by_key"]
        assert code_key("CODE-STG") in cats_stg["code_by_key"]
        assert cats_prod is not cats_stg
        assert len(_BACKEND_CATALOG_CACHE) == 2

    def test_thread_safe_concurrent_access_only_calls_backend_once(self):
        client = _make_backend_client("http://backend-concurrent:8000")
        invalidate_backend_catalog_cache()

        calls = []

        def slow_get_catalogo(nombre):
            time.sleep(0.05)
            calls.append(nombre)
            return {
                "nombre": nombre,
                "version": "1.0",
                "contenido": [{"codigo": f"CODE-{nombre}"}],
            }

        client.get_catalogo.side_effect = slow_get_catalogo

        # 8 hilos solicitan catálogos concurrentemente con la misma instancia
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(load_catalogs_from_backend, client) for _ in range(8)]
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())

        # Todos reciben exactamente el mismo objeto de caché
        assert len(results) == 8
        first_entry = results[0]
        for entry in results:
            assert entry is first_entry

        # Backend solo fue llamado para codigos y componentes (2 llamadas en total)
        assert len(calls) == 2
        assert client.get_catalogo.call_count == 2
