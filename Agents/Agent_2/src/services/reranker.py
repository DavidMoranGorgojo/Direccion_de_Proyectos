
import math

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
    Calcula la puntuación del reranker para cada resultado
    y los ordena de mayor a menor puntuación.

    Args:
        query: consulta del usuario.
        results: candidatos obtenidos tras la fusión RRF.
        model: modelo de reranking con un método predict().

    Returns:
        Lista de resultados con 'rerank_score',
        ordenada de mayor a menor puntuación.

    Raises:
        ValueError: si el número de scores no coincide con
                    el número de resultados o si alguna
                    puntuación no es finita.
    """

    if not results:
        return []

    pairs = [
        [query, result["texto"]]
        for result in results
    ]

    scores = model.predict(pairs)

    if len(scores) != len(results):
        raise ValueError(
            "El número de scores del reranker no coincide "
            "con el número de resultados"
        )

    reranked_results = []

    for result, score in zip(results, scores):
        score = float(score)

        # Rechazar NaN e infinito para evitar resultados
        # incorrectos durante la ordenación y el filtrado.
        if not math.isfinite(score):
            raise ValueError(
                "El reranker ha devuelto una puntuación no finita"
            )

        reranked_result = result.copy()
        reranked_result["rerank_score"] = score
        reranked_results.append(reranked_result)

    return sort_by_rerank_score(reranked_results)
