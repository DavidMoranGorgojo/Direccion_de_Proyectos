"""Regresiones de la interfaz pública firmada, incluida su salida en errores."""

from dataclasses import fields

import pytest
import requests

from Agents.Agent_2.src.models.ctr_002 import ChunkMetadata
from Agents.Agent_2.src.services import pipeline
from Agents.Agent_2.src.services.filter_inference import invalidate_backend_catalog_cache
from Agents.Agent_2.src.services.pipeline import recuperar_evidencias
from .test_cierre_agente2 import Encoder, Reranker, Session


@pytest.fixture
def real_entrypoint(monkeypatch):
    """Punto público normal con transporte y modelos deterministas."""
    invalidate_backend_catalog_cache()
    monkeypatch.setenv('ARSOFT_ENV', 'production')
    monkeypatch.setattr(requests, 'Session', Session)
    monkeypatch.setattr(pipeline, 'get_bge_m3_client', lambda: Encoder())
    monkeypatch.setattr('Agents.Agent_2.src.clients.reranker_loader.get_reranker', Reranker)
    yield recuperar_evidencias
    invalidate_backend_catalog_cache()


def test_public_success_preserves_every_contract_metadata_field(real_entrypoint):
    result = real_entrypoint({'texto_preprocesado': 'bomba refrigeracion V1.1'})
    assert result['estado'] == 'suficiente'
    assert len(result['resultados']) == len(result['evidencias']) > 0
    expected = {field.name for field in fields(ChunkMetadata)}
    for public, internal in zip(result['resultados'], result['evidencias']):
        assert set(public) == {'chunk_id', 'score_final', 'texto', 'metadatos'}
        assert set(public['metadatos']) == expected
        assert 0 <= public['score_final'] <= 1
        assert public['chunk_id'] == internal['chunk_id']
        assert public['texto'] == internal['texto']
        for key in expected:
            assert public['metadatos'][key] == internal['metadata'][key]


def test_public_and_compatibility_metadata_do_not_share_mutable_lists(real_entrypoint):
    result = real_entrypoint({'texto_preprocesado': 'bomba refrigeracion V1.1'})
    original = list(result['evidencias'][0]['metadata']['versiones'])
    result['resultados'][0]['metadatos']['versiones'].append('V9.9')
    assert result['evidencias'][0]['metadata']['versiones'] == original


@pytest.mark.parametrize('query', [None, {}, {'texto_preprocesado': 42},
                                     {'texto_preprocesado': 'consulta', 'filtros': []}])
def test_invalid_requests_always_have_empty_results_and_explicit_error(query):
    result = recuperar_evidencias(query)
    assert result['estado'] == 'error'
    assert result['codigo_error'] == 'entrada_invalida'
    assert result['resultados'] == []


def test_no_hits_is_not_a_technical_error(real_entrypoint, monkeypatch):
    monkeypatch.setattr(requests, 'Session', lambda: Session(parents=[]))
    result = real_entrypoint({'texto_preprocesado': 'consulta sin coincidencias'})
    assert result['estado'] == 'sin_evidencia'
    assert result['resultados'] == []
    assert not result.get('codigo_error')


def test_catalog_timeout_stays_an_error_with_empty_results(real_entrypoint, monkeypatch):
    session = Session()
    def timeout(*args, **kwargs):
        raise requests.Timeout()
    session.get = timeout
    monkeypatch.setattr(requests, 'Session', lambda: session)
    result = real_entrypoint({'texto_preprocesado': 'bomba refrigeracion V1.1'})
    assert result['estado'] == 'error'
    assert result['codigo_error'] == 'tiempo_agotado'
    assert result['resultados'] == []
