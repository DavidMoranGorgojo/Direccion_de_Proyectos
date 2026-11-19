"""Regresiones de seguridad y contrato encontradas en la auditoría prepublicación.

Estos casos no usan el Backend real ni descargan pesos de modelos.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.services.filter_inference import (
    FIXTURE_CATALOG_DIR, infer_component, infer_filters, load_catalogs, merge_filters,
)
from Agents.Agent_2.src.services.filters import filter_chunks, version_applies
from Agents.Agent_2.src.services.fusion import rrf
from Agents.Agent_2.src.services.vigencia import resolve_retrieval


def _chunk(chunk_id: str, *, component: str = "refrigeracion", version="V1.1") -> dict:
    return {
        "chunk_id": chunk_id, "texto": "Procedimiento de refrigeración",
        "documento": "HTM240-MAN-001", "seccion": "3.2", "pagina": 2,
        "versiones": [version], "componente": component,
        "tipo_documento": "manual", "obsoleto": False,
        "sustituido_por": None, "vigente_para": [version],
        "fecha_revision": "2026-01-01", "orden_en_seccion": 2,
        "version_documento": "1.0", "afectado_por": [],
        "ids_referenciados": [], "rerank_score": 0.91,
    }


def test_filtro_version_sustituida_no_se_relaja():
    chunk = _chunk("c1", version="V1.0")
    chunk.update(obsoleto=True, sustituido_por="c2", vigente_para=["V1.0"],
                 versiones=["V1.0", "V1.1"])
    assert version_applies(chunk, "V1.0")
    assert not version_applies(chunk, "V1.1")
    assert filter_chunks([chunk], {"version": "V1.1"}) == []


def test_filtro_version_actual_prefiere_vigente_para_cuando_existe():
    chunk = _chunk("c1", version="V1.1")
    chunk.update(versiones=["V1.0", "V1.1"], vigente_para=["V1.1"])
    assert not version_applies(chunk, "V1.0")
    assert version_applies(chunk, "V1.1")


@pytest.mark.parametrize("filtros", [
    {"version": "banana"},
    {"componente": "componente-inventado"},
    {"version": "V1.1", "componente": "fantasma"},
    {"tipo_documento": "tipo-no-existente"},
])
def test_filtro_explicito_invalido_se_rechaza(filtros):
    with pytest.raises(ValueError, match="Filtros explícitos no admitidos"):
        merge_filters(filtros, {})


def test_no_inferir_motor_generico_ni_diagnostico_ambiguo():
    assert infer_component("el motor") is None
    assert infer_component("motor de la batería") is None
    assert infer_component("circuito del motor") == "motor"


def test_produccion_no_admite_fixtures_ni_con_flag_explicitamente_activada(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/sin/catalogos/empresa"))
    monkeypatch.setenv("ARSOFT_ENV", "production")
    monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "1")
    with pytest.raises(FileNotFoundError):
        load_catalogs(allow_synthetic=True)
    with pytest.raises(FileNotFoundError):
        load_catalogs(FIXTURE_CATALOG_DIR)


def test_entorno_sin_definir_no_autoriza_fixtures(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/sin/catalogos/empresa"))
    monkeypatch.delenv("ARSOFT_ENV", raising=False)
    monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "1")
    with pytest.raises(FileNotFoundError):
        load_catalogs()


def test_entorno_de_pruebas_carga_catalogo_sintetico_explicito(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/sin/catalogos/empresa"))
    monkeypatch.setenv("ARSOFT_ENV", "test")
    assert infer_filters("HTM-0142")['codigos'] == ['HTM-0142']


def test_rrf_detecta_metadatos_contradictorios():
    vec = [{"chunk_id": "c1", "texto": "Un texto", "documento": "DOC-1", "componente": "motor"}]
    lex = [{"chunk_id": "c1", "texto": "Un texto", "documento": "DOC-1", "componente": "bateria"}]
    with pytest.raises(ValueError, match="Metadatos documentales contradictorios"):
        rrf(vec, lex)


def test_vecinos_no_pueden_cruzar_version_o_componente():
    parent = _chunk("c1")
    compatible = _chunk("c2")
    incompatible_version = _chunk("c3", version="V2.0")
    incompatible_component = _chunk("c4", component="bateria")
    all_neighbors = [compatible, incompatible_version, incompatible_component]

    result = resolve_retrieval([parent], filters={"version": "V1.1", "componente": "refrigeracion"},
                               fetch_neighbors=lambda _: all_neighbors)
    assert result.estado == "suficiente"
    assert {c["chunk_id"] for c in result.candidatos} == {"c1", "c2"}


def test_vecino_sin_rerank_score_no_recibe_score_parental():
    # Los candidatos de vecinos pueden conservarse en la expansión para
    # contexto, pero no pueden considerarse automáticamente rerankeados.
    parent = _chunk("c1")
    neighbor = _chunk("c2")
    neighbor.pop("rerank_score")
    expanded = resolve_retrieval([parent], filters={"version": "V1.1"},
                                 fetch_neighbors=lambda _: [neighbor])
    assert expanded.estado == "suficiente"
    only_neighbor = next(c for c in expanded.candidatos if c["chunk_id"] == "c2")
    assert only_neighbor["es_vecino"] is True
    assert "rerank_score" not in only_neighbor


def test_punto_publico_falla_controladamente_sin_catalogos_reales(monkeypatch):
    from unittest.mock import Mock
    from Agents.Agent_2.src.clients.backend import BackendAPIClient
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline
    monkeypatch.setenv("ARSOFT_ENV", "production")
    monkeypatch.setenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "0")
    monkeypatch.setattr(config, "CATALOG_DIR", Path("/sin/catalogos/empresa"))
    # Tras corregir el arranque, la ausencia local obliga a consultar Backend.
    # Simular su 503 contractual evita depender del puerto localhost:8000.
    response = Mock(status_code=503, json=lambda: {"codigo": "indice_no_disponible"})
    backend = BackendAPIClient("http://backend.test", "BAAI/bge-m3",
                               session=Mock(get=Mock(return_value=response)))
    pipeline = Agent2Pipeline(backend_client=backend)
    respuesta = pipeline.procesar_consulta({"texto_preprocesado": "avería HTM-0142"})
    assert respuesta["estado"] == "error"
    assert respuesta["codigo_error"] == "indice_no_disponible"
    assert respuesta["resultados"] == []


def test_reintento_amplia_solo_tipo_documento():
    from Agents.Agent_2.src.clients.backend import BackendAPIClient
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline
    from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession

    chunk = _chunk("c-doc")
    chunk["tipo_documento"] = "boletin"
    # El tipo manual está admitido por el índice, pero no hay documentos de
    # ese tipo aplicables a V1.1 + refrigeracion (debe devolver 200 vacío).
    other = _chunk("c-manual", component="motor", version="V2.0")
    other["tipo_documento"] = "manual"
    simulator = BackendSimulator([chunk, other])
    backend = BackendAPIClient("http://backend.test", simulator.modelo_embeddings,
                               session=SimulatedSession(simulator))
    class Encoder:
        def encode_query(self, text):
            return [0.01] * 1024
    class Reranker:
        def predict(self, pairs):
            return [0.96] * len(pairs)

    pipe = Agent2Pipeline(backend_client=backend, embedding_client=Encoder(),
                          reranker_model=Reranker(), threshold=0.45)
    response = pipe.procesar_consulta({
        "texto_preprocesado": "bomba refrigeracion V1.1",
        "filtros": {"version": "V1.1", "componente": "refrigeracion", "tipo_documento": "manual"},
    })
    assert response["estado"] == "suficiente"
    assert response["metricas"]["tipo_documento_ampliado"] is True
    assert response["resultados"][0]["metadatos"]["tipo_documento"] == "boletin"
    assert simulator.peticiones
    assert all(r["cuerpo"]["filtros"].get("version") == "V1.1"
               for r in simulator.peticiones if r["metodo"] == "POST")
