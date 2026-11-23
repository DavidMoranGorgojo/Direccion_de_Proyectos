
from Agents.Agent_2.src.core import config


def _valor_vacio(valor):
    """
    Comprueba si un metadato no contiene información útil.

    Considera vacíos None, cadenas sin contenido y
    colecciones vacías.
    """

    if valor is None:
        return True

    if isinstance(valor, str):
        return not valor.strip()

    if isinstance(valor, (list, tuple, dict, set)):
        return len(valor) == 0

    return False


def _validar_chunk_id(result):
    """
    Valida el identificador de un resultado RRF.

    Admite cadenas no vacías y números enteros,
    incluido el identificador 0.

    Rechaza booleanos, listas y otros tipos
    que no representan identificadores válidos.
    """

    if not isinstance(result, dict) or "chunk_id" not in result:
        raise ValueError(
            "Resultado RRF inválido: falta el campo obligatorio 'chunk_id'"
        )

    chunk_id = result["chunk_id"]

    if isinstance(chunk_id, bool):
        raise ValueError(
            "Resultado RRF inválido: 'chunk_id' no puede ser booleano"
        )

    if isinstance(chunk_id, str):
        if not chunk_id.strip():
            raise ValueError(
                "Resultado RRF inválido: 'chunk_id' no puede estar vacío"
            )

    elif not isinstance(chunk_id, int):
        raise ValueError(
            "Resultado RRF inválido: 'chunk_id' "
            "debe ser una cadena no vacía o un entero"
        )

    return chunk_id


_CAMPOS_DOCUMENTALES_ESTABLES = frozenset({
    "texto", "documento", "seccion", "pagina", "versiones",
    "componente", "tipo_documento", "obsoleto", "sustituido_por",
    "vigente_para", "fecha_revision", "orden_en_seccion", "version_documento",
})


def _metadatos_equivalentes(campo, anterior, nuevo):
    if campo in {"versiones", "vigente_para"} and isinstance(anterior, (list, tuple)) and isinstance(nuevo, (list, tuple)):
        return set(anterior) == set(nuevo)
    return anterior == nuevo


def rrf(vector_results, bm25_results, k=None):
    """
    Fusiona dos rankings mediante Reciprocal Rank Fusion (RRF).

    Cada chunk contribuye como máximo una vez por ranking.
    Conserva los metadatos útiles de ambas fuentes y
    mantiene separadas las puntuaciones vectorial,
    BM25 y RRF.

    No exige el campo 'texto': su validación corresponde
    a la etapa de reranking.

    Args:
        vector_results: resultados de la búsqueda vectorial.
        bm25_results: resultados de la búsqueda BM25.
        k: constante RRF; por defecto, config.RRF_K.

    Returns:
        Resultados fusionados y ordenados por rrf_score.

    Raises:
        ValueError: si k o algún chunk_id son inválidos.
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

        # Evitar que un chunk sume varias veces
        # dentro de un mismo motor de búsqueda.
        ids_vistos = set()

        # La posición RRF se calcula entre resultados
        # únicos para que los duplicados no desplacen
        # artificialmente al resto de candidatos.
        posicion_unica = 0

        for result in ranking:

            chunk_id = _validar_chunk_id(result)

            if chunk_id not in chunks:
                chunks[chunk_id] = {}

            fusionado = chunks[chunk_id]

            # Conservar los metadatos útiles de ambas fuentes.
            # Un valor vacío puede sustituirse por otro
            # que sí contenga información.
            for campo, valor in result.items():
                if campo == "score":
                    continue

                if (campo in _CAMPOS_DOCUMENTALES_ESTABLES
                        and campo in fusionado
                        and not _valor_vacio(fusionado[campo])
                        and not _valor_vacio(valor)
                        and not _metadatos_equivalentes(campo, fusionado[campo], valor)):
                    raise ValueError(
                        f"Metadatos documentales contradictorios para chunk_id={chunk_id!r}: {campo}"
                    )

                if (
                    campo not in fusionado
                    or (
                        _valor_vacio(fusionado[campo])
                        and not _valor_vacio(valor)
                    )
                ):
                    fusionado[campo] = valor

            # Guardar la puntuación original de cada motor.
            # En caso de duplicados, conservar la primera
            # puntuación válida de esa fuente.
            if fuente == "vectorial":
                campo_score = "score_vectorial"
            else:
                campo_score = "score_bm25"

            if chunk_id not in ids_vistos:
                if campo_score in result:
                    score_original = result[campo_score]
                else:
                    score_original = result.get("score")

                if (
                    score_original is not None
                    and (
                        campo_score not in fusionado
                        or _valor_vacio(fusionado[campo_score])
                    )
                ):
                    fusionado[campo_score] = score_original

            # Los duplicados pueden completar metadatos,
            # pero nunca sumar otra contribución RRF.
            if chunk_id in ids_vistos:
                continue

            ids_vistos.add(chunk_id)
            posicion_unica += 1

            scores[chunk_id] = (
                scores.get(chunk_id, 0.0)
                + 1 / (k + posicion_unica)
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
