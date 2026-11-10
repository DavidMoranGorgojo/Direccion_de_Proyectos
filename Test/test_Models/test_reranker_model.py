
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from Agents.Agent_2.src.clients.reranker_model import RerankerModel
from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
)


class FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = None

    def compute_score(self, pairs, normalize=False):
        self.received_pairs = pairs
        self.normalize = normalize
        return self.scores


class FakeModelConError:
    """Simula un fallo durante la ejecución del modelo."""

    def compute_score(self, pairs, normalize=False):
        raise RuntimeError("Error simulado del modelo de reranking")


class FakeModelConcurrencia:
    """
    Detecta si dos hilos entran simultáneamente en compute_score().

    El contador se protege con un lock independiente para
    medir la concurrencia sin interferir con el modelo probado.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.inferencias_activas = 0
        self.max_inferencias_simultaneas = 0
        self.total_inferencias = 0

    def compute_score(self, pairs, normalize=False):
        with self.lock:
            self.inferencias_activas += 1
            self.total_inferencias += 1

            self.max_inferencias_simultaneas = max(
                self.max_inferencias_simultaneas,
                self.inferencias_activas,
            )

        try:
            time.sleep(0.02)
            return [0.9] * len(pairs)
        finally:
            with self.lock:
                self.inferencias_activas -= 1


class FakeModelFalloRecuperable:
    """
    Falla durante la primera inferencia y permite
    comprobar que el lock se libera correctamente.
    """

    def __init__(self):
        self.llamadas = 0

    def compute_score(self, pairs, normalize=False):
        self.llamadas += 1

        if self.llamadas == 1:
            raise RuntimeError("Fallo temporal de inferencia")

        return [0.8] * len(pairs)


def test_predict_devuelve_scores_del_modelo():
    fake_model = FakeModel([0.90, 0.35])

    reranker = RerankerModel(model=fake_model)

    pairs = [
        ["problema con el motor", "El motor presenta una avería."],
        ["problema con el motor", "Información sobre los neumáticos."],
    ]

    scores = reranker.predict(pairs)

    assert scores == [0.90, 0.35]


def test_predict_envia_los_pares_al_modelo():
    fake_model = FakeModel([0.80])

    reranker = RerankerModel(model=fake_model)

    pairs = [
        ["fallo de batería", "Procedimiento para revisar la batería."]
    ]

    reranker.predict(pairs)

    assert fake_model.received_pairs == pairs


def test_predict_lista_vacia():
    fake_model = FakeModel([])

    reranker = RerankerModel(model=fake_model)

    scores = reranker.predict([])

    assert scores == []


def test_predict_solicita_scores_normalizados():
    fake_model = FakeModel([0.90])

    reranker = RerankerModel(model=fake_model)

    pairs = [
        ["fallo de batería", "Procedimiento para revisar la batería."]
    ]

    reranker.predict(pairs)

    assert fake_model.normalize is True


def test_predict_propaga_error_del_modelo():
    """Un fallo del modelo no debe confundirse con cero resultados."""

    fake_model = FakeModelConError()
    reranker = RerankerModel(model=fake_model)

    pairs = [
        ["fallo de batería", "Procedimiento para revisar la batería."]
    ]

    with pytest.raises(
        RuntimeError,
        match="Error simulado del modelo de reranking"
    ):
        reranker.predict(pairs)


@pytest.mark.skipif(
    os.getenv("RUN_REAL_RERANKER_TEST") != "1",
    reason="La prueba con el modelo real se ejecuta opcionalmente",
)
def test_integracion_con_modelo_real():
    """
    Comprueba el adaptador, el reranking y el umbral
    utilizando BAAI/bge-reranker-v2-m3.

    Requiere FlagEmbedding y los pesos del modelo.
    """

    from FlagEmbedding import FlagReranker

    modelo_real = FlagReranker(
        "BAAI/bge-reranker-v2-m3",
        use_fp16=False,
    )

    reranker = RerankerModel(model=modelo_real)

    query = "¿Cómo funciona la bomba auxiliar?"

    resultados = [
        {
            "chunk_id": "C1",
            "texto": "El calendario de vacaciones se publica en enero.",
        },
        {
            "chunk_id": "C2",
            "texto": "La bomba auxiliar suministra presión al sistema.",
        },
    ]

    ordenados = rerank_results(query, resultados, reranker)

    assert len(ordenados) == 2
    assert ordenados[0]["chunk_id"] == "C2"
    assert ordenados[0]["rerank_score"] > ordenados[1]["rerank_score"]

    filtrados = apply_threshold(ordenados, threshold=0.45)

    assert [resultado["chunk_id"] for resultado in filtrados] == ["C2"]


def test_predict_serializa_inferencias_concurrentes():
    """
    Cinco hilos comparten una única instancia de RerankerModel.

    Aunque las consultas se lancen concurrentemente, el modelo
    subyacente nunca debe ejecutar dos inferencias a la vez.
    """

    modelo = FakeModelConcurrencia()
    reranker = RerankerModel(model=modelo)

    numero_hilos = 5
    inicio = threading.Barrier(numero_hilos)

    def ejecutar_consulta(indice):
        inicio.wait(timeout=5)

        return reranker.predict([
            [
                f"Consulta {indice}",
                f"Documento {indice}",
            ]
        ])

    with ThreadPoolExecutor(max_workers=numero_hilos) as executor:
        resultados = list(
            executor.map(ejecutar_consulta, range(numero_hilos))
        )

    assert resultados == [[0.9]] * numero_hilos
    assert modelo.total_inferencias == numero_hilos
    assert modelo.max_inferencias_simultaneas == 1
    assert modelo.inferencias_activas == 0


def test_predict_libera_lock_tras_error():
    """
    Si compute_score() falla, el error se propaga,
    pero el lock debe quedar disponible para otra consulta.
    """

    modelo = FakeModelFalloRecuperable()
    reranker = RerankerModel(model=modelo)

    pairs = [
        ["fallo de batería", "Revisar la batería."]
    ]

    with pytest.raises(
        RuntimeError,
        match="Fallo temporal de inferencia"
    ):
        reranker.predict(pairs)

    resultado = reranker.predict(pairs)

    assert resultado == [0.8]
    assert modelo.llamadas == 2
