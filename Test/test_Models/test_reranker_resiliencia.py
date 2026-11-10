
"""
Pruebas de resiliencia del servicio de reranking del Agente 2.

Comprueban que las entradas malformadas y las respuestas
incorrectas del modelo no se aceptan silenciosamente.
"""

import pytest

from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
)


class FakeReranker:
    """Modelo simulado que devuelve una respuesta configurable."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    def predict(self, pairs):
        self.llamadas += 1
        return self.respuesta


def test_rerank_rechaza_resultado_sin_texto():
    """Un candidato sin texto debe producir un error descriptivo."""

    resultados = [
        {"chunk_id": "A"},
    ]

    with pytest.raises(ValueError, match="texto"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker([0.9]),
        )


def test_rerank_rechaza_resultado_que_no_es_diccionario():
    """Un candidato de tipo incorrecto no debe aceptarse."""

    resultados = [
        "resultado incorrecto",
    ]

    with pytest.raises(ValueError, match="diccionario"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker([0.9]),
        )


def test_threshold_rechaza_resultado_sin_score():
    """El filtrado no debe aceptar resultados sin puntuación."""

    resultados = [
        {"chunk_id": "A"},
    ]

    with pytest.raises(KeyError, match="rerank_score"):
        apply_threshold(
            results=resultados,
            threshold=0.45,
        )


def test_rerank_rechaza_respuesta_none_del_modelo():
    """Una respuesta None del modelo debe producir un error."""

    resultados = [
        {"chunk_id": "A", "texto": "Texto de prueba"},
    ]

    with pytest.raises(ValueError, match="no ha devuelto puntuaciones"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(None),
        )


def test_rerank_rechaza_score_no_numerico():
    """Una puntuación no convertible a número debe rechazarse."""

    resultados = [
        {"chunk_id": "A", "texto": "Texto de prueba"},
    ]

    with pytest.raises(ValueError, match="no numérica"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(["puntuacion-invalida"]),
        )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "\n\t",
        None,
        123,
    ],
)
def test_rerank_rechaza_consulta_invalida(query):
    """La consulta debe ser una cadena con contenido real."""

    modelo = FakeReranker([0.9])

    resultados = [
        {"chunk_id": "A", "texto": "Texto de prueba"},
    ]

    with pytest.raises(ValueError, match="consulta"):
        rerank_results(
            query=query,
            results=resultados,
            model=modelo,
        )

    assert modelo.llamadas == 0


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "   ",
        "\n\t",
        None,
        123,
        [],
    ],
)
def test_rerank_rechaza_texto_invalido(texto):
    """Un candidato debe contener texto válido y no vacío."""

    modelo = FakeReranker([0.9])

    resultados = [
        {"chunk_id": "A", "texto": texto},
    ]

    with pytest.raises(ValueError, match="texto"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=modelo,
        )

    assert modelo.llamadas == 0


def test_rerank_valida_todos_los_candidatos_antes_de_inferencia():
    """
    Si un candidato es inválido, no se debe ejecutar
    una inferencia parcial con los anteriores.
    """

    modelo = FakeReranker([0.9, 0.8])

    resultados = [
        {"chunk_id": "A", "texto": "Primer texto válido"},
        {"chunk_id": "B", "texto": "Segundo texto válido"},
        {"chunk_id": "C", "texto": ""},
    ]

    with pytest.raises(ValueError, match="candidato 2"):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=modelo,
        )

    assert modelo.llamadas == 0


def test_rerank_rechaza_candidato_invalido_sin_llamar_modelo():
    """Una entrada malformada no debe llegar al modelo."""

    modelo = FakeReranker([0.9])

    with pytest.raises(ValueError, match="diccionario"):
        rerank_results(
            query="problema con el motor",
            results=[None],
            model=modelo,
        )

    assert modelo.llamadas == 0


def test_rerank_conserva_texto_original_valido():
    """
    La validación no debe alterar el contenido original
    ni los metadatos de un candidato válido.
    """

    modelo = FakeReranker([0.9])

    resultados = [
        {
            "chunk_id": "A",
            "texto": "  Texto con espacios válidos  ",
            "score_vectorial": 0.85,
            "rrf_score": 0.03,
        },
    ]

    ordenados = rerank_results(
        query="problema con el motor",
        results=resultados,
        model=modelo,
    )

    assert ordenados[0]["texto"] == "  Texto con espacios válidos  "
    assert ordenados[0]["score_vectorial"] == 0.85
    assert ordenados[0]["rrf_score"] == 0.03
    assert ordenados[0]["rerank_score"] == 0.9
    assert "rerank_score" not in resultados[0]
