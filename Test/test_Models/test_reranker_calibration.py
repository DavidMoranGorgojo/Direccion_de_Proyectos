import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    REPO_ROOT / "Test" / "fixtures" / "agent2" / "calibracion_reranker.json"
)

from Agents.Agent_2.src.evaluation.calibration import (  # noqa: E402
    CalibrationError,
    ThresholdCalibrator,
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
    assert item["precision"] == pytest.approx(0.5)
    assert item["recall"] == pytest.approx(0.5)
    assert item["f1"] == pytest.approx(0.5)
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
    assert item["precision"] == 0.0
    assert item["recall"] == 0.0
    assert item["f1"] == 0.0
    assert item["retained_count"] == 0


def test_relevante_ausente_cuenta_como_fn():
    result = evaluate_thresholds(_datos_simple(), [0.0])

    item = result["results"][0]

    assert item["tp"] == 2
    assert item["fp"] == 1
    assert item["fn"] == 0
    assert item["recall"] == 1.0


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
    assert item["precision"] == 0.0
    assert item["queries"][0]["recall"] is None
    assert item["queries"][0]["f1"] is None
    assert item["recall"] == 0.0
    assert item["macro"]["recall"] == 0.0


def test_macro_y_micro_se_distinguen():
    result = evaluate_thresholds(_datos_simple(), [0.5])

    item = result["results"][0]

    assert item["micro"]["precision"] == item["precision"]
    assert item["macro"]["precision"] == pytest.approx(0.5)
    assert item["macro"]["recall"] == pytest.approx(0.5)


def test_precision_cero_si_no_hay_conservados():
    result = evaluate_thresholds(_datos_simple(), [0.95])

    item = result["results"][0]

    assert item["precision"] == 0.0
    assert item["f1"] == 0.0


def test_resultados_en_orden_ascendente():
    result = evaluate_thresholds(_datos_simple(), [0.9, 0.1, 0.5])

    thresholds = [item["threshold"] for item in result["results"]]

    assert thresholds == [0.1, 0.5, 0.9]


def test_no_modifica_datos_originales():
    datos = _datos_simple()
    copia = json.loads(json.dumps(datos))

    evaluate_thresholds(datos, [0.1, 0.9])

    assert datos == copia


def test_normalizacion_acepta_aliases():
    datos = [
        {
            "id": "Q1",
            "results": [
                {"id": "a", "score": 0.90},
            ],
            "relevant": ["a"],
        }
    ]

    normalized = normalize_calibration_data(datos)

    assert normalized[0]["query_id"] == "Q1"
    assert normalized[0]["ranking"][0]["chunk_id"] == "a"
    assert normalized[0]["ranking"][0]["rerank_score"] == 0.90
    assert normalized[0]["relevant_chunk_ids"] == ["a"]


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
    assert item["precision"] == pytest.approx(4 / 7)
    assert item["recall"] == pytest.approx(4 / 6)
    assert item["f1"] == pytest.approx(0.6153846154)
    assert item["retained_count"] == 7
    assert item["average_retained_per_query"] == pytest.approx(1.75)
    assert item["macro"]["precision"] == pytest.approx(0.5416666667)
    assert item["macro"]["recall"] == pytest.approx(0.7777777778)
    assert item["macro"]["f1"] == pytest.approx(0.7333333333)


def test_evaluate_threshold_individual():
    item = evaluate_threshold(_datos_simple(), 0.5)

    assert item["threshold"] == 0.5
    assert item["tp"] == 1


def test_clase_calibrador():
    calibrador = ThresholdCalibrator()

    result = calibrador.evaluate_thresholds(_datos_simple(), [0.5])

    assert result["results"][0]["tp"] == 1


def test_format_calibration_table():
    result = evaluate_thresholds(_datos_simple(), [0.5])
    tabla = format_calibration_table(result)

    assert "umbral" in tabla
    assert "0.50" in tabla


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
        str(REPO_ROOT / "scripts" / "calibrar_reranker.py"),
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
        str(REPO_ROOT / "scripts" / "calibrar_reranker.py"),
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
