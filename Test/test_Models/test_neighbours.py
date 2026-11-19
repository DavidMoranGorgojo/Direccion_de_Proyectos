from Agents.Agent_2.src.clients.backend import get_chunk_with_neighbors
import pytest

def test_neighbors_stay_in_same_document_and_section():
    chunks = [
        {
            "chunk_id": "siguiente",
            "documento": "DOC-1",
            "seccion": "2",
            "orden_en_seccion": 3,
        },
        {
            "chunk_id": "otra-seccion",
            "documento": "DOC-1",
            "seccion": "3",
            "orden_en_seccion": 1,
        },
        {
            "chunk_id": "centro",
            "documento": "DOC-1",
            "seccion": "2",
            "orden_en_seccion": 2,
        },
        {
            "chunk_id": "anterior",
            "documento": "DOC-1",
            "seccion": "2",
            "orden_en_seccion": 1,
        },
        {
            "chunk_id": "otro-documento",
            "documento": "DOC-2",
            "seccion": "2",
            "orden_en_seccion": 1,
        },
    ]

    results = get_chunk_with_neighbors(chunks, "centro", radius=1)

    assert [chunk["chunk_id"] for chunk in results] == [
        "anterior",
        "centro",
        "siguiente",
    ]


def test_missing_chunk_id_returns_empty_list():
    assert get_chunk_with_neighbors([], "no-existe") == []


def test_duplicate_chunk_id_raises_error():
    chunks = [
        {
            "chunk_id": "duplicado",
            "documento": "DOC-1",
            "seccion": "1",
            "orden_en_seccion": 1,
        },
        {
            "chunk_id": "duplicado",
            "documento": "DOC-1",
            "seccion": "1",
            "orden_en_seccion": 2,
        },
    ]

    with pytest.raises(ValueError, match="duplicado"):
        get_chunk_with_neighbors(chunks, "duplicado")
