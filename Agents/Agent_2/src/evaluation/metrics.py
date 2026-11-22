"""Métricas de evaluación para los rankings del Agente 2.

Las funciones trabajan con identificadores de chunk y etiquetas de relevancia.
No modifican las entradas y no dependen del modelo ni del pipeline.
``calibration.py`` las usa para calcular Recall@k y MRR por umbral, solo sobre
las consultas con relevantes.

Criterios comunes:

- El ranking es una lista o tupla ordenada de identificadores únicos.
- Los documentos relevantes son una colección de identificadores únicos.
- ``k`` debe ser un entero mayor que cero.
- Un ranking vacío es válido y produce ``0.0`` en las métricas que dependen
  del ranking, siempre que existan documentos relevantes.
- Una consulta sin documentos relevantes produce ``ValueError`` porque
  Recall@k y MRR no están definidos en ese caso.
- Precision@k usa ``k`` como denominador. Si el ranking contiene menos de
  ``k`` resultados, las posiciones ausentes se consideran no relevantes.
"""


def _validar_k(k):
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k debe ser un entero mayor que cero")
    return k


def _validar_ids(ids, nombre):
    for chunk_id in ids:
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError(
                f"{nombre} debe contener identificadores de chunk no vacíos"
            )


def _validar_ranking(ranked_chunk_ids):
    if not isinstance(ranked_chunk_ids, (list, tuple)):
        raise ValueError("El ranking debe ser una lista o tupla")

    ranking = list(ranked_chunk_ids)
    _validar_ids(ranking, "El ranking")

    if len(ranking) != len(set(ranking)):
        raise ValueError("El ranking no puede tener duplicados")

    return ranking


def _validar_relevantes(relevant_chunk_ids):
    if isinstance(relevant_chunk_ids, (str, bytes)) or not isinstance(
        relevant_chunk_ids, (list, tuple, set, frozenset)
    ):
        raise ValueError("Los relevantes deben ser identificadores")

    relevantes = list(relevant_chunk_ids)
    _validar_ids(relevantes, "Los documentos relevantes")

    if len(relevantes) != len(set(relevantes)):
        raise ValueError("Los relevantes no pueden tener duplicados")

    if not relevantes:
        raise ValueError("No se puede calcular sin documentos relevantes")

    return set(relevantes)


def precision_at_k(ranked_chunk_ids, relevant_chunk_ids, k):
    """Calcula la proporción de documentos relevantes en el top-k.

    El denominador es ``k``, aunque el ranking contenga menos resultados.
    Las posiciones ausentes se consideran no relevantes.
    """

    _validar_k(k)
    ranking = _validar_ranking(ranked_chunk_ids)
    relevantes = _validar_relevantes(relevant_chunk_ids)

    relevantes_recuperados = sum(
        1 for chunk_id in ranking[:k] if chunk_id in relevantes
    )
    return relevantes_recuperados / k


def recall_at_k(ranked_chunk_ids, relevant_chunk_ids, k):
    """Calcula la proporción de documentos relevantes recuperados.

    La métrica se limita a los primeros ``k`` resultados.
    """

    _validar_k(k)
    ranking = _validar_ranking(ranked_chunk_ids)
    relevantes = _validar_relevantes(relevant_chunk_ids)

    relevantes_recuperados = sum(
        1 for chunk_id in ranking[:k] if chunk_id in relevantes
    )
    return relevantes_recuperados / len(relevantes)


def reciprocal_rank(ranked_chunk_ids, relevant_chunk_ids):
    """Calcula el recíproco de la posición del primer documento relevante.

    Devuelve ``0.0`` si ningún documento relevante aparece en el ranking.
    """

    ranking = _validar_ranking(ranked_chunk_ids)
    relevantes = _validar_relevantes(relevant_chunk_ids)

    for posicion, chunk_id in enumerate(ranking, start=1):
        if chunk_id in relevantes:
            return 1.0 / posicion

    return 0.0


def mean_reciprocal_rank(rankings, relevantes_por_consulta):
    """Calcula la media del recíproco de la posición del primer relevante.

    ``rankings`` y ``relevantes_por_consulta`` son secuencias paralelas con
    un ranking y un conjunto de documentos relevantes por consulta.
    """

    if not isinstance(rankings, (list, tuple)):
        raise ValueError("Rankings debe ser lista o tupla de rankings")

    if not isinstance(relevantes_por_consulta, (list, tuple)):
        raise ValueError("Relevantes debe ser lista o tupla de colecciones")

    if not rankings:
        raise ValueError("Se necesita al menos una consulta para calcular MRR")

    if len(rankings) != len(relevantes_por_consulta):
        raise ValueError(
            "Debe haber un conjunto de documentos relevantes por cada ranking"
        )

    total = 0.0
    for ranking, relevantes in zip(rankings, relevantes_por_consulta):
        total += reciprocal_rank(ranking, relevantes)

    return total / len(rankings)
