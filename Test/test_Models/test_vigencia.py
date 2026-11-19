import json
from pathlib import Path

import pytest

from Agents.Agent_2.src.clients.backend import get_chunk_with_neighbors
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.models.retrieval import RetrievalDecision
from Agents.Agent_2.src.services.vigencia import (
    classify_state,
    common_version,
    document_state,
    is_current,
    resolve_retrieval,
)

DATA_FILE = (
    Path(__file__).resolve().parents[2]
    / "Agents"
    / "Agent_2"
    / "fixtures"
    / "bbdd_sintetica_chunks.json"
)


def read_dataset():
    return json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))["chunks"]


def make_chunk(chunk_id, **overrides):
    chunk = {
        "chunk_id": chunk_id,
        "texto": f"Texto de {chunk_id}",
        "documento": "HTM240-DOC-001",
        "seccion": "1",
        "pagina": 1,
        "versiones": ["V1.0"],
        "componente": "bateria",
        "tipo_documento": "manual",
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


def test_document_state_without_version():
    assert document_state(make_chunk("vigente")) == "vigente"
    assert document_state(make_chunk("obsoleto", obsoleto=True)) == "obsoleto"
    assert (
        document_state(
            make_chunk(
                "sustituido",
                obsoleto=True,
                sustituido_por="HTM240-DOC-001",
            )
        )
        == "sustituido"
    )


def test_substituted_document_is_current_only_for_vigente_para():
    chunk = make_chunk(
        "prc",
        versiones=["V1.0"],
        obsoleto=True,
        sustituido_por="HTM240-PRC-003",
        vigente_para=["V1.0"],
    )

    assert document_state(chunk, "V1.0") == "vigente"
    assert document_state(chunk, "1.0") == "vigente"
    assert document_state(chunk, "V1.1") == "sustituido"
    assert document_state(chunk) == "sustituido"


def test_chunk_from_another_version_is_not_current():
    chunk = make_chunk("antiguo", versiones=["V1.0"])

    assert document_state(chunk, "V1.0") == "vigente"
    assert document_state(chunk, "V2.0") == "obsoleto"
    assert is_current(chunk, "V1.0")
    assert not is_current(chunk, "V2.0")


def test_empty_candidates_are_insufficient():
    assert classify_state([], {}) == RetrievalDecision("insuficiente")
    assert classify_state((), {}) == RetrievalDecision("insuficiente")


def test_single_current_candidate_is_sufficient():
    assert classify_state([make_chunk("a")], {}).estado == "suficiente"


def test_all_obsolete_or_substituted_is_solo_obsoleto():
    candidates = [
        make_chunk("obsoleto", obsoleto=True),
        make_chunk(
            "sustituido",
            obsoleto=True,
            sustituido_por="HTM240-DOC-002",
        ),
    ]

    decision = classify_state(candidates, {})

    assert decision.estado == "solo_obsoleto"
    assert decision.campo_ambiguo is None


def test_mixed_current_and_obsolete_is_sufficient():
    candidates = [
        make_chunk("vigente"),
        make_chunk("obsoleto", obsoleto=True),
    ]

    assert classify_state(candidates, {}).estado == "suficiente"


def test_substituted_with_vigente_para_is_not_solo_obsoleto():
    chunk = make_chunk(
        "prc",
        versiones=["V1.0"],
        obsoleto=True,
        sustituido_por="HTM240-PRC-003",
        vigente_para=["V1.0"],
    )

    assert classify_state([chunk], {"version": "V1.0"}).estado == "suficiente"
    assert classify_state([chunk], {"version": "V1.1"}).estado == "solo_obsoleto"


def test_different_components_are_ambiguous():
    candidates = [
        make_chunk("bateria", componente="bateria"),
        make_chunk("motor", componente="motor"),
    ]

    decision = classify_state(candidates, {})

    assert decision.estado == "ambiguo"
    assert decision.campo_ambiguo == "componente"

    fixed = classify_state(candidates, {"componente": "bateria"})
    assert fixed.estado == "suficiente"
    assert fixed.campo_ambiguo is None


def test_different_versions_are_ambiguous():
    candidates = [
        make_chunk("v10", versiones=["V1.0"]),
        make_chunk("v20", versiones=["V2.0"]),
    ]

    decision = classify_state(candidates, {})

    assert decision.estado == "ambiguo"
    assert decision.campo_ambiguo == "version"

    fixed = classify_state(candidates, {"version": "V1.0"})
    assert fixed.estado == "suficiente"


def test_version_ambiguity_has_priority_over_component():
    candidates = [
        make_chunk("a", versiones=["V1.0"], componente="bateria"),
        make_chunk("b", versiones=["V2.0"], componente="motor"),
    ]

    assert classify_state(candidates, {}).campo_ambiguo == "version"


def test_shared_version_is_not_ambiguous():
    candidates = [
        make_chunk("a", versiones=["V1.0", "V1.1"]),
        make_chunk("b", versiones=["V1.1", "V2.0"]),
    ]

    assert common_version(candidates) == {"V1.1"}
    assert classify_state(candidates, {}).estado == "suficiente"


def test_common_version_is_none_for_disjoint_versions():
    candidates = [
        make_chunk("a", versiones=["V1.0"]),
        make_chunk("b", versiones=["V2.0"]),
    ]

    assert common_version(candidates) is None


def test_obsolete_incompatible_versions_still_require_clarification():
    candidates = [
        make_chunk(
            "a",
            versiones=["V1.0"],
            componente="bateria",
            obsoleto=True,
        ),
        make_chunk(
            "b",
            versiones=["V2.0"],
            componente="motor",
            obsoleto=True,
        ),
    ]

    # CTR-004 §4: el aviso de obsolescencia no resuelve una versión ambigua.
    decision = classify_state(candidates, {})
    assert decision.estado == "ambiguo"
    assert decision.campo_ambiguo == "version"


def test_classify_rejects_invalid_inputs():
    with pytest.raises(TypeError):
        classify_state(None, {})
    with pytest.raises(TypeError):
        classify_state({}, {})
    with pytest.raises(TypeError):
        classify_state("candidatos", {})
    with pytest.raises(TypeError):
        classify_state(["texto"], {})
    with pytest.raises(TypeError):
        classify_state([make_chunk("a")], ["version"])
    with pytest.raises(ValueError):
        classify_state([{"chunk_id": ""}], {})
    with pytest.raises(ValueError):
        classify_state([{"chunk_id": "   "}], {})
    with pytest.raises(ValueError):
        classify_state([{}], {})


def test_resolve_without_neighbors_marks_candidates_copying_them():
    candidates = [make_chunk("a")]

    result = resolve_retrieval(candidates, {})

    assert result.estado == "suficiente"
    assert result.campo_ambiguo is None
    assert result.codigo_error is None
    assert [chunk["chunk_id"] for chunk in result.candidatos] == ["a"]
    assert result.candidatos[0]["es_vecino"] is False
    assert result.candidatos[0]["estado_documento"] == "vigente"

    # No se mutan los candidatos originales del reranker.
    assert "es_vecino" not in candidates[0]
    assert "estado_documento" not in candidates[0]


def test_resolve_expands_neighbors_in_section_order():
    parent = make_chunk("centro", orden_en_seccion=2)
    previous = make_chunk("antes", orden_en_seccion=1)
    following = make_chunk("despues", orden_en_seccion=3)

    result = resolve_retrieval(
        [parent],
        {},
        lambda chunk_id: [following, previous],
    )

    assert result.estado == "suficiente"
    assert [chunk["chunk_id"] for chunk in result.candidatos] == [
        "antes",
        "centro",
        "despues",
    ]
    assert [chunk["es_vecino"] for chunk in result.candidatos] == [
        True,
        False,
        True,
    ]
    assert all(
        chunk["estado_documento"] == "vigente"
        for chunk in result.candidatos
    )


def test_resolve_marks_neighbors_with_their_version_state():
    parent = make_chunk("centro", orden_en_seccion=2, versiones=["V1.1"])
    old_neighbor = make_chunk("antiguo", orden_en_seccion=1, obsoleto=True)

    result = resolve_retrieval(
        [parent],
        {},
        lambda chunk_id: [old_neighbor],
    )

    states = {
        chunk["chunk_id"]: chunk["estado_documento"]
        for chunk in result.candidatos
    }

    assert states == {"centro": "vigente", "antiguo": "obsoleto"}


def test_resolve_discards_neighbors_incompatible_with_version_filter():
    parent = make_chunk("centro", orden_en_seccion=2, versiones=["V1.1"])
    incompatible_neighbor = make_chunk(
        "incompatible",
        orden_en_seccion=1,
        versiones=["V1.0"],
    )

    result = resolve_retrieval(
        [parent],
        {"version": "V1.1"},
        lambda chunk_id: [incompatible_neighbor],
    )

    assert [c["chunk_id"] for c in result.candidatos] == ["centro"]


def test_resolve_returns_error_when_the_backend_fails():
    def fail(chunk_id):
        raise BackendRequestError(
            "indice_no_disponible",
            "Índice no disponible.",
        )

    result = resolve_retrieval([make_chunk("a")], {}, fail)

    assert result.estado == "error"
    assert result.es_error
    assert result.codigo_error == "indice_no_disponible"
    assert result.mensaje_error == "Índice no disponible."
    assert result.candidatos == []


def test_resolve_returns_error_on_unexpected_neighbor_failure():
    def fail(chunk_id):
        raise RuntimeError("boom")

    result = resolve_retrieval([make_chunk("a")], {}, fail)

    assert result.estado == "error"
    assert result.codigo_error == "servicio_no_disponible"
    assert result.mensaje_error == (
        "No se pudieron recuperar los vecinos de a."
    )


def test_insufficient_never_requests_neighbors():
    calls = []

    def fetch(chunk_id):
        calls.append(chunk_id)
        return []

    result = resolve_retrieval([], {}, fetch)

    assert result.estado == "insuficiente"
    assert result.candidatos == []
    assert calls == []


def test_solo_obsoleto_still_requests_neighbors():
    calls = []

    def fetch(chunk_id):
        calls.append(chunk_id)
        return []

    obsolete = make_chunk("obsoleto", obsoleto=True)
    result = resolve_retrieval([obsolete], {}, fetch)

    assert result.estado == "solo_obsoleto"
    assert calls == ["obsoleto"]
    assert result.candidatos[0]["estado_documento"] == "obsoleto"


def test_real_dataset_section_with_two_components_is_ambiguous():
    chunks = read_dataset()
    section = [
        chunk
        for chunk in chunks
        if chunk["documento"] == "HTM240-CAT-001"
        and chunk["seccion"] == "CMP-02"
    ]

    assert len(section) == 2

    decision = classify_state(section, {})
    assert decision.estado == "ambiguo"
    assert decision.campo_ambiguo == "componente"

    assert classify_state(
        section,
        {"version": "V1.1", "componente": "bateria"},
    ).estado == "suficiente"


def test_real_dataset_neighbors_stay_in_the_same_section():
    chunks = read_dataset()
    center = next(
        chunk
        for chunk in chunks
        if chunk["chunk_id"] == "HTM240-CAT-001@1.0_p1_cat_001_02"
    )

    def fetch(chunk_id):
        return [
            chunk
            for chunk in get_chunk_with_neighbors(chunks, chunk_id, radius=1)
            if chunk["chunk_id"] != chunk_id
        ]

    result = resolve_retrieval([center], {"version": "V1.1"}, fetch)

    assert result.estado == "suficiente"
    assert [chunk["chunk_id"] for chunk in result.candidatos] == [
        "HTM240-CAT-001@1.0_p1_cat_001_02",
        "HTM240-CAT-001@1.0_p1_cat_001_03",
    ]
    assert all(
        chunk["documento"] == center["documento"]
        and chunk["seccion"] == center["seccion"]
        for chunk in result.candidatos
    )
    assert [chunk["es_vecino"] for chunk in result.candidatos] == [
        False,
        True,
    ]
