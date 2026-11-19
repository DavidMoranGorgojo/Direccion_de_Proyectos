
import math
import time

from Agents.Agent_2.src.core import config


def apply_threshold(results, threshold=None):
    """
    Filtra los resultados del reranker según un umbral mínimo.

    Args:
        results: lista de resultados con un campo 'rerank_score'.
        threshold: puntuación mínima necesaria para conservar
                   el resultado. Si no se indica, utiliza
                   RERANK_THRESHOLD de la configuración.

    Returns:
        Lista de resultados cuya puntuación alcanza el umbral.

    Raises:
        ValueError: si el umbral no es un número finito
                    comprendido entre 0 y 1.
    """

    if threshold is None:
        threshold = config.RERANK_THRESHOLD

    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise ValueError(
            "El umbral del reranker debe ser un número finito entre 0 y 1"
        )

    return [
        result
        for result in results
        if result["rerank_score"] >= threshold
    ]


def sort_by_rerank_score(results):
    """
    Ordena los resultados por puntuación del reranker,
    de mayor a menor.

    Args:
        results: lista de resultados con un campo 'rerank_score'.

    Returns:
        Lista de resultados ordenada por rerank_score descendente.
    """

    return sorted(
        results,
        key=lambda result: result["rerank_score"],
        reverse=True
    )


def rerank_results(query, results, model):
    """
    Calcula la puntuación del reranker para los candidatos
    mejor posicionados por RRF y los ordena por relevancia.

    Limita el número de candidatos mediante RERANK_TOP_K
    y valida las entradas antes de ejecutar la inferencia.

    Args:
        query: consulta del usuario.
        results: candidatos obtenidos tras la fusión RRF.
        model: modelo de reranking con un método predict().

    Returns:
        Lista de resultados con 'rerank_score',
        ordenada de mayor a menor puntuación.

    Raises:
        ValueError: si la consulta, los candidatos,
                    las puntuaciones RRF o las puntuaciones
                    del modelo son inválidos.
    """

    if not results:
        return []

    # Validar la consulta antes de ejecutar la inferencia.
    if not isinstance(query, str) or not query.strip():
        raise ValueError(
            "La consulta del reranker debe ser un texto no vacío"
        )

    # Validar todos los candidatos antes de seleccionarlos.
    for indice, result in enumerate(results):
        if not isinstance(result, dict):
            raise ValueError(
                f"El candidato {indice} del reranker debe ser un diccionario"
            )

        texto = result.get("texto")

        if not isinstance(texto, str) or not texto.strip():
            raise ValueError(
                f"El candidato {indice} del reranker "
                "no contiene un campo 'texto' válido"
            )

    # Aplicar el límite únicamente cuando se supera RERANK_TOP_K.
    # Los resultados de RRF deben incluir rrf_score para poder
    # seleccionar correctamente los candidatos más relevantes.
    if len(results) > config.RERANK_TOP_K:
        for indice, result in enumerate(results):
            score_rrf = result.get("rrf_score")

            if (
                isinstance(score_rrf, bool)
                or not isinstance(score_rrf, (int, float))
                or not math.isfinite(score_rrf)
            ):
                raise ValueError(
                    f"El candidato {indice} no contiene "
                    "un 'rrf_score' válido"
                )

        candidatos = sorted(
            results,
            key=lambda result: result["rrf_score"],
            reverse=True,
        )[:config.RERANK_TOP_K]
    else:
        candidatos = results

    pairs = [
        [query, result["texto"]]
        for result in candidatos
    ]

    scores = model.predict(pairs)

    if scores is None:
        raise ValueError(
            "El reranker no ha devuelto puntuaciones"
        )

    if len(scores) != len(candidatos):
        raise ValueError(
            "El número de scores del reranker no coincide "
            "con el número de resultados"
        )

    reranked_results = []

    for result, score in zip(candidatos, scores):
        try:
            score = float(score)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                "El reranker ha devuelto una puntuación no numérica"
            ) from error

        if not math.isfinite(score):
            raise ValueError(
                "El reranker ha devuelto una puntuación no finita"
            )

        reranked_result = result.copy()
        reranked_result["rerank_score"] = score
        reranked_results.append(reranked_result)

    return sort_by_rerank_score(reranked_results)


def rerank_with_threshold(
    query,
    results,
    model,
    threshold=None,
    return_metrics=False,
):
    """
    Ejecuta el reranking de candidatos y aplica el umbral mínimo de similitud,
    devolviendo opcionalmente las métricas estructuradas de la operación.

    Args:
        query: consulta del usuario (str no vacío).
        results: candidatos provenientes de RRF.
        model: modelo de reranking con método predict().
        threshold: puntuación mínima del reranker (None para usar config.RERANK_THRESHOLD).
        return_metrics: si es True, devuelve una tupla (resultados_filtrados, metricas).

    Returns:
        Lista de candidatos que superan el umbral ordenados por rerank_score descendente,
        o una tupla (candidatos_filtrados, metricas_dict) si return_metrics=True.
    """
    t_inicio = time.monotonic()
    reranked = rerank_results(query, results, model)
    duracion_ms = round((time.monotonic() - t_inicio) * 1000, 2)

    filtrados = apply_threshold(reranked, threshold=threshold)

    if return_metrics:
        umbral_usado = threshold if threshold is not None else config.RERANK_THRESHOLD
        metricas = {
            "total_candidatos_entrada": len(results),
            "candidatos_evaluados": len(reranked),
            "superan_umbral": len(filtrados),
            "descartados_umbral": len(reranked) - len(filtrados),
            "umbral_aplicado": umbral_usado,
            "latencia_ms": duracion_ms,
        }
        return filtrados, metricas

    return filtrados


__all__ = [
    "apply_threshold",
    "rerank_results",
    "rerank_with_threshold",
    "sort_by_rerank_score",
]
