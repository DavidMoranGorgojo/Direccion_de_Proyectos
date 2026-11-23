"""Prueba del parche mínimo al servicio A1 en la copia conjunta versionada."""

import json
from unittest.mock import Mock

from Agents import service


def test_real_service_health_does_not_hide_backend_or_model_failures(monkeypatch):
    monkeypatch.setattr(service, "USE_REAL_AGENT2", True)
    monkeypatch.setattr(service.httpx, "get", Mock(return_value=Mock(json=lambda: {"data": [{"id": service.MODELO_LLM}]})))
    monkeypatch.setattr(service, "check_readiness", lambda: {"status": "unavailable", "codigo_error": "indice_no_disponible"})
    result = service.health()
    assert result.status_code == 503
    assert json.loads(result.body)["codigo_error"] == "indice_no_disponible"


def test_mock_service_health_is_explicit_and_does_not_load_a2_models(monkeypatch):
    monkeypatch.setattr(service, "USE_REAL_AGENT2", False)
    monkeypatch.setattr(service.httpx, "get", Mock(return_value=Mock(json=lambda: {"data": [{"id": service.MODELO_LLM}]})))
    check = Mock(side_effect=AssertionError("No debe cargar modelos A2 en mock"))
    monkeypatch.setattr(service, "check_readiness", check)
    assert service.health() == {"status": "ok", "recuperacion": "mock"}
    check.assert_not_called()
