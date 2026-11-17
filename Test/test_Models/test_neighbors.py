import pytest

from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.neighbors import expand_with_neighbors


def make_chunk(chunk_id, **overrides):
    chunk = {
        "chunk_id": chunk_id,
        "texto": f"Texto de {chunk_id}",
        "documento": "HTM240-PRC-003",
        "seccion": "Corriente",
        "pagina": 1,
        "versiones": ["V1.0"],
        "componente": "refrigeracion",
        "tipo_documento": "procedimiento",
        "obsoleto": False,
        "sustituido_por": None,
        "vigente_para": [],
        "fecha_revision": "2025-09-18",
        "orden_en_seccion": 1,
        "version_documento": "1.0",
        "afectado_por": [],
        "ids_referenciados": [],
    }
    chunk.update(overrides)
    return chunk


def test_without_fetch_it_only_marks_parents():
    candidate = make_chunk("centro", score=0.9)

    expanded = expand_with_neighbors([candidate])

    assert expanded == [dict(candidate, es_vecino=False)]
    assert "es_vecino" not in candidate
    assert expanded[0] is not candidate


def test_neighbors_are_inserted_in_section_order():
    parent = make_chunk("centro", orden_en_seccion=2)

    expanded = expand_with_neighbors(
        [parent],
        lambda chunk_id: [
            make_chunk("despues", orden_en_seccion=3),
            make_chunk("antes", orden_en_seccion=1),
        ],
    )

    assert [chunk["chunk_id"] for chunk in expanded] == [
        "antes",
        "centro",
        "despues",
    ]
    assert [chunk["es_vecino"] for chunk in expanded] == [True, False, True]


def test_neighbors_do_not_duplicate_candidates():
    first = make_chunk("primero", orden_en_seccion=1)
    second = make_chunk("segundo", orden_en_seccion=2)

    def fetch(chunk_id):
        if chunk_id == "primero":
            return [second]
        return [first]

    expanded = expand_with_neighbors([first, second], fetch)

    assert [chunk["chunk_id"] for chunk in expanded] == [
        "primero",
        "segundo",
    ]
    # Los dos siguen siendo candidatos con su puntuación, no vecinos.
    assert [chunk["es_vecino"] for chunk in expanded] == [False, False]


def test_a_shared_neighbor_is_emitted_once():
    first = make_chunk("primero", orden_en_seccion=2)
    second = make_chunk("segundo", orden_en_seccion=4)
    shared = make_chunk("compartido", orden_en_seccion=3)

    def fetch(chunk_id):
        return [shared]

    expanded = expand_with_neighbors([first, second], fetch)

    assert [chunk["chunk_id"] for chunk in expanded] == [
        "primero",
        "compartido",
        "segundo",
    ]
    assert [chunk["es_vecino"] for chunk in expanded] == [
        False,
        True,
        False,
    ]


def test_blocks_keep_the_candidate_ranking_order():
    parent = make_chunk("centro", orden_en_seccion=2)
    previous = make_chunk("antes", orden_en_seccion=1)

    expanded = expand_with_neighbors([parent], lambda chunk_id: [previous])

    assert expanded[0]["chunk_id"] == "antes"
    assert expanded[1]["chunk_id"] == "centro"


def test_the_center_is_ignored_if_the_fetcher_returns_it():
    parent = make_chunk("centro", orden_en_seccion=2)

    expanded = expand_with_neighbors([parent], lambda chunk_id: [parent])

    assert [chunk["chunk_id"] for chunk in expanded] == ["centro"]
    assert expanded[0]["es_vecino"] is False


def test_backend_errors_are_propagated():
    def fail(chunk_id):
        raise BackendRequestError("indice_no_disponible", "Índice no disponible.")

    with pytest.raises(BackendRequestError) as error:
        expand_with_neighbors([make_chunk("centro")], fail)

    assert error.value.codigo_error == "indice_no_disponible"


def test_unexpected_fetch_errors_become_backend_errors():
    def fail(chunk_id):
        raise RuntimeError("boom")

    with pytest.raises(BackendRequestError) as error:
        expand_with_neighbors([make_chunk("centro")], fail)

    assert error.value.codigo_error == "servicio_no_disponible"


def test_invalid_fetch_response_is_rejected():
    with pytest.raises(BackendRequestError):
        expand_with_neighbors(
            [make_chunk("centro")],
            lambda chunk_id: "no es una lista",
        )


def test_neighbors_must_be_objects_with_chunk_id():
    with pytest.raises(BackendRequestError):
        expand_with_neighbors(
            [make_chunk("centro")],
            lambda chunk_id: ["no es un objeto"],
        )

    with pytest.raises(BackendRequestError):
        expand_with_neighbors(
            [make_chunk("centro")],
            lambda chunk_id: [{"chunk_id": ""}],
        )


def test_neighbors_must_belong_to_the_same_document_and_section():
    with pytest.raises(BackendRequestError):
        expand_with_neighbors(
            [make_chunk("centro")],
            lambda chunk_id: [make_chunk("otro", documento="HTM240-OTRO")],
        )

    with pytest.raises(BackendRequestError):
        expand_with_neighbors(
            [make_chunk("centro")],
            lambda chunk_id: [make_chunk("otro", seccion="Otra")],
        )


def test_invalid_arguments_are_rejected():
    with pytest.raises(TypeError):
        expand_with_neighbors(None)
    with pytest.raises(TypeError):
        expand_with_neighbors([make_chunk("centro")], "fetch")
    with pytest.raises(TypeError):
        expand_with_neighbors(["no es un objeto"])
    with pytest.raises(ValueError):
        expand_with_neighbors([{"chunk_id": ""}])
    with pytest.raises(ValueError):
        expand_with_neighbors(
            [make_chunk("centro"), make_chunk("centro")]
        )
