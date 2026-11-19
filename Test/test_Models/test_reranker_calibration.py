import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    REPO_ROOT / "Test" / "fixtures" / "agent2" / "calibracion_reranker.json"
)

from Agents.Agent_2.src.evaluation.calibration import (  # noqa: E402
    CalibrationError,
    dump_calibration_result,
    evaluate_threshold,
    evaluate_thresholds,
    format_calibration_table,
    load_calibration_data,
    normalize_calibration_data,
    normalize_thresholds,
)


def _datos_simple():
    return [
        {
            "query_id": "Q1",
            "ranking": [
                {"chunk_id": "a", "rerank_score": 0.90},
                {"chunk_id": "b", "rerank_score": 0.60},
                {"chunk_id": "c", "rerank_score": 0.30},
            ],
            "relevant_chunk_ids": ["a", "c"],
        }
    ]


def test_normalize_thresholds_predeterminados_incluyen_045():
    thresholds = normalize_thresholds()

    assert thresholds[0] == 0.0
    assert thresholds[-1] == 1.0
    assert 0.45 in thresholds
    assert thresholds == sorted(thresholds)


def test_normalize_thresholds_rechaza_vacios_duplicados_e_invalidos():
    with pytest.raises(CalibrationError):
        normalize_thresholds([])

    with pytest.raises(CalibrationError):
        normalize_thresholds([0.1, 0.1])

    for value in [-0.1, 1.1, float("nan"), float("inf"), "0.5", True]:
        with pytest.raises(CalibrationError):
            normalize_thresholds([value])


def test_calculo_umbral_simple():
    result = evaluate_thresholds(_datos_simple(), [0.5])

    item = result["results"][0]

    assert item["tp"] == 1
    assert item["fp"] == 1
    assert item["fn"] == 1
    assert item["micro"]["precision"] == pytest.approx(0.5)
    assert item["micro"]["recall"] == pytest.approx(0.5)
    assert item["micro"]["f1"] == pytest.approx(0.5)
    assert item["retained_count"] == 2
    assert item["average_retained_per_query"] == pytest.approx(2.0)


def test_umbral_conserva_score_igual():
    result = evaluate_thresholds(_datos_simple(), [0.60])

    item = result["results"][0]

    assert item["tp"] == 1
    assert item["fp"] == 1
    assert item["retained_count"] == 2


def test_umbral_deja_cero_resultados():
    result = evaluate_thresholds(_datos_simple(), [0.95])

    item = result["results"][0]

    assert item["tp"] == 0
    assert item["fp"] == 0
    assert item["fn"] == 2
    assert item["micro"]["precision"] is None
    assert item["micro"]["recall"] == 0.0
    assert item["micro"]["f1"] == 0.0
    assert item["retained_count"] == 0


def test_relevante_ausente_cuenta_como_fn():
    result = evaluate_thresholds(_datos_simple(), [0.0])

    item = result["results"][0]

    assert item["tp"] == 2
    assert item["fp"] == 1
    assert item["fn"] == 0
    assert item["micro"]["recall"] == 1.0


def test_consulta_sin_relevantes_no_distorsiona_recall():
    datos = [
        {
            "query_id": "Q2",
            "ranking": [
                {"chunk_id": "x", "rerank_score": 0.80},
                {"chunk_id": "y", "rerank_score": 0.20},
            ],
            "relevant_chunk_ids": [],
        }
    ]

    result = evaluate_thresholds(datos, [0.5])
    item = result["results"][0]

    assert item["tp"] == 0
    assert item["fp"] == 1
    assert item["fn"] == 0
    assert item["micro"]["precision"] == 0.0
    assert item["queries"][0]["recall"] is None
    assert item["queries"][0]["f1"] is None
    assert item["micro"]["recall"] is None
    assert item["micro"]["f1"] is None
    assert item["macro"]["recall"] is None
    assert item["macro"]["f1"] is None


def test_macro_y_micro_se_distinguen():
    datos = _datos_simple() + [
        {
            "query_id": "Q2",
            "ranking": [{"chunk_id": "d", "rerank_score": 0.9}],
            "relevant_chunk_ids": ["d", "e", "f"],
        }
    ]

    item = evaluate_thresholds(datos, [0.5])["results"][0]

    # micro: TP=2, FP=1, FN=3; macro: media de (0.5, 1.0) y (0.5, 1/3).
    assert item["micro"]["precision"] == pytest.approx(2 / 3)
    assert item["micro"]["recall"] == pytest.approx(2 / 5)
    assert item["macro"]["precision"] == pytest.approx(0.75)
    assert item["macro"]["recall"] == pytest.approx((0.5 + 1 / 3) / 2)


def test_micro_y_macro_siguen_la_misma_convencion_sin_conservados():
    """Sin resultados conservados la precisión no está definida en ambas."""

    item = evaluate_thresholds(_datos_simple(), [0.95])["results"][0]

    assert item["micro"]["precision"] is None
    assert item["macro"]["precision"] is None
    assert item["queries"][0]["precision"] is None
    assert item["micro"]["f1"] == 0.0
    assert item["macro"]["f1"] == 0.0


def _consulta(query_id, ranking, relevantes):
    return {
        "query_id": query_id,
        "ranking": [
            {"chunk_id": chunk_id, "rerank_score": score}
            for chunk_id, score in ranking
        ],
        "relevant_chunk_ids": relevantes,
    }


def test_abstencion_correcta_no_penaliza_precision_macro():
    datos = [
        _consulta("Q_perfecta", [("a", 0.9)], ["a"]),
        _consulta("Q_sin_evidencia", [("x", 0.2)], []),
    ]

    item = evaluate_thresholds(datos, [0.5])["results"][0]
    abstencion = item["queries"][1]

    assert abstencion["retained_count"] == 0
    assert abstencion["precision"] is None
    assert abstencion["recall"] is None
    assert abstencion["f1"] is None
    assert item["macro"]["precision"] == pytest.approx(1.0)
    assert item["macro"]["f1"] == pytest.approx(1.0)


def test_falso_positivo_sin_relevantes_si_penaliza_precision_macro():
    datos = [
        _consulta("Q_perfecta", [("a", 0.9)], ["a"]),
        _consulta("Q_sin_evidencia", [("x", 0.9)], []),
    ]

    item = evaluate_thresholds(datos, [0.5])["results"][0]

    assert item["queries"][1]["precision"] == 0.0
    assert item["macro"]["precision"] == pytest.approx(0.5)


def test_abstencion_con_relevantes_penaliza_recall_y_f1():
    datos = [
        _consulta("Q_perfecta", [("a", 0.9)], ["a"]),
        _consulta("Q_perdida", [("b", 0.2)], ["b"]),
    ]

    item = evaluate_thresholds(datos, [0.5])["results"][0]
    perdida = item["queries"][1]

    assert perdida["precision"] is None
    assert perdida["recall"] == 0.0
    assert perdida["f1"] == 0.0
    assert item["macro"]["precision"] == pytest.approx(1.0)
    assert item["macro"]["recall"] == pytest.approx(0.5)
    assert item["macro"]["f1"] == pytest.approx(0.5)


def test_metricas_de_abstencion():
    datos = [
        _consulta("Q_perfecta", [("a", 0.9)], ["a"]),
        _consulta("Q_perdida", [("b", 0.2)], ["b"]),
        _consulta("Q_abst_ok", [("x", 0.2)], []),
        _consulta("Q_sin_evidencia", [("y", 0.9)], []),
        _consulta("Q_abst_ok_vacia", [], []),
    ]

    abstencion = evaluate_thresholds(datos, [0.5])["results"][0]["abstencion"]

    assert abstencion == {
        "consultas_sin_relevantes": 3,
        "consultas_con_relevantes": 2,
        "abstenciones_correctas": 2,
        "abstenciones_falsas": 1,
        "respuestas_sin_evidencia": 1,
        "tasa_abstencion_correcta": pytest.approx(2 / 3),
        "tasa_abstencion_falsa": pytest.approx(0.5),
    }


def test_abstencion_depende_del_umbral():
    datos = [
        _consulta("Q_rel", [("a", 0.6)], ["a"]),
        _consulta("Q_sin_rel", [("x", 0.4)], []),
    ]

    resultados = evaluate_thresholds(datos, [0.3, 0.5, 0.7])["results"]
    abst = [item["abstencion"] for item in resultados]

    assert [a["abstenciones_correctas"] for a in abst] == [0, 1, 1]
    assert [a["abstenciones_falsas"] for a in abst] == [0, 0, 1]


def test_tasas_de_abstencion_no_definidas_sin_consultas_del_tipo():
    solo_con_relevantes = evaluate_thresholds(_datos_simple(), [0.5])
    abstencion = solo_con_relevantes["results"][0]["abstencion"]

    assert abstencion["consultas_sin_relevantes"] == 0
    assert abstencion["tasa_abstencion_correcta"] is None
    assert abstencion["tasa_abstencion_falsa"] == 0.0

    solo_sin_relevantes = evaluate_thresholds(
        [_consulta("Q", [("x", 0.9)], [])], [0.5]
    )
    abstencion = solo_sin_relevantes["results"][0]["abstencion"]

    assert abstencion["tasa_abstencion_falsa"] is None
    assert abstencion["tasa_abstencion_correcta"] == 0.0


def test_resultados_en_orden_ascendente():
    result = evaluate_thresholds(_datos_simple(), [0.9, 0.1, 0.5])

    thresholds = [item["threshold"] for item in result["results"]]

    assert thresholds == [0.1, 0.5, 0.9]


def test_no_modifica_datos_originales():
    datos = _datos_simple()
    copia = json.loads(json.dumps(datos))

    evaluate_thresholds(datos, [0.1, 0.9])

    assert datos == copia


@pytest.mark.parametrize(
    "datos",
    [
        [{"query_id": "Q1", "results": [], "relevant_chunk_ids": []}],
        [{"query_id": "Q1", "ranking": [], "relevant": ["a"]}],
        [
            {
                "query_id": "Q1",
                "ranking": [{"id": "a", "rerank_score": 0.9}],
                "relevant_chunk_ids": [],
            }
        ],
        [
            {
                "query_id": "Q1",
                "ranking": [{"chunk_id": "a", "score": 0.9}],
                "relevant_chunk_ids": [],
            }
        ],
        {"queries": [{"query_id": "Q1", "ranking": [], "relevant_chunk_ids": []}]},
    ],
)
def test_normalizacion_rechaza_nombres_alternativos(datos):
    with pytest.raises(CalibrationError):
        normalize_calibration_data(datos)


def test_query_id_se_genera_si_falta():
    normalized = normalize_calibration_data(
        [{"ranking": [], "relevant_chunk_ids": []}]
    )

    assert normalized[0]["query_id"] == "Q001"


def test_validacion_ranking_invalido():
    casos = [
        {"query_id": "Q", "ranking": "no-lista", "relevant_chunk_ids": []},
        {
            "query_id": "Q",
            "ranking": [{"chunk_id": "a", "rerank_score": 0.5}],
            "relevant_chunk_ids": "no-lista",
        },
        {
            "query_id": "Q",
            "ranking": [
                {"chunk_id": "a", "rerank_score": 0.5},
                {"chunk_id": "a", "rerank_score": 0.4},
            ],
            "relevant_chunk_ids": [],
        },
        {
            "query_id": "Q",
            "ranking": [{"chunk_id": "a", "rerank_score": float("nan")}],
            "relevant_chunk_ids": [],
        },
        {
            "query_id": "Q",
            "ranking": [{"chunk_id": "", "rerank_score": 0.5}],
            "relevant_chunk_ids": [],
        },
        {
            "query_id": "Q",
            "ranking": [{"chunk_id": "a"}],
            "relevant_chunk_ids": [],
        },
        {
            "query_id": "Q",
            "ranking": [{"rerank_score": 0.5}],
            "relevant_chunk_ids": [],
        },
    ]

    for caso in casos:
        with pytest.raises(CalibrationError):
            normalize_calibration_data([caso])


def test_validacion_consulta_sin_ranking_ni_relevantes():
    with pytest.raises(CalibrationError):
        normalize_calibration_data([{"query_id": "Q"}])


def test_top_level_invalido():
    with pytest.raises(CalibrationError):
        normalize_calibration_data({})

    with pytest.raises(CalibrationError):
        normalize_calibration_data([])


def test_load_calibration_data_fixture():
    queries = load_calibration_data(FIXTURE)

    assert len(queries) == 4
    assert queries[0]["query_id"] == "Q001"


def test_fixture_resultados_conocidos_en_045():
    queries = load_calibration_data(FIXTURE)
    result = evaluate_thresholds(queries, [0.45])
    item = result["results"][0]

    assert item["tp"] == 4
    assert item["fp"] == 3
    assert item["fn"] == 2
    assert item["micro"]["precision"] == pytest.approx(4 / 7)
    assert item["micro"]["recall"] == pytest.approx(4 / 6)
    assert item["micro"]["f1"] == pytest.approx(0.6153846154)
    assert item["retained_count"] == 7
    assert item["average_retained_per_query"] == pytest.approx(1.75)
    assert item["macro"]["precision"] == pytest.approx(0.5416666667)
    assert item["macro"]["recall"] == pytest.approx(0.7777777778)
    assert item["macro"]["f1"] == pytest.approx(0.7333333333)


def test_evaluate_threshold_individual():
    item = evaluate_threshold(_datos_simple(), 0.5)

    assert item["threshold"] == 0.5
    assert item["tp"] == 1


def test_salida_con_un_solo_nombre_por_campo():
    result = evaluate_thresholds(_datos_simple(), [0.5])
    item = result["results"][0]

    assert set(result) == {"results"}
    assert set(item) == {
        "threshold",
        "tp",
        "fp",
        "fn",
        "micro",
        "macro",
        "ranking",
        "abstencion",
        "retained_count",
        "average_retained_per_query",
        "queries",
    }
    assert set(item["micro"]) == set(item["macro"]) == {
        "precision",
        "recall",
        "f1",
    }


def test_mrr_y_recall_at_k_sobre_los_conservados():
    datos = [
        _consulta("Q1", [("x", 0.9), ("a", 0.8), ("b", 0.7)], ["a", "b"]),
        _consulta("Q2", [("c", 0.95)], ["c"]),
        _consulta("Q_sin_rel", [("y", 0.9)], []),
    ]

    ranking = evaluate_thresholds(datos, [0.5], recall_ks=[1, 2, 3])[
        "results"
    ][0]["ranking"]

    # Q1: primer relevante en posición 2 → 1/2; Q2 → 1. Q_sin_rel no cuenta.
    assert ranking["mrr"] == pytest.approx(0.75)
    assert ranking["recall_at_k"] == {
        "1": pytest.approx((0 + 1) / 2),
        "2": pytest.approx((0.5 + 1) / 2),
        "3": pytest.approx((1 + 1) / 2),
    }


def test_mrr_ordena_por_rerank_score_y_respeta_el_umbral():
    datos = [_consulta("Q1", [("x", 0.6), ("a", 0.9), ("b", 0.3)], ["b"])]

    ranking = evaluate_thresholds(datos, [0.5])["results"][0]["ranking"]

    assert ranking["mrr"] == 0.0
    assert ranking["recall_at_k"]["5"] == 0.0


def test_metricas_de_ranking_no_definidas_sin_relevantes():
    datos = [_consulta("Q", [("x", 0.9)], [])]

    ranking = evaluate_thresholds(datos, [0.5])["results"][0]["ranking"]

    assert ranking["mrr"] is None
    assert set(ranking["recall_at_k"].values()) == {None}


@pytest.mark.parametrize("ks", [[], [0], [1, 1], [True], "1"])
def test_recall_ks_invalidos(ks):
    with pytest.raises(CalibrationError):
        evaluate_thresholds(_datos_simple(), [0.5], recall_ks=ks)


def test_format_calibration_table():
    result = evaluate_thresholds(_datos_simple(), [0.5, 0.95])
    tabla = format_calibration_table(result)

    assert "umbral" in tabla
    assert "mrr" in tabla
    assert "0.50" in tabla
    assert "abst_ok" in tabla
    assert "abst_mal" in tabla
    # Con 0.95 no se conserva nada: la precisión se muestra como no definida.
    assert "  -   " in tabla.splitlines()[-1]


def test_dump_calibration_result(tmp_path):
    result = evaluate_thresholds(_datos_simple(), [0.5])
    salida = tmp_path / "salida.json"

    dump_calibration_result(result, salida)

    with salida.open(encoding="utf-8") as file:
        cargado = json.load(file)

    assert cargado["results"][0]["tp"] == 1


def test_script_lectura_y_salida(tmp_path):
    import subprocess
    import sys

    entrada = tmp_path / "entrada.json"
    salida = tmp_path / "salida.json"

    with entrada.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "consultas": [
                    {
                        "query_id": "Q1",
                        "ranking": [{"chunk_id": "a", "rerank_score": 0.90}],
                        "relevant_chunk_ids": ["a"],
                    }
                ]
            },
            file,
        )

    comando = [
        sys.executable,
        "-m",
        "scripts.calibrar_reranker",
        "--input",
        str(entrada),
        "--output",
        str(salida),
        "--thresholds",
        "0.5,1.0",
    ]

    ejecucion = subprocess.run(
        comando,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert ejecucion.returncode == 0, ejecucion.stderr
    assert "0.50" in ejecucion.stdout
    assert salida.exists()

    with salida.open(encoding="utf-8") as file:
        cargado = json.load(file)

    assert len(cargado["results"]) == 2


def test_script_error_archivo_invalido(tmp_path):
    import subprocess
    import sys

    entrada = tmp_path / "entrada.json"
    entrada.write_text("{invalido", encoding="utf-8")

    comando = [
        sys.executable,
        "-m",
        "scripts.calibrar_reranker",
        "--input",
        str(entrada),
    ]

    ejecucion = subprocess.run(
        comando,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert ejecucion.returncode == 1
    assert "Error:" in ejecucion.stderr


def test_reproducibilidad():
    primero = evaluate_thresholds(_datos_simple(), [0.1, 0.5, 0.9])
    segundo = evaluate_thresholds(_datos_simple(), [0.1, 0.5, 0.9])

    assert primero == segundo
