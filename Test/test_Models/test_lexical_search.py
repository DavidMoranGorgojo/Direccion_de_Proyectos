from Agents.Agent_2.src.clients.backend import search_lexical


def test_lexical_search_matches_dtc_as_an_exact_code():
    chunks = [
        {
            "chunk_id": "exacto",
            "texto": "Se registra el código HTM-0142 en la TCU.",
        },
        {
            "chunk_id": "mas_largo",
            "texto": "Se registra el código HTM-01420 en la TCU.",
        },
        {
            "chunk_id": "sin_guion",
            "texto": "Se registra el código HTM0142 en la TCU.",
        },
    ]

    results = search_lexical(chunks, "htm-0142", k=5)

    assert [chunk["chunk_id"] for chunk in results] == ["exacto"]

def test_lexical_search_applies_filters_before_top_k():
    chunks = [
        {
            "chunk_id": "otra-version",
            "texto": "HTM-0142 " * 10,
            "vigente_para": ["V2.0"],
            "componente": "bateria",
            "tipo_documento": "codigo_averia",
            "score": 0,
        },
        {
            "chunk_id": "correcto",
            "texto": "HTM-0142",
            "vigente_para": ["V1.1"],
            "componente": "bateria",
            "tipo_documento": "codigo_averia",
            "score": 0,
        },
        {
            "chunk_id": "otro-componente",
            "texto": "HTM-0142 " * 10,
            "vigente_para": ["V1.1"],
            "componente": "motor",
            "tipo_documento": "codigo_averia",
            "score": 0,
        },
    ]

    results = search_lexical(
        chunks,
        "HTM-0142",
        filters={"version": "V1.1", "componente": "bateria"},
        k=1,
    )

    assert [chunk["chunk_id"] for chunk in results] == ["correcto"]
    assert results[0]["score"] > 0
    assert chunks[0]["score"] == 0

def test_lexical_search_normalizes_case_and_accents():
    chunks = [
        {
            "chunk_id": "refrigeracion",
            "texto": "Avería en la refrigeración de la batería.",
        }
    ]

    results = search_lexical(chunks, "AVERIA REFRIGERACION", k=5)

    assert [chunk["chunk_id"] for chunk in results] == ["refrigeracion"]