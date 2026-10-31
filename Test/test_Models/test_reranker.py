from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
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

    from Agents.Agent_2.src.services.reranker import sort_by_rerank_score

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

    import pytest

    with pytest.raises(ValueError):
        rerank_results(
            query="problema con el motor",
            results=resultados,
            model=FakeReranker(),
        )