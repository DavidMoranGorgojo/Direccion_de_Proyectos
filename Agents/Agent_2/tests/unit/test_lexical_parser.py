import copy

import pytest

from Agents.Agent_2.src.models.lexical import (
    LexicalCandidate,
    LexicalIndexInfo,
    LexicalSearchResponse,
)
from Agents.Agent_2.src.services.lexical_parser import (
    LexicalContractError,
    LexicalParserError,
    LexicalValidationError,
    parse_lexical_response,
)


def _candidate(**overrides):
    candidate = {
        "chunk_id": "HTM240-DTC-001@1.0_p1_htm0142",
        "score": 4.25,
        "texto": "HTM-0142: revisar CMP-17-B en V1.1. Código exacto HTM-0142.",
        "documento": "HTM240-DTC-001",
        "seccion": "HTM-0142",
        "pagina": 1,
        "versiones": ["V1.0", "V1.1"],
        "componente": "bateria",
        "tipo_documento": "codigo_averia",
        "obsoleto": False,
        "sustituido_por": None,
        "vigente_para": [],
        "fecha_revision": "2025-09-18",
        "orden_en_seccion": 1,
        "version_documento": "1.0",
        "afectado_por": ["BOL-003"],
        "ids_referenciados": ["CMP-17", "CMP-18", "HTM-0142"],
    }
    candidate.update(overrides)
    return candidate


def _payload():
    return {
        "indice": {
            "version": "v1.0-bd",
            "modelo_embeddings": "BAAI/bge-m3",
        },
        "resultados": [
            _candidate(),
            _candidate(
                chunk_id="HTM240-BOL-003@1.0_p1_significado_HTM0142_v20",
                score=2,
                texto="Boletín BOL-003: HTM-0142 cambia en V2.0 hacia cmp-18.",
                documento="HTM240-BOL-003",
                tipo_documento="boletin",
                versiones=["V1.0", "V1.1", "V2.0"],
                ids_referenciados=["CMP-18", "HTM-0142"],
            ),
        ],
    }


def test_valid_response_is_parsed_and_preserves_order():
    parsed = parse_lexical_response(_payload())

    assert isinstance(parsed, LexicalSearchResponse)
    assert isinstance(parsed.indice, LexicalIndexInfo)
    assert parsed.indice == LexicalIndexInfo(
        version="v1.0-bd",
        modelo_embeddings="BAAI/bge-m3",
    )
    assert all(isinstance(c, LexicalCandidate) for c in parsed.resultados)
    assert [c.chunk_id for c in parsed.resultados] == [
        "HTM240-DTC-001@1.0_p1_htm0142",
        "HTM240-BOL-003@1.0_p1_significado_HTM0142_v20",
    ]


def test_empty_results_are_valid():
    payload = _payload()
    payload["resultados"] = []

    parsed = parse_lexical_response(payload)

    assert parsed.resultados == []


def test_score_is_converted_to_float():
    payload = _payload()
    payload["resultados"][1]["score"] = 2

    parsed = parse_lexical_response(payload)

    assert parsed.resultados[1].score_lexico == 2.0
    assert isinstance(parsed.resultados[1].score_lexico, float)


def test_exact_codes_and_identifiers_are_not_normalized():
    payload = _payload()
    original = payload["resultados"][1]

    parsed = parse_lexical_response(payload)
    candidate = parsed.resultados[1]

    assert candidate.chunk_id == original["chunk_id"]
    assert candidate.texto == original["texto"]
    assert candidate.metadatos.documento == original["documento"]
    assert candidate.metadatos.ids_referenciados == [
        "CMP-18",
        "HTM-0142",
    ]
    assert "cmp-18" in candidate.texto
    assert "CMP-18" not in candidate.texto


def test_payload_is_not_mutated():
    payload = _payload()
    original = copy.deepcopy(payload)

    parse_lexical_response(payload)

    assert payload == original


def test_preserves_all_metadata():
    payload = _payload()
    original = payload["resultados"][0]

    metadatos = parse_lexical_response(payload).resultados[0].metadatos

    assert metadatos.documento == original["documento"]
    assert metadatos.seccion == original["seccion"]
    assert metadatos.pagina == original["pagina"]
    assert metadatos.versiones == original["versiones"]
    assert metadatos.componente == original["componente"]
    assert metadatos.tipo_documento == original["tipo_documento"]
    assert metadatos.obsoleto == original["obsoleto"]
    assert metadatos.sustituido_por == original["sustituido_por"]
    assert metadatos.vigente_para == original["vigente_para"]
    assert metadatos.fecha_revision == original["fecha_revision"]
    assert metadatos.orden_en_seccion == original["orden_en_seccion"]
    assert metadatos.version_documento == original["version_documento"]
    assert metadatos.afectado_por == original["afectado_por"]
    assert metadatos.ids_referenciados == original["ids_referenciados"]


@pytest.mark.parametrize("payload", [[], None, "texto", 7])
def test_payload_must_be_an_object(payload):
    with pytest.raises(LexicalContractError):
        parse_lexical_response(payload)


@pytest.mark.parametrize("field", ["indice", "resultados"])
def test_missing_top_level_fields_are_contract_errors(field):
    payload = _payload()
    del payload[field]

    with pytest.raises(LexicalContractError, match=field):
        parse_lexical_response(payload)


def test_resultados_must_be_a_list():
    payload = _payload()
    payload["resultados"] = None

    with pytest.raises(LexicalValidationError, match="resultados"):
        parse_lexical_response(payload)


def test_indice_must_be_an_object():
    payload = _payload()
    payload["indice"] = []

    with pytest.raises(LexicalValidationError, match="indice"):
        parse_lexical_response(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", ""),
        ("version", "   "),
        ("modelo_embeddings", ""),
        ("modelo_embeddings", "   "),
        ("version", None),
        ("modelo_embeddings", 7),
    ],
)
def test_invalid_index_fields_are_rejected(field, value):
    payload = _payload()
    payload["indice"][field] = value

    with pytest.raises(LexicalParserError, match=field):
        parse_lexical_response(payload)


def test_candidate_must_be_an_object():
    payload = _payload()
    payload["resultados"][0] = "no es un objeto"

    with pytest.raises(LexicalContractError, match=r"resultados\[0\]"):
        parse_lexical_response(payload)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("chunk_id", "", LexicalValidationError),
        ("chunk_id", "   ", LexicalValidationError),
        ("texto", "", LexicalValidationError),
        ("texto", "   ", LexicalValidationError),
        ("score", "4.25", LexicalValidationError),
        ("score", True, LexicalValidationError),
        ("score", float("nan"), LexicalValidationError),
        ("score", float("inf"), LexicalValidationError),
        ("score", float("-inf"), LexicalValidationError),
    ],
)
def test_invalid_candidate_values_are_rejected(field, value, error):
    payload = _payload()
    payload["resultados"][0][field] = value

    with pytest.raises(error, match=rf"resultados\[0\]\.{field}"):
        parse_lexical_response(payload)


@pytest.mark.parametrize(
    "field",
    [
        "chunk_id",
        "score",
        "texto",
        "documento",
        "seccion",
        "pagina",
        "versiones",
        "componente",
        "tipo_documento",
        "obsoleto",
        "sustituido_por",
        "vigente_para",
        "fecha_revision",
        "orden_en_seccion",
        "version_documento",
        "afectado_por",
        "ids_referenciados",
    ],
)
def test_missing_candidate_fields_are_contract_errors(field):
    payload = _payload()
    del payload["resultados"][0][field]

    with pytest.raises(LexicalContractError, match=rf"resultados\[0\]\.{field}"):
        parse_lexical_response(payload)


def test_duplicate_chunk_id_is_rejected():
    payload = _payload()
    payload["resultados"][1]["chunk_id"] = payload["resultados"][0]["chunk_id"]

    with pytest.raises(
        LexicalValidationError,
        match=r"resultados\[1\]\.chunk_id",
    ):
        parse_lexical_response(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("documento", 3),
        ("seccion", None),
        ("pagina", "3"),
        ("pagina", True),
        ("versiones", "V1.1"),
        ("versiones", [1]),
        ("componente", None),
        ("tipo_documento", 1),
        ("obsoleto", 0),
        ("obsoleto", "false"),
        ("sustituido_por", 3),
        ("vigente_para", "V1.0"),
        ("vigente_para", [1]),
        ("orden_en_seccion", "3"),
        ("orden_en_seccion", False),
        ("version_documento", 1.0),
        ("afectado_por", "BOL-003"),
        ("afectado_por", [1]),
        ("ids_referenciados", None),
        ("ids_referenciados", [1]),
        ("fecha_revision", 20261015),
    ],
)
def test_invalid_metadata_types_are_rejected(field, value):
    payload = _payload()
    payload["resultados"][0][field] = value

    with pytest.raises(
        LexicalValidationError,
        match=rf"resultados\[0\]\.{field}",
    ):
        parse_lexical_response(payload)


def test_null_optional_fields_are_allowed():
    payload = _payload()
    payload["resultados"][0]["sustituido_por"] = None
    payload["resultados"][0]["fecha_revision"] = None

    parsed = parse_lexical_response(payload)

    assert parsed.resultados[0].metadatos.sustituido_por is None
    assert parsed.resultados[0].metadatos.fecha_revision is None


@pytest.mark.parametrize(
    "value",
    ["2026-02-30", "2026-13-01", "15-10-2026", "20261015", "   "],
)
def test_invalid_dates_are_rejected(value):
    payload = _payload()
    payload["resultados"][0]["fecha_revision"] = value

    with pytest.raises(
        LexicalValidationError,
        match=r"resultados\[0\]\.fecha_revision",
    ):
        parse_lexical_response(payload)


def test_empty_lists_are_allowed():
    payload = _payload()
    payload["resultados"][0]["afectado_por"] = []
    payload["resultados"][0]["ids_referenciados"] = []
    payload["resultados"][0]["vigente_para"] = []

    parsed = parse_lexical_response(payload)

    assert parsed.resultados[0].metadatos.afectado_por == []
    assert parsed.resultados[0].metadatos.ids_referenciados == []
    assert parsed.resultados[0].metadatos.vigente_para == []


def test_parser_errors_are_value_errors():
    assert issubclass(LexicalParserError, ValueError)
    assert issubclass(LexicalContractError, LexicalParserError)
    assert issubclass(LexicalValidationError, LexicalParserError)
