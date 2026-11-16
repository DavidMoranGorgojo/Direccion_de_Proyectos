
import importlib

import pytest

from Agents.Agent_2.src.core import config


VARIABLES_CONFIG = (
    "ARSOFT_SERVICE_TOKEN",
    "AGENT2_RRF_K",
    "AGENT2_RERANKER_MODEL",
    "AGENT2_RERANK_THRESHOLD",
    "AGENT2_SEARCH_TOP_K",
    "AGENT2_RERANK_TOP_K",
)


@pytest.fixture(autouse=True)
def restaurar_configuracion(monkeypatch):
    """
    Aísla las pruebas de configuración.

    Al terminar cada prueba, restaura las variables de entorno
    y recarga el módulo para que otras pruebas no hereden
    valores modificados.
    """

    # Se conserva el entorno original para restaurarlo después.
    valores_originales = {
        variable: config.os.environ.get(variable)
        for variable in VARIABLES_CONFIG
    }

    yield

    # Restaurar primero las variables de entorno.
    for variable, valor in valores_originales.items():
        if valor is None:
            monkeypatch.delenv(variable, raising=False)
        else:
            monkeypatch.setenv(variable, valor)

    # Restaurar los valores del módulo compartido.
    importlib.reload(config)


def test_config_valores_por_defecto(monkeypatch):
    """Comprueba los valores predeterminados."""

    for variable in VARIABLES_CONFIG:
        monkeypatch.delenv(variable, raising=False)

    importlib.reload(config)

    assert config.RRF_K == 60
    assert config.RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"
    assert config.RERANK_THRESHOLD == 0.45
    assert config.SEARCH_TOP_K == 30
    assert config.RERANK_TOP_K == 20
    assert config.SERVICE_TOKEN == ""


def test_config_variables_entorno(monkeypatch):
    """Comprueba que las variables de entorno se aplican."""

    monkeypatch.setenv("AGENT2_RRF_K", "80")
    monkeypatch.setenv(
        "AGENT2_RERANKER_MODEL",
        "modelo-prueba",
    )
    monkeypatch.setenv("AGENT2_RERANK_THRESHOLD", "0.60")
    monkeypatch.setenv("AGENT2_SEARCH_TOP_K", "25")
    monkeypatch.setenv("AGENT2_RERANK_TOP_K", "12")
    monkeypatch.setenv("ARSOFT_SERVICE_TOKEN", "token-de-servicio")

    importlib.reload(config)

    assert config.RRF_K == 80
    assert config.RERANKER_MODEL == "modelo-prueba"
    assert config.RERANK_THRESHOLD == 0.60
    assert config.SEARCH_TOP_K == 25
    assert config.RERANK_TOP_K == 12
    assert config.SERVICE_TOKEN == "token-de-servicio"


@pytest.mark.parametrize(
    "valor",
    ["0", "-1", "abc", "1.5", ""],
)
def test_config_rechaza_rrf_invalido(monkeypatch, valor):
    """RRF_K debe ser un entero positivo."""

    monkeypatch.setenv("AGENT2_RRF_K", valor)

    with pytest.raises(ValueError, match="AGENT2_RRF_K"):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["-0.1", "1.1", "nan", "inf", "abc", ""],
)
def test_config_rechaza_umbral_invalido(monkeypatch, valor):
    """El umbral debe ser finito y estar entre 0 y 1."""

    monkeypatch.setenv("AGENT2_RERANK_THRESHOLD", valor)

    with pytest.raises(ValueError, match="AGENT2_RERANK_THRESHOLD"):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["0", "-5", "abc", "2.5", ""],
)
def test_config_rechaza_top_k_invalido(monkeypatch, valor):
    """SEARCH_TOP_K debe ser un entero positivo."""

    monkeypatch.setenv("AGENT2_SEARCH_TOP_K", valor)

    with pytest.raises(ValueError, match="AGENT2_SEARCH_TOP_K"):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["0", "-1", "abc", "1.5", ""],
)
def test_config_rechaza_rerank_top_k_invalido(monkeypatch, valor):
    """RERANK_TOP_K debe ser un entero positivo."""

    monkeypatch.setenv("AGENT2_RERANK_TOP_K", valor)

    with pytest.raises(ValueError, match="AGENT2_RERANK_TOP_K"):
        importlib.reload(config)


@pytest.mark.parametrize(
    "valor",
    ["", "   ", "\t"],
)
def test_config_rechaza_modelo_vacio(monkeypatch, valor):
    """El nombre del modelo no puede estar vacío."""

    monkeypatch.setenv("AGENT2_RERANKER_MODEL", valor)

    with pytest.raises(ValueError, match="AGENT2_RERANKER_MODEL"):
        importlib.reload(config)


def test_config_elimina_espacios_del_nombre_modelo(monkeypatch):
    """Los espacios exteriores del nombre se eliminan."""

    monkeypatch.setenv(
        "AGENT2_RERANKER_MODEL",
        "  BAAI/bge-reranker-v2-m3  ",
    )

    importlib.reload(config)

    assert config.RERANKER_MODEL == "BAAI/bge-reranker-v2-m3"
