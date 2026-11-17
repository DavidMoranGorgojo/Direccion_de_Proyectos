import dataclasses
import json
import math
from pathlib import Path

import pytest
import requests

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.filters import filter_chunks
from Agents.Agent_2.src.services.lexical_parser import parse_lexical_response
from Agents.Agent_2.src.services.vigencia import resolve_retrieval
from Agents.Agent_2.src.testing.backend_simulator import (
    BackendSimulator,
    SimulatedSession,
    build_app,
)

DATA_FILE = (
    Path(__file__).resolve().parents[2]
    / "Agents"
    / "Agent_2"
    / "fixtures"
    / "bbdd_sintetica_chunks.json"
)
CATALOG_DIR = DATA_FILE.parent / "catalogos"

METADATOS = (
    "chunk_id",
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
)


def read_chunks():
    return json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))["chunks"]


@pytest.fixture(scope="module")
def chunks():
    return read_chunks()


@pytest.fixture()
def simulator(chunks):
    return BackendSimulator(chunks, catalogo_dir=CATALOG_DIR)


@pytest.fixture()
def client(simulator):
    return BackendAPIClient(
        base_url="http://backend.simulado",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )


def test_vectorial_round_trip_fulfils_ctr002(simulator, client):
    vector = simulator.embed_query("query: HTM-0142 sensor de presión")
    respuesta = client.search_vector(vector=vector, k=8)

    assert set(respuesta) == {"indice", "resultados"}
    assert respuesta["indice"] == {
        "version": simulator.version,
        "modelo_embeddings": "BAAI/bge-m3",
    }

    resultados = respuesta["resultados"]
    assert resultados
    assert len(resultados) <= 8

    scores = [resultado["score"] for resultado in resultados]
    assert all(isinstance(score, float) for score in scores)
    assert all(math.isfinite(score) for score in scores)
    assert scores == sorted(scores, reverse=True)

    for resultado in resultados:
        assert set(resultado) == set(METADATOS) | {"score"}
        assert "score_vectorial" not in resultado
        assert isinstance(resultado["versiones"], list)
        assert isinstance(resultado["obsoleto"], bool)

    # El simulador indexa el texto real del dataset, no un índice propio.
    assert resultados[0]["chunk_id"] == "HTM240-DTC-001@1.0_p1_htm0142"
    ids = {resultado["chunk_id"] for resultado in resultados}
    assert "HTM240-DTC-001@1.0_p1_htm0142_v20" in ids


def test_the_query_prefix_is_checked_before_building_the_vector(simulator):
    with pytest.raises(ValueError):
        simulator.embed_query("HTM-0142")

    with pytest.raises(ValueError):
        simulator.embed_query("query:HTM-0142")

    with pytest.raises(ValueError):
        simulator.embed_query("  query: HTM-0142")

    vector = simulator.embed_query("query: HTM-0142")
    assert len(vector) == simulator.dimensiones
    assert any(valor != 0 for valor in vector)


def test_lexical_round_trip_preserves_exact_codes(simulator, client):
    crudo = client.search_lexical(text="HTM-0142", k=6)
    respuesta = parse_lexical_response(crudo)

    assert respuesta.indice.version == simulator.version
    assert respuesta.indice.modelo_embeddings == "BAAI/bge-m3"
    assert respuesta.resultados

    for candidato in respuesta.resultados:
        assert candidato.score_lexico > 0
        assert candidato.texto.strip()
        assert candidato.metadatos.obsoleto is False

    por_id = {
        candidato.chunk_id: candidato for candidato in respuesta.resultados
    }
    assert "HTM-0142" in por_id[
        "HTM240-DTC-001@1.0_p1_htm0142"
    ].metadatos.ids_referenciados
    assert "HTM240-BOL-003@1.0_p1_significado_HTM0142_v20" in por_id


def test_hard_filters_are_applied_and_never_relaxed(simulator, client):
    version = client.search_lexical(
        text="HTM-0142",
        filtros={"version": "V2.0"},
        k=30,
    )["resultados"]

    assert version
    assert all(
        "V2.0" in resultado["versiones"]
        or (
            not resultado["obsoleto"]
            and "V2.0" in resultado["versiones"]
        )
        for resultado in version
    )
    ids = {resultado["chunk_id"] for resultado in version}
    assert "HTM240-DTC-001@1.0_p1_htm0142" not in ids
    assert "HTM240-DTC-001@1.0_p1_htm0142_v20" in ids

    componente = client.search_lexical(
        text="batería refrigerante",
        filtros={"componente": "refrigeracion"},
        k=10,
    )["resultados"]

    assert componente
    assert all(
        resultado["componente"] == "refrigeracion"
        for resultado in componente
    )

    vacio = client.search_lexical(
        text="HTM-0142",
        filtros={"version": "V2.0", "componente": "motor"},
        k=10,
    )
    assert vacio["resultados"] == []


def test_unknown_filter_values_are_rejected_with_filtro_invalido(simulator):
    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/lexica",
        {"texto": "batería", "filtros": {"version": "V9.9"}},
    )

    assert estado == 400
    assert cuerpo["codigo"] == "filtro_invalido"
    assert cuerpo["campo"] == "version"
    assert "V9.9" not in cuerpo["valores_validos"]
    assert "V2.0" in cuerpo["valores_validos"]

    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/vectorial",
        {
            "vector": [0.0] * simulator.dimensiones,
            "filtros": {"componente": "turbo"},
            "k": 5,
        },
    )

    assert estado == 400
    assert cuerpo["codigo"] == "filtro_invalido"
    assert cuerpo["campo"] == "componente"


def test_filters_outside_ctr002_are_rejected(simulator):
    # §5.1: los códigos de avería no son filtro del Backend.
    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/vectorial",
        {
            "vector": [0.0] * simulator.dimensiones,
            "filtros": {"codigos": ["HTM-0142"]},
            "k": 5,
        },
    )

    assert estado == 400
    assert cuerpo["codigo"] == "peticion_invalida"
    assert {
        "campo": "filtros.codigos",
        "motivo": "campo no permitido",
    } in cuerpo["errores"]

    # En la léxica el esquema inválido llega como 422 de la pasarela.
    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/lexica",
        {"texto": "batería", "filtros": {"codigos": ["HTM-0142"]}},
    )

    assert estado == 422
    assert cuerpo["codigo"] == "entrada_invalida"


def test_invalid_bodies_are_rejected_with_the_contract_errors(simulator):
    casos = [
        ({"vector": [0.0] * 3, "k": 5}, "vector"),
        ({"vector": [0.0] * simulator.dimensiones}, "k"),
        ({"vector": [0.0] * simulator.dimensiones, "k": 0}, "k"),
        ({"vector": [0.0] * simulator.dimensiones, "k": 201}, "k"),
        ({"vector": [0.0] * simulator.dimensiones, "k": True}, "k"),
        ({"vector": [0.0] * simulator.dimensiones, "k": 5, "otro": 1}, "otro"),
    ]

    for cuerpo, campo in casos:
        estado, respuesta = simulator.atender(
            "POST",
            "/conocimiento/vectorial",
            cuerpo,
        )

        assert estado == 400
        assert respuesta["codigo"] == "peticion_invalida"
        assert campo in {error["campo"] for error in respuesta["errores"]}

    estado, respuesta = simulator.atender(
        "POST",
        "/conocimiento/lexica",
        {"texto": "   "},
    )
    assert estado == 422
    assert respuesta["codigo"] == "entrada_invalida"


def test_document_type_filter_admits_a_single_value(simulator, client):
    resultados = client.search_lexical(
        text="mantenimiento",
        filtros={"tipo_documento": "mantenimiento"},
        k=10,
    )["resultados"]

    assert resultados
    assert all(
        resultado["tipo_documento"] == "mantenimiento"
        for resultado in resultados
    )


def test_model_and_index_errors_match_ctr002(simulator):
    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/vectorial",
        {
            "vector": [0.0] * simulator.dimensiones,
            "modelo_embeddings": "otro/modelo",
            "k": 5,
        },
    )

    assert estado == 409
    assert cuerpo["codigo"] == "modelo_incompatible"
    assert cuerpo["modelo_indice"] == "BAAI/bge-m3"

    simulator.desactivar_indice()

    estado, cuerpo = simulator.atender(
        "POST",
        "/conocimiento/lexica",
        {"texto": "batería"},
    )

    assert estado == 503
    assert cuerpo["codigo"] == "indice_no_disponible"


def test_chunk_and_neighbours_stay_in_the_same_section(simulator, client):
    chunk_id = "HTM240-MAN-001@1.1_p1_man_001_02"
    respuesta = client.get_chunk(chunk_id, vecinos=1)

    assert respuesta["indice"] == {"version": simulator.version}
    assert respuesta["chunk"]["chunk_id"] == chunk_id

    vecinos = respuesta["vecinos"]
    assert [vecino["chunk_id"] for vecino in vecinos] == [
        "HTM240-MAN-001@1.1_p1_man_001_03",
        "HTM240-MAN-001@1.1_p1_man_001_03b",
        "HTM240-MAN-001@1.1_p2_man_001_04",
    ]
    assert all(
        vecino["documento"] == respuesta["chunk"]["documento"]
        and vecino["seccion"] == respuesta["chunk"]["seccion"]
        for vecino in vecinos
    )

    assert client.get_chunk(chunk_id, vecinos=0)["vecinos"] == []


def test_unknown_chunk_is_mapped_to_index_unavailable(simulator, client):
    estado, cuerpo = simulator.atender(
        "GET",
        "/conocimiento/chunks/no-existe",
        parametros={"vecinos": 1},
    )

    assert estado == 404
    assert cuerpo["codigo"] == "recurso_no_encontrado"

    with pytest.raises(BackendRequestError) as error:
        client.get_neighbors("no-existe")

    assert error.value.codigo_error == "indice_no_disponible"


def test_invalid_neighbour_parameter_is_rejected(simulator):
    for vecinos in (2, -1, "dos"):
        estado, cuerpo = simulator.atender(
            "GET",
            "/conocimiento/chunks/HTM240-MAN-001@1.1_p1_man_001_02",
            parametros={"vecinos": vecinos},
        )

        assert estado == 422
        assert cuerpo["codigo"] == "entrada_invalida"


def test_simulated_timeouts_reach_the_client_as_tiempo_agotado(simulator):
    client = BackendAPIClient(
        base_url="http://backend.simulado",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator, timeout=True),
        timeout=2,
    )

    with pytest.raises(BackendRequestError) as exc_info:
        client.search_lexical(text="batería")
    assert exc_info.value.codigo_error == "tiempo_agotado"

    with pytest.raises(BackendRequestError) as error:
        client.get_chunk("HTM240-MAN-001@1.1_p1_man_001_02")

    assert error.value.codigo_error == "tiempo_agotado"


def test_forced_errors_are_served_once_and_in_order(simulator):
    simulator.forzar_error(503, "indice_no_disponible")
    simulator.forzar_error(504, "tiempo_agotado")

    assert simulator.atender("GET", "/conocimiento/info")[0] == 503
    assert simulator.atender("GET", "/conocimiento/info")[0] == 504
    assert simulator.atender("GET", "/conocimiento/info")[0] == 200


def test_info_and_catalogs(simulator, client):
    info = simulator.atender("GET", "/conocimiento/info")[1]

    assert info["n_chunks"] == len(simulator.chunks)
    assert info["dimensiones"] == 1024
    assert info["tokenizador"]

    estado, codigos = simulator.atender("GET", "/catalogos/codigos")
    assert estado == 200
    assert codigos["codigos"]

    estado, cuerpo = simulator.atender("GET", "/catalogos/inexistente")
    assert estado == 404
    assert cuerpo["codigo"] == "recurso_no_encontrado"


def test_version_filter_agrees_with_the_client_filter(chunks):
    for version in ("V1.0", "V1.1", "V2.0"):
        simulados = {
            resultado["chunk_id"]
            for resultado in BackendSimulator(chunks).post_lexica(
                {"texto": "el la de", "filtros": {"version": version}, "k": 200}
            )["resultados"]
        }

        esperados = {
            chunk["chunk_id"]
            for chunk in filter_chunks(chunks, {"version": version})
        }

        # La léxica solo devuelve chunks con algún término de la consulta, así
        # que se compara sobre los que sí puntúan en el simulador.
        assert simulados <= esperados or simulados == set()
        for chunk_id in simulados:
            assert chunk_id in esperados


def test_end_to_end_from_lexical_to_vigencia_with_neighbours(simulator, client):
    # Caso 1: Con filtro generico de componente, los vecinos en la seccion se expanden.
    crudo_amplio = client.search_lexical(
        text="HTM-0142",
        filtros={"componente": "bateria"},
        k=5,
    )
    candidatos_amplios = []
    for candidato in parse_lexical_response(crudo_amplio).resultados:
        datos = dataclasses.asdict(candidato.metadatos)
        datos.update(
            {
                "chunk_id": candidato.chunk_id,
                "texto": candidato.texto,
                "score": candidato.score_lexico,
            }
        )
        candidatos_amplios.append(datos)

    resultado_amplio = resolve_retrieval(
        candidatos_amplios,
        {"componente": "bateria"},
        client.get_neighbors,
    )
    assert any(c["es_vecino"] for c in resultado_amplio.candidatos)

    # Caso 2: Con version 'V1.1', el vecino de seccion HTM240-DTC-001@1.0_p1_htm0142_v20
    # pertenece a V2.0 y por tanto es descartado correctamente por los filtros hard.
    crudo = client.search_lexical(
        text="HTM-0142",
        filtros={"version": "V1.1", "componente": "bateria"},
        k=5,
    )
    candidatos = []
    for candidato in parse_lexical_response(crudo).resultados:
        datos = dataclasses.asdict(candidato.metadatos)
        datos.update(
            {
                "chunk_id": candidato.chunk_id,
                "texto": candidato.texto,
                "score": candidato.score_lexico,
            }
        )
        candidatos.append(datos)

    resultado = resolve_retrieval(
        candidatos,
        {"version": "V1.1", "componente": "bateria"},
        client.get_neighbors,
    )

    assert resultado.estado == "suficiente"
    assert resultado.campo_ambiguo is None
    assert resultado.codigo_error is None

    ids = [candidato["chunk_id"] for candidato in resultado.candidatos]
    assert "HTM240-DTC-001@1.0_p1_htm0142" in ids
    assert len(ids) == len(set(ids))

    centros = {
        candidato["chunk_id"] for candidato in candidatos
    }
    assert all(
        candidato["estado_documento"] == "vigente"
        for candidato in resultado.candidatos
        if candidato["chunk_id"] in centros
    )
    # El vecino V2.0 es incompatible con el filtro V1.1 y se descarta conforme a CTR-002
    assert not any(
        candidato["es_vecino"] for candidato in resultado.candidatos
    )


def test_backend_failure_during_neighbour_expansion_becomes_error(
    simulator,
    client,
):
    simulator.forzar_error(503, "indice_no_disponible")

    resultado = resolve_retrieval(
        [
            {
                "chunk_id": "HTM240-DTC-001@1.0_p1_htm0142",
                "texto": "HTM-0142",
                "documento": "HTM240-DTC-001",
                "seccion": "HTM-0142",
                "pagina": 1,
                "versiones": ["V1.0", "V1.1"],
                "componente": "bateria",
                "tipo_documento": "diagnostico",
                "obsoleto": False,
                "sustituido_por": None,
                "vigente_para": [],
                "fecha_revision": "2025-09-18",
                "orden_en_seccion": 1,
                "version_documento": "1.0",
                "afectado_por": [],
                "ids_referenciados": ["HTM-0142"],
            }
        ],
        {"version": "V1.1"},
        client.get_neighbors,
    )

    assert resultado.estado == "error"
    assert resultado.codigo_error == "indice_no_disponible"
    assert resultado.candidatos == []


def test_build_app_exposes_ctr002_over_http(simulator):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    cliente = fastapi_testclient.TestClient(build_app(simulator))

    info = cliente.get("/conocimiento/info")
    assert info.status_code == 200
    assert info.json()["n_chunks"] == len(simulator.chunks)

    invalida = cliente.post(
        "/conocimiento/vectorial",
        json={"vector": [0.0] * 3, "k": 5},
    )
    assert invalida.status_code == 400
    assert invalida.json()["codigo"] == "peticion_invalida"

    chunk = cliente.get(
        "/conocimiento/chunks/HTM240-MAN-001@1.1_p1_man_001_02",
        params={"vecinos": 1},
    )
    assert chunk.status_code == 200
    assert len(chunk.json()["vecinos"]) == 3
