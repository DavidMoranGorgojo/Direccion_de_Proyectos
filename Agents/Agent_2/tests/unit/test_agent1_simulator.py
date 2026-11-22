import json
from pathlib import Path

import pytest

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.services.vigencia import resolve_retrieval
from Agents.Agent_2.src.testing.agent1_simulator import (
    construir_mensaje_ctr004,
    es_obsoleta,
    resolver_evidencias,
    validar_respuesta_agente2,
)
from Agents.Agent_2.src.testing.backend_simulator import (
    BackendSimulator,
    SimulatedSession,
)

DATA_FILE = (
    Path(__file__).resolve().parents[4]
    / "Agents"
    / "Agent_2"
    / "fixtures"
    / "bbdd_sintetica_chunks.json"
)


def make_evidence(chunk_id="HTM240-DTC-001@1.0_p1_htm0142", **overrides):
    evidencia = {
        "chunk_id": chunk_id,
        "texto": f"Texto de {chunk_id}",
        "score_final": 0.82,
        "metadata": {
            "version": "1.0",
            "versiones": ["V1.0", "V1.1"],
            "documento": "HTM240-DTC-001",
            "seccion": "HTM-0142",
            "pagina": 1,
            "obsoleto": False,
            "sustituido_por": None,
            "componente": "bateria",
            "tipo_documento": "diagnostico",
        },
        "estado_documento": "vigente",
    }
    evidencia.update(overrides)
    return evidencia


def make_message(estado="suficiente", evidencias=None, **overrides):
    mensaje = {
        "estado": estado,
        "evidencias": [make_evidence()] if evidencias is None else evidencias,
        "campo_ambiguo": None,
        "mensaje_error": None,
        "codigo_error": "",
    }
    mensaje.update(overrides)
    return mensaje


def test_a_valid_message_survives_the_agent1_validation():
    mensaje = make_message()

    validado = validar_respuesta_agente2(mensaje)

    assert validado["estado"] == "suficiente"
    assert validado["evidencias"] == mensaje["evidencias"]
    assert validado["campo_ambiguo"] is None
    assert validado["mensaje_error"] is None
    assert validado["codigo_error"] == ""


@pytest.mark.parametrize(
    "mensaje",
    [
        "no es un objeto",
        {"estado": "ok", "evidencias": []},
        {"evidencias": []},
        make_message(estado="suficiente", evidencias=[]),
        make_message(estado="insuficiente", evidencias=[make_evidence()]),
        make_message(estado="solo_obsoleto", evidencias=[]),
        make_message(campo_ambiguo="   "),
        make_message(mensaje_error=7),
        make_message(evidencias=[{"chunk_id": "x", "texto": "y"}]),
        make_message(
            evidencias=[make_evidence(texto="   ")],
        ),
        make_message(
            evidencias=[
                make_evidence(metadata={"pagina": -1}),
            ],
        ),
        make_message(
            evidencias=[
                make_evidence(estado_documento="desconocido"),
            ],
        ),
    ],
)
def test_invalid_messages_are_rejected(mensaje):
    validado = validar_respuesta_agente2(mensaje)

    assert validado == {
        "estado": "error",
        "evidencias": [],
        "campo_ambiguo": None,
        "mensaje_error": "Contrato de Agente 2 inválido.",
        "codigo_error": "error_verificacion",
    }


def test_non_finite_scores_are_rejected():
    mensaje = make_message(
        evidencias=[make_evidence(score_final=float("nan"))],
    )

    assert validar_respuesta_agente2(mensaje)["estado"] == "error"


def test_identical_duplicate_evidence_is_deduplicated():
    evidencia = make_evidence()
    validado = validar_respuesta_agente2(
        make_message(evidencias=[evidencia, dict(evidencia)])
    )

    assert len(validado["evidencias"]) == 1


def test_different_evidence_with_the_same_chunk_id_is_rejected():
    evidencia = make_evidence()
    otra = make_evidence(texto="Otro texto")

    assert (
        validar_respuesta_agente2(
            make_message(evidencias=[evidencia, otra])
        )["estado"]
        == "error"
    )


def test_error_codes_are_normalised_and_never_lost():
    sin_codigo = validar_respuesta_agente2(
        make_message(estado="error", evidencias=[], codigo_error="")
    )
    assert sin_codigo["codigo_error"] == "error_verificacion"

    raro = validar_respuesta_agente2(
        make_message(
            estado="error",
            evidencias=[],
            codigo_error="codigo_inventado",
        )
    )
    assert raro["codigo_error"] == "error_verificacion"

    estandar = validar_respuesta_agente2(
        make_message(
            estado="error",
            evidencias=[],
            codigo_error="indice_no_disponible",
        )
    )
    assert estandar["codigo_error"] == "indice_no_disponible"


def test_ambiguo_becomes_an_aclaracion_request():
    final = resolver_evidencias(
        make_message(estado="ambiguo", campo_ambiguo="version")
    )

    assert final["estado"] == "aclaracion"
    assert final["campo_aclaracion"] == "version"
    assert "version" in final["texto"]
    assert final["fuentes"] == []


def test_insuficiente_becomes_sin_evidencia_without_calling_the_redactor():
    final = resolver_evidencias(make_message(estado="insuficiente", evidencias=[]))

    assert final["estado"] == "sin_evidencia"
    assert final["fuentes"] == []
    assert "No se ha encontrado" in final["texto"]


def test_suficiente_produces_ctr001_sources():
    final = resolver_evidencias(make_message())

    assert final["estado"] == "respuesta"
    assert final["aviso"] is None
    assert final["fuentes"] == [
        {
            "chunk_id": "HTM240-DTC-001@1.0_p1_htm0142",
            "documento": "HTM240-DTC-001",
            "seccion": "HTM-0142",
            "pagina": 1,
            "versiones": ["V1.0", "V1.1"],
            "obsoleto": False,
        }
    ]


def test_solo_obsoleto_produces_a_warning():
    obsoleta = make_evidence(
        metadata={
            "version": "1.0",
            "versiones": ["V1.0"],
            "documento": "HTM240-MNT-001",
            "seccion": "1",
            "pagina": 1,
            "obsoleto": True,
            "sustituido_por": "HTM240-MNT-001",
        },
        estado_documento="sustituido",
    )

    final = resolver_evidencias(
        make_message(estado="solo_obsoleto", evidencias=[obsoleta])
    )

    assert final["estado"] == "respuesta"
    assert final["aviso"].startswith("AVISO")
    assert final["fuentes"][0]["obsoleto"] is True


def test_solo_obsoleto_with_current_evidence_is_an_inconsistency():
    final = resolver_evidencias(
        make_message(estado="solo_obsoleto", evidencias=[make_evidence()])
    )

    assert final["estado"] == "error"
    assert "incoherente" in final["texto"]


def test_version_mismatch_is_an_error():
    final = resolver_evidencias(make_message(), version="V2.0")

    assert final["estado"] == "error"
    assert "versión" in final["texto"]


def test_an_a2_error_is_propagated_with_its_code():
    final = resolver_evidencias(
        make_message(
            estado="error",
            evidencias=[],
            mensaje_error="Índice no disponible.",
            codigo_error="indice_no_disponible",
        )
    )

    assert final["estado"] == "error"
    assert final["texto"] == "Índice no disponible."
    assert final["codigo_error"] == "indice_no_disponible"


def test_agent1_respects_vigente_para_like_a2_06():
    # Un sustituido sigue vigente para las versiones de ``vigente_para``.
    evidencia = make_evidence(
        metadata={
            "version": "1.0",
            "versiones": ["V1.0"],
            "documento": "HTM240-PRC-003",
            "seccion": "1",
            "pagina": 1,
            "obsoleto": True,
            "sustituido_por": "HTM240-PRC-003@2.0",
            "vigente_para": ["V1.0"],
        },
        estado_documento="vigente",
    )

    assert es_obsoleta(evidencia, "V1.0") is False
    assert es_obsoleta(evidencia, "1.0") is False
    assert es_obsoleta(evidencia, "V2.0") is True
    assert es_obsoleta(evidencia) is True


def test_construir_mensaje_ctr004_from_a2_with_the_simulated_backend():
    chunks = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))["chunks"]
    simulator = BackendSimulator(chunks)
    client = BackendAPIClient(
        base_url="http://backend.simulado",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )

    candidatos = simulator.post_lexica(
        {
            "texto": "HTM-0142",
            "filtros": {
                "version": "V1.1",
                "componente": "bateria",
            },
            "k": 3,
        }
    )["resultados"]

    resultado = resolve_retrieval(
        candidatos,
        {"version": "V1.1", "componente": "bateria"},
        client.get_neighbors,
    )
    mensaje = construir_mensaje_ctr004(resultado)

    invitado = validar_respuesta_agente2(mensaje)
    assert invitado["estado"] == "suficiente"
    assert invitado["codigo_error"] == ""
    assert invitado["evidencias"]

    final = resolver_evidencias(mensaje, version="V1.1")
    assert final["estado"] == "respuesta"
    assert final["fuentes"]
    assert {
        fuente["chunk_id"] for fuente in final["fuentes"]
    } >= {"HTM240-DTC-001@1.0_p1_htm0142"}

    for evidencia in mensaje["evidencias"]:
        assert set(evidencia) == {
            "chunk_id",
            "texto",
            "score_final",
            "metadata",
            "estado_documento",
        }
        assert evidencia["metadata"]["versiones"]


def test_construir_mensaje_ctr004_keeps_the_error_without_evidence():
    class Resultado:
        estado = "error"
        candidatos = []
        campo_ambiguo = None
        mensaje_error = "Índice no disponible."
        codigo_error = "indice_no_disponible"

    mensaje = construir_mensaje_ctr004(Resultado())

    assert mensaje["estado"] == "error"
    assert mensaje["evidencias"] == []
    assert mensaje["codigo_error"] == "indice_no_disponible"
    assert validar_respuesta_agente2(mensaje)["estado"] == "error"


def test_construir_mensaje_ctr004_rejects_unknown_states():
    class Resultado:
        estado = "casi"
        candidatos = []
        campo_ambiguo = None
        mensaje_error = None
        codigo_error = None

    with pytest.raises(ValueError):
        construir_mensaje_ctr004(Resultado())
