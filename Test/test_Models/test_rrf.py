from Agents.Agent_2.src.services.fusion import rrf


def test_rrf_fusion():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "C"},
        {"chunk_id": "B"},
    ]

    bm25_results = [
        {"chunk_id": "B"},
        {"chunk_id": "A"},
        {"chunk_id": "D"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 4
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"
    assert resultado[2]["chunk_id"] == "C"
    assert resultado[3]["chunk_id"] == "D"

    assert "rrf_score" in resultado[0]

def test_rrf_vectorial_vacio():
    vector_results = []

    bm25_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 2
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"


def test_rrf_lexico_vacio():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    bm25_results = []

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 2
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"


def test_rrf_ambos_vacios():
    resultado = rrf([], [])

    assert resultado == []


def test_rrf_chunk_en_ambos_rankings():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    bm25_results = [
        {"chunk_id": "A"},
        {"chunk_id": "C"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert resultado[0]["chunk_id"] == "A"

    score_esperado = (1 / 61) + (1 / 61)
    assert resultado[0]["rrf_score"] == score_esperado


def test_rrf_conserva_metadatos():
    vector_results = [
        {
            "chunk_id": "A",
            "texto": "Comprobar el sensor de presión",
            "documento": "manual_taller",
            "pagina": 15,
        }
    ]

    resultado = rrf(vector_results, [])

    assert resultado[0]["chunk_id"] == "A"
    assert resultado[0]["texto"] == "Comprobar el sensor de presión"
    assert resultado[0]["documento"] == "manual_taller"
    assert resultado[0]["pagina"] == 15
    assert "rrf_score" in resultado[0]


def test_rrf_k_personalizable():
    vector_results = [
        {"chunk_id": "A"},
    ]

    resultado = rrf(vector_results, [], k=10)

    assert resultado[0]["rrf_score"] == 1 / 11



def test_rrf_no_modifica_resultados_originales():
    vector_results = [
        {"chunk_id": "A", "score": 0.90},
    ]

    bm25_results = [
        {"chunk_id": "A", "score": 8.5},
    ]

    rrf(vector_results, bm25_results)

    assert "rrf_score" not in vector_results[0]
    assert "rrf_score" not in bm25_results[0]

def test_rrf_rechaza_resultado_sin_chunk_id():
    import pytest

    resultados_invalidos = [
        {"texto": "Fragmento sin identificador"}
    ]

    with pytest.raises(ValueError, match="chunk_id"):
        rrf(resultados_invalidos, [])