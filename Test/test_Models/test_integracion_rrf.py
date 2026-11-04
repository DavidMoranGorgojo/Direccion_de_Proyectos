from Agents.Agent_2.src.services.fusion import rrf


def test_integracion_busquedas_con_rrf():
    # Resultados simulados de la búsqueda vectorial
    resultados_vectoriales = [
        {"chunk_id": "C001", "texto": "Manual del motor", "score": 0.92},
        {"chunk_id": "C002", "texto": "Sistema de frenos", "score": 0.85},
    ]

    # Resultados simulados de la búsqueda BM25
    resultados_bm25 = [
        {"chunk_id": "C002", "texto": "Sistema de frenos", "score": 3.5},
        {"chunk_id": "C003", "texto": "Revisión de neumáticos", "score": 2.8},
    ]

    # Fusionamos ambos rankings
    resultados = rrf(resultados_vectoriales, resultados_bm25)

    # Comprobamos que aparecen los tres fragmentos sin duplicados
    assert len(resultados) == 3
    assert {r["chunk_id"] for r in resultados} == {"C001", "C002", "C003"}

    # C002 aparece en ambas búsquedas, por lo que debe quedar primero
    assert resultados[0]["chunk_id"] == "C002"

    # Comprobamos que se conserva el texto y se añade la puntuación RRF
    assert resultados[0]["texto"] == "Sistema de frenos"
    assert "rrf_score" in resultados[0]