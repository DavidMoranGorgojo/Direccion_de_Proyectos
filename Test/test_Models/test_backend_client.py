from Agents.Agent_2.src.clients.backend import BackendAPIClient, ctr002_filters
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.lexical_parser import LexicalContractError
import pytest
import requests

class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, json, timeout, headers=None):
        call = {
            "url": url,
            "json": json,
            "timeout": timeout,
        }
        if headers is not None:
            call["headers"] = headers
        self.calls.append(call)
        return self.response


def test_vector_search_sends_ctr002_request_and_preserves_response():
    response_body = {
        "indice": {
            "version": "v1.0-bd",
            "modelo_embeddings": "BAAI/bge-m3",
        },
        "resultados": [
            {
                "chunk_id": "c45",
                "score": 0.8324,
                "texto": "Fragmento de prueba",
            }
        ],
    }
    session = FakeSession(FakeResponse(response_body))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    vector = [0.0] * 1024
    filtros = {
        "version": "V1.1",
        "componente": "refrigeracion",
    }

    result = client.search_vector(vector=vector, filtros=filtros, k=30)

    assert session.calls == [{
        "url": "http://backend.test/conocimiento/vectorial",
        "json": {
            "vector": vector,
            "modelo_embeddings": "BAAI/bge-m3",
            "filtros": filtros,
            "k": 30,
        },
        "timeout": 2,
    }]
    assert result == response_body
    assert "score" in result["resultados"][0]
    assert "score_vectorial" not in result["resultados"][0]

def test_lexical_search_sends_plain_text_and_preserves_common_response():
    response_body = {
        "indice": {
            "version": "v1.0-bd",
            "modelo_embeddings": "BAAI/bge-m3",
        },
        "resultados": [
            {
                "chunk_id": "c45",
                "score": 4.25,
                "texto": "Avería HTM-0142",
            }
        ],
    }
    session = FakeSession(FakeResponse(response_body))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    texto = "Fallo HTM-0142 en V1.1"
    filtros = {
        "version": "V1.1",
        "componente": "refrigeracion",
    }

    result = client.search_lexical(text=texto, filtros=filtros, k=30)

    assert session.calls == [{
        "url": "http://backend.test/conocimiento/lexica",
        "json": {
            "texto": texto,
            "filtros": filtros,
            "k": 30,
        },
        "timeout": 2,
    }]
    assert result == response_body
    assert "HTM-0142" in session.calls[0]["json"]["texto"]
    assert "score" in result["resultados"][0]

@pytest.mark.parametrize("status_code", [409, 503])
def test_vector_search_propagates_backend_http_errors(status_code):
    session = FakeSession(
        FakeResponse({}, status_code=status_code)
    )
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    with pytest.raises(requests.HTTPError):
        client.search_vector(
            vector=[0.0] * 1024,
            filtros={"version": "V1.1"},
            k=30,
        )


def test_client_strips_trailing_slash_from_base_url():
    session = FakeSession(FakeResponse({"resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test/",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    client.search_vector(vector=[0.0] * 1024, k=1)

    assert session.calls[0]["url"] == (
        "http://backend.test/conocimiento/vectorial"
    )


def test_client_accepts_numpy_like_vector():
    class NumpyLikeVector:
        def tolist(self):
            return [0.0] * 1024

    session = FakeSession(FakeResponse({"resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    client.search_vector(vector=NumpyLikeVector(), k=1)

    assert session.calls[0]["json"]["vector"] == [0.0] * 1024


def test_vector_search_rejects_wrong_dimension_without_http_call():
    session = FakeSession(FakeResponse({"resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    with pytest.raises(ValueError, match="1024"):
        client.search_vector(vector=[0.0] * 10)

    assert session.calls == []


def test_lexical_search_rejects_empty_text_without_http_call():
    session = FakeSession(FakeResponse({"resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    with pytest.raises(ValueError):
        client.search_lexical(text="   ")

    assert session.calls == []


def test_search_methods_use_empty_filters_by_default():
    session = FakeSession(FakeResponse({"resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    client.search_vector(vector=[0.0] * 1024)
    client.search_lexical(text="HTM-0142")

    assert session.calls[0]["json"]["filtros"] == {}
    assert session.calls[1]["json"]["filtros"] == {}
    assert session.calls[1]["json"]["texto"] == "HTM-0142"


def test_lexical_search_propagates_backend_http_errors():
    session = FakeSession(FakeResponse({}, status_code=503))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    with pytest.raises(requests.HTTPError):
        client.search_lexical(text="HTM-0142")


def test_search_lexical_candidates_requests_and_parses():
    response_body = {
        "indice": {
            "version": "v1.0-bd",
            "modelo_embeddings": "BAAI/bge-m3",
        },
        "resultados": [
            {
                "chunk_id": "HTM240-DTC-001@1.0_p1_htm0142",
                "score": 4.25,
                "texto": "HTM-0142: revisar CMP-17-B.",
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
                "ids_referenciados": ["CMP-17", "HTM-0142"],
            }
        ],
    }
    session = FakeSession(FakeResponse(response_body))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    parsed = client.search_lexical_candidates(
        text="HTM-0142",
        filtros={"version": "V1.1"},
    )

    assert session.calls[0]["url"] == (
        "http://backend.test/conocimiento/lexica"
    )
    assert session.calls[0]["json"]["texto"] == "HTM-0142"
    assert session.calls[0]["json"]["k"] == 30
    assert parsed.resultados[0].chunk_id == (
        "HTM240-DTC-001@1.0_p1_htm0142"
    )
    assert parsed.resultados[0].metadatos.ids_referenciados == [
        "CMP-17",
        "HTM-0142",
    ]


def test_search_lexical_candidates_propagates_parse_errors():
    response_body = {
        "indice": {
            "version": "v1.0-bd",
            "modelo_embeddings": "BAAI/bge-m3",
        },
        "resultados": [{}],
    }
    session = FakeSession(FakeResponse(response_body))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )

    with pytest.raises(LexicalContractError):
        client.search_lexical_candidates(text="HTM-0142")


class FakeGetSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, *, params, timeout, headers=None):
        call = {
            "url": url,
            "params": params,
            "timeout": timeout,
        }
        if headers is not None:
            call["headers"] = headers
        self.calls.append(call)

        if self.error is not None:
            raise self.error

        return self.response


def make_backend_chunk(chunk_id, **overrides):
    chunk = {
        "chunk_id": chunk_id,
        "texto": f"Texto de {chunk_id}",
        "documento": "HTM240-PRC-003",
        "seccion": "Corriente",
        "pagina": 1,
        "versiones": ["V1.0", "V1.1"],
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


def make_chunk_payload(chunk_id, vecinos=None):
    return {
        "indice": {"version": "v1.0-bd"},
        "chunk": make_backend_chunk(chunk_id, orden_en_seccion=2),
        "vecinos": [] if vecinos is None else vecinos,
    }


def make_backend_client(session):
    return BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
    )


def test_get_chunk_requests_neighbors_and_validates_response():
    chunk_id = "HTM240-PRC-003@1.0_p1_sustituido_corriente_bomba_3_5A"
    neighbor = make_backend_chunk(
        "HTM240-PRC-003@1.0_p1_vecino",
        orden_en_seccion=1,
    )
    session = FakeGetSession(
        FakeResponse(make_chunk_payload(chunk_id, [neighbor]))
    )

    result = make_backend_client(session).get_chunk(chunk_id, vecinos=1)

    assert session.calls == [{
        "url": (
            "http://backend.test/conocimiento/chunks/"
            "HTM240-PRC-003%401.0_p1_sustituido_corriente_bomba_3_5A"
        ),
        "params": {"vecinos": 1},
        "timeout": 2,
    }]
    assert result["indice"] == {"version": "v1.0-bd"}
    assert result["chunk"]["chunk_id"] == chunk_id
    assert result["vecinos"] == [neighbor]


def test_get_neighbors_returns_only_the_neighbors():
    chunk_id = "HTM240-PRC-003@1.0_p1_centro"
    neighbor = make_backend_chunk(
        "HTM240-PRC-003@1.0_p1_vecino",
        orden_en_seccion=1,
    )
    session = FakeGetSession(
        FakeResponse(make_chunk_payload(chunk_id, [neighbor]))
    )

    assert make_backend_client(session).get_neighbors(chunk_id) == [neighbor]


def test_get_chunk_can_request_zero_neighbors():
    chunk_id = "HTM240-PRC-003@1.0_p1_centro"
    session = FakeGetSession(FakeResponse(make_chunk_payload(chunk_id)))

    result = make_backend_client(session).get_chunk(chunk_id, vecinos=0)

    assert session.calls[0]["params"] == {"vecinos": 0}
    assert result["vecinos"] == []


def test_get_chunk_accepts_a_null_revision_date():
    chunk_id = "HTM240-PRC-003@1.0_p1_centro"
    center = make_backend_chunk(chunk_id, fecha_revision=None)
    neighbor = make_backend_chunk(
        "HTM240-PRC-003@1.0_p1_vecino",
        fecha_revision=None,
        orden_en_seccion=1,
    )
    payload = {
        "indice": {"version": "v1.0-bd"},
        "chunk": center,
        "vecinos": [neighbor],
    }
    session = FakeGetSession(FakeResponse(payload))

    result = make_backend_client(session).get_chunk(chunk_id)

    assert result["chunk"]["fecha_revision"] is None
    assert result["vecinos"][0]["fecha_revision"] is None


@pytest.mark.parametrize(
    ("status_code", "payload", "expected_code"),
    [
        (
            503,
            {"detail": {"codigo": "indice_no_disponible"}},
            "indice_no_disponible",
        ),
        (404, {"detail": {"codigo": "recurso_no_encontrado"}}, "indice_no_disponible"),
        (422, {"detail": {"codigo": "entrada_invalida"}}, "entrada_invalida"),
        (500, {"codigo_error": "modelo_no_disponible"}, "modelo_no_disponible"),
        (504, {}, "tiempo_agotado"),
        (400, {"codigo": "peticion_invalida"}, "entrada_invalida"),
        (400, {"codigo": "filtro_invalido"}, "entrada_invalida"),
        (503, {"detail": {"codigo": "codigo_raro"}}, "servicio_no_disponible"),
    ],
)
def test_get_chunk_maps_http_errors_to_standard_codes(
    status_code,
    payload,
    expected_code,
):
    session = FakeGetSession(FakeResponse(payload, status_code=status_code))

    with pytest.raises(BackendRequestError) as error:
        make_backend_client(session).get_chunk(
            "HTM240-PRC-003@1.0_p1_centro"
        )

    assert error.value.codigo_error == expected_code


def test_get_chunk_maps_timeouts():
    session = FakeGetSession(error=requests.Timeout())

    with pytest.raises(BackendRequestError) as error:
        make_backend_client(session).get_chunk(
            "HTM240-PRC-003@1.0_p1_centro"
        )

    assert error.value.codigo_error == "tiempo_agotado"


def test_get_chunk_maps_connection_errors():
    session = FakeGetSession(error=requests.ConnectionError())

    with pytest.raises(BackendRequestError) as error:
        make_backend_client(session).get_chunk(
            "HTM240-PRC-003@1.0_p1_centro"
        )

    assert error.value.codigo_error == "servicio_no_disponible"


@pytest.mark.parametrize(
    "payload",
    [
        "no es un objeto",
        {"chunk": make_backend_chunk("x"), "vecinos": []},
        {"indice": {"version": ""}, "chunk": make_backend_chunk("x"), "vecinos": []},
        {"indice": {"version": "v1"}, "chunk": None, "vecinos": []},
        {"indice": {"version": "v1"}, "chunk": make_backend_chunk("x"), "vecinos": None},
        {"indice": {"version": "v1"}, "chunk": make_backend_chunk("otro"), "vecinos": []},
        {
            "indice": {"version": "v1"},
            "chunk": make_backend_chunk("x"),
            "vecinos": [make_backend_chunk("y", pagina=0)],
        },
        {
            "indice": {"version": "v1"},
            "chunk": make_backend_chunk("x"),
            "vecinos": [make_backend_chunk("y", seccion="Otra")],
        },
        {
            "indice": {"version": "v1"},
            "chunk": make_backend_chunk("x"),
            "vecinos": [
                make_backend_chunk("y"),
                make_backend_chunk("y", orden_en_seccion=2),
            ],
        },
    ],
)
def test_get_chunk_rejects_invalid_payloads(payload):
    session = FakeGetSession(FakeResponse(payload))

    with pytest.raises(BackendRequestError) as error:
        make_backend_client(session).get_chunk("x")

    assert error.value.codigo_error == "servicio_no_disponible"


def test_get_chunk_rejects_invalid_arguments():
    client = make_backend_client(FakeGetSession(FakeResponse({})))

    for chunk_id in ("", "   ", None, 7):
        with pytest.raises(ValueError):
            client.get_chunk(chunk_id)

    for vecinos in (2, -1, True, "1", 1.0):
        with pytest.raises(ValueError):
            client.get_chunk("HTM240-PRC-003@1.0_p1_centro", vecinos=vecinos)


def test_ctr002_filters_keep_only_the_contract_fields():
    assert ctr002_filters(None) == {}
    assert ctr002_filters({}) == {}
    assert ctr002_filters(
        {"version": "V1.1", "componente": "bateria"}
    ) == {"version": "V1.1", "componente": "bateria"}

    # Los filtros locales del Agente 2 no viajan al Backend (§5.1).
    assert ctr002_filters(
        {
            "version": "V1.1",
            "codigos": ["HTM-0142"],
            "incluir_obsoletos": False,
        }
    ) == {"version": "V1.1"}

    # Un valor vacío equivale a no restringir.
    assert ctr002_filters(
        {"version": "   ", "componente": "", "tipo_documento": ""}
    ) == {}


def test_ctr002_filters_admit_a_single_document_type():
    assert ctr002_filters({"tipo_documento": "manual"}) == {
        "tipo_documento": "manual"
    }
    assert ctr002_filters({"tipo_documento": ["manual"]}) == {
        "tipo_documento": "manual"
    }
    assert ctr002_filters({"tipo_documento": ["", "manual", "manual"]}) == {
        "tipo_documento": "manual"
    }

    # CTR-002 solo admite un tipo por petición: no se elige uno al azar.
    with pytest.raises(ValueError):
        ctr002_filters({"tipo_documento": ["manual", "boletin"]})


def test_ctr002_filters_reject_invalid_values():
    with pytest.raises(TypeError):
        ctr002_filters("filtros")
    with pytest.raises(TypeError):
        ctr002_filters({"version": 1.1})
    with pytest.raises(TypeError):
        ctr002_filters({"componente": 3})
    with pytest.raises(TypeError):
        ctr002_filters({"tipo_documento": 5})
    with pytest.raises(TypeError):
        ctr002_filters({"tipo_documento": [5]})


def test_searches_send_the_filters_normalised_to_ctr002():
    session = FakeSession(FakeResponse({"indice": {}, "resultados": []}))
    client = make_backend_client(session)

    client.search_lexical(
        text="batería",
        filtros={
            "version": "V1.1",
            "componente": "bateria",
            "tipo_documento": ["manual"],
            "codigos": ["HTM-0142"],
        },
    )

    assert session.calls[0]["json"]["filtros"] == {
        "version": "V1.1",
        "componente": "bateria",
        "tipo_documento": "manual",
    }

    client.search_vector(vector=[0.0] * 1024, filtros={"incluir_obsoletos": False})

    assert session.calls[1]["json"]["filtros"] == {}


def test_searches_refuse_to_relax_several_document_types():
    session = FakeSession(FakeResponse({"indice": {}, "resultados": []}))
    client = make_backend_client(session)

    with pytest.raises(ValueError):
        client.search_lexical(
            text="batería",
            filtros={"tipo_documento": ["manual", "boletin"]},
        )

    assert session.calls == []


def test_searches_send_the_service_bearer_when_a_token_is_configured():
    session = FakeSession(FakeResponse({"indice": {}, "resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
        token="token-de-servicio",
    )

    client.search_lexical(text="batería")
    client.search_vector(vector=[0.0] * 1024)

    assert session.calls[0]["headers"] == {
        "Authorization": "Bearer token-de-servicio"
    }
    assert session.calls[1]["headers"] == {
        "Authorization": "Bearer token-de-servicio"
    }


def test_searches_omit_the_header_when_there_is_no_token():
    session = FakeSession(FakeResponse({"indice": {}, "resultados": []}))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
        token="",
    )

    client.search_lexical(text="batería")

    assert "headers" not in session.calls[0]


def test_get_chunk_sends_the_service_bearer_when_a_token_is_configured():
    chunk_id = "HTM240-PRC-003@1.0_p1_sustituido_corriente_bomba_3_5A"
    session = FakeGetSession(FakeResponse(make_chunk_payload(chunk_id)))
    client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=session,
        timeout=2,
        token="token-de-servicio",
    )

    client.get_chunk(chunk_id)

    assert session.calls[0]["headers"] == {
        "Authorization": "Bearer token-de-servicio"
    }
