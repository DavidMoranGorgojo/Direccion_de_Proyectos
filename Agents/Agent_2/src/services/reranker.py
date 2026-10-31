DEFAULT_THRESHOLD = 0.45


def apply_threshold(results, threshold=DEFAULT_THRESHOLD):
    """
    Filtra los resultados del reranker según un umbral mínimo.

    Args:
        results: lista de resultados con un campo 'rerank_score'.
        threshold: puntuación mínima necesaria para conservar el resultado.

    Returns:
        Lista de resultados cuya puntuación alcanza el umbral.
    """

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
        ValueError: si el número de scores devuelto por el modelo
        no coincide con el número de resultados.
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
        reranked_result = result.copy()
        reranked_result["rerank_score"] = float(score)
        reranked_results.append(reranked_result)

    return sort_by_rerank_score(reranked_results)