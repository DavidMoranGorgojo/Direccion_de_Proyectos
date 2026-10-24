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