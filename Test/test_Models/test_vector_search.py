import pytest
from Agents.Agent_2.src.clients.backend import search_vector


def test_vector_search_ranks_by_cosine_and_limits_k():
    chunks = [
        {"chunk_id": "cercano", "texto": "cerca"},
        {"chunk_id": "medio", "texto": "medio"},
        {"chunk_id": "lejano", "texto": "lejos"},
    ]
    vectors = {
        "cercano": [1.0, 0.0],
        "medio": [0.8, 0.6],
        "lejano": [0.0, 1.0],
    }

    results = search_vector(
        chunks,
        query_vector=[1.0, 0.0],
        vectors_by_chunk_id=vectors,
        k=2,
    )

    assert [chunk["chunk_id"] for chunk in results] == ["cercano", "medio"]
    assert len(results) == 2
    assert results[0]["score"] == pytest.approx(1.0)
    assert results[1]["score"] == pytest.approx(0.8)

def test_vector_search_applies_strict_filters_before_top_k():
    chunks = [
        {
            "chunk_id": "otra-version",
            "vigente_para": ["V2.0"],
            "componente": "bateria",
        },
        {
            "chunk_id": "correcto",
            "vigente_para": ["V1.1"],
            "componente": "bateria",
        },
        {
            "chunk_id": "otro-componente",
            "vigente_para": ["V1.1"],
            "componente": "motor",
        },
    ]
    vectors = {
        "otra-version": [1.0, 0.0],
        "correcto": [0.8, 0.6],
        "otro-componente": [1.0, 0.0],
    }

    results = search_vector(
        chunks,
        query_vector=[1.0, 0.0],
        vectors_by_chunk_id=vectors,
        filters={"version": "V1.1", "componente": "bateria"},
        k=1,
    )

    assert [chunk["chunk_id"] for chunk in results] == ["correcto"]


def test_missing_chunk_vector_raises_error():
    chunks = [
        {
            "chunk_id": "sin-vector",
            "vigente_para": ["V1.1"],
            "componente": "bateria",
        }
    ]

    with pytest.raises(ValueError, match="Falta el vector"):
        search_vector(
            chunks,
            query_vector=[1.0, 0.0],
            vectors_by_chunk_id={},
        )