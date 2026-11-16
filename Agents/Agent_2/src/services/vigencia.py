"""Estados de recuperación y vigencia de los candidatos (A2-06).

El estado se decide con los candidatos que ya superaron el umbral del reranker
(A2-05):

* ``suficiente``: hay evidencia vigente y la consulta permite elegir.
* ``ambiguo``: hay evidencia vigente de versiones o componentes distintos y la
  consulta no fija ese campo. Se indica ``campo_ambiguo``.
* ``solo_obsoleto``: todo lo recuperado está obsoleto o sustituido.
* ``insuficiente``: no hay candidatos (lista vacía válida).
* ``error``: fallo del Backend al recuperar los vecinos. Nunca se confunde con
  ``insuficiente``.

La vigencia se calcula con ``versiones``, ``vigente_para``, ``obsoleto`` y
``sustituido_por``. Un documento sustituido sigue vigente para las versiones
que figuran en ``vigente_para``.
"""

from __future__ import annotations

from ..core.errors import BackendRequestError, CODIGO_ERROR_POR_DEFECTO
from ..models.retrieval import RetrievalDecision, RetrievalResult
from .filters import normalize_component, normalize_version, version_applies
from .neighbors import expand_with_neighbors


DOCUMENT_STATES = frozenset({"vigente", "obsoleto", "sustituido"})


def _require_candidates(candidates):
    if not isinstance(candidates, (list, tuple)):
        raise TypeError("candidates debe ser una lista.")

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

    return list(candidates)


def document_state(chunk, version=None):
    """Calcula ``vigente``, ``obsoleto`` o ``sustituido`` para un chunk."""

    if not isinstance(chunk, dict):
        raise TypeError("chunk debe ser un diccionario.")

    version = normalize_version(version)
    obsoleto = chunk.get("obsoleto") is True
    sustituido = chunk.get("sustituido_por") is not None

    if version is not None:
        # Un documento sustituido sigue vigente para versiones anteriores.
        if version in (chunk.get("vigente_para") or []) and (
            obsoleto or sustituido
        ):
            return "vigente"

        # Un chunk de otra versión no es válido para la solicitada.
        if not version_applies(chunk, version):
            return "sustituido" if sustituido else "obsoleto"

    if sustituido:
        return "sustituido"

    if obsoleto:
        return "obsoleto"

    return "vigente"


def is_current(chunk, version=None):
    """Indica si el chunk está vigente para la versión solicitada."""

    return document_state(chunk, version) == "vigente"


def common_version(candidates):
    """Versión que aplica a todos los candidatos, o ``None`` si no existe.

    Evita marcar como ambiguos dos fragmentos que comparten al menos una
    versión, aunque sus rangos no sean idénticos.
    """

    common = None

    for candidate in candidates:
        versiones = {
            version
            for version in (candidate.get("versiones") or [])
            if isinstance(version, str) and version.strip()
        }
        common = versiones if common is None else common & versiones

        if not common:
            return None

    return common


def classify_state(candidates, filters=None):
    """Decide el estado a partir de los candidatos sobre el umbral."""

    candidates = _require_candidates(candidates)
    filters = filters or {}

    if not isinstance(filters, dict):
        raise TypeError("filters debe ser un diccionario.")

    if not candidates:
        return RetrievalDecision("insuficiente")

    version = normalize_version(filters.get("version"))
    component = normalize_component(filters.get("componente"))

    current = [candidate for candidate in candidates if is_current(candidate, version)]

    if not current:
        return RetrievalDecision("solo_obsoleto")

    # La versión es la ambigüedad prioritaria: condiciona la compatibilidad.
    if version is None and common_version(current) is None:
        return RetrievalDecision("ambiguo", campo_ambiguo="version")

    if component is None:
        components = {candidate.get("componente") for candidate in current}
        if len(components) > 1:
            return RetrievalDecision("ambiguo", campo_ambiguo="componente")

    return RetrievalDecision("suficiente")


def resolve_retrieval(candidates, filters=None, fetch_neighbors=None):
    """Calcula el estado y amplía los candidatos con sus vecinos.

    Si el Backend falla al recuperar vecinos, el resultado es ``error`` con el
    ``codigo_error`` estándar; nunca una lista vacía.
    """

    filters = filters or {}
    decision = classify_state(candidates, filters)

    if decision.estado == "insuficiente":
        return RetrievalResult(estado="insuficiente", candidatos=[])

    version = normalize_version(filters.get("version"))

    try:
        expanded = expand_with_neighbors(candidates, fetch_neighbors)
    except BackendRequestError as error:
        return RetrievalResult(
            estado="error",
            candidatos=[],
            codigo_error=error.codigo_error,
            mensaje_error=error.mensaje,
        )
    except Exception:
        return RetrievalResult(
            estado="error",
            candidatos=[],
            codigo_error=CODIGO_ERROR_POR_DEFECTO,
            mensaje_error="Fallo inesperado al recuperar los vecinos.",
        )

    for candidate in expanded:
        candidate["estado_documento"] = document_state(candidate, version)

    return RetrievalResult(
        estado=decision.estado,
        candidatos=expanded,
        campo_ambiguo=decision.campo_ambiguo,
    )


__all__ = [
    "DOCUMENT_STATES",
    "classify_state",
    "common_version",
    "document_state",
    "is_current",
    "resolve_retrieval",
]
