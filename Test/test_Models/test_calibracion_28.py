"""Pruebas de la calibración A2-08 con la batería de 20 de control y 8 trampa."""

import importlib.util
import json
from pathlib import Path

import pytest

from Agents.Agent_2.src.evaluation.calibration import CalibrationError, evaluate_thresholds
from Agents.Agent_2.src.evaluation.dataset_calibracion import (
    PREGUNTAS_POR_DEFECTO,
    cargar_preguntas,
    construir_consultas,
    ranking_por_documento,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "Agents" / "Agent_2" / "scripts" / "calibrar_umbrales_28.py"


def _escribir(tmp_path, preguntas):
    path = tmp_path / "preguntas.json"
    path.write_text(json.dumps({"preguntas": preguntas}), encoding="utf-8")
    return path


# --- Batería oficial --------------------------------------------------------

def test_bateria_oficial_tiene_20_de_control_y_8_trampa():
    preguntas = cargar_preguntas()

    assert len(preguntas) == 28
    assert sum(p["tipo"] == "control" for p in preguntas) == 20
    assert sum(p["tipo"] == "trampa" for p in preguntas) == 8
    assert all(p["doc_esperado"] is None for p in preguntas if p["tipo"] == "trampa")
    assert PREGUNTAS_POR_DEFECTO.name == "preguntas_control_trampa.json"


@pytest.mark.parametrize(
    "pregunta,mensaje",
    [
        ({"id": "T1", "tipo": "trampa", "doc_esperado": "DOC", "pregunta": "x"}, "no puede tener"),
        ({"id": "C1", "tipo": "control", "doc_esperado": None, "pregunta": "x"}, "necesita doc_esperado"),
        ({"id": "C1", "tipo": "otro", "doc_esperado": "DOC", "pregunta": "x"}, "Tipo no válido"),
        ({"id": "C1", "tipo": "control", "doc_esperado": "DOC", "pregunta": " "}, "no tiene texto"),
    ],
)
def test_cargar_preguntas_rechaza_entradas_mal_formadas(tmp_path, pregunta, mensaje):
    with pytest.raises(CalibrationError, match=mensaje):
        cargar_preguntas(_escribir(tmp_path, [pregunta]))


def test_cargar_preguntas_rechaza_ids_duplicados(tmp_path):
    pregunta = {"id": "C1", "tipo": "control", "doc_esperado": "DOC", "pregunta": "x"}
    with pytest.raises(CalibrationError, match="Identificador"):
        cargar_preguntas(_escribir(tmp_path, [pregunta, dict(pregunta)]))


# --- Ranking por documento --------------------------------------------------

def test_ranking_por_documento_conserva_la_mejor_puntuacion():
    ranking = [
        {"chunk_id": "DOC-A@1.0_p1", "documento": "DOC-A", "rerank_score": 0.4},
        {"chunk_id": "DOC-B@1.0_p1", "documento": "DOC-B", "rerank_score": 0.7},
        {"chunk_id": "DOC-A@1.0_p2", "documento": "DOC-A", "rerank_score": 0.9},
    ]

    assert ranking_por_documento(ranking) == [
        {"chunk_id": "DOC-A", "rerank_score": 0.9},
        {"chunk_id": "DOC-B", "rerank_score": 0.7},
    ]


def test_ranking_por_documento_deduce_el_documento_del_chunk_id():
    ranking = [{"chunk_id": "HTM240-DTC-001@1.0_p1_htm0142", "rerank_score": 0.5}]

    assert ranking_por_documento(ranking) == [{"chunk_id": "HTM240-DTC-001", "rerank_score": 0.5}]


# --- Construcción de consultas ---------------------------------------------

PREGUNTAS = [
    {"id": "C1", "tipo": "control", "doc_esperado": "DOC-A", "pregunta": "a"},
    {"id": "C2", "tipo": "control", "doc_esperado": "DOC-FALTA", "pregunta": "b"},
    {"id": "T1", "tipo": "trampa", "doc_esperado": None, "pregunta": "c"},
]

RANKINGS = {
    "a": [{"chunk_id": "DOC-A@p1", "documento": "DOC-A", "rerank_score": 0.8},
          {"chunk_id": "DOC-B@p1", "documento": "DOC-B", "rerank_score": 0.3}],
    "b": [{"chunk_id": "DOC-B@p1", "documento": "DOC-B", "rerank_score": 0.6}],
    "c": [{"chunk_id": "DOC-B@p2", "documento": "DOC-B", "rerank_score": 0.2}],
}


def _ranking(pregunta):
    return RANKINGS[pregunta["pregunta"]]


def test_construir_consultas_trampa_sin_relevantes_y_excluye_documentos_ausentes():
    datos = construir_consultas(PREGUNTAS, _ranking, {"DOC-A", "DOC-B"})

    assert [c["query_id"] for c in datos["consultas"]] == ["C1", "T1"]
    assert datos["consultas"][0]["relevant_chunk_ids"] == ["DOC-A"]
    assert datos["consultas"][1]["relevant_chunk_ids"] == []
    assert datos["excluidas"] == [
        {"id": "C2", "doc_esperado": "DOC-FALTA", "motivo": "documento esperado ausente del índice"}
    ]


def test_sin_lista_de_documentos_no_excluye_nada():
    datos = construir_consultas(PREGUNTAS, _ranking)

    assert len(datos["consultas"]) == 3
    assert datos["excluidas"] == []


def test_las_consultas_alimentan_evaluate_thresholds():
    datos = construir_consultas(PREGUNTAS, _ranking, {"DOC-A", "DOC-B"})

    resultado = evaluate_thresholds(datos["consultas"], thresholds=[0.0, 0.5])
    bajo, alto = resultado["results"]

    # Umbral 0.0: no se abstiene en nada; la trampa se queda con evidencia.
    assert bajo["abstencion"]["abstenciones_correctas"] == 0
    assert bajo["ranking"]["recall_at_k"]["1"] == 1.0
    assert bajo["ranking"]["mrr"] == 1.0
    # Umbral 0.5: la trampa (0.2) se abstiene y el control (0.8) se conserva.
    assert alto["abstencion"]["abstenciones_correctas"] == 1
    assert alto["abstencion"]["abstenciones_falsas"] == 0


# --- Script -----------------------------------------------------------------

def _cargar_script():
    spec = importlib.util.spec_from_file_location("calibrar_umbrales_28", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_recomendar_umbral_equilibra_trampas_y_controles():
    script = _cargar_script()
    datos = construir_consultas(PREGUNTAS, _ranking, {"DOC-A", "DOC-B"})
    resultado = evaluate_thresholds(datos["consultas"], thresholds=[0.0, 0.5, 0.9])

    recomendacion = script.recomendar_umbral(resultado["results"])

    # 0.5 acierta la trampa sin perder el control; 0.9 pierde el control.
    assert recomendacion == {"threshold": 0.5, "equilibrio": 1.0}


def test_script_simulado_genera_json_y_tabla(tmp_path):
    script = _cargar_script()

    assert script.main(["--backend", "simulado", "--reranker", "solapamiento", "--salida", str(tmp_path)]) == 0

    informe = json.loads((tmp_path / "calibracion_28_simulado_solapamiento.json").read_text(encoding="utf-8"))
    assert informe["valido_para_fijar_umbral"] is False
    assert informe["granularidad"] == "documento"
    assert informe["preguntas_evaluadas"] + len(informe["excluidas"]) == 28
    assert all(t["estado_a2"] != "error" for t in informe["trazas"].values())
    assert informe["results"][0]["threshold"] == 0.0
    tabla = (tmp_path / "calibracion_28_simulado_solapamiento.md").read_text(encoding="utf-8")
    assert tabla.startswith("| Umbral | Recall@1")


# --- Traza del reranker en el pipeline -------------------------------------

def _pipeline_simulado(**kwargs):
    script = _cargar_script()
    from Agents.Agent_2.src.clients.backend import BackendAPIClient
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline
    from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession

    chunks, _ = script._documentos_dataset()
    simulador = BackendSimulator(chunks, catalogo_dir=script.DATASET.parent / "catalogos")
    cliente = BackendAPIClient("http://backend.simulado", simulador.modelo_embeddings,
                               session=SimulatedSession(simulador), timeout=5)
    return Agent2Pipeline(backend_client=cliente, embedding_client=script._EmbedderSimulado(simulador),
                          reranker_model=script.RerankerSolapamiento(), require_reranker=True, **kwargs)


def test_traza_incluye_el_ranking_completo_del_reranker_con_umbral_cero():
    salida = _pipeline_simulado(threshold=0.0, trace_retrieval=True).procesar_consulta(
        {"texto_preprocesado": "codigo HTM-0142"}
    )

    ranking = salida["metricas"]["rankings"]["reranker"]
    assert ranking, "el ranking del reranker no puede estar vacío"
    assert set(ranking[0]) == {"chunk_id", "documento", "rerank_score"}
    assert all(item["documento"] for item in ranking)
    scores = [item["rerank_score"] for item in ranking]
    assert scores == sorted(scores, reverse=True)
    assert len(ranking) == salida["metricas"]["candidatos_evaluados"]


def test_sin_traza_no_se_expone_el_ranking_del_reranker():
    salida = _pipeline_simulado(threshold=0.0).procesar_consulta({"texto_preprocesado": "codigo HTM-0142"})

    assert "rankings" not in salida["metricas"]
