"""Tests parametrizados de mapeo HTTP → código de error contractual (B01).

Verifica que _post_conocimiento() y _backend_error_code() producen los
códigos correctos según CTR-002 y no convierten todos los errores en
servicio_no_disponible.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from Agents.Agent_2.src.clients.backend import (
    BackendAPIClient,
    _backend_error_code,
)
from Agents.Agent_2.src.core.errors import BackendRequestError


def _make_response(status_code, body=None):
    """Crea un mock de requests.Response con status_code y cuerpo JSON."""
    resp = MagicMock()
    resp.status_code = status_code
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ── _backend_error_code ──────────────────────────────────────────────

class TestBackendErrorCode:
    """Mapeo directo de HTTP status → código contractual."""

    @pytest.mark.parametrize("status,body,expected", [
        (400, None, "entrada_invalida"),
        (400, {"codigo_error": "peticion_invalida"}, "entrada_invalida"),
        (400, {"codigo_error": "filtro_invalido"}, "entrada_invalida"),
        (409, None, "modelo_incompatible"),
        (409, {"codigo_error": "modelo_incompatible"}, "modelo_incompatible"),
        (404, None, "indice_no_disponible"),
        (404, {"codigo_error": "recurso_no_encontrado"}, "indice_no_disponible"),
        (422, None, "entrada_invalida"),
        (503, None, "indice_no_disponible"),
        (503, {"codigo_error": "servicio_no_disponible"}, "servicio_no_disponible"),
        (504, None, "tiempo_agotado"),
        (500, None, "servicio_no_disponible"),
        (502, None, "servicio_no_disponible"),
    ])
    def test_status_to_code(self, status, body, expected):
        resp = _make_response(status, body)
        assert _backend_error_code(resp) == expected

    def test_nested_detail_codigo(self):
        resp = _make_response(409, {"detail": {"codigo": "modelo_incompatible"}})
        assert _backend_error_code(resp) == "modelo_incompatible"


# ── _post_conocimiento integrado ─────────────────────────────────────

class TestPostConocimientoHTTPErrors:
    """Verifica que _post_conocimiento propaga el código correcto."""

    @pytest.fixture
    def client(self):
        session = MagicMock()
        return BackendAPIClient(
            base_url="http://test:8000",
            model_embeddings="BAAI/bge-m3",
            session=session,
            timeout=5,
            token="test-token",
        )

    @pytest.mark.parametrize("status,expected_code", [
        (400, "entrada_invalida"),
        (409, "modelo_incompatible"),
        (404, "indice_no_disponible"),
        (503, "indice_no_disponible"),
        (504, "tiempo_agotado"),
        (500, "servicio_no_disponible"),
    ])
    def test_http_error_produces_correct_code(self, client, status, expected_code):
        resp = _make_response(status)
        client.session.post.return_value = resp

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == expected_code

    def test_http_200_empty_results_is_not_error(self, client):
        resp = _make_response(200, {"indice": {}, "resultados": []})
        client.session.post.return_value = resp

        result = client._post_conocimiento("/conocimiento/vectorial", {})
        assert result == {"indice": {}, "resultados": []}

    def test_timeout_produces_tiempo_agotado(self, client):
        import requests as req
        client.session.post.side_effect = req.Timeout("timeout")

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == "tiempo_agotado"

    def test_connection_error_produces_servicio_no_disponible(self, client):
        import requests as req
        client.session.post.side_effect = req.ConnectionError("refused")

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == "servicio_no_disponible"

    def test_malformed_json_produces_servicio_no_disponible(self, client):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        client.session.post.return_value = resp

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == "servicio_no_disponible"

    def test_409_with_body_produces_modelo_incompatible(self, client):
        resp = _make_response(409, {"codigo_error": "modelo_incompatible"})
        client.session.post.return_value = resp

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == "modelo_incompatible"

    def test_503_with_body_code_produces_that_code(self, client):
        resp = _make_response(503, {"codigo_error": "servicio_no_disponible"})
        client.session.post.return_value = resp

        with pytest.raises(BackendRequestError) as exc_info:
            client._post_conocimiento("/conocimiento/vectorial", {})

        assert exc_info.value.codigo_error == "servicio_no_disponible"
