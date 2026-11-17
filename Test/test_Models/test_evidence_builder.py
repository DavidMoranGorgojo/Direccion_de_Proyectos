from __future__ import annotations

import copy
import json
import sys
from dataclasses import fields
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "Test" / "fixtures" / "agent2"

sys.path.insert(0, str(REPO_ROOT))

from Agents.Agent_2.src.models.ctr_002 import ChunkMetadata
from Agents.Agent_2.src.services.evidence_builder import (
    EvidenceBuilderError,
    EvidenceContractError,
    EvidenceValidationError,
    build_evidence_response,
)
from Agents.Agent_2.src.services.fusion import rrf
from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
)

CAMPOS_EVIDENCIA = {
    "chunk_id",
    "score_final",
    "texto",
    "metadatos",
}

CAMPOS_METADATOS = {field.name for field in fields(ChunkMetadata)}

CAMPOS_INTERMEDIOS = {
    "score_vectorial",
    "score_bm25",
    "rrf_score",
    "rerank_score",
}


def _load(name: str):
    with (FIXTURES_DIR / name).open(encoding="utf-8") as fixture:
        return json.load(fixture)


def _candidatos():
    return _load("evidencias_candidatos.json")


def _candidato():
    return copy.deepcopy(_candidatos()[0])


def _resultado_busqueda(candidate, score):
    result = copy.deepcopy(candidate)

    for campo in CAMPOS_INTERMEDIOS:
        result.pop(campo, None)

    result["score"] = score
    return result


def test_empaqueta_una_evidencia_valida():
    candidate = _candidato()

    response = build_evidence_response([candidate])

    assert set(response) == {"resultados"}
    assert len(response["resultados"]) == 1
    assert response["resultados"][0]["chunk_id"] == "c45"


def test_salida_coincide_con_el_fixture_esperado():
    response = build_evidence_response(_candidatos())

    assert response == _load("evidencias_esperadas.json")


def test_empaqueta_varias_evidencias():
    candidates = _candidatos()

    response = build_evidence_response(candidates)

    assert len(response["resultados"]) == 3
    assert [item["chunk_id"] for item in response["resultados"]] == [
        "c45",
        "c46",
        "c47",
    ]


def test_conserva_el_orden_de_entrada():
    candidates = list(reversed(_candidatos()))

    response = build_evidence_response(candidates)

    assert [item["chunk_id"] for item in response["resultados"]] == [
        "c47",
        "c46",
        "c45",
    ]


def test_cada_evidencia_tiene_exactamente_cuatro_campos():
    response = build_evidence_response(_candidatos())

    for item in response["resultados"]:
        assert set(item) == CAMPOS_EVIDENCIA


def test_conserva_los_catorce_metadatos_ctr_002():
    candidates = _candidatos()

    response = build_evidence_response(candidates)

    assert len(CAMPOS_METADATOS) == 14
    assert "vigente_para" in CAMPOS_METADATOS

    for candidate, item in zip(candidates, response["resultados"]):
        assert set(item["metadatos"]) == CAMPOS_METADATOS

        for campo in CAMPOS_METADATOS:
            assert item["metadatos"][campo] == candidate[campo]


def test_metadatos_anidados_correctamente():
    response = build_evidence_response([_candidato()])
    item = response["resultados"][0]

    assert "documento" not in item
    assert "metadatos" in item
    assert item["metadatos"]["documento"] == "HTM240-DTC-001"


def test_score_final_es_rerank_score():
    candidates = _candidatos()

    response = build_evidence_response(candidates)

    for candidate, item in zip(candidates, response["resultados"]):
        assert item["score_final"] == candidate["rerank_score"]


def test_no_usa_rrf_score_ni_score_vectorial_como_fallback():
    candidate = _candidato()
    candidate["rerank_score"] = 0.73
    candidate["rrf_score"] = 0.99
    candidate["score_vectorial"] = 0.88

    response = build_evidence_response([candidate])

    assert response["resultados"][0]["score_final"] == 0.73


def test_falta_rerank_score_es_error():
    candidate = _candidato()
    del candidate["rerank_score"]

    with pytest.raises(EvidenceContractError):
        build_evidence_response([candidate])


def test_no_usa_otra_puntuacion_si_falta_rerank_score():
    candidate = _candidato()
    del candidate["rerank_score"]
    candidate["rrf_score"] = 0.99
    candidate["score_vectorial"] = 0.88

    with pytest.raises(EvidenceContractError):
        build_evidence_response([candidate])


@pytest.mark.parametrize(
    "valor",
    ["", "   ", 123, None, True],
)
def test_chunk_id_invalido(valor):
    candidate = _candidato()
    candidate["chunk_id"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate])


def test_chunk_id_ausente():
    candidate = _candidato()
    del candidate["chunk_id"]

    with pytest.raises(EvidenceContractError):
        build_evidence_response([candidate])


def test_chunk_id_duplicado():
    candidate = _candidato()

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate, copy.deepcopy(candidate)])


@pytest.mark.parametrize(
    "valor",
    ["", "   ", 123, None],
)
def test_texto_invalido(valor):
    candidate = _candidato()
    candidate["texto"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate])


def test_texto_ausente():
    candidate = _candidato()
    del candidate["texto"]

    with pytest.raises(EvidenceContractError):
        build_evidence_response([candidate])


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("documento", 1),
        ("pagina", "3"),
        ("pagina", True),
        ("versiones", "V1.1"),
        ("versiones", ["V1.1", 2]),
        ("obsoleto", "false"),
        ("sustituido_por", 1),
        ("vigente_para", "V1.1"),
        ("vigente_para", ["V1.1", 2]),
        ("fecha_revision", "2026-13-01"),
        ("orden_en_seccion", True),
        ("afectado_por", ["BOL-003", 1]),
        ("ids_referenciados", "HTM-0142"),
    ],
)
def test_metadatos_incorrectos(campo, valor):
    candidate = _candidato()
    candidate[campo] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate])


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("documento", ""),
        ("documento", "   "),
        ("seccion", ""),
        ("seccion", "  "),
        ("pagina", 0),
        ("pagina", -1),
    ],
)
def test_fuente_no_citable_rechazada(campo, valor):
    """CTR-004 §5: sin documento, sección y página la evidencia no es válida."""
    candidate = _candidato()
    candidate[campo] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate])


def test_conserva_vigente_para_distinto_de_versiones():
    """CTR-004 §3: el Agente 2 no descarta metadatos de CTR-002."""
    candidate = _candidato()
    candidate["versiones"] = ["V1.1", "V2.0"]
    candidate["vigente_para"] = ["V2.0"]

    metadatos = build_evidence_response([candidate])["resultados"][0][
        "metadatos"
    ]

    assert metadatos["versiones"] == ["V1.1", "V2.0"]
    assert metadatos["vigente_para"] == ["V2.0"]


@pytest.mark.parametrize(
    "campo",
    ["documento", "seccion", "pagina", "vigente_para"],
)
def test_metadato_ausente(campo):
    candidate = _candidato()
    del candidate[campo]

    with pytest.raises(EvidenceContractError):
        build_evidence_response([candidate])


@pytest.mark.parametrize(
    "valor",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.1,
        1.1,
        True,
        "0.5",
        None,
    ],
)
def test_rerank_score_invalido(valor):
    candidate = _candidato()
    candidate["rerank_score"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidence_response([candidate])


def test_entrada_vacia_es_valida():
    assert build_evidence_response([]) == {"resultados": []}


@pytest.mark.parametrize(
    "candidates",
    [
        None,
        {},
        "no es una lista",
        [None],
        [{}],
        [{"chunk_id": "c45"}],
    ],
)
def test_entrada_mal_formada_produce_error(candidates):
    with pytest.raises(EvidenceBuilderError):
        build_evidence_response(candidates)


def test_propaga_errores_sin_perder_codigo_error():
    class ErrorConCodigo(RuntimeError):
        codigo_error = "error_tecnico_simulado"

    class CandidatoQueFalla(dict):
        def __contains__(self, key):
            raise ErrorConCodigo("Fallo técnico simulado")

    with pytest.raises(ErrorConCodigo) as error:
        build_evidence_response([CandidatoQueFalla()])

    assert error.value.codigo_error == "error_tecnico_simulado"


def test_no_modifica_los_candidatos_originales():
    candidates = _candidatos()
    originales = copy.deepcopy(candidates)

    build_evidence_response(candidates)

    assert candidates == originales


def test_los_metadatos_de_salida_no_comparten_listas_con_la_entrada():
    candidate = _candidato()

    response = build_evidence_response([candidate])
    response["resultados"][0]["metadatos"]["versiones"].append("V9.9")

    assert candidate["versiones"] == ["V1.1", "V2.0"]


def test_serializacion_json_sin_nan_ni_infinity():
    response = build_evidence_response(_candidatos())

    serialized = json.dumps(response, allow_nan=False)

    assert json.loads(serialized) == response


def test_no_incluye_puntuaciones_intermedias():
    response = build_evidence_response(_candidatos())

    for item in response["resultados"]:
        assert CAMPOS_INTERMEDIOS.isdisjoint(item)
        assert CAMPOS_INTERMEDIOS.isdisjoint(item["metadatos"])


def test_integracion_light_con_rrf_reranker_y_umbral():
    class FakeReranker:
        def predict(self, pairs):
            return [0.20, 0.95, 0.70][: len(pairs)]

    candidates = _candidatos()

    vector_results = [
        _resultado_busqueda(candidate, 0.90 - posicion * 0.10)
        for posicion, candidate in enumerate(candidates)
    ]
    bm25_results = [
        _resultado_busqueda(candidate, 8.0 - posicion)
        for posicion, candidate in enumerate(candidates)
    ]

    fused = rrf(vector_results, bm25_results)
    reranked = rerank_results(
        query="avería en el sistema de refrigeración",
        results=fused,
        model=FakeReranker(),
    )
    filtered = apply_threshold(reranked, threshold=0.45)

    response = build_evidence_response(filtered)

    assert len(response["resultados"]) == 2
    assert [item["chunk_id"] for item in response["resultados"]] == [
        result["chunk_id"] for result in filtered
    ]

    for result, item in zip(filtered, response["resultados"]):
        assert item["score_final"] == result["rerank_score"]
        assert item["texto"] == result["texto"]
