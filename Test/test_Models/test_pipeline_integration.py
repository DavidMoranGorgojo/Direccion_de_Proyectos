"""Pruebas de integración del pipeline completo del Agente 2 y conexión con Agente 1."""

import json
from unittest.mock import MagicMock
import pytest
import requests

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline, recuperar_evidencias
from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
from Agents.agente1.core import Agente1, consultar_asistente, normalizar_respuesta_agente2


class FakeEmbeddingClient:
    """Simulador de BgeM3 para pruebas sin cargar el modelo pesado en CPU."""
    def encode(self, text, use_prefix=True):
        return [0.01] * 1024


@pytest.fixture
def mock_dataset():
    return [
        {
            "chunk_id": "HTM240-MAN-001@1.1_p10_culata",
            "texto": "El par de apriete de la culata es 40 Nm más 90 grados.",
            "documento": "HTM240-MAN-001",
            "seccion": "Culata",
            "pagina": 10,
            "versiones": ["V1.0", "V1.1"],
            "componente": "refrigeracion",
            "tipo_documento": "manual",
            "obsoleto": False,
            "sustituido_por": None,
            "vigente_para": ["V1.0", "V1.1"],
            "fecha_revision": "2025-09-18",
            "orden_en_seccion": 1,
            "version_documento": "1.0",
            "afectado_por": [],
            "ids_referenciados": ["CMP-01"],
        },
        {
            "chunk_id": "HTM240-BOL-002@1.1_p5_bomba",
            "texto": "Sustitución de la bomba de refrigerante a los 60.000 km.",
            "documento": "HTM240-BOL-002",
            "seccion": "Refrigeracion",
            "pagina": 5,
            "versiones": ["V1.1"],
            "componente": "refrigeracion",
            "tipo_documento": "boletin",
            "obsoleto": False,
            "sustituido_por": None,
            "vigente_para": ["V1.1"],
            "fecha_revision": "2026-01-01",
            "orden_en_seccion": 1,
            "version_documento": "1.1",
            "afectado_por": [],
            "ids_referenciados": ["CMP-17"],
        },
    ]


def test_pipeline_e2e_successful_retrieval(mock_dataset):
    simulator = BackendSimulator(mock_dataset)
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=FakeEmbeddingClient(),
        reranker_model=None,
        threshold=0.0,
    )

    query = {
        "texto_busqueda": "par de apriete de la culata en V1.1",
        "filtros": {"version": "V1.1", "componente": "refrigeracion"},
        "opciones": {"top_k": 3},
    }

    resultado = pipeline.procesar_consulta(query)

    assert resultado["estado"] in {"suficiente", "vigente"}
    assert len(resultado["evidencias"]) > 0
    primera = resultado["evidencias"][0]
    assert "culata" in primera["texto"].lower()
    assert "V1.1" in primera["metadata"]["versiones"]
    assert "score" in primera
    assert "rerank_score" in primera


def test_pipeline_handles_backend_timeout():
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings="BAAI/bge-m3",
        session=MagicMock(post=MagicMock(side_effect=requests.Timeout("Timeout")),
                          get=MagicMock(side_effect=requests.Timeout("Timeout"))),
        timeout=1,
    )
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=FakeEmbeddingClient(),
    )

    resultado = pipeline.procesar_consulta({"texto_busqueda": "prueba de fallo"})

    assert resultado["estado"] == "error"
    assert resultado["codigo_error"] == "tiempo_agotado"
    assert resultado["evidencias"] == []


def test_pipeline_rejects_invalid_query_structure():
    assert recuperar_evidencias(None)["estado"] == "error"
    assert recuperar_evidencias({"texto_busqueda": ""})["estado"] == "sin_evidencia"
    assert recuperar_evidencias({"texto_busqueda": "hola", "filtros": "no_dict"})["estado"] == "error"


def test_pipeline_integration_with_agente1(mock_dataset):
    simulator = BackendSimulator(mock_dataset)
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=FakeEmbeddingClient(),
        threshold=0.0,
    )

    def agente2_adapter(query_json):
        return pipeline.procesar_consulta(query_json)

    # Verificamos que normalizar_respuesta_agente2 del Agente 1 acepta el resultado
    query_prueba = {
        "trace_id": "test-trace-1",
        "intencion": "procedimiento",
        "texto_busqueda": "culata V1.1",
        "filtros": {"version": "V1.1"},
        "opciones": {"top_k": 3, "incluir_obsoletos": True},
    }

    raw_a2 = agente2_adapter(query_prueba)
    normalizado = normalizar_respuesta_agente2(raw_a2)

    assert normalizado["estado"] in {"suficiente", "solo_obsoleto", "ambiguo", "sin_evidencia"}
    assert isinstance(normalizado["evidencias"], list)
    if normalizado["evidencias"]:
        ev = normalizado["evidencias"][0]
        assert "chunk_id" in ev
        assert "metadata" in ev
        assert "score" in ev



def test_b01_pipeline_usa_encode_query(mock_dataset):
    """B01: Comprueba que el pipeline utiliza encode_query cuando está disponible."""
    simulator = BackendSimulator(mock_dataset)
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )

    class CustomBgeM3:
        def __init__(self):
            self.encode_query_called = False

        def encode_query(self, text):
            self.encode_query_called = True
            return [0.01] * 1024

    mock_bge = CustomBgeM3()
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=mock_bge,
        threshold=0.0,
    )

    res = pipeline.procesar_consulta({"texto_busqueda": "prueba apriete culata"})
    assert mock_bge.encode_query_called is True
    assert res["estado"] in {"suficiente", "vigente"}


def test_b03_pipeline_sin_reranker_no_descarta_por_escala_rrf(mock_dataset):
    """B03: Cuando no hay reranker activo, no se debe aplicar el umbral de cross-encoder a scores RRF."""
    simulator = BackendSimulator(mock_dataset)
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )
    # RERANK_THRESHOLD suele ser 0.5; los scores RRF son ~0.016.
    # El pipeline debe conservar los candidatos sin descartarlos a 'insuficiente'.
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=FakeEmbeddingClient(),
        reranker_model=None,
        threshold=0.5,  # Umbral alto que eliminaría scores RRF si se compararan directamente
    )

    res = pipeline.procesar_consulta({"texto_busqueda": "culata 40 Nm"})
    assert res["estado"] in {"suficiente", "vigente"}
    assert len(res["evidencias"]) > 0


def test_b02_pipeline_con_reranker_real_utiliza_threshold_y_metricas(mock_dataset):
    """B02: Comprueba uso efectivo del reranker y sus métricas estructuradas."""
    simulator = BackendSimulator(mock_dataset)
    backend_client = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )

    class FakeReranker:
        def predict(self, pairs):
            return [0.95 for _ in pairs]

    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=FakeEmbeddingClient(),
        reranker_model=FakeReranker(),
        threshold=0.6,
    )

    res = pipeline.procesar_consulta({"texto_busqueda": "culata"})
    assert res["estado"] in {"suficiente", "vigente"}
    assert len(res["evidencias"]) > 0
    assert "superan_umbral" in res["metricas"]
    assert res["metricas"]["superan_umbral"] >= 1
