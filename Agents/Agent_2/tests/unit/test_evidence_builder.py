from __future__ import annotations

import copy
import json
import sys
from dataclasses import fields
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_DIR = REPO_ROOT / "Agents" / "Agent_2" / "tests" / "fixtures"

sys.path.insert(0, str(REPO_ROOT))

from Agents.Agent_2.src.models.ctr_002 import ChunkMetadata
from Agents.Agent_2.src.services.evidence_builder import (
    CODIGOS_ERROR,
    EvidenceBuilderError,
    EvidenceContractError,
    EvidenceValidationError,
    build_evidence_response,
    build_evidences,
)
from Agents.Agent_2.src.services.fusion import rrf
from Agents.Agent_2.src.services.reranker import (
    apply_threshold,
    rerank_results,
)

CAMPOS_MENSAJE = {
    "estado",
    "evidencias",
    "campo_ambiguo",
    "codigo_error",
    "mensaje_error",
}

CAMPOS_EVIDENCIA = {
    "chunk_id",
    "texto",
    "score_final",
    "estado_documento",
    "metadata",
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


# --- Evidencias -------------------------------------------------------------


def test_salida_coincide_con_el_fixture_esperado():
    response = build_evidence_response("suficiente", _candidatos())

    assert response == _load("evidencias_esperadas.json")


def test_conserva_el_orden_de_entrada():
    candidates = list(reversed(_candidatos()))

    evidencias = build_evidences(candidates)

    assert [item["chunk_id"] for item in evidencias] == ["c47", "c46", "c45"]


def test_cada_evidencia_tiene_exactamente_sus_campos():
    for item in build_evidences(_candidatos()):
        assert set(item) == CAMPOS_EVIDENCIA


def test_metadata_conserva_los_catorce_metadatos_ctr_002_y_version():
    candidates = _candidatos()

    assert len(CAMPOS_METADATOS) == 14
    assert "vigente_para" in CAMPOS_METADATOS

    for candidate, item in zip(candidates, build_evidences(candidates)):
        assert set(item["metadata"]) == CAMPOS_METADATOS | {"version"}

        for campo in CAMPOS_METADATOS:
            assert item["metadata"][campo] == candidate[campo]

        assert item["metadata"]["version"] == candidate["version_documento"]


def test_un_solo_nombre_por_campo():
    """No se duplican resultados/evidencias ni metadatos/metadata."""

    response = build_evidence_response("suficiente", _candidatos())

    assert set(response) == CAMPOS_MENSAJE
    assert "resultados" not in response

    for item in response["evidencias"]:
        assert "metadatos" not in item
        assert "documento" not in item


def test_score_final_es_rerank_score():
    candidates = _candidatos()

    for candidate, item in zip(candidates, build_evidences(candidates)):
        assert item["score_final"] == candidate["rerank_score"]


def test_no_usa_otra_puntuacion_si_falta_rerank_score():
    candidate = _candidato()
    del candidate["rerank_score"]
    candidate["rrf_score"] = 0.99
    candidate["score_vectorial"] = 0.88

    with pytest.raises(EvidenceContractError):
        build_evidences([candidate])


@pytest.mark.parametrize(
    "valor",
    [float("nan"), float("inf"), float("-inf"), -0.1, 1.1, True, "0.5", None],
)
def test_rerank_score_invalido(valor):
    candidate = _candidato()
    candidate["rerank_score"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate])


@pytest.mark.parametrize("valor", ["", "   ", 123, None, True])
def test_chunk_id_invalido(valor):
    candidate = _candidato()
    candidate["chunk_id"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate])


def test_chunk_id_ausente():
    candidate = _candidato()
    del candidate["chunk_id"]

    with pytest.raises(EvidenceContractError):
        build_evidences([candidate])


def test_chunk_id_duplicado():
    candidate = _candidato()

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate, copy.deepcopy(candidate)])


@pytest.mark.parametrize("valor", ["", "   ", 123, None])
def test_texto_invalido(valor):
    candidate = _candidato()
    candidate["texto"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate])


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
        ("fecha_revision", ""),
        ("orden_en_seccion", True),
        ("afectado_por", ["BOL-003", 1]),
        ("ids_referenciados", "HTM-0142"),
    ],
)
def test_metadatos_incorrectos(campo, valor):
    candidate = _candidato()
    candidate[campo] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate])


def test_fecha_revision_null_permitida():
    candidate = _candidato()
    candidate["fecha_revision"] = None

    evidencia = build_evidences([candidate])[0]

    assert evidencia["metadata"]["fecha_revision"] is None


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
        build_evidences([candidate])


@pytest.mark.parametrize(
    "campo",
    ["documento", "seccion", "pagina", "vigente_para", "fecha_revision"],
)
def test_metadato_ausente(campo):
    candidate = _candidato()
    del candidate[campo]

    with pytest.raises(EvidenceContractError):
        build_evidences([candidate])


def test_conserva_vigente_para_distinto_de_versiones():
    candidate = _candidato()
    candidate["versiones"] = ["V1.1", "V2.0"]
    candidate["vigente_para"] = ["V2.0"]

    metadata = build_evidences([candidate])[0]["metadata"]

    assert metadata["versiones"] == ["V1.1", "V2.0"]
    assert metadata["vigente_para"] == ["V2.0"]


# Estado_documento


def test_estado_documento_de_a2_06_tiene_prioridad():
    """Un sustituido aún vigente para la versión consultada sigue «vigente»."""

    candidate = copy.deepcopy(_candidatos()[2])
    assert candidate["obsoleto"] is True
    candidate["estado_documento"] = "vigente"

    assert build_evidences([candidate])[0]["estado_documento"] == "vigente"


@pytest.mark.parametrize(
    "obsoleto,sustituido_por,esperado",
    [
        (False, None, "vigente"),
        (True, "HTM240-BOL-009", "sustituido"),
        (True, None, "obsoleto"),
    ],
)
def test_estado_documento_deducido_sin_a2_06(obsoleto, sustituido_por, esperado):
    candidate = _candidato()
    candidate["obsoleto"] = obsoleto
    candidate["sustituido_por"] = sustituido_por

    assert build_evidences([candidate])[0]["estado_documento"] == esperado


@pytest.mark.parametrize("valor", ["caducado", "", None, 1])
def test_estado_documento_invalido(valor):
    candidate = _candidato()
    candidate["estado_documento"] = valor

    with pytest.raises(EvidenceValidationError):
        build_evidences([candidate])


#  Mensaje completo
def test_sin_evidencia_es_un_estado_explicito():
    assert build_evidence_response("sin_evidencia") == {
        "estado": "sin_evidencia",
        "evidencias": [],
        "campo_ambiguo": None,
        "codigo_error": None,
        "mensaje_error": None,
    }


def test_insuficiente_de_a2_06_se_entrega_como_sin_evidencia():
    assert build_evidence_response("insuficiente")["estado"] == "sin_evidencia"


@pytest.mark.parametrize("codigo", CODIGOS_ERROR)
def test_error_lleva_codigo_y_nunca_evidencias(codigo):
    response = build_evidence_response(
        "error", codigo_error=codigo, mensaje_error="Fallo del Backend."
    )

    assert response["estado"] == "error"
    assert response["evidencias"] == []
    assert response["codigo_error"] == codigo


def test_error_sin_codigo_ctr_001_rechazado():
    for codigo in (None, "", "error_tecnico"):
        with pytest.raises(EvidenceValidationError):
            build_evidence_response("error", codigo_error=codigo)


def test_error_con_evidencias_rechazado():
    with pytest.raises(EvidenceValidationError):
        build_evidence_response(
            "error", _candidatos(), codigo_error="tiempo_agotado"
        )


def test_codigo_error_solo_en_estado_error():
    with pytest.raises(EvidenceValidationError):
        build_evidence_response(
            "suficiente", _candidatos(), codigo_error="tiempo_agotado"
        )


@pytest.mark.parametrize("estado", ["suficiente", "solo_obsoleto"])
def test_estados_con_contenido_necesitan_evidencias(estado):
    with pytest.raises(EvidenceValidationError):
        build_evidence_response(estado, [])


def test_sin_evidencia_con_evidencias_rechazado():
    with pytest.raises(EvidenceValidationError):
        build_evidence_response("sin_evidencia", _candidatos())


def test_ambiguo_lleva_campo_ambiguo():
    response = build_evidence_response(
        "ambiguo", _candidatos(), campo_ambiguo="version"
    )

    assert response["campo_ambiguo"] == "version"
    assert len(response["evidencias"]) == 3


@pytest.mark.parametrize(
    "estado,campo",
    [("ambiguo", "tipo_documento"), ("suficiente", "version")],
)
def test_campo_ambiguo_invalido(estado, campo):
    with pytest.raises(EvidenceValidationError):
        build_evidence_response(estado, _candidatos(), campo_ambiguo=campo)


@pytest.mark.parametrize("estado", ["respuesta", "aclaracion", "", None])
def test_estado_desconocido_rechazado(estado):
    with pytest.raises(EvidenceValidationError):
        build_evidence_response(estado, _candidatos())


@pytest.mark.parametrize(
    "candidates",
    [None, {}, "no es una lista", [None], [{}], [{"chunk_id": "c45"}]],
)
def test_entrada_mal_formada_produce_error(candidates):
    with pytest.raises(EvidenceBuilderError):
        build_evidences(candidates)


def test_propaga_errores_ajenos_sin_ocultarlos():
    class ErrorConCodigo(RuntimeError):
        codigo_error = "error_tecnico_simulado"

    class CandidatoQueFalla(dict):
        def __contains__(self, key):
            raise ErrorConCodigo("Fallo técnico simulado")

    with pytest.raises(ErrorConCodigo) as error:
        build_evidences([CandidatoQueFalla()])

    assert error.value.codigo_error == "error_tecnico_simulado"


def test_no_modifica_los_candidatos_originales():
    candidates = _candidatos()
    originales = copy.deepcopy(candidates)

    build_evidence_response("suficiente", candidates)

    assert candidates == originales


def test_metadata_no_comparte_listas_con_la_entrada():
    candidate = _candidato()

    evidencia = build_evidences([candidate])[0]
    evidencia["metadata"]["versiones"].append("V9.9")

    assert candidate["versiones"] == ["V1.1", "V2.0"]


def test_serializacion_json_sin_nan_ni_infinity():
    response = build_evidence_response("suficiente", _candidatos())

    serialized = json.dumps(response, allow_nan=False)

    assert json.loads(serialized) == response


def test_no_incluye_puntuaciones_intermedias():
    for item in build_evidences(_candidatos()):
        assert CAMPOS_INTERMEDIOS.isdisjoint(item)
        assert CAMPOS_INTERMEDIOS.isdisjoint(item["metadata"])


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

    response = build_evidence_response("suficiente", filtered)

    assert len(response["evidencias"]) == 2
    assert [item["chunk_id"] for item in response["evidencias"]] == [
        result["chunk_id"] for result in filtered
    ]

    for result, item in zip(filtered, response["evidencias"]):
        assert item["score_final"] == result["rerank_score"]
        assert 0 <= item["score_final"] <= 1
        assert item["texto"] == result["texto"]
