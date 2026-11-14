
import math

import pytest

from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
    sort_by_rerank_score,
)


def test_threshold_mantiene_resultados_validos():
    resultados = [
        {"chunk_id": "A", "rerank_score": 0.90},
        {"chunk_id": "B", "rerank_score": 0.60},
        {"chunk_id": "C", "rerank_score": 0.30},
    ]

    filtrados = apply_threshold(resultados)

    assert len(filtrados) == 2
    assert filtrados[0]["chunk_id"] == "A"
    assert filtrados[1]["chunk_id"] == "B"


def test_threshold_devuelve_vacio_si_ninguno_supera_umbral():
    resultados = [
        {"chunk_id": "A", "rerank_score": 0.20},
        {"chunk_id": "B", "rerank_score": 0.10},
    ]

    filtrados = apply_threshold(resultados)

    assert filtrados == []


def test_threshold_es_configurable():
    resultados = [
        {"chunk_id": "A", "rerank_score": 0.70},
        {"chunk_id": "B", "rerank_score": 0.50},
    ]

    filtrados = apply_threshold(resultados, threshold=0.60)

    assert len(filtrados) == 1
    assert filtrados[0]["chunk_id"] == "A"


def test_reranker_ordena_por_score_descendente():
    resultados = [
        {"chunk_id": "A", "rerank_score": 0.40},
        {"chunk_id": "B", "rerank_score": 0.90},
        {"chunk_id": "C", "rerank_score": 0.60},
    ]

    ordenados = sort_by_rerank_score(resultados)

    assert ordenados[0]["chunk_id"] == "B"
    assert ordenados[1]["chunk_id"] == "C"
    assert ordenados[2]["chunk_id"] == "A"


def test_rerank_results_asigna_scores_y_ordena():
    class FakeReranker:
        def predict(self, pairs):
            return [0.30, 0.90, 0.60]

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
        {"chunk_id": "B", "texto": "Texto B"},
        {"chunk_id": "C", "texto": "Texto C"},
    ]

    resultado = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=FakeReranker(),
    )

    assert resultado[0]["chunk_id"] == "B"
    assert resultado[0]["rerank_score"] == 0.90

    assert resultado[1]["chunk_id"] == "C"
    assert resultado[1]["rerank_score"] == 0.60

    assert resultado[2]["chunk_id"] == "A"
    assert resultado[2]["rerank_score"] == 0.30


def test_rerank_y_threshold():
    class FakeReranker:
        def predict(self, pairs):
            return [0.30, 0.90, 0.60]

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
        {"chunk_id": "B", "texto": "Texto B"},
        {"chunk_id": "C", "texto": "Texto C"},
    ]

    rerankeados = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=FakeReranker(),
    )

    filtrados = apply_threshold(rerankeados)

    assert len(filtrados) == 2

    assert filtrados[0]["chunk_id"] == "B"
    assert filtrados[0]["rerank_score"] == 0.90

    assert filtrados[1]["chunk_id"] == "C"
    assert filtrados[1]["rerank_score"] == 0.60


def test_rerank_results_lista_vacia():
    class FakeReranker:
        def predict(self, pairs):
            raise AssertionError("El modelo no debería ejecutarse")

    resultado = rerank_results(
        query="problema con el motor",
        results=[],
        model=FakeReranker(),
    )

    assert resultado == []


def test_rerank_results_no_modifica_originales():
    class FakeReranker:
        def predict(self, pairs):
            return [0.80]

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
    ]

    rerank_results(
        query="problema con el motor",
        results=resultados,
        model=FakeReranker(),
    )

    assert "rerank_score" not in resultados[0]


def test_rerank_results_detecta_numero_incorrecto_de_scores():
    class FakeReranker:
        def predict(self, pairs):
            return [0.90]

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
        {"chunk_id": "B", "texto": "Texto B"},
    ]

    with pytest.raises(ValueError):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(),
        )


def test_rerank_results_propaga_error_del_modelo():
    """Un fallo del modelo debe propagarse al llamador."""

    class FakeReranker:
        def predict(self, pairs):
            raise RuntimeError("Fallo simulado del reranker")

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
    ]

    with pytest.raises(RuntimeError, match="Fallo simulado"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(),
        )


@pytest.mark.parametrize(
    "score_invalido",
    [math.nan, math.inf, -math.inf],
)
def test_rerank_results_rechaza_scores_no_finitos(score_invalido):
    """NaN e infinito no deben aceptarse como puntuaciones válidas."""

    class FakeReranker:
        def predict(self, pairs):
            return [score_invalido]

    resultados = [
        {"chunk_id": "A", "texto": "Texto A"},
    ]

    with pytest.raises(ValueError, match="no finita"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(),
        )


def test_threshold_utiliza_configuracion(monkeypatch):
    """
    Comprueba que apply_threshold utiliza config.RERANK_THRESHOLD
    cuando no se indica un umbral explícito.
    """

    monkeypatch.setattr(config, "RERANK_THRESHOLD", 0.75)

    resultados = [
        {"chunk_id": "A", "rerank_score": 0.90},
        {"chunk_id": "B", "rerank_score": 0.70},
        {"chunk_id": "C", "rerank_score": 0.50},
    ]

    filtrados = apply_threshold(resultados)

    assert len(filtrados) == 1
    assert filtrados[0]["chunk_id"] == "A"


def test_threshold_explicito_tiene_prioridad(monkeypatch):
    """
    Comprueba que un umbral explícito tiene prioridad
    sobre el configurado en config.py.
    """

    monkeypatch.setattr(config, "RERANK_THRESHOLD", 0.80)

    resultados = [
        {"chunk_id": "A", "rerank_score": 0.90},
        {"chunk_id": "B", "rerank_score": 0.60},
        {"chunk_id": "C", "rerank_score": 0.30},
    ]

    filtrados = apply_threshold(resultados, threshold=0.50)

    assert len(filtrados) == 2
    assert filtrados[0]["chunk_id"] == "A"
    assert filtrados[1]["chunk_id"] == "B"


def test_threshold_incluye_puntuacion_igual_al_umbral():
    """
    Un resultado con puntuación exactamente igual
    al umbral debe conservarse.
    """

    resultados = [
        {"chunk_id": "A", "rerank_score": 0.60},
        {"chunk_id": "B", "rerank_score": 0.59},
    ]

    filtrados = apply_threshold(resultados, threshold=0.60)

    assert len(filtrados) == 1
    assert filtrados[0]["chunk_id"] == "A"


@pytest.mark.parametrize(
    "threshold_invalido",
    [-0.1, 1.1, "abc", True, math.nan, math.inf, -math.inf],
)
def test_threshold_rechaza_valores_invalidos(threshold_invalido):
    """
    El umbral debe ser un número finito entre 0 y 1.
    """

    resultados = [
        {"chunk_id": "A", "rerank_score": 0.90},
    ]

    with pytest.raises(ValueError, match="umbral"):
        apply_threshold(resultados, threshold=threshold_invalido)


class FakeRerankerConRegistro:
    """
    Modelo simulado que registra los pares recibidos.

    Permite comprobar el límite de candidatos sin cargar
    el modelo real.
    """

    def __init__(self):
        self.pares_recibidos = None
        self.llamadas = 0

    def predict(self, pairs):
        self.llamadas += 1
        self.pares_recibidos = pairs
        return [0.9] * len(pairs)


def crear_candidatos_rrf(cantidad):
    """Genera candidatos con puntuaciones RRF distintas."""

    return [
        {
            "chunk_id": f"C{indice}",
            "texto": f"Texto del candidato {indice}",
            "rrf_score": (cantidad - indice) / 1000,
        }
        for indice in range(cantidad)
    ]


def test_rerank_limita_60_candidatos_a_20(monkeypatch):
    """El modelo no debe recibir más de 20 candidatos."""

    monkeypatch.setattr(config, "RERANK_TOP_K", 20)

    resultados = crear_candidatos_rrf(60)
    modelo = FakeRerankerConRegistro()

    ordenados = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=modelo,
    )

    assert modelo.llamadas == 1
    assert len(modelo.pares_recibidos) == 20
    assert len(ordenados) == 20

    ids = {resultado["chunk_id"] for resultado in ordenados}
    assert ids == {f"C{indice}" for indice in range(20)}


def test_rerank_selecciona_mejores_rrf_desordenados(monkeypatch):
    """El límite debe aplicarse por puntuación RRF, no por posición."""

    monkeypatch.setattr(config, "RERANK_TOP_K", 3)

    resultados = crear_candidatos_rrf(8)
    resultados.reverse()

    modelo = FakeRerankerConRegistro()

    ordenados = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=modelo,
    )

    ids = {resultado["chunk_id"] for resultado in ordenados}

    assert ids == {"C0", "C1", "C2"}
    assert len(modelo.pares_recibidos) == 3


def test_rerank_respeta_limite_configurable(monkeypatch):
    """RERANK_TOP_K debe poder cambiarse desde la configuración."""

    monkeypatch.setattr(config, "RERANK_TOP_K", 5)

    resultados = crear_candidatos_rrf(15)
    modelo = FakeRerankerConRegistro()

    ordenados = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=modelo,
    )

    assert len(ordenados) == 5
    assert len(modelo.pares_recibidos) == 5


@pytest.mark.parametrize(
    "score_invalido",
    [None, "abc", math.nan, math.inf, True],
)
def test_rerank_rechaza_rrf_invalido_al_limitar(
    monkeypatch,
    score_invalido,
):
    """
    Si es necesario limitar candidatos, las puntuaciones
    RRF deben ser numéricas y finitas.
    """

    monkeypatch.setattr(config, "RERANK_TOP_K", 2)

    resultados = crear_candidatos_rrf(3)
    resultados[0]["rrf_score"] = score_invalido

    modelo = FakeRerankerConRegistro()

    with pytest.raises(ValueError, match="rrf_score"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=modelo,
        )

    assert modelo.llamadas == 0


def test_rerank_limite_no_modifica_originales(monkeypatch):
    """Aplicar el límite no debe modificar los candidatos originales."""

    monkeypatch.setattr(config, "RERANK_TOP_K", 3)

    resultados = crear_candidatos_rrf(10)
    copia_original = [resultado.copy() for resultado in resultados]

    modelo = FakeRerankerConRegistro()

    rerank_results(
        query="problema con el motor",
        results=resultados,
        model=modelo,
    )

    assert resultados == copia_original
    assert all("rerank_score" not in resultado for resultado in resultados)
