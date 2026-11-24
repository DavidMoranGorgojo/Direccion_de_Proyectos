"""Ampliación de candidatos con los chunks vecinos de su sección (A2-06).

Los vecinos aportan pasos intermedios y avisos de seguridad que podrían quedar
fuera del top-k. El Backend los devuelve de la misma sección y documento, de
modo que la ampliación nunca cruza manuales ni versiones.

Los vecinos no tienen puntuación de reranking. Se marcan con ``es_vecino`` y
el empaquetado CTR-004 (A2-07) decide su ``score_final``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..core.errors import BackendRequestError


def _require_parents(candidates):
    if not isinstance(candidates, (list, tuple)):
        raise TypeError("candidates debe ser una lista.")

    parents = []
    parent_ids = set()

    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise TypeError(
                f"El candidato en la posición {position} debe ser un objeto."
            )

        chunk_id = candidate.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError(
                f"El candidato en la posición {position} no tiene 'chunk_id'."
            )

        if chunk_id in parent_ids:
            raise ValueError(f"chunk_id duplicado: {chunk_id}")

        parent_ids.add(chunk_id)
        parents.append(dict(candidate))

    return parents, parent_ids


def _order_key(chunk):
    order = chunk.get("orden_en_seccion")
    if type(order) is not int:
        order = 0

    return order, chunk.get("chunk_id") or ""


def _fetch(fetch_neighbors, chunk_id):
    try:
        neighbors = fetch_neighbors(chunk_id)
    except BackendRequestError:
        raise
    except Exception as error:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"No se pudieron recuperar los vecinos de {chunk_id}.",
        ) from error

    if not isinstance(neighbors, (list, tuple)):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"La respuesta de vecinos de {chunk_id} no es una lista.",
        )

    return neighbors


def _neighbor_item(neighbor, parent):
    if not isinstance(neighbor, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"La respuesta de vecinos de {parent['chunk_id']} contiene un "
            "elemento que no es un objeto.",
        )

    chunk_id = neighbor.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise BackendRequestError(
            "servicio_no_disponible",
            f"Un vecino de {parent['chunk_id']} no tiene 'chunk_id'.",
        )

    documento = parent.get("documento")
    if documento is not None and neighbor.get("documento") != documento:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El vecino {chunk_id} no pertenece al documento "
            f"{documento}.",
        )

    seccion = parent.get("seccion")
    if seccion is not None and neighbor.get("seccion") != seccion:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El vecino {chunk_id} no pertenece a la sección {seccion}.",
        )

    edition = parent.get("version_documento")
    if edition is not None and neighbor.get("version_documento") != edition:
        return None

    item = dict(neighbor)
    item["es_vecino"] = True
    return item


def expand_with_neighbors(candidates, fetch_neighbors=None, max_workers=4):
    """Devuelve los candidatos con sus vecinos de sección ya integrados.

    ``fetch_neighbors(chunk_id)`` debe devolver la lista de chunks vecinos que
    el Backend considera adyacentes (±1). Si es ``None`` solo se marcan los
    candidatos como no vecinos. Un fallo del Backend se propaga como
    :class:`BackendRequestError` para que el estado final sea ``error``.
    """
    if fetch_neighbors is not None and not callable(fetch_neighbors):
        raise TypeError("fetch_neighbors debe ser invocable o None.")

    parents, parent_ids = _require_parents(candidates)

    if fetch_neighbors is None:
        for parent in parents:
            parent["es_vecino"] = False
        return parents

    # Pide los vecinos en paralelo conservando el orden y propagando excepciones
    fetched_by_id = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(_fetch, fetch_neighbors, parent["chunk_id"]): parent["chunk_id"]
            for parent in parents
        }
        for future in future_to_id:
            cid = future_to_id[future]
            fetched_by_id[cid] = future.result()

    expanded = []
    emitted = set()

    for parent in parents:
        fetched = [
            _neighbor_item(neighbor, parent)
            for neighbor in fetched_by_id[parent["chunk_id"]]
        ]
        fetched = [item for item in fetched if item is not None]
        neighbor_items = [
            item
            for item in fetched
            if item["chunk_id"] != parent["chunk_id"]
        ]

        parent_item = dict(parent)
        parent_item["es_vecino"] = False

        block = neighbor_items + [parent_item]
        block.sort(key=_order_key)

        for item in block:
            chunk_id = item["chunk_id"]

            if chunk_id in emitted:
                continue

            # Un vecino que también es candidato se emite como candidato, con
            # su puntuación, en su posición de ranking.
            if item["es_vecino"] and chunk_id in parent_ids:
                continue

            emitted.add(chunk_id)
            expanded.append(item)

    return expanded


__all__ = ["expand_with_neighbors"]
