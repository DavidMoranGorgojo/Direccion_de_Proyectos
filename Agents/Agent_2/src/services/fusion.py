
from Agents.Agent_2.src.core import config


def rrf(vector_results, bm25_results, k=None):
    """
    Fusiona dos rankings mediante Reciprocal Rank Fusion (RRF).

    Conserva los metadatos de ambas fuentes y mantiene
    separadas las puntuaciones vectorial, BM25 y RRF.

    No exige el campo 'texto': su validación corresponde
    a la etapa de reranking.

    Args:
        vector_results: resultados de la búsqueda vectorial.
        bm25_results: resultados de la búsqueda BM25.
        k: constante RRF; por defecto, config.RRF_K.

    Returns:
        Resultados fusionados y ordenados por rrf_score.

    Raises:
        ValueError: si k es inválido o falta chunk_id.
    """

    if k is None:
        k = config.RRF_K

    if type(k) is not int or k <= 0:
        raise ValueError(
            "El parámetro k de RRF debe ser un entero mayor que cero"
        )

    scores = {}
    chunks = {}

    rankings = [
        ("vectorial", vector_results),
        ("bm25", bm25_results),
    ]

    for fuente, ranking in rankings:
        for position, result in enumerate(ranking, start=1):

            if not isinstance(result, dict) or not result.get("chunk_id"):
                raise ValueError(
                    "Resultado RRF inválido: falta el campo obligatorio 'chunk_id'"
                )

            chunk_id = result["chunk_id"]

            if chunk_id not in chunks:
                chunks[chunk_id] = {}

            fusionado = chunks[chunk_id]

            # Incorporar campos de ambas fuentes sin sobrescribir
            # metadatos existentes con valores vacíos.
            for campo, valor in result.items():
                if campo == "score":
                    continue

                if campo not in fusionado or fusionado[campo] is None:
                    fusionado[campo] = valor

            # Guardar la puntuación original con un nombre
            # específico para cada motor de búsqueda.
            if fuente == "vectorial":
                if "score_vectorial" in result:
                    fusionado["score_vectorial"] = result["score_vectorial"]
                elif "score" in result:
                    fusionado["score_vectorial"] = result["score"]

            elif fuente == "bm25":
                if "score_bm25" in result:
                    fusionado["score_bm25"] = result["score_bm25"]
                elif "score" in result:
                    fusionado["score_bm25"] = result["score"]

            scores[chunk_id] = (
                scores.get(chunk_id, 0.0)
                + 1 / (k + position)
            )

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
