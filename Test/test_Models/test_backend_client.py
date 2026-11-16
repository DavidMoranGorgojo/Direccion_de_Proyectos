from Agents.Agent_2.src.clients.backend import BackendAPIClient
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

    def post(self, url, *, json, timeout):
        self.calls.append({
            "url": url,
            "json": json,
            "timeout": timeout,
        })
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