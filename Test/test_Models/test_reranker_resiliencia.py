
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

    def predict(self, pairs):
        return self.respuesta


def test_rerank_rechaza_resultado_sin_texto():
    """Un candidato sin texto debe producir un error."""

    resultados = [
        {"chunk_id": "A"},
    ]

    with pytest.raises(KeyError, match="texto"):
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

    with pytest.raises(TypeError):
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

    with pytest.raises(TypeError):
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

    with pytest.raises(ValueError):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(["puntuacion-invalida"]),
        )
