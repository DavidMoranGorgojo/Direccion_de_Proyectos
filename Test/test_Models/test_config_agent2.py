
import importlib
import math

import pytest

from Agents.Agent_2.src.core import config


def test_config_valores_por_defecto(monkeypatch):
    """Comprueba los valores predeterminados."""

    for variable in (
        "AGENT2_RRF_K",
        "AGENT2_RERANKER_MODEL",
        "AGENT2_RERANK_THRESHOLD",
        "AGENT2_SEARCH_TOP_K",
    ):
        monkeypatch.delenv(variable, raising=False)

    importlib.reload(config)

    assert config.RRF_K == 60
    assert config.RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"
    assert config.RERANK_THRESHOLD == 0.45
    assert config.SEARCH_TOP_K == 30


def test_config_variables_entorno(monkeypatch):
    """Comprueba que las variables de entorno se aplican."""

    monkeypatch.setenv("AGENT2_RRF_K", "80")
    monkeypatch.setenv(
        "AGENT2_RERANKER_MODEL",
        "modelo-prueba",
    )
    monkeypatch.setenv("AGENT2_RERANK_THRESHOLD", "0.60")
    monkeypatch.setenv("AGENT2_SEARCH_TOP_K", "20")

    importlib.reload(config)

    assert config.RRF_K == 80
    assert config.RERANKER_MODEL == "modelo-prueba"
    assert config.RERANK_THRESHOLD == 0.60
    assert config.SEARCH_TOP_K == 20


@pytest.mark.parametrize(
    "valor",
    ["0", "-1", "abc", "1.5"],
)
def test_config_rechaza_rrf_invalido(monkeypatch, valor):
    """RRF_K debe ser un entero positivo."""

    monkeypatch.setenv("AGENT2_RRF_K", valor)

    with pytest.raises(ValueError):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["-0.1", "1.1", "nan", "inf", "abc"],
)
def test_config_rechaza_umbral_invalido(monkeypatch, valor):
    """El umbral debe ser finito y estar entre 0 y 1."""

    monkeypatch.setenv("AGENT2_RERANK_THRESHOLD", valor)

    with pytest.raises(ValueError):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["0", "-5", "abc", "2.5"],
)
def test_config_rechaza_top_k_invalido(monkeypatch, valor):
    """SEARCH_TOP_K debe ser un entero positivo."""

    monkeypatch.setenv("AGENT2_SEARCH_TOP_K", valor)

    with pytest.raises(ValueError):
        importlib.reload(config)
