"""Regresiones del punto público real A2; HTTP y modelos inyectados, sin pesos."""

import copy
import json
from pathlib import Path
import time
from unittest.mock import Mock

import pytest
import requests

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.core.errors import BackendRequestError
from Agents.Agent_2.src.services import pipeline as module
from Agents.Agent_2.src.services.filter_inference import (
    invalidate_backend_catalog_cache, load_catalogs_from_backend, merge_filters,
)
from Agents.Agent_2.src.services.pipeline import recuperar_evidencias
from Agents.Agent_2.src.services import runtime
from Agents.Agent_2.src.services.vigencia import classify_state


def chunk(cid="parent", version="V1.1", **changes):
    result = dict(chunk_id=cid, texto="Comprobar la bomba de refrigeracion.", score=0.8,
                  documento="HTM240-MAN-001", seccion="2.1", pagina=3, versiones=[version],
                  componente="refrigeracion", tipo_documento="manual", obsoleto=False,
                  sustituido_por=None, vigente_para=[version], fecha_revision="2026-10-01",
                  orden_en_seccion=1, version_documento="1.0", afectado_por=[], ids_referenciados=[])
    result.update(changes)
    return result


class Session:
    """Doble explícito con las envolturas HTTP del Backend actual."""
    def __init__(self, parents=None, neighbors=None):
        self.parents = [chunk()] if parents is None else parents
        self.neighbors = neighbors or []
        self.calls = []
        self.catalogs = {"codigos": [{"codigo": "HTM-0142"}], "componentes": [{"codigo": "CMP-18"}]}

    def response(self, data, status=200):
        return Mock(status_code=status, json=lambda: copy.deepcopy(data))

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "/catalogos/" in url:
            name = url.rsplit("/", 1)[1]
            return self.response({"nombre": name, "version": "audit-v1", "contenido": self.catalogs[name]})
        if url.endswith("/info"):
            return self.response(dict(version="audit-v1", modelo_embeddings="BAAI/bge-m3", dimensiones=1024))
        parent = next(c for c in self.parents if c["chunk_id"] == url.rsplit("/", 1)[1])
        return self.response({"indice": {"version": "audit-v1"}, "chunk": parent, "vecinos": self.neighbors})

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response({"indice": {"version": "audit-v1", "modelo_embeddings": "BAAI/bge-m3"},
                              "resultados": self.parents})


class Encoder:
    def encode_query(self, text):
        return [0.01] * 1024


class Reranker:
    def __init__(self, neighbor_score=0.81):
        self.pairs = []
        self.neighbor_score = neighbor_score

    def predict(self, pairs):
        self.pairs.extend(pairs)
        return [self.neighbor_score if "Desconectar" in text else 0.95 for _, text in pairs]


@pytest.fixture(autouse=True)
def isolated_catalogs(monkeypatch, tmp_path):
    invalidate_backend_catalog_cache()
    monkeypatch.setenv("ARSOFT_ENV", "production")
    monkeypatch.setattr(config, "CATALOG_DIR", tmp_path / "no-local-catalogs")
    yield
    invalidate_backend_catalog_cache()


def public(monkeypatch, session=None, reranker=None, query=None, **kwargs):
    session = session or Session()
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(module, "get_bge_m3_client", lambda: Encoder())
    monkeypatch.setattr("Agents.Agent_2.src.clients.reranker_loader.get_reranker", lambda: reranker or Reranker())
    result = recuperar_evidencias(query or {"texto_preprocesado": "bomba refrigeracion V1.1"}, **kwargs)
    return result, session


def test_public_production_boot_downloads_before_search(monkeypatch):
    result, session = public(monkeypatch)
    assert result["estado"] == "suficiente"
    paths = [url.rsplit("/", 1)[1] for url, _ in session.calls]
    assert paths[:2] == ["codigos", "componentes"]
    assert "vectorial" in paths and "lexica" in paths
    assert result["evidencias"][0]["chunk_id"] == "parent"
    esperado = (config.CONNECT_TIMEOUT, config.REQUEST_TIMEOUT)
    assert all(kwargs["timeout"] == esperado for _, kwargs in session.calls)


@pytest.mark.parametrize("failure,code", [(requests.Timeout(), "tiempo_agotado"),
                                         (requests.ConnectionError(), "servicio_no_disponible")])
def test_production_catalog_network_errors_are_not_empty(monkeypatch, failure, code):
    session = Session()
    session.get = Mock(side_effect=failure)
    result, _ = public(monkeypatch, session)
    assert result["estado"] == "error" and result["codigo_error"] == code
    assert not any(url.endswith("/vectorial") for url, _ in session.calls)


@pytest.mark.parametrize("bad", [None, {}, "invalid", [None], [{"codigo": ""}]])
def test_bad_catalog_never_enters_cache(monkeypatch, bad):
    session = Session()
    session.catalogs["codigos"] = bad
    result, _ = public(monkeypatch, session)
    assert result["estado"] == "error"
    assert result["codigo_error"] == "servicio_no_disponible"
    session.catalogs["codigos"] = [{"codigo": "HTM-0142"}]
    assert public(monkeypatch, session)[0]["estado"] == "suficiente"


def test_catalog_invalidation_refreshes_public_pipeline(monkeypatch):
    session = Session()
    public(monkeypatch, session)
    client = BackendAPIClient(config.BACKEND_BASE_URL, config.EMBEDDINGS_MODEL, session=session)
    assert "htm0142" in load_catalogs_from_backend(client)["code_by_key"]
    session.catalogs["codigos"] = [{"codigo": "HTM-9999"}]
    invalidate_backend_catalog_cache(client)
    catalogs = load_catalogs_from_backend(client)
    assert "htm9999" in catalogs["code_by_key"] and "htm0142" not in catalogs["code_by_key"]


@pytest.mark.parametrize("doc_type", ["codigo_averia", "mantenimiento", "boletin", "catalogo", "DTC", "MNT"])
def test_canonical_document_types_and_known_aliases_are_accepted(doc_type):
    assert merge_filters({"tipo_documento": doc_type}, {})["tipo_documento"]


@pytest.mark.parametrize("filters", [{"componente": "culata"}, {"componente": "CMP-18"},
                                     {"tipo_documento": "otro"}, {"version": "fantasia"}, {"inventado": "x"}])
def test_unresolved_explicit_filters_do_not_disappear(filters):
    with pytest.raises(ValueError):
        merge_filters(filters, {})


@pytest.mark.parametrize("score,included", [(0.81, True), (0.10, False)])
def test_neighbors_receive_own_reranking_and_reach_output(monkeypatch, score, included):
    neighbor = chunk("safety", texto="Desconectar la alimentacion antes de continuar.", orden_en_seccion=2)
    model = Reranker(score)
    result, _ = public(monkeypatch, Session(neighbors=[neighbor]), model)
    assert result["estado"] == "suficiente"
    by_id = {e["chunk_id"]: e for e in result["evidencias"]}
    assert ("safety" in by_id) is included
    assert len(model.pairs) == 2
    if included:
        assert by_id["safety"]["score_final"] == score
        assert by_id["safety"]["score_final"] != by_id["parent"]["score_final"]


@pytest.mark.parametrize("changes", [{"versiones": ["V2.0"], "vigente_para": ["V2.0"]},
                                     {"componente": "bateria"}, {"obsoleto": True, "vigente_para": [], "sustituido_por": "NEW"}])
def test_neighbors_preserve_hard_filters_and_applicability(monkeypatch, changes):
    neighbor = chunk("unsafe", **changes)
    result, _ = public(monkeypatch, Session(neighbors=[neighbor]))
    assert result["estado"] == "suficiente"
    assert {e["chunk_id"] for e in result["evidencias"]} == {"parent"}


def test_incompatible_neighbors_cannot_make_the_answer_unambiguous(monkeypatch):
    result, _ = public(monkeypatch, Session(neighbors=[chunk("v2", "V2.0")]),
                       query={"texto_preprocesado": "consulta", "filtros": {}})
    assert result["estado"] == "ambiguo" and result["campo_ambiguo"] == "version"


def test_vigente_para_determines_common_compatibility():
    one = chunk("one", versiones=["V1.0", "V1.1"], vigente_para=["V1.0"])
    two = chunk("two", versiones=["V1.0", "V1.1"], vigente_para=["V1.1"])
    assert classify_state([one, two]).estado == "ambiguo"
    assert classify_state([one], {"version": "V1.0"}).estado == "suficiente"


def test_final_top_k_does_not_reduce_retrieval_pool(monkeypatch):
    result, session = public(monkeypatch, query={"texto_preprocesado": "consulta", "opciones": {"top_k": 3}})
    assert result["estado"] == "suficiente"
    assert all(kwargs["json"]["k"] >= config.SEARCH_TOP_K for url, kwargs in session.calls if "json" in kwargs)


def test_stage_metrics_cover_success_and_early_errors(monkeypatch):
    result, _ = public(monkeypatch)
    expected = {"tiempo_embedding_ms", "tiempo_vectorial_ms", "tiempo_lexica_ms", "tiempo_rrf_ms",
                "tiempo_reranker_ms", "tiempo_vecinos_ms", "tiempo_evidencias_ms", "tiempo_total_ms"}
    assert expected <= result["metricas"].keys()
    assert all(result["metricas"][key] >= 0 for key in expected)
    invalid = recuperar_evidencias({})
    assert invalid["estado"] == "error" and "tiempo_total_ms" in invalid["metricas"]


def test_budget_exhaustion_is_error_not_no_evidence(monkeypatch):
    session = Session()
    original = session.post
    def slow(*args, **kwargs):
        time.sleep(0.01)
        return original(*args, **kwargs)
    session.post = slow
    result, _ = public(monkeypatch, session, timeout_s=0.005)
    assert result["estado"] == "error" and result["codigo_error"] == "tiempo_agotado"


def test_health_backend_only_does_not_claim_models_verified():
    client = BackendAPIClient("http://audit", "BAAI/bge-m3", session=Session())
    result = runtime.check_readiness(client, load_models=False)
    assert result["status"] == "partial" and not result["modelos_verificados"]


def test_health_checks_both_real_model_interfaces(monkeypatch):
    client = BackendAPIClient("http://audit", "BAAI/bge-m3", session=Session())
    monkeypatch.setattr(runtime, "get_bge_m3_client", lambda: Encoder())
    monkeypatch.setattr(runtime, "get_reranker", lambda: Reranker())
    assert runtime.check_readiness(client)["status"] == "ok"
    monkeypatch.setattr(runtime, "get_reranker", Mock(side_effect=RuntimeError("missing weights")))
    assert runtime.check_readiness(client)["status"] == "unavailable"


@pytest.mark.parametrize("change,code", [({"modelo_embeddings": "wrong"}, "modelo_incompatible"),
                                        ({"dimensiones": 3}, "modelo_incompatible"), ({"version": ""}, "indice_no_disponible")])
def test_index_health_validates_backend_metadata(change, code):
    session = Session()
    info = dict(version="audit-v1", modelo_embeddings="BAAI/bge-m3", dimensiones=1024)
    info.update(change)
    session.get = lambda *a, **k: session.response(info)
    client = BackendAPIClient("http://audit", "BAAI/bge-m3", session=session)
    with pytest.raises(BackendRequestError) as error:
        client.get_info()
    assert error.value.codigo_error == code


def test_cli_rejects_malformed_json_without_inference(tmp_path, capsys):
    from Agents.Agent_2.__main__ import main
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")
    assert main(["--query", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["codigo_error"] == "entrada_invalida"


def test_apptainer_has_complete_a2_source_and_real_entrypoint():
    root = Path(__file__).resolve().parents[4]
    definition = (root / "Agents/Agent_2/apptainer/agente2.def").read_text()
    assert "Agents/Agent_2 /opt/arsoft/Agents/Agent_2" in definition
    assert "-r /opt/arsoft/Agents/Agent_2/requirements.txt" in definition
    assert "python -m Agents.Agent_2" in definition and "ARSOFT_ENV=production" in definition


def test_neighbors_from_another_index_are_a_technical_error(monkeypatch):
    session = Session()
    original = session.get
    def changed_index(url, **kwargs):
        response = original(url, **kwargs)
        if "/chunks/" in url:
            body = response.json()
            body["indice"]["version"] = "reindexed-v2"
            return session.response(body)
        return response
    session.get = changed_index
    result, _ = public(monkeypatch, session)
    assert result["estado"] == "error" and result["codigo_error"] == "indice_no_disponible"


def test_neighbors_of_another_document_edition_are_excluded(monkeypatch):
    neighbor = chunk("another-edition", version_documento="2.0")
    result, _ = public(monkeypatch, Session(neighbors=[neighbor]))
    assert result["estado"] == "suficiente"
    assert [e["chunk_id"] for e in result["evidencias"]] == ["parent"]


def test_evaluator_measures_rankings_without_sending_labels(monkeypatch):
    from Agents.Agent_2.tools.evaluar_agente2 import evaluate
    seen = []
    def retrieve(query, **kwargs):
        seen.append(query)
        return {"estado": "suficiente", "evidencias": [{"chunk_id": "parent", "texto": "texto", "metadata": chunk()}],
                "metricas": {"rankings": {"vectorial": ["parent"], "lexica": [], "fusion": ["parent"]}}}
    data = {"procedencia": "fixture unitario", "tipo": "sintetico",
            "consultas": [{"id": "q1", "query": {"texto_preprocesado": "consulta"}, "relevant_chunk_ids": ["parent"]}]}
    report = evaluate(data, retrieve=retrieve)
    assert report["recall_medio"] == 1 and report["mrr"] == 1
    assert report["detalle"][0]["fusion_no_inferior"] is True
    assert not report["certifica_despliegue"]
    assert seen == [{"texto_preprocesado": "consulta"}]


def test_evaluator_does_not_count_errors_as_correct_abstention():
    from Agents.Agent_2.tools.evaluar_agente2 import evaluate
    data = {"procedencia": "fixture unitario", "tipo": "sintetico", "consultas": [
        {"id": "q1", "query": {"texto_preprocesado": "consulta"}, "relevant_chunk_ids": []}]}
    report = evaluate(data, retrieve=lambda *a, **k: {"estado": "error", "evidencias": [], "codigo_error": "tiempo_agotado"})
    assert report["errores"] == 1 and report["abstencion"] == 0


def test_trace_rankings_are_explicit_opt_in(monkeypatch):
    result, _ = public(monkeypatch, trace_retrieval=True)
    assert result["metricas"]["rankings"]["fusion"] == ["parent"]
    ordinary, _ = public(monkeypatch)
    assert "rankings" not in ordinary["metricas"]
