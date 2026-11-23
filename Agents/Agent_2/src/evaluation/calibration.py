"""Evaluación de umbrales del reranker (A2-08).

El módulo trabaja con puntuaciones ya calculadas. No carga el modelo real ni
llama a servicios externos.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .metrics import mean_reciprocal_rank, recall_at_k

DEFAULT_THRESHOLDS = [round(index * 0.05, 2) for index in range(21)]
DEFAULT_RECALL_KS = (1, 3, 5)


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


def _validate_recall_ks(ks):
    if not isinstance(ks, (list, tuple)) or not ks:
        raise CalibrationError("Los valores de k deben ser una lista no vacía")

    for k in ks:
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise CalibrationError("Cada k debe ser un entero mayor que cero")

    if len(set(ks)) != len(ks):
        raise CalibrationError("Los valores de k no pueden estar duplicados")

    return sorted(ks)


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


def _validate_id(value, mensaje):
    if not isinstance(value, str) or not value.strip():
        raise CalibrationError(mensaje)
    return value.strip()


def _normalize_query(item, index):
    if not isinstance(item, dict):
        raise CalibrationError(f"La consulta {index} debe ser un diccionario")

    query_id = item.get("query_id", f"Q{index + 1:03d}")
    query_id = _validate_id(
        query_id, f"El identificador de la consulta {index} no es válido"
    )

    if "ranking" not in item:
        raise CalibrationError(f"La consulta {query_id} no contiene 'ranking'")

    raw_ranking = item["ranking"]
    if not isinstance(raw_ranking, list):
        raise CalibrationError(f"El ranking de {query_id} debe ser una lista")

    if "relevant_chunk_ids" not in item:
        raise CalibrationError(
            f"La consulta {query_id} no contiene 'relevant_chunk_ids'"
        )

    raw_relevant = item["relevant_chunk_ids"]
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

        if "chunk_id" not in entry:
            raise CalibrationError(
                f"El resultado {position} de {query_id} no contiene chunk_id"
            )

        chunk_id = _validate_id(
            entry["chunk_id"],
            f"El identificador del resultado {position} "
            f"de {query_id} no es válido",
        )

        if chunk_id in seen_ids:
            raise CalibrationError(
                f"El chunk {chunk_id} está duplicado en {query_id}"
            )
        seen_ids.add(chunk_id)

        if "rerank_score" not in entry:
            raise CalibrationError(
                f"El resultado {position} de {query_id} "
                "no contiene rerank_score"
            )

        ranking.append(
            {
                "chunk_id": chunk_id,
                "rerank_score": _validate_score(
                    entry["rerank_score"], query_id, position
                ),
            }
        )

    relevant_ids = []
    seen_relevant = set()

    for relevant_id in raw_relevant:
        relevant_id = _validate_id(
            relevant_id,
            f"Los relevantes de {query_id} deben ser "
            "identificadores no vacíos",
        )
        if relevant_id in seen_relevant:
            raise CalibrationError(
                f"El relevante {relevant_id} está duplicado en {query_id}"
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
        if "consultas" not in data:
            raise CalibrationError("Los datos deben contener 'consultas'")
        raw_queries = data["consultas"]
    else:
        raise CalibrationError("Los datos deben ser una lista o diccionario")

    if not isinstance(raw_queries, list) or not raw_queries:
        raise CalibrationError("La lista de consultas no puede estar vacía")

    return [
        _normalize_query(item, index) for index, item in enumerate(raw_queries)
    ]


def _ratio(numerador, denominador):
    return numerador / denominador if denominador > 0 else None


def _f1(precision, recall):
    """F1 según la convención del módulo (ver docstring)."""

    if recall is None:
        return None
    if not precision or not recall:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _mean(values):
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


def _metrics_for_query(ranking, relevant_ids, threshold):
    relevant_set = set(relevant_ids)
    retained = sorted(
        (item for item in ranking if item["rerank_score"] >= threshold),
        key=lambda item: item["rerank_score"],
        reverse=True,
    )
    retained_ids = [item["chunk_id"] for item in retained]

    tp = sum(1 for chunk_id in retained_ids if chunk_id in relevant_set)
    fp = len(retained_ids) - tp
    fn = len(relevant_set) - tp

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, len(relevant_set))

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
        "retained_count": len(retained_ids),
        "relevant_count": len(relevant_set),
        "retained_ids": retained_ids,
    }


def _abstention_metrics(per_query):
    """Mide la abstención: consultas en las que no se conserva ningún resultado.

    - Correcta: la consulta no tiene relevantes y no se conserva nada.
    - Falsa: la consulta tiene relevantes y no se conserva nada.
    - Respuesta sin evidencia: la consulta no tiene relevantes y se
      conserva algún resultado.

    Las tasas son ``None`` si no hay consultas del tipo correspondiente.
    """

    sin_relevantes = [q for q in per_query if q["relevant_count"] == 0]
    con_relevantes = [q for q in per_query if q["relevant_count"] > 0]

    correctas = sum(1 for q in sin_relevantes if q["retained_count"] == 0)
    falsas = sum(1 for q in con_relevantes if q["retained_count"] == 0)

    return {
        "consultas_sin_relevantes": len(sin_relevantes),
        "consultas_con_relevantes": len(con_relevantes),
        "abstenciones_correctas": correctas,
        "abstenciones_falsas": falsas,
        "respuestas_sin_evidencia": len(sin_relevantes) - correctas,
        "tasa_abstencion_correcta": _ratio(correctas, len(sin_relevantes)),
        "tasa_abstencion_falsa": _ratio(falsas, len(con_relevantes)),
    }


def _ranking_metrics(per_query, normalized, recall_ks):
    """Recall@k y MRR de ``metrics.py`` sobre las consultas con relevantes."""

    rankings = []
    relevantes = []

    for metrics, query in zip(per_query, normalized):
        if query["relevant_chunk_ids"]:
            rankings.append(metrics["retained_ids"])
            relevantes.append(query["relevant_chunk_ids"])

    if not rankings:
        return {
            "mrr": None,
            "recall_at_k": {str(k): None for k in recall_ks},
        }

    return {
        "mrr": mean_reciprocal_rank(rankings, relevantes),
        "recall_at_k": {
            str(k): sum(
                recall_at_k(ranking, relevant, k)
                for ranking, relevant in zip(rankings, relevantes)
            )
            / len(rankings)
            for k in recall_ks
        },
    }


def evaluate_threshold(queries, threshold, recall_ks=DEFAULT_RECALL_KS):
    return evaluate_thresholds(queries, [threshold], recall_ks)["results"][0]


def evaluate_thresholds(queries, thresholds=None, recall_ks=DEFAULT_RECALL_KS):
    normalized = normalize_calibration_data(queries)
    threshold_values = normalize_thresholds(thresholds)
    recall_ks = _validate_recall_ks(recall_ks)

    threshold_results = []

    for threshold in threshold_values:
        metrics_per_query = [
            _metrics_for_query(
                query["ranking"], query["relevant_chunk_ids"], threshold
            )
            for query in normalized
        ]

        per_query = [
            {
                "query_id": query["query_id"],
                **{k: v for k, v in metrics.items() if k != "retained_ids"},
            }
            for query, metrics in zip(normalized, metrics_per_query)
        ]

        tp_total = sum(item["tp"] for item in per_query)
        fp_total = sum(item["fp"] for item in per_query)
        fn_total = sum(item["fn"] for item in per_query)
        retained_total = sum(item["retained_count"] for item in per_query)

        precision_micro = _ratio(tp_total, tp_total + fp_total)
        recall_micro = _ratio(tp_total, tp_total + fn_total)

        threshold_results.append(
            {
                "threshold": threshold,
                "tp": tp_total,
                "fp": fp_total,
                "fn": fn_total,
                "micro": {
                    "precision": precision_micro,
                    "recall": recall_micro,
                    "f1": _f1(precision_micro, recall_micro),
                },
                "macro": {
                    "precision": _mean(i["precision"] for i in per_query),
                    "recall": _mean(i["recall"] for i in per_query),
                    "f1": _mean(i["f1"] for i in per_query),
                },
                "ranking": _ranking_metrics(
                    metrics_per_query, normalized, recall_ks
                ),
                "abstencion": _abstention_metrics(per_query),
                "retained_count": retained_total,
                "average_retained_per_query": retained_total / len(normalized),
                "queries": per_query,
            }
        )

    return {"results": threshold_results}


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


def _fmt(value):
    return f"{value:.4f}" if value is not None else "  -   "


def format_calibration_table(result):
    header = (
        "umbral  precision  recall     f1         mrr        media  "
        "TP  FP  FN  abst_ok  abst_mal"
    )
    lines = [header, "-" * len(header)]

    for item in result["results"]:
        micro = item["micro"]
        abstencion = item["abstencion"]
        lines.append(
            f"{item['threshold']:.2f}    "
            f"{_fmt(micro['precision'])}   "
            f"{_fmt(micro['recall'])}   "
            f"{_fmt(micro['f1'])}   "
            f"{_fmt(item['ranking']['mrr'])}   "
            f"{item['average_retained_per_query']:.4f}  "
            f"{item['tp']:>2}  "
            f"{item['fp']:>2}  "
            f"{item['fn']:>2}  "
            f"{abstencion['abstenciones_correctas']:>2}/"
            f"{abstencion['consultas_sin_relevantes']:<4}  "
            f"{abstencion['abstenciones_falsas']:>2}/"
            f"{abstencion['consultas_con_relevantes']}"
        )

    return "\n".join(lines)


__all__ = [
    "CalibrationError",
    "DEFAULT_RECALL_KS",
    "DEFAULT_THRESHOLDS",
    "dump_calibration_result",
    "evaluate_threshold",
    "evaluate_thresholds",
    "format_calibration_table",
    "load_calibration_data",
    "normalize_calibration_data",
    "normalize_thresholds",
]
