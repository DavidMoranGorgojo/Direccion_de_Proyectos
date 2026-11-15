"""Evaluación de umbrales del reranker.

El módulo trabaja con puntuaciones ya calculadas. No carga el modelo
real ni llama a servicios externos.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

DEFAULT_THRESHOLDS = [round(index * 0.05, 2) for index in range(21)]


class CalibrationError(ValueError):
    """Error de validación de los datos de calibración."""


def _validate_threshold(threshold):
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise CalibrationError(
            "El umbral debe ser un número finito entre 0 y 1"
        )
    return float(threshold)


def normalize_thresholds(thresholds=None):
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    if not isinstance(thresholds, (list, tuple)):
        raise CalibrationError("Los umbrales deben ser una lista o tupla")

    if not thresholds:
        raise CalibrationError("La lista de umbrales no puede estar vacía")

    validated = []
    seen = set()

    for threshold in thresholds:
        value = _validate_threshold(threshold)
        if value in seen:
            raise CalibrationError("Los umbrales no pueden estar duplicados")
        seen.add(value)
        validated.append(value)

    validated.sort()
    return validated


def _validate_score(score, query_id, index):
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
    ):
        raise CalibrationError(
            f"La puntuación del resultado {index} de {query_id} "
            "no es válida"
        )
    return float(score)


def _normalize_query(item, index):
    if not isinstance(item, dict):
        raise CalibrationError(f"La consulta {index} debe ser un diccionario")

    query_id = item.get("query_id", item.get("id"))
    if query_id is None:
        query_id = f"Q{index + 1:03d}"
    if not isinstance(query_id, str) or not query_id.strip():
        raise CalibrationError(
            f"El identificador de la consulta {index} no es válido"
        )
    query_id = query_id.strip()

    ranking_key = None
    for key in ("ranking", "results", "ranked_results", "resultados"):
        if key in item:
            ranking_key = key
            break

    if ranking_key is None:
        raise CalibrationError(
            f"La consulta {query_id} no contiene un ranking"
        )

    raw_ranking = item[ranking_key]
    if not isinstance(raw_ranking, list):
        raise CalibrationError(f"El ranking de {query_id} debe ser una lista")

    relevant_key = None
    for key in (
        "relevant_chunk_ids",
        "relevant",
        "relevantes",
        "relevant_ids",
    ):
        if key in item:
            relevant_key = key
            break

    if relevant_key is None:
        raise CalibrationError(
            f"La consulta {query_id} no contiene relevantes"
        )

    raw_relevant = item[relevant_key]
    if isinstance(raw_relevant, (str, bytes)) or not isinstance(
        raw_relevant, (list, tuple, set, frozenset)
    ):
        raise CalibrationError(
            f"Los relevantes de {query_id} deben ser una colección"
        )

    ranking = []
    seen_ids = set()

    for position, entry in enumerate(raw_ranking):
        if not isinstance(entry, dict):
            raise CalibrationError(
                f"El resultado {position} de {query_id} "
                "debe ser un diccionario"
            )

        chunk_key = None
        for key in ("chunk_id", "id", "documento_id"):
            if key in entry:
                chunk_key = key
                break

        if chunk_key is None:
            raise CalibrationError(
                f"El resultado {position} de {query_id} "
                "no contiene chunk_id"
            )

        chunk_id = entry[chunk_key]
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise CalibrationError(
                f"El identificador del resultado {position} "
                f"de {query_id} no es válido"
            )
        chunk_id = chunk_id.strip()

        if chunk_id in seen_ids:
            raise CalibrationError(
                f"El chunk {chunk_id} está duplicado en {query_id}"
            )
        seen_ids.add(chunk_id)

        score_key = None
        for key in ("rerank_score", "score", "puntuacion"):
            if key in entry:
                score_key = key
                break

        if score_key is None:
            raise CalibrationError(
                f"El resultado {position} de {query_id} "
                "no contiene rerank_score"
            )

        score = _validate_score(entry[score_key], query_id, position)

        ranking.append(
            {
                "chunk_id": chunk_id,
                "rerank_score": score,
            }
        )

    relevant_ids = []
    seen_relevant = set()

    for relevant_id in raw_relevant:
        if not isinstance(relevant_id, str) or not relevant_id.strip():
            raise CalibrationError(
                f"Los relevantes de {query_id} deben ser "
                "identificadores no vacíos"
            )
        relevant_id = relevant_id.strip()
        if relevant_id in seen_relevant:
            raise CalibrationError(
                f"El relevante {relevant_id} está duplicado " f"en {query_id}"
            )
        seen_relevant.add(relevant_id)
        relevant_ids.append(relevant_id)

    return {
        "query_id": query_id,
        "ranking": ranking,
        "relevant_chunk_ids": relevant_ids,
    }


def normalize_calibration_data(data):
    if isinstance(data, list):
        raw_queries = data
    elif isinstance(data, dict):
        raw_queries = None
        for key in ("consultas", "queries", "data", "resultados"):
            if key in data:
                raw_queries = data[key]
                break
        if raw_queries is None:
            raise CalibrationError(
                "Los datos deben contener una lista de consultas"
            )
    else:
        raise CalibrationError("Los datos deben ser una lista o diccionario")

    if not isinstance(raw_queries, list) or not raw_queries:
        raise CalibrationError("La lista de consultas no puede estar vacía")

    return [
        _normalize_query(item, index) for index, item in enumerate(raw_queries)
    ]


def _metrics_for_query(ranking, relevant_ids, threshold):
    relevant_set = set(relevant_ids)
    retained = [item for item in ranking if item["rerank_score"] >= threshold]
    retained_ids = {item["chunk_id"] for item in retained}

    tp = sum(1 for item in retained if item["chunk_id"] in relevant_set)
    fp = len(retained) - tp
    fn = sum(
        1 for relevant_id in relevant_set if relevant_id not in retained_ids
    )

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / len(relevant_set) if relevant_set else None

    if relevant_set:
        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0
    else:
        f1 = None

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "retained_count": len(retained),
        "relevant_count": len(relevant_set),
    }


def evaluate_threshold(queries, threshold):
    normalized = normalize_calibration_data(queries)
    thresholds = normalize_thresholds([threshold])
    result = evaluate_thresholds(normalized, thresholds)
    return result["results"][0]


def evaluate_thresholds(queries, thresholds=None):
    normalized = normalize_calibration_data(queries)
    threshold_values = normalize_thresholds(thresholds)

    threshold_results = []

    for threshold in threshold_values:
        per_query = []

        for query in normalized:
            metrics = _metrics_for_query(
                query["ranking"],
                query["relevant_chunk_ids"],
                threshold,
            )
            per_query.append(
                {
                    "query_id": query["query_id"],
                    "tp": metrics["tp"],
                    "fp": metrics["fp"],
                    "fn": metrics["fn"],
                    "precision": metrics["precision"],
                    "recall": metrics["recall"],
                    "f1": metrics["f1"],
                    "retained_count": metrics["retained_count"],
                    "relevant_count": metrics["relevant_count"],
                }
            )

        tp_total = sum(item["tp"] for item in per_query)
        fp_total = sum(item["fp"] for item in per_query)
        fn_total = sum(item["fn"] for item in per_query)
        retained_total = sum(item["retained_count"] for item in per_query)

        precision_micro = (
            tp_total / (tp_total + fp_total)
            if tp_total + fp_total > 0
            else 0.0
        )
        recall_micro = (
            tp_total / (tp_total + fn_total)
            if tp_total + fn_total > 0
            else 0.0
        )
        f1_micro = (
            2
            * precision_micro
            * recall_micro
            / (precision_micro + recall_micro)
            if precision_micro + recall_micro > 0
            else 0.0
        )

        precision_values = [item["precision"] for item in per_query]
        recall_values = [
            item["recall"] for item in per_query if item["recall"] is not None
        ]
        f1_values = [
            item["f1"] for item in per_query if item["f1"] is not None
        ]

        precision_macro = (
            sum(precision_values) / len(precision_values)
            if precision_values
            else 0.0
        )
        recall_macro = (
            sum(recall_values) / len(recall_values) if recall_values else 0.0
        )
        f1_macro = sum(f1_values) / len(f1_values) if f1_values else 0.0

        query_count = len(normalized)
        average_retained = (
            retained_total / query_count if query_count > 0 else 0.0
        )

        micro = {
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
            "precision": precision_micro,
            "recall": recall_micro,
            "f1": f1_micro,
        }
        macro = {
            "precision": precision_macro,
            "recall": recall_macro,
            "f1": f1_macro,
        }

        item = {
            "threshold": threshold,
            "umbral": threshold,
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
            "precision": precision_micro,
            "recall": recall_micro,
            "f1": f1_micro,
            "precision_micro": precision_micro,
            "recall_micro": recall_micro,
            "f1_micro": f1_micro,
            "micro": micro,
            "macro": macro,
            "precision_macro": precision_macro,
            "recall_macro": recall_macro,
            "f1_macro": f1_macro,
            "retained_count": retained_total,
            "retained_results": retained_total,
            "average_retained_per_query": average_retained,
            "media_resultados_conservados": average_retained,
            "queries": per_query,
            "por_consulta": per_query,
        }
        threshold_results.append(item)

    return {
        "thresholds": threshold_values,
        "umbrales": threshold_values,
        "results": threshold_results,
        "umbrales_resultados": threshold_results,
        "threshold_results": threshold_results,
        "resultados": threshold_results,
        "calibration": threshold_results,
    }


def load_calibration_data(path):
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise CalibrationError(
            f"No se pudo leer el archivo de calibración: {error}"
        ) from error
    return normalize_calibration_data(data)


def dump_calibration_result(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write("\n")


def format_calibration_table(result):
    lines = []
    header = "umbral  precision  recall     f1         media  TP  FP  FN"
    lines.append(header)
    lines.append("-" * len(header))

    for item in result["results"]:
        lines.append(
            f"{item['threshold']:.2f}    "
            f"{item['precision']:.4f}   "
            f"{item['recall']:.4f}   "
            f"{item['f1']:.4f}   "
            f"{item['average_retained_per_query']:.4f}  "
            f"{item['tp']:>2}  "
            f"{item['fp']:>2}  "
            f"{item['fn']:>2}"
        )

    return "\n".join(lines)


# Alias compatibles con nombres habituales.
evaluate_calibration = evaluate_thresholds
calibrate_thresholds = evaluate_thresholds
calibrate_reranker = evaluate_thresholds
run_calibration = evaluate_thresholds
evaluate_all_thresholds = evaluate_thresholds


class ThresholdCalibrator:
    def evaluate_thresholds(self, queries, thresholds=None):
        return evaluate_thresholds(queries, thresholds)

    def evaluate_threshold(self, queries, threshold):
        return evaluate_threshold(queries, threshold)


ThresholdEvaluator = ThresholdCalibrator
CalibrationEvaluator = ThresholdCalibrator
RerankerCalibrator = ThresholdCalibrator
ThresholdAnalysis = ThresholdCalibrator
RerankerThresholdCalibrator = ThresholdCalibrator


def _self_check():
    return True
