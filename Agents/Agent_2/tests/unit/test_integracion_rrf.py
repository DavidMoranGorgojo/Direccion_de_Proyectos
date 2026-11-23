import json
from pathlib import Path

import pytest

from Agents.Agent_2.src.services.fusion import rrf


def test_integracion_busquedas_con_rrf():
    """Comprueba la fusión de resultados vectoriales y BM25 simulados."""

    resultados_vectoriales = [
        {
            "chunk_id": "chunk_1",
            "texto": "Información sobre la bomba auxiliar",
            "score": 0.95,
        },
        {
            "chunk_id": "chunk_2",
            "texto": "Información sobre el sistema hidráulico",
            "score": 0.85,
        },
    ]

    resultados_bm25 = [
        {
            "chunk_id": "chunk_1",
            "texto": "Información sobre la bomba auxiliar",
            "score": 8.5,
        },
        {
            "chunk_id": "chunk_3",
            "texto": "Información sobre mantenimiento",
            "score": 7.2,
        },
    ]

    resultados = rrf(resultados_vectoriales, resultados_bm25)

    assert len(resultados) == 3

    # El chunk presente en ambas búsquedas debe quedar primero.
    assert resultados[0]["chunk_id"] == "chunk_1"

    # No deben aparecer fragmentos duplicados.
    ids = [resultado["chunk_id"] for resultado in resultados]
    assert len(ids) == len(set(ids))

    # Deben conservarse los metadatos y añadirse la puntuación RRF.
    for resultado in resultados:
        assert "texto" in resultado
        assert "rrf_score" in resultado


def test_integracion_bm25_real_con_rrf():
    """Comprueba la integración con el BM25 y el dataset sintético."""

    dataset_path = Path(
        "Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json"
    )

    # El dataset todavía puede no estar integrado en nuestra rama.
    if not dataset_path.exists():
        pytest.skip("Dataset sintético todavía no integrado")

    # Importación opcional: backend.py puede estar pendiente de integración.
    from Agents.Agent_2.src.clients import backend

    if not hasattr(backend, "search_lexical"):
        pytest.skip("Búsqueda BM25 del recuperador todavía no integrada")

    with dataset_path.open(encoding="utf-8-sig") as archivo:
        dataset = json.load(archivo)

    resultados_bm25 = backend.search_lexical(
        dataset["chunks"],
        "bomba auxiliar",
        k=5,
    )

    resultados = rrf([], resultados_bm25)

    assert len(resultados) == 5

    # El orden debe coincidir con BM25 al no haber resultados vectoriales.
    assert [r["chunk_id"] for r in resultados] == [
        r["chunk_id"] for r in resultados_bm25
    ]

    # Comprobamos la fórmula RRF con k=60.
    for posicion, resultado in enumerate(resultados, start=1):
        assert resultado["rrf_score"] == pytest.approx(
            1 / (60 + posicion)
        )
        assert "texto" in resultado