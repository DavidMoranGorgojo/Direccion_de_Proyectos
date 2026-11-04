def rrf(vector_results, bm25_results, k=60):
    """
    Fusiona dos rankings utilizando Reciprocal Rank Fusion (RRF).

    Args:
        vector_results: resultados de la búsqueda vectorial.
        bm25_results: resultados de la búsqueda BM25.
        k: constante de RRF. Por defecto, 60.

    Returns:
        Lista de resultados ordenada por puntuación RRF.
    """

    scores = {}
    chunks = {}

    for ranking in [vector_results, bm25_results]:
        for position, result in enumerate(ranking, start=1):

            # Validar que el resultado tenga un identificador válido.
            if not isinstance(result, dict) or not result.get("chunk_id"):
                raise ValueError(
                    "Resultado RRF inválido: falta el campo obligatorio 'chunk_id'"
                )

            chunk_id = result["chunk_id"]

            chunks[chunk_id] = result

            if chunk_id not in scores:
                scores[chunk_id] = 0.0

            scores[chunk_id] += 1 / (k + position)

    fused_results = []

    for chunk_id, score in scores.items():
        result = chunks[chunk_id].copy()
        result["rrf_score"] = score
        fused_results.append(result)

    fused_results.sort(
        key=lambda result: result["rrf_score"],
        reverse=True
    )

    return fused_results