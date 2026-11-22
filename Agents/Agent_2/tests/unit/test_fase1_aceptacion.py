"""Pruebas funcionales de aceptación y regresión para la Fase 1 del Pipeline de Agente 2.

Cubre exhaustivamente:
- F01: Inicialización diferida y reutilizable de BGE-M3.
- F02: Carga, inferencia real y umbral del reranker, y gestión de fallos.
- F06 y F09: Interfaz contractual CTR-004 (texto_preprocesado y evidencias).
- F07: Validación estricta y exhaustiva de entradas.
- F12: Prefijo obligatorio 'query: ' de BGE-M3 en búsquedas vectoriales.
- F14: Validación del modelo e índice devueltos por Backend.
- Recorrido completo E2E de aceptación CTR-004.
"""

import math
from unittest.mock import MagicMock
import pytest

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client, get_bge_m3_client, QUERY_PREFIX
from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline, recuperar_evidencias
from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
from Agents.agente1.core import normalizar_respuesta_agente2


@pytest.fixture
def dataset_prueba():
    return [
        {
            "chunk_id": "HTM240-MAN-001@1.1_p10_culata",
            "texto": "El par de apriete de los tornillos de la culata es de 40 Nm más 90 grados.",
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
            "chunk_id": "HTM240-MAN-001@1.1_p11_culata_paso2",
            "texto": "Comprobar la planeidad del bloque motor antes de montar la junta.",
            "documento": "HTM240-MAN-001",
            "seccion": "Culata",
            "pagina": 11,
            "versiones": ["V1.0", "V1.1"],
            "componente": "refrigeracion",
            "tipo_documento": "manual",
            "obsoleto": False,
            "sustituido_por": None,
            "vigente_para": ["V1.0", "V1.1"],
            "fecha_revision": "2025-09-18",
            "orden_en_seccion": 2,
            "version_documento": "1.0",
            "afectado_por": [],
            "ids_referenciados": ["CMP-01"],
        },
    ]


class MockBgeEncoder:
    def __init__(self):
        self.texts_received = []

    def encode(self, texts, **kwargs):
        self.texts_received.extend(texts)
        return {"dense_vecs": [[0.05] * 1024 for _ in texts]}


class MockRerankerModel:
    def __init__(self, scores=None):
        self.scores = scores if scores is not None else [0.88, 0.40]
        self.pairs_received = []

    def predict(self, pairs):
        self.pairs_received.extend(pairs)
        return self.scores[: len(pairs)]


# ---------------------------------------------------------------------------
# F01 y F12: BGE-M3 y Prefijo Obligatorio
# ---------------------------------------------------------------------------

def test_f01_bge_m3_cliente_y_prefijo():
    """F01 & F12: Comprueba codificación con prefijo obligatorio y dimensión."""
    encoder = MockBgeEncoder()
    client = BgeM3Client(encoder)

    vec = client.encode_query("consulta prueba")
    assert len(vec) == 1024
    assert encoder.texts_received[0].startswith(QUERY_PREFIX)
    assert not encoder.texts_received[0].startswith(QUERY_PREFIX + QUERY_PREFIX)


def test_f12_prefijo_no_se_duplica_si_ya_presente():
    """F12: Si el texto ya tiene 'query: ', no se antepone dos veces."""
    encoder = MockBgeEncoder()
    client = BgeM3Client(encoder)

    client.encode_query("query: texto ya prefijado")
    assert encoder.texts_received[0] == "query: texto ya prefijado"


# ---------------------------------------------------------------------------
# F06 y F09: Interfaz Contractual CTR-004
# ---------------------------------------------------------------------------

def test_f06_texto_preprocesado_como_entrada_contractual(dataset_prueba):
    """F06: La entrada contractual 'texto_preprocesado' es aceptada prioritariamente."""
    simulator = BackendSimulator(dataset_prueba)
    backend = BackendAPIClient("http://backend.test", simulator.modelo_embeddings, session=SimulatedSession(simulator))
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=BgeM3Client(MockBgeEncoder()))

    entrada_ctr004 = {
        "texto_preprocesado": "par de apriete culata",
        "filtros": {"version": "V1.1"},
        "opciones": {"top_k": 2},
    }

    resp = pipeline.procesar_consulta(entrada_ctr004)
    assert resp["estado"] in {"suficiente", "vigente"}
    assert "evidencias" in resp
    assert len(resp["evidencias"]) > 0


def test_f09_estructura_resultados_ctr004(dataset_prueba):
    """F09: resultados/metadatos sigue CTR-004 y A1 conserva su adaptador."""
    simulator = BackendSimulator(dataset_prueba)
    backend = BackendAPIClient("http://backend.test", simulator.modelo_embeddings, session=SimulatedSession(simulator))
    reranker = MockRerankerModel([0.92, 0.85])
    pipeline = Agent2Pipeline(
        backend_client=backend,
        embedding_client=BgeM3Client(MockBgeEncoder()),
        reranker_model=reranker,
        threshold=0.5,
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "culata 40 Nm"})
    assert "evidencias" in resp
    assert "resultados" in resp

    primer_resultado = resp["resultados"][0]
    assert "chunk_id" in primer_resultado
    assert "score_final" in primer_resultado
    assert "texto" in primer_resultado
    assert "metadatos" in primer_resultado
    assert isinstance(primer_resultado["score_final"], float)
    assert primer_resultado["score_final"] == 0.92  # Procede del reranker real

    # Metadatos completos
    meta = primer_resultado["metadatos"]
    for campo in ("documento", "seccion", "pagina", "versiones", "componente", "tipo_documento", "obsoleto"):
        assert campo in meta


# ---------------------------------------------------------------------------
# F07: Validación Estricta de Entradas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "entrada_invalida,codigo_esperado",
    [
        (None, "entrada_invalida"),
        ([], "entrada_invalida"),
        ("no es json", "entrada_invalida"),
        ({"texto_preprocesado": 12345}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "filtros": "no es dict"}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": "no es dict"}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"top_k": 0}}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"top_k": -5}}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"top_k": "5"}}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"top_k": True}}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"incluir_obsoletos": "false"}}, "entrada_invalida"),
        ({"texto_preprocesado": "valido", "opciones": {"incluir_obsoletos": 1}}, "entrada_invalida"),
    ],
)
def test_f07_entradas_invalidas_rechazadas_controladamente(entrada_invalida, codigo_esperado):
    resp = recuperar_evidencias(entrada_invalida)
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == codigo_esperado
    assert resp["evidencias"] == []
    assert resp["evidencias"] == []


def test_f07_texto_vacio_devuelve_sin_evidencia():
    for vacio in ("", "   ", "\n\t"):
        resp = recuperar_evidencias({"texto_preprocesado": vacio})
        assert resp["estado"] == "sin_evidencia"
        assert resp["evidencias"] == []


# ---------------------------------------------------------------------------
# F14: Validación de Modelo e Índice
# ---------------------------------------------------------------------------

def test_f14_modelo_incompatible_debe_devolver_error():
    """F14: Si el backend anuncia un modelo incompatible, debe propagarse modelo_incompatible."""
    class FakeBackendWithIncompatibleModel:
        model_embeddings = "BAAI/bge-m3"
        def search_vector(self, **kwargs):
            return {
                "indice": {"version": "1.0", "modelo_embeddings": "modelo-totalmente-incompatible"},
                "resultados": []
            }
        def search_lexical_candidates(self, **kwargs):
            return MagicMock(resultados=[])

    pipeline = Agent2Pipeline(
        backend_client=FakeBackendWithIncompatibleModel(),
        embedding_client=BgeM3Client(MockBgeEncoder()),
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta test"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "modelo_incompatible"
    assert "incompatible" in resp["mensaje_error"].lower()


# ---------------------------------------------------------------------------
# F02: Carga, Reranker Real y Gestión de Errores
# ---------------------------------------------------------------------------

def test_f02_reranker_obligatorio_ausente_devuelve_error():
    """F02: Si require_reranker=True y el modelo no está disponible, reporta error estándar."""
    backend_mock = MagicMock()
    backend_mock.model_embeddings = "BAAI/bge-m3"
    pipeline = Agent2Pipeline(
        backend_client=backend_mock,
        embedding_client=BgeM3Client(MockBgeEncoder()),
        reranker_model=None,
        require_reranker=True,
    )

    # El mock de backend devuelve candidatos válidos
    backend_mock.search_vector.return_value = {
        "indice": {"version": "1.0", "modelo_embeddings": "BAAI/bge-m3"},
        "resultados": [
            {
                "chunk_id": "c1",
                "texto": "texto 1",
                "score": 0.9,
                "documento": "D1", "seccion": "S1", "pagina": 1,
                "versiones": ["V1.0"], "componente": "motor", "tipo_documento": "manual",
                "obsoleto": False, "sustituido_por": None, "vigente_para": ["V1.0"],
                "fecha_revision": "2025-01-01", "orden_en_seccion": 1,
                "version_documento": "1.0", "afectado_por": [], "ids_referenciados": []
            }
        ]
    }
    backend_mock.search_lexical_candidates.return_value = MagicMock(
        indice=MagicMock(version="1.0", modelo_embeddings="BAAI/bge-m3"), resultados=[]
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    # No debe degradar silenciosamente a puntuaciones RRF como rerank_score
    # Sino reportar servicio_no_disponible si el reranker obligatorio no está
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "servicio_no_disponible"


def test_f02_fallo_durante_inferencia_reranker_reporta_error():
    """F02: Si el reranker lanza una excepción durante predict(), se propaga error controlado."""
    class FailingReranker:
        def predict(self, pairs):
            raise RuntimeError("CUDA Out of Memory simulado en Reranker")

    backend_mock = MagicMock()
    backend_mock.model_embeddings = "BAAI/bge-m3"
    backend_mock.search_vector.return_value = {
        "indice": {"version": "1.0", "modelo_embeddings": "BAAI/bge-m3"},
        "resultados": [
            {
                "chunk_id": "c1", "texto": "texto 1", "score": 0.9,
                "documento": "D1", "seccion": "S1", "pagina": 1,
                "versiones": ["V1.0"], "componente": "motor", "tipo_documento": "manual",
                "obsoleto": False, "sustituido_por": None, "vigente_para": ["V1.0"],
                "fecha_revision": "2025-01-01", "orden_en_seccion": 1,
                "version_documento": "1.0", "afectado_por": [], "ids_referenciados": []
            }
        ]
    }
    backend_mock.search_lexical_candidates.return_value = MagicMock(
        indice=MagicMock(version="1.0", modelo_embeddings="BAAI/bge-m3"), resultados=[]
    )

    pipeline = Agent2Pipeline(
        backend_client=backend_mock,
        embedding_client=BgeM3Client(MockBgeEncoder()),
        reranker_model=FailingReranker(),
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "servicio_no_disponible"
    assert "reranking" in resp["mensaje_error"].lower()


# ---------------------------------------------------------------------------
# Recorrido Funcional Completo E2E (Aceptación de la Fase 1)
# ---------------------------------------------------------------------------

def test_recorrido_completo_e2e_aceptacion(dataset_prueba):
    """
    Recorrido completo:
    Entrada pública CTR-004
    → Inicialización de encoder
    → Generación del vector
    → Llamadas simuladas contractuales a Backend
    → Parseo de respuestas
    → Fusión RRF
    → Reranking con modelo simulado
    → Aplicación del umbral
    → Construcción de evidencias
    → Respuesta CTR-004
    """
    simulator = BackendSimulator(dataset_prueba)
    backend = BackendAPIClient(
        base_url="http://backend.test",
        model_embeddings=simulator.modelo_embeddings,
        session=SimulatedSession(simulator),
        timeout=2,
    )
    encoder = MockBgeEncoder()
    reranker = MockRerankerModel([0.95, 0.45])

    pipeline = Agent2Pipeline(
        backend_client=backend,
        embedding_client=BgeM3Client(encoder),
        reranker_model=reranker,
        threshold=0.70,  # Conserva el primer chunk (0.95) y descarta el segundo (0.45)
    )

    consulta_formal = {
        "texto_preprocesado": "apriete de culata en V1.1",
        "filtros": {"version": "V1.1", "componente": "refrigeracion"},
        "opciones": {"top_k": 5, "incluir_obsoletos": False},
    }

    resultado = pipeline.procesar_consulta(consulta_formal)

    # 1. Comprobaciones de Estado y Citas
    assert resultado["estado"] in {"suficiente", "vigente"}
    assert len(resultado["evidencias"]) >= 1
    ev = resultado["evidencias"][0]

    # 2. Score procede de la inferencia real del reranker
    assert ev["score_final"] == 0.95

    # 3. Metadatos íntegros
    meta = ev["metadata"]
    assert meta["documento"] == "HTM240-MAN-001"
    assert meta["seccion"] == "Culata"
    assert meta["pagina"] == 10
    assert meta["componente"] == "refrigeracion"
    assert "V1.1" in meta["versiones"]

    # 4. Compatibilidad con Agente 1
    normalizado_a1 = normalizar_respuesta_agente2(resultado)
    assert normalizado_a1["estado"] in {"suficiente", "vigente"}
    assert len(normalizado_a1["evidencias"]) >= 1
    assert normalizado_a1["evidencias"][0]["chunk_id"] == ev["chunk_id"]

    # 5. Métricas estructuradas presentes
    assert "tiempo_total_ms" in resultado["metricas"]
    assert "tiempo_embedding_ms" in resultado["metricas"]
    assert "tiempo_backend_ms" in resultado["metricas"]
    assert resultado["metricas"]["superan_umbral"] == 1
    assert resultado["metricas"]["descartados_umbral"] == 1
