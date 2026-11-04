
import pytest

from Agents.Agent_2.src.clients.reranker_model import RerankerModel


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
