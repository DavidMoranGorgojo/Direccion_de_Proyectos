"""Cliente HTTP para las rutas de conocimiento del Backend (A2-01).

Implementa el acceso por API a:
  * ``POST /conocimiento/vectorial``
  * ``POST /conocimiento/lexica``
  * ``GET /conocimiento/chunks/{chunk_id}?vecinos=1``

Aplica el principio de No Duplicidad: el cliente de producción delega el
almacenamiento y las búsquedas en el Backend y no mantiene índices locales.
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

import requests

from ..core.config import EMBEDDING_DIMENSION, SEARCH_TOP_K, SERVICE_TOKEN
from ..core.errors import (
    CODIGO_ERROR_POR_DEFECTO,
    CODIGOS_ERROR,
    BackendRequestError,
)
from ..services.lexical_parser import parse_lexical_response
from ..testing.local_index import (
    get_chunk_with_neighbors,
    load_chunks,
    search_lexical,
    search_vector,
)

CTR002_FILTER_FIELDS = ("version", "componente")


def ctr002_filters(filtros):
    """Reduce los filtros internos a la forma que admite CTR-002 §3.

    El Backend solo acepta ``version``, ``componente`` y ``tipo_documento``, con
    un único valor por campo y sin campos extra (§5.1 prohíbe enviar códigos de
    avería como filtro). ``codigos`` e ``incluir_obsoletos`` son filtros locales
    del Agente 2 y no viajan al Backend.
    """
    if filtros is None:
        return {}

    if not isinstance(filtros, dict):
        raise TypeError("filtros debe ser un diccionario o None.")

    limpios = {}

    for campo in CTR002_FILTER_FIELDS:
        valor = filtros.get(campo)

        if valor is None:
            continue

        if not isinstance(valor, str):
            raise TypeError(f"filtros.{campo} debe ser texto o None.")

        if valor.strip():
            limpios[campo] = valor

    tipos = filtros.get("tipo_documento")

    if isinstance(tipos, str):
        tipos = [tipos]

    if tipos:
        if not isinstance(tipos, (list, tuple)):
            raise TypeError(
                "filtros.tipo_documento debe ser texto o una lista de texto."
            )

        unicos = []

        for tipo in tipos:
            if not isinstance(tipo, str):
                raise TypeError(
                    "filtros.tipo_documento debe contener solo texto."
                )

            if tipo.strip() and tipo not in unicos:
                unicos.append(tipo)

        if len(unicos) > 1:
            raise ValueError(
                "CTR-002 solo admite un tipo_documento por petición; "
                f"se recibieron {unicos}."
            )

        if unicos:
            limpios["tipo_documento"] = unicos[0]

    return limpios


def split_ctr002_requests(filtros: dict | None) -> list[dict]:
    """Divide un diccionario de filtros en múltiples diccionarios compatibles con CTR-002 (ALB-7).

    CTR-002 solo admite un tipo_documento por petición. Si filtros['tipo_documento']
    contiene una lista con varios tipos, devuelve un diccionario por cada tipo,
    manteniendo 'version' y 'componente' idénticos.
    """
    if not isinstance(filtros, dict) or not filtros:
        return [{}]

    tipos = filtros.get("tipo_documento")
    if isinstance(tipos, (list, tuple)) and len(tipos) > 1:
        reqs = []
        for t in tipos:
            f = dict(filtros)
            f["tipo_documento"] = t
            reqs.append(f)
        return reqs

    return [dict(filtros)]


REQUIRED_CHUNK_FIELDS = {
    "chunk_id",
    "texto",
    "documento",
    "seccion",
    "pagina",
    "versiones",
    "componente",
    "tipo_documento",
    "obsoleto",
    "sustituido_por",
    "vigente_para",
    "fecha_revision",
    "orden_en_seccion",
    "version_documento",
    "afectado_por",
    "ids_referenciados",
}


class BackendAPIClient:
    def __init__(
        self,
        base_url,
        model_embeddings,
        session=None,
        timeout=5,
        token=None,
        connect_timeout=None,
    ):
        """``timeout`` es el de lectura; con ``connect_timeout`` se envía a
        ``requests`` el par ``(conexión, lectura)`` para fallar rápido si el
        Backend no acepta la conexión sin recortar el tiempo de búsqueda."""
        self.base_url = base_url.rstrip("/")
        self.model_embeddings = model_embeddings
        self.timeout = (
            timeout if connect_timeout is None else (connect_timeout, timeout)
        )
        self.token = (
            SERVICE_TOKEN if token is None else str(token)
        ).strip()

        if session is None:
            session = requests.Session()

        self.session = session

    def __repr__(self):
        # Nunca mostrar el token de servicio (logs, trazas, depuración).
        return (
            f"BackendAPIClient(base_url={self.base_url!r}, "
            f"model_embeddings={self.model_embeddings!r}, "
            f"timeout={self.timeout!r}, token={'***' if self.token else None})"
        )

    def _auth_kwargs(self):
        """Cabecera de servicio solo cuando hay token configurado."""
        if not self.token:
            return {}

        return {"headers": {"Authorization": f"Bearer {self.token}"}}

    def _post_conocimiento(self, ruta, payload):
        """Helper privado con mapeo exhaustivo de errores según CTR-002 (ALB-7).

        No utiliza raise_for_status() directamente para poder inspeccionar el
        código HTTP y el cuerpo de la respuesta antes de decidir el código de
        error contractual (entrada_invalida, modelo_incompatible, etc.).
        """
        try:
            response = self.session.post(
                f"{self.base_url}{ruta}",
                json=payload,
                timeout=self.timeout,
                **self._auth_kwargs(),
            )
        except requests.ConnectTimeout as error:
            # El Backend no aceptó la conexión a tiempo: no está disponible.
            # (ConnectTimeout hereda de Timeout; va antes para no confundirlo
            # con una búsqueda lenta, que sí es tiempo_agotado.)
            raise BackendRequestError(
                "servicio_no_disponible",
                "Tiempo de conexión agotado: el Backend no acepta conexiones.",
            ) from error
        except requests.Timeout as error:
            raise BackendRequestError(
                "tiempo_agotado",
                f"Tiempo agotado al contactar con el Backend en {ruta}.",
            ) from error
        except requests.ConnectionError as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"No se pudo conectar con el Backend en {ruta}.",
            ) from error
        except requests.RequestException as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                # Sin el texto de la excepción: podría incluir datos de la
                # petición. La causa queda encadenada para depurar.
                f"Error de red al contactar con el Backend en {ruta} "
                f"({type(error).__name__}).",
            ) from error

        if response.status_code >= 400:
            codigo = _backend_error_code(response)
            raise BackendRequestError(
                codigo,
                f"El Backend devolvió error HTTP {response.status_code} en {ruta}.",
            )

        try:
            return response.json()
        except (TypeError, ValueError) as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El Backend devolvió una respuesta no JSON en {ruta}.",
            ) from error

    def search_vector(self, vector, filtros=None, k=None):
        if k is None:
            k = SEARCH_TOP_K

        if hasattr(vector, "tolist"):
            vector = vector.tolist()

        if (
            not isinstance(vector, (list, tuple))
            or len(vector) != EMBEDDING_DIMENSION
        ):
            raise ValueError(
                "El vector debe contener exactamente "
                f"{EMBEDDING_DIMENSION} valores."
            )

        payload = {
            "vector": list(vector),
            "modelo_embeddings": self.model_embeddings,
            "filtros": ctr002_filters(filtros),
            "k": k,
        }

        return self._post_conocimiento("/conocimiento/vectorial", payload)

    def search_lexical(self, text, filtros=None, k=None):
        if k is None:
            k = SEARCH_TOP_K

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text debe ser texto no vacío.")

        payload = {
            "texto": text,
            "filtros": ctr002_filters(filtros),
            "k": k,
        }

        return self._post_conocimiento("/conocimiento/lexica", payload)

    def search_lexical_candidates(self, text, filtros=None, k=None):
        """Solicita la búsqueda léxica y valida la respuesta de CTR-002."""
        if k is None:
            k = SEARCH_TOP_K

        payload = self.search_lexical(text=text, filtros=filtros, k=k)

        # Validación del modelo de embeddings (ALB-7.6)
        indice_info = payload.get("indice", {})
        modelo_resp = indice_info.get("modelo_embeddings")
        if modelo_resp and modelo_resp != self.model_embeddings:
            raise BackendRequestError(
                "modelo_incompatible",
                f"Modelo de embeddings incompatible: esperado {self.model_embeddings}, "
                f"obtenido {modelo_resp}.",
            )

        return parse_lexical_response(payload)

    def get_chunk(self, chunk_id, vecinos=1):
        """Recupera un fragmento y, opcionalmente, sus vecinos de sección."""
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("chunk_id debe ser texto no vacío.")

        if type(vecinos) is not int or vecinos not in (0, 1):
            raise ValueError("vecinos debe ser 0 o 1.")

        url = (
            f"{self.base_url}/conocimiento/chunks/"
            f"{quote(chunk_id, safe='')}"
        )

        try:
            response = self.session.get(
                url,
                params={"vecinos": vecinos},
                timeout=self.timeout,
                **self._auth_kwargs(),
            )
        except requests.ConnectTimeout as error:
            # El Backend no aceptó la conexión a tiempo: no está disponible.
            # (ConnectTimeout hereda de Timeout; va antes para no confundirlo
            # con una búsqueda lenta, que sí es tiempo_agotado.)
            raise BackendRequestError(
                "servicio_no_disponible",
                "Tiempo de conexión agotado: el Backend no acepta conexiones.",
            ) from error
        except requests.Timeout as error:
            raise BackendRequestError(
                "tiempo_agotado",
                f"Tiempo agotado al recuperar el fragmento {chunk_id}.",
            ) from error
        except requests.RequestException as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"No se pudo contactar con el Backend al recuperar el "
                f"fragmento {chunk_id}.",
            ) from error

        if response.status_code >= 400:
            raise _chunk_request_error(response, chunk_id)

        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El Backend devolvió una respuesta no JSON para el "
                f"fragmento {chunk_id}.",
            ) from error

        return _parse_chunk_response(payload, chunk_id)

    def get_neighbors(self, chunk_id):
        """Recupera solo los vecinos de sección de un fragmento dado."""
        result = self.get_chunk(chunk_id, vecinos=1)
        return result["vecinos"]

    def get_catalogo(self, nombre):
        """Descarga un catálogo versionado desde el Backend (CTR-002 §2).

        Args:
            nombre: Uno de 'codigos', 'terminos', 'vehiculos', 'componentes'.

        Returns:
            dict con {'nombre': ..., 'version': ..., 'contenido': ...}

        Raises:
            ValueError: Si el nombre del catálogo no es válido.
            BackendRequestError: Si el catálogo no existe (indice_no_disponible) o hay error HTTP/red.
        """
        validos = {"codigos", "terminos", "vehiculos", "componentes"}
        if not isinstance(nombre, str) or nombre not in validos:
            raise ValueError(
                f"Nombre de catálogo inválido: {nombre!r}. Debe ser uno de {sorted(validos)}."
            )

        url = f"{self.base_url}/catalogos/{quote(nombre, safe='')}"
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                **self._auth_kwargs(),
            )
        except requests.ConnectTimeout as error:
            # El Backend no aceptó la conexión a tiempo: no está disponible.
            # (ConnectTimeout hereda de Timeout; va antes para no confundirlo
            # con una búsqueda lenta, que sí es tiempo_agotado.)
            raise BackendRequestError(
                "servicio_no_disponible",
                "Tiempo de conexión agotado: el Backend no acepta conexiones.",
            ) from error
        except requests.Timeout as error:
            raise BackendRequestError(
                "tiempo_agotado",
                f"Tiempo agotado al recuperar el catálogo {nombre}.",
            ) from error
        except requests.RequestException as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"No se pudo contactar con el Backend al recuperar el catálogo "
                f"{nombre} ({type(error).__name__}).",
            ) from error

        if response.status_code == 404:
            raise BackendRequestError(
                "indice_no_disponible",
                f"El catálogo {nombre!r} no existe en el Backend o el índice no está disponible.",
            )

        if response.status_code >= 400:
            codigo = _backend_error_code(response)
            raise BackendRequestError(
                codigo,
                f"El Backend devolvió error HTTP {response.status_code} al recuperar el catálogo {nombre}.",
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El Backend devolvió una respuesta no JSON para el catálogo {nombre}.",
            ) from error

        if not isinstance(payload, dict):
            raise BackendRequestError(
                "servicio_no_disponible",
                f"Respuesta inválida para el catálogo {nombre}: se esperaba un objeto JSON.",
            )

        if "contenido" not in payload:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"Respuesta incompleta para el catálogo {nombre}: falta el campo 'contenido'.",
            )

        return payload

    def get_info(self):
        """Consulta la ficha real del índice sin sustituirla por datos locales."""
        try:
            response = self.session.get(
                f"{self.base_url}/conocimiento/info", timeout=self.timeout, **self._auth_kwargs()
            )
        except requests.ConnectTimeout as error:
            # El Backend no aceptó la conexión a tiempo: no está disponible.
            # (ConnectTimeout hereda de Timeout; va antes para no confundirlo
            # con una búsqueda lenta, que sí es tiempo_agotado.)
            raise BackendRequestError(
                "servicio_no_disponible",
                "Tiempo de conexión agotado: el Backend no acepta conexiones.",
            ) from error
        except requests.Timeout as error:
            raise BackendRequestError("tiempo_agotado", "Tiempo agotado consultando el índice.") from error
        except requests.RequestException as error:
            raise BackendRequestError("servicio_no_disponible", "Backend no disponible.") from error
        if response.status_code >= 400:
            raise BackendRequestError(_backend_error_code(response), "No se pudo consultar la ficha del índice.")
        try:
            info = response.json()
        except (TypeError, ValueError) as error:
            raise BackendRequestError("servicio_no_disponible", "Ficha del índice no JSON.") from error
        if not isinstance(info, dict) or not isinstance(info.get("version"), str) or not info["version"].strip():
            raise BackendRequestError("indice_no_disponible", "Ficha del índice malformada.")
        if info.get("modelo_embeddings") != self.model_embeddings:
            raise BackendRequestError("modelo_incompatible", "El modelo de la ficha no coincide con A2.")
        if info.get("dimensiones") != EMBEDDING_DIMENSION:
            raise BackendRequestError("modelo_incompatible", "Dimensión de índice incompatible.")
        return info


def _invalid_chunk_fields(chunk, require_fecha_revision=True):
    problems = []

    text_fields = (
        "chunk_id",
        "texto",
        "documento",
        "seccion",
        "componente",
        "tipo_documento",
        "version_documento",
    )

    for field in text_fields:
        value = chunk.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field} debe ser texto no vacío")

    pagina = chunk.get("pagina")
    if type(pagina) is not int or pagina <= 0:
        problems.append("pagina debe ser un entero mayor que cero")

    orden = chunk.get("orden_en_seccion")
    if type(orden) is not int or orden <= 0:
        problems.append("orden_en_seccion debe ser un entero mayor que cero")

    versiones = chunk.get("versiones")
    if (
        not isinstance(versiones, list)
        or not versiones
        or any(not isinstance(value, str) or not value.strip() for value in versiones)
    ):
        problems.append("versiones debe ser una lista no vacía de textos")

    if type(chunk.get("obsoleto")) is not bool:
        problems.append("obsoleto debe ser booleano")

    for field in ("vigente_para", "afectado_por", "ids_referenciados"):
        values = chunk.get(field)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in values
        ):
            problems.append(f"{field} debe ser una lista de textos")

    sustituido_por = chunk.get("sustituido_por")
    if sustituido_por is not None and (
        not isinstance(sustituido_por, str) or not sustituido_por.strip()
    ):
        problems.append("sustituido_por debe ser texto o null")

    fecha_revision = chunk.get("fecha_revision")
    if fecha_revision is None and not require_fecha_revision:
        pass
    else:
        try:
            if not isinstance(fecha_revision, str):
                raise TypeError
            date.fromisoformat(fecha_revision)
        except (TypeError, ValueError):
            problems.append("fecha_revision debe tener formato YYYY-MM-DD")

    return problems


def _backend_error_code(response):
    raw_code = None
    try:
        cuerpo = response.json()
        if isinstance(cuerpo, dict):
            # Check top-level keys first
            for candidate in (cuerpo.get("codigo_error"), cuerpo.get("codigo")):
                if isinstance(candidate, str) and candidate.strip():
                    raw_code = candidate.strip()
                    break
            # Also check nested detail.codigo
            if raw_code is None:
                detail = cuerpo.get("detail")
                if isinstance(detail, dict):
                    candidate = detail.get("codigo")
                    if isinstance(candidate, str) and candidate.strip():
                        raw_code = candidate.strip()
    except (TypeError, ValueError):
        pass

    # Map input-validation backend codes to canonical entrada_invalida
    if raw_code in ("peticion_invalida", "filtro_invalido"):
        return "entrada_invalida"

    # Map recurso_no_encontrado (404) to indice_no_disponible
    if raw_code == "recurso_no_encontrado":
        return "indice_no_disponible"

    if raw_code in CODIGOS_ERROR:
        return raw_code

    if response.status_code == 409:
        return "modelo_incompatible"
    elif response.status_code == 504:
        return "tiempo_agotado"
    elif response.status_code == 400 or response.status_code == 422:
        return "entrada_invalida"
    elif response.status_code == 404:
        return "indice_no_disponible"
    elif response.status_code == 503 and raw_code is None:
        return "indice_no_disponible"
    else:
        return CODIGO_ERROR_POR_DEFECTO


def _chunk_request_error(response, chunk_id):
    codigo = _backend_error_code(response)
    mensaje = (
        f"El Backend devolvió error {response.status_code} al recuperar el "
        f"fragmento {chunk_id}."
    )
    return BackendRequestError(codigo, mensaje)


def _parse_chunk_response(payload, chunk_id):
    if not isinstance(payload, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"La respuesta de {chunk_id} no es un objeto JSON.",
        )

    indice = payload.get("indice")
    if not isinstance(indice, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"Falta el bloque 'indice' en la respuesta de {chunk_id}.",
        )

    version = indice.get("version")
    if not isinstance(version, str) or not version.strip():
        raise BackendRequestError(
            "servicio_no_disponible",
            f"La versión del índice no es válida en la respuesta de {chunk_id}.",
        )

    chunk = payload.get("chunk")
    if not isinstance(chunk, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"Falta el bloque 'chunk' en la respuesta de {chunk_id}.",
        )

    vecinos = payload.get("vecinos")
    if not isinstance(vecinos, list):
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El bloque 'vecinos' debe ser una lista en la respuesta de {chunk_id}.",
        )

    problems = _invalid_chunk_fields(chunk, require_fecha_revision=False)
    if problems:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El fragmento {chunk_id} no cumple CTR-002: {'; '.join(problems)}.",
        )

    if chunk.get("chunk_id") != chunk_id:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El Backend devolvió el fragmento {chunk.get('chunk_id')!r} en lugar de {chunk_id!r}.",
        )

    valid_neighbors = []
    seen = {chunk_id}

    for position, neighbor in enumerate(vecinos):
        if not isinstance(neighbor, dict):
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El vecino en la posición {position} no es un objeto.",
            )

        problems = _invalid_chunk_fields(neighbor, require_fecha_revision=False)
        if problems:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El vecino en la posición {position} no cumple CTR-002: {'; '.join(problems)}.",
            )

        neighbor_id = neighbor["chunk_id"]
        if neighbor_id in seen:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"Vecino duplicado o igual al fragmento: {neighbor_id}.",
            )

        if (
            neighbor.get("documento") != chunk.get("documento")
            or neighbor.get("seccion") != chunk.get("seccion")
        ):
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El vecino {neighbor_id} no pertenece a la misma sección que {chunk_id}.",
            )

        seen.add(neighbor_id)
        valid_neighbors.append(neighbor)

    return {
        "indice": {"version": version},
        "chunk": chunk,
        "vecinos": valid_neighbors,
    }


__all__ = [
    "CTR002_FILTER_FIELDS",
    "REQUIRED_CHUNK_FIELDS",
    "BackendAPIClient",
    "ctr002_filters",
    "get_chunk_with_neighbors",
    "load_chunks",
    "search_lexical",
    "search_vector",
    "split_ctr002_requests",
]
