
import os

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
