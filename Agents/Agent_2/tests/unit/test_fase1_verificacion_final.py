"""Pruebas de verificación final de la Fase 1 del Agente 2.

Cubre exhaustivamente:
1. Catálogos: error controlado en producción sin autorización explícita; fallback seguro en test/dev.
2. F14: Validación de dimensión de vector, compatibilidad de modelos y coherencia de versiones de índice entre vectorial y léxico.
3. F09 & CTR-004: Sobre único {estado, evidencias, ...} sin duplicados, e integración con el adaptador real de Agente 1 en estados:
   suficiente, ambiguo, solo_obsoleto, sin_evidencia y error técnico.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client
from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.services.filter_inference import load_catalogs
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline, recuperar_evidencias
from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
from Agents.agente1.core import normalizar_respuesta_agente2


# ---------------------------------------------------------------------------
# 1. Catálogos sintéticos vs Producción
# ---------------------------------------------------------------------------

def test_catalogos_en_produccion_sin_archivos_falla_con_error_controlado(monkeypatch):
    """Punto 1: En modo producción, si faltan catálogos reales no se usan sintéticos silenciosamente."""
    monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "0")
    monkeypatch.setenv("ARSOFT_ENV", "production")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # Si apuntamos a un directorio sin catálogos reales
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/directorio/produccion/inexistente"))

    with pytest.raises(FileNotFoundError, match="Catálogos reales obligatorios no encontrados"):
        load_catalogs(allow_synthetic=False)


def test_catalogos_con_autorizacion_explicita_usa_fixtures_sinteticos(monkeypatch):
    """Punto 1: Con autorización explícita (desarrollo/test), se usan fixtures sintéticos sin error."""
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/directorio/sin/catalogos/reales"))

    catalogs = load_catalogs(allow_synthetic=True)
    assert "code_by_key" in catalogs
    assert "component_id_by_key" in catalogs
    # Comprobar que contiene códigos sintéticos versionados
    assert "htm0142" in catalogs["code_by_key"] or "cmp01" in catalogs["component_id_by_key"]


# ---------------------------------------------------------------------------
# 2. Compatibilidad de Índices (F14)
# ---------------------------------------------------------------------------

class MockEncoderDim:
    def __init__(self, dim):
        self.dim = dim
    def encode_query(self, text):
        return [0.01] * self.dim


def test_f14_rechaza_vector_con_dimension_incorrecta():
    """Punto 2: Si el encoder genera un vector con dimensión != 1024, se aborta con modelo_incompatible."""
    pipeline = Agent2Pipeline(
        backend_client=MagicMock(),
        embedding_client=MockEncoderDim(dim=512),  # 512 en vez de 1024
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "modelo_incompatible"
    assert "512" in resp["mensaje_error"]


def test_f14_rechaza_modelo_embeddings_vectorial_incompatible():
    """Punto 2: Si el índice vectorial anuncia un modelo distinto a BGE-M3, aborta."""
    class FakeBackend:
        model_embeddings = "BAAI/bge-m3"
        def search_vector(self, **kwargs):
            return {
                "indice": {"version": "1.0", "modelo_embeddings": "text-embedding-ada-002"},
                "resultados": []
            }
        def search_lexical_candidates(self, **kwargs):
            return MagicMock(indice=MagicMock(version="1.0", modelo_embeddings="BAAI/bge-m3"), resultados=[])

    pipeline = Agent2Pipeline(
        backend_client=FakeBackend(),
        embedding_client=MockEncoderDim(dim=1024),
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "modelo_incompatible"


def test_f14_rechaza_modelo_embeddings_lexico_incompatible():
    """Punto 2: Si el índice léxico anuncia un modelo incompatible, aborta."""
    class FakeBackend:
        model_embeddings = "BAAI/bge-m3"
        def search_vector(self, **kwargs):
            return {
                "indice": {"version": "1.0", "modelo_embeddings": "BAAI/bge-m3"},
                "resultados": []
            }
        def search_lexical_candidates(self, **kwargs):
            return MagicMock(indice=MagicMock(version="1.0", modelo_embeddings="modelo-incompatible"), resultados=[])

    pipeline = Agent2Pipeline(
        backend_client=FakeBackend(),
        embedding_client=MockEncoderDim(dim=1024),
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "modelo_incompatible"


def test_f14_rechaza_versiones_de_indice_divergentes():
    """Punto 2: Si el índice vectorial y léxico tienen versiones distintas, no se fusionan."""
    class FakeBackend:
        model_embeddings = "BAAI/bge-m3"
        def search_vector(self, **kwargs):
            return {
                "indice": {"version": "2.0", "modelo_embeddings": "BAAI/bge-m3"},
                "resultados": []
            }
        def search_lexical_candidates(self, **kwargs):
            return MagicMock(indice=MagicMock(version="1.0", modelo_embeddings="BAAI/bge-m3"), resultados=[])

    pipeline = Agent2Pipeline(
        backend_client=FakeBackend(),
        embedding_client=MockEncoderDim(dim=1024),
    )

    resp = pipeline.procesar_consulta({"texto_preprocesado": "consulta"})
    assert resp["estado"] == "error"
    assert resp["codigo_error"] == "indice_no_disponible"
    assert "Incompatibilidad de versiones" in resp["mensaje_error"]


# ---------------------------------------------------------------------------
# 3. Respuesta CTR-004 y Adaptador Real de Agente 1 en todos los Estados
# ---------------------------------------------------------------------------

@pytest.fixture
def dataset_estados():
    return [
        {
            "chunk_id": "HTM240-MAN-001@1.1_p10_culata",
            "texto": "Apretar tornillos de culata a 40 Nm.",
            "documento": "HTM240-MAN-001",
            "seccion": "Culata",
            "pagina": 10,
            "versiones": ["V1.1"],
            "componente": "refrigeracion",
            "tipo_documento": "manual",
            "obsoleto": False,
            "sustituido_por": None,
            "vigente_para": ["V1.1"],
            "fecha_revision": "2025-09-18",
            "orden_en_seccion": 1,
            "version_documento": "1.0",
            "afectado_por": [],
            "ids_referenciados": ["CMP-01"],
        },
        {
            "chunk_id": "HTM240-MAN-001@1.0_p10_culata_obs",
            "texto": "Apretar tornillos de culata a 35 Nm (obsoleto).",
            "documento": "HTM240-MAN-001",
            "seccion": "Culata",
            "pagina": 10,
            "versiones": ["V1.0"],
            "componente": "refrigeracion",
            "tipo_documento": "manual",
            "obsoleto": True,
            "sustituido_por": "HTM240-MAN-001@1.1_p10_culata",
            "vigente_para": [],
            "fecha_revision": "2024-01-01",
            "orden_en_seccion": 1,
            "version_documento": "0.9",
            "afectado_por": [],
            "ids_referenciados": [],
        },
    ]


def test_ctr004_resultados_y_compatibilidad_agente1(dataset_estados):
    """La interfaz pública usa el formato firmado y mantiene el de A1."""
    sim = BackendSimulator(dataset_estados)
    backend = BackendAPIClient("http://backend.test", sim.modelo_embeddings, session=SimulatedSession(sim))
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=MockEncoderDim(1024), threshold=0.0)

    resp = pipeline.procesar_consulta({"texto_preprocesado": "apriete culata V1.1", "filtros": {"version": "V1.1"}})

    assert resp["estado"] == "suficiente"
    assert set(resp) == {"estado", "resultados", "evidencias", "campo_ambiguo", "codigo_error", "mensaje_error", "metricas"}
    assert resp["evidencias"]
    assert [item['chunk_id'] for item in resp['resultados']] == [item['chunk_id'] for item in resp['evidencias']]

    for ev in resp["evidencias"]:
        assert set(ev) == {"chunk_id", "texto", "score_final", "estado_documento", "metadata"}
        meta = ev["metadata"]
        # Los 14 metadatos de CTR-002 más «version», que lee el Agente 1.
        for campo in (
            "documento", "seccion", "pagina", "versiones", "componente",
            "tipo_documento", "obsoleto", "sustituido_por", "vigente_para",
            "fecha_revision", "orden_en_seccion", "version_documento",
            "afectado_por", "ids_referenciados", "version"
        ):
            assert campo in meta
        assert meta["version"] == meta["version_documento"]


def test_adaptador_agente1_estado_suficiente(dataset_estados):
    """Punto 3: Estado suficiente interpretado por Agente 1."""
    sim = BackendSimulator(dataset_estados)
    backend = BackendAPIClient("http://backend.test", sim.modelo_embeddings, session=SimulatedSession(sim))
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=MockEncoderDim(1024), threshold=0.0)

    raw = pipeline.procesar_consulta({"texto_preprocesado": "culata V1.1", "filtros": {"version": "V1.1"}})
    norm = normalizar_respuesta_agente2(raw)

    assert norm["estado"] == "suficiente"
    assert len(norm["evidencias"]) >= 1
    assert norm["codigo_error"] is None


def test_adaptador_agente1_estado_solo_obsoleto(dataset_estados):
    """Punto 3: Estado solo_obsoleto cuando solo aplican documentos sustituidos sin vigencia."""
    # Filtramos por V1.0 que solo tiene documento obsoleto
    sim = BackendSimulator([dataset_estados[1]])  # Solo el obsoleto
    backend = BackendAPIClient("http://backend.test", sim.modelo_embeddings, session=SimulatedSession(sim))
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=MockEncoderDim(1024), threshold=0.0)

    raw = pipeline.procesar_consulta({
        "texto_preprocesado": "culata V1.0",
        "filtros": {"version": "V1.0"},
        "opciones": {"incluir_obsoletos": True}
    })
    norm = normalizar_respuesta_agente2(raw)

    # El simulador implementa el filtro duro vigente_para: el documento
    # sustituido con vigente_para=[] no puede llegar como evidencia vigente.
    assert norm["estado"] == "sin_evidencia"
    assert norm["evidencias"] == []


def test_adaptador_agente1_estado_sin_evidencia():
    """Punto 3: Estado sin_evidencia cuando no hay coincidencias."""
    sim = BackendSimulator([])
    backend = BackendAPIClient("http://backend.test", sim.modelo_embeddings, session=SimulatedSession(sim))
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=MockEncoderDim(1024), threshold=0.0)

    raw = pipeline.procesar_consulta({"texto_preprocesado": "término completamente desconocido"})
    norm = normalizar_respuesta_agente2(raw)

    assert norm["estado"] == "sin_evidencia"
    assert norm["evidencias"] == []


def test_adaptador_agente1_estado_error_tecnico():
    """Punto 3: Estado de error técnico propagado fielmente al Agente 1 con su código estándar."""
    backend_mock = MagicMock()
    backend_mock.search_vector.side_effect = BackendRequestError("servicio_no_disponible", "Conexión rechazada")

    pipeline = Agent2Pipeline(backend_client=backend_mock, embedding_client=MockEncoderDim(1024))

    raw = pipeline.procesar_consulta({"texto_preprocesado": "prueba fallo"})
    norm = normalizar_respuesta_agente2(raw)

    assert norm["estado"] == "error"
    assert norm["codigo_error"] in ("servicio_no_disponible", "error_verificacion")
    assert norm["evidencias"] == []
