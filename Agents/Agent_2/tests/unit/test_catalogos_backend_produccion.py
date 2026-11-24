"""Tests del cliente de catálogos Backend (CTR-002 §2) y política de producción (B02).

Verifica:
1. get_catalogo() en BackendAPIClient con validación, errores HTTP y parseo.
2. load_catalogs_from_backend() con caché y mapeo canónico.
3. Política estricta de producción: NUNCA usar catálogos sintéticos en producción
   ni con entorno indefinido, salvo autorización explícita en desarrollo/test.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.filters import code_key
from Agents.Agent_2.src.services.filter_inference import (
    load_catalogs,
    load_catalogs_from_backend,
    _BACKEND_CATALOG_CACHE,
    FIXTURE_CATALOG_DIR,
)


def _make_response(status_code, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


class TestBackendGetCatalogo:
    @pytest.fixture
    def client(self):
        session = MagicMock()
        return BackendAPIClient(
            base_url="http://backend:8000",
            model_embeddings="BAAI/bge-m3",
            session=session,
            timeout=5,
            token="test-token",
        )

    @pytest.mark.parametrize("nombre", ["codigos", "terminos", "vehiculos", "componentes"])
    def test_get_catalogo_valid_names(self, client, nombre):
        expected_payload = {
            "nombre": nombre,
            "version": "1.0",
            "contenido": [{"codigo": "TEST-01"}]
        }
        client.session.get.return_value = _make_response(200, expected_payload)

        result = client.get_catalogo(nombre)
        assert result == expected_payload
        client.session.get.assert_called_once()
        assert f"/catalogos/{nombre}" in client.session.get.call_args[0][0]

    def test_get_catalogo_invalid_name_raises_value_error(self, client):
        with pytest.raises(ValueError, match="Catálogo no válido|Nombre de catálogo inválido"):
            client.get_catalogo("manuales_invalidos")

    def test_get_catalogo_404_raises_indice_no_disponible(self, client):
        client.session.get.return_value = _make_response(404, {"codigo_error": "recurso_no_encontrado"})
        with pytest.raises(BackendRequestError) as exc_info:
            client.get_catalogo("codigos")
        assert exc_info.value.codigo_error == "indice_no_disponible"

    def test_get_catalogo_504_raises_tiempo_agotado(self, client):
        client.session.get.return_value = _make_response(504)
        with pytest.raises(BackendRequestError) as exc_info:
            client.get_catalogo("codigos")
        assert exc_info.value.codigo_error == "tiempo_agotado"

    def test_get_catalogo_missing_contenido_raises(self, client):
        client.session.get.return_value = _make_response(200, {"nombre": "codigos", "version": "1.0"})
        with pytest.raises(BackendRequestError) as exc_info:
            client.get_catalogo("codigos")
        assert exc_info.value.codigo_error == "servicio_no_disponible"


class TestLoadCatalogsFromBackend:
    def test_load_and_cache(self):
        client = MagicMock()
        client.base_url = "http://backend-test:8000"
        client.get_catalogo.side_effect = lambda nombre: {
            "codigos": {
                "nombre": "codigos",
                "version": "v1.0",
                "contenido": [{"codigo": "HTM-0142", "descripcion": "Fallo"}]
            },
            "componentes": {
                "nombre": "componentes",
                "version": "v1.0",
                "contenido": [{"codigo": "CMP-18", "nombre": "Sensor"}]
            }
        }[nombre]

        _BACKEND_CATALOG_CACHE.clear()

        catalogs = load_catalogs_from_backend(client)
        assert code_key("HTM-0142") in catalogs["code_by_key"]
        assert catalogs["code_by_key"][code_key("HTM-0142")] == "HTM-0142"
        assert code_key("CMP-18") in catalogs["component_id_by_key"]
        assert catalogs["component_id_by_key"][code_key("CMP-18")] == "CMP-18"

        # Segunda llamada usa caché (no llama a get_catalogo de nuevo)
        call_count_before = client.get_catalogo.call_count
        catalogs_cached = load_catalogs_from_backend(client, use_cache=True)
        assert client.get_catalogo.call_count == call_count_before
        assert catalogs_cached is catalogs


class TestCatalogPolicyEnvironments:
    """Demuestra la política de seguridad estricta para catálogos sintéticos."""

    @pytest.fixture(autouse=True)
    def mock_missing_real_catalogs(self, monkeypatch):
        # Simular que los catálogos reales no están presentes en CATALOG_DIR
        monkeypatch.setattr(
            "Agents.Agent_2.src.core.config.CATALOG_DIR",
            Path("C:/ruta/inexistente/de/catalogos_reales"),
        )

    def test_production_environment_forbids_synthetic_catalogs(self, monkeypatch):
        monkeypatch.setenv("ARSOFT_ENV", "production")
        monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "1")  # ignorado en prod

        # Intento de cargar fixtures explícitamente en producción
        with pytest.raises(FileNotFoundError, match="En producción no se pueden utilizar"):
            load_catalogs(catalog_dir=str(FIXTURE_CATALOG_DIR))

        # Intento sin directorio (faltan reales)
        with pytest.raises(FileNotFoundError, match="Catálogos reales obligatorios no encontrados"):
            load_catalogs(catalog_dir=None)

    def test_undefined_environment_forbids_synthetic_silently(self, monkeypatch):
        monkeypatch.delenv("ARSOFT_ENV", raising=False)
        monkeypatch.delenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", raising=False)

        # Sin entorno ni flag, no debe cargar fixtures silenciosamente si falta la ruta real
        with pytest.raises(FileNotFoundError, match="Catálogos reales obligatorios no encontrados"):
            load_catalogs(catalog_dir=None)

    def test_development_without_optin_forbids_synthetic(self, monkeypatch):
        monkeypatch.setenv("ARSOFT_ENV", "development")
        monkeypatch.delenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", raising=False)

        with pytest.raises(FileNotFoundError, match="Catálogos reales obligatorios no encontrados"):
            load_catalogs(catalog_dir=None)

    def test_development_with_optin_allows_synthetic(self, monkeypatch):
        monkeypatch.setenv("ARSOFT_ENV", "development")
        monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "1")

        # Fallback a fixtures sintéticos permitido
        cats = load_catalogs(catalog_dir=None)
        assert "code_by_key" in cats
        assert len(cats["code_by_key"]) > 0

    def test_test_environment_allows_synthetic(self, monkeypatch):
        monkeypatch.setenv("ARSOFT_ENV", "test")

        cats = load_catalogs(catalog_dir=None)
        assert "code_by_key" in cats
        assert len(cats["code_by_key"]) > 0
