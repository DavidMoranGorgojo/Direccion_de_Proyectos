import json
import warnings
from datetime import date
from pathlib import Path
from collections import Counter
import math
import re
import unicodedata
from urllib.parse import quote

import requests

from ..core.config import EMBEDDING_DIMENSION, SEARCH_TOP_K, SERVICE_TOKEN
from ..core.errors import (
    CODIGO_ERROR_POR_DEFECTO,
    CODIGOS_ERROR,
    BackendRequestError,
)
from ..services.filters import filter_chunks
from ..services.lexical_parser import parse_lexical_response

CTR002_FILTER_FIELDS = ("version", "componente")


def ctr002_filters(filtros):
    """Reduce los filtros internos a la forma que admite CTR-002 §3.

    El Backend solo acepta ``version``, ``componente`` y ``tipo_documento``, con
    un único valor por campo y sin campos extra (§5.1 prohíbe enviar códigos de
    avería como filtro). ``codigos`` e ``incluir_obsoletos`` son filtros locales
    del Agente 2 y no viajan al Backend.

    ``tipo_documento`` con varios valores se rechaza: CTR-002 solo admite uno
    por petición, así que hay que lanzar una petición por tipo. Rechazarlo evita
    relajar un filtro duro en silencio.
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
    ):
        self.base_url = base_url.rstrip("/")
        self.model_embeddings = model_embeddings
        self.timeout = timeout
        # Bearer de servicio interno (CTR-002). Sin token, las rutas de
        # /conocimiento responden 401 o 503 según la configuración del Backend.
        self.token = (
            SERVICE_TOKEN if token is None else str(token)
        ).strip()

        if session is None:
            session = requests.Session()

        self.session = session

    def _auth_kwargs(self):
        """Cabecera de servicio solo cuando hay token configurado."""

        if not self.token:
            return {}

        return {"headers": {"Authorization": f"Bearer {self.token}"}}

    def search_vector(self, vector, filtros=None, k=30):
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

        response = self.session.post(
            f"{self.base_url}/conocimiento/vectorial",
            json=payload,
            timeout=self.timeout,
            **self._auth_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def search_lexical(self, text, filtros=None, k=30):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text debe ser texto no vacío.")

        payload = {
            "texto": text,
            "filtros": ctr002_filters(filtros),
            "k": k,
        }

        response = self.session.post(
            f"{self.base_url}/conocimiento/lexica",
            json=payload,
            timeout=self.timeout,
            **self._auth_kwargs(),
        )
        response.raise_for_status()
        return response.json()

    def search_lexical_candidates(self, text, filtros=None, k=None):
        """Solicita la búsqueda léxica y valida la respuesta de CTR-002."""

        if k is None:
            k = SEARCH_TOP_K

        payload = self.search_lexical(text=text, filtros=filtros, k=k)
        return parse_lexical_response(payload)

    def get_chunk(self, chunk_id, vecinos=1):
        """Recupera un fragmento y, opcionalmente, sus vecinos de sección.

        ``vecinos=1`` devuelve los chunks contiguos (±1) de la misma sección y
        documento. Un fallo del Backend se traduce a ``BackendRequestError``
        con un código estándar.
        """

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

    def get_neighbors(self, chunk_id, vecinos=1):
        """Devuelve solo los fragmentos vecinos de la misma sección."""

        return self.get_chunk(chunk_id, vecinos=vecinos)["vecinos"]


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

    for field in ("pagina", "orden_en_seccion"):
        value = chunk.get(field)
        if type(value) is not int or value <= 0:
            problems.append(f"{field} debe ser un entero mayor que cero")

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
    codigo = None

    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None

    if isinstance(payload, dict):
        detalle = payload.get("detail")
        if isinstance(detalle, dict):
            codigo = detalle.get("codigo")
        if codigo is None:
            codigo = payload.get("codigo_error") or payload.get("codigo")

    if codigo in CODIGOS_ERROR:
        return codigo

    # CTR-002 §4 usa nombres propios para la petición mal formada; el Agente 1
    # solo conoce el código estándar equivalente.
    if codigo in {"peticion_invalida", "filtro_invalido"}:
        return "entrada_invalida"

    status = getattr(response, "status_code", None)

    if status == 404:
        # El índice activo no contiene un fragmento que se acaba de recuperar.
        return "indice_no_disponible"
    if status in (408, 504):
        return "tiempo_agotado"
    if status == 422:
        return "entrada_invalida"

    return CODIGO_ERROR_POR_DEFECTO


def _chunk_request_error(response, chunk_id):
    return BackendRequestError(
        _backend_error_code(response),
        f"El Backend devolvió HTTP {response.status_code} al recuperar el "
        f"fragmento {chunk_id}.",
    )


def _parse_chunk_response(payload, chunk_id):
    if not isinstance(payload, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            "La respuesta del fragmento debe ser un objeto.",
        )

    indice = payload.get("indice")
    version = indice.get("version") if isinstance(indice, dict) else None

    if not isinstance(version, str) or not version.strip():
        raise BackendRequestError(
            "servicio_no_disponible",
            "La respuesta del fragmento no incluye 'indice.version'.",
        )

    chunk = payload.get("chunk")
    vecinos = payload.get("vecinos")

    if not isinstance(chunk, dict):
        raise BackendRequestError(
            "servicio_no_disponible",
            "La respuesta no incluye el objeto 'chunk'.",
        )

    if not isinstance(vecinos, list):
        raise BackendRequestError(
            "servicio_no_disponible",
            "La respuesta no incluye la lista 'vecinos'.",
        )

    problems = _invalid_chunk_fields(chunk, require_fecha_revision=False)
    if problems:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El fragmento {chunk_id} no cumple CTR-002: "
            f"{'; '.join(problems)}.",
        )

    if chunk.get("chunk_id") != chunk_id:
        raise BackendRequestError(
            "servicio_no_disponible",
            f"El Backend devolvió el fragmento "
            f"{chunk.get('chunk_id')!r} en lugar de {chunk_id!r}.",
        )

    valid_neighbors = []
    seen = {chunk_id}

    for position, neighbor in enumerate(vecinos):
        if not isinstance(neighbor, dict):
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El vecino en la posición {position} no es un objeto.",
            )

        problems = _invalid_chunk_fields(
            neighbor,
            require_fecha_revision=False,
        )
        if problems:
            raise BackendRequestError(
                "servicio_no_disponible",
                f"El vecino en la posición {position} no cumple CTR-002: "
                f"{'; '.join(problems)}.",
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
                f"El vecino {neighbor_id} no pertenece a la misma sección "
                f"que {chunk_id}.",
            )

        seen.add(neighbor_id)
        valid_neighbors.append(neighbor)

    return {
        "indice": {"version": version},
        "chunk": chunk,
        "vecinos": valid_neighbors,
    }


def load_chunks(path):
    dataset_path = Path(path)

    with dataset_path.open(encoding="utf-8-sig") as file:
        dataset = json.load(file)

    if not isinstance(dataset, dict):
        raise ValueError("La raíz del dataset debe ser un objeto JSON.")

    chunks = dataset.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("El dataset debe contener una lista 'chunks'.")

    total_chunks = dataset.get("total_chunks")
    if type(total_chunks) is not int or total_chunks != len(chunks):
        raise ValueError(
            "total_chunks no coincide con la cantidad de elementos de 'chunks'."
        )

    valid_chunks = []

    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            warnings.warn(
                f"Fragmento en índice {index} incompleto; se omite.",
                UserWarning,
                stacklevel=2,
            )
            continue

        missing_fields = sorted(REQUIRED_CHUNK_FIELDS - chunk.keys())
        if missing_fields:
            chunk_id = chunk.get("chunk_id") or f"índice {index}"
            warnings.warn(
                f"Fragmento {chunk_id} incompleto; se omite. "
                f"Faltan: {', '.join(missing_fields)}",
                UserWarning,
                stacklevel=2,
            )
            continue

        invalid_fields = _invalid_chunk_fields(chunk)
        if invalid_fields:
            chunk_id = chunk.get("chunk_id") or f"índice {index}"
            warnings.warn(
                f"Fragmento {chunk_id} inválido; se omite. "
                f"{'; '.join(invalid_fields)}",
                UserWarning,
                stacklevel=2,
            )
            continue

        valid_chunks.append(chunk)

    return valid_chunks

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


def _tokenize(text):
    normalized = unicodedata.normalize("NFD", text.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )
    return _TOKEN_PATTERN.findall(normalized)


def search_lexical(chunks, text, filters=None, k=30):
    if not isinstance(text, str):
        raise TypeError("text debe ser texto.")

    if type(k) is not int or k <= 0:
        raise ValueError("k debe ser un entero mayor que cero.")

    query_terms = set(_tokenize(text))
    if not query_terms:
        return []

    candidates = filter_chunks(chunks, filters)
    if not candidates:
        return []

    tokenized_chunks = [
        _tokenize(chunk.get("texto", ""))
        for chunk in candidates
    ]

    document_count = len(tokenized_chunks)
    document_lengths = [len(tokens) for tokens in tokenized_chunks]
    average_length = sum(document_lengths) / document_count

    if average_length == 0:
        return []

    document_frequency = Counter(
        term
        for tokens in tokenized_chunks
        for term in set(tokens)
    )

    k1 = 1.5
    b = 0.75
    scored_chunks = []

    for chunk, tokens, document_length in zip(
        candidates,
        tokenized_chunks,
        document_lengths,
    ):
        term_frequency = Counter(tokens)
        score = 0.0

        for term in query_terms:
            frequency = term_frequency[term]
            if frequency == 0:
                continue

            frequency_in_corpus = document_frequency[term]
            inverse_frequency = math.log(
                1
                + (document_count - frequency_in_corpus + 0.5)
                / (frequency_in_corpus + 0.5)
            )

            length_normalizer = k1 * (
                1 - b + b * document_length / average_length
            )
            score += inverse_frequency * (
                frequency * (k1 + 1) / (frequency + length_normalizer)
            )

        if score > 0:
            result = dict(chunk)
            result["score"] = score
            scored_chunks.append(result)

    scored_chunks.sort(key=lambda chunk: chunk["score"], reverse=True)
    return scored_chunks[:k]
def get_chunk_with_neighbors(chunks, chunk_id, radius=1):
    if type(radius) is not int or radius < 0:
        raise ValueError("radius debe ser un entero mayor o igual que cero.")

    chunks = list(chunks)
    matches = [
        chunk for chunk in chunks
        if chunk.get("chunk_id") == chunk_id
    ]

    if not matches:
        return []

    if len(matches) > 1:
        raise ValueError(f"chunk_id duplicado: {chunk_id}")

    center = matches[0]
    same_section = [
        chunk for chunk in chunks
        if chunk.get("documento") == center.get("documento")
        and chunk.get("seccion") == center.get("seccion")
    ]
    same_section.sort(key=lambda chunk: chunk["orden_en_seccion"])

    center_index = same_section.index(center)
    start = max(0, center_index - radius)
    end = min(len(same_section), center_index + radius + 1)

    return same_section[start:end]

def search_vector(
    chunks,
    query_vector,
    vectors_by_chunk_id,
    filters=None,
    k=30,
):
    if type(k) is not int or k <= 0:
        raise ValueError("k debe ser un entero mayor que cero.")

    if not isinstance(query_vector, (list, tuple)) or not query_vector:
        raise ValueError("query_vector debe ser una lista no vacía.")

    if not isinstance(vectors_by_chunk_id, dict):
        raise TypeError("vectors_by_chunk_id debe ser un diccionario.")

    def validate_vector(vector, label):
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError(f"{label} debe ser una lista no vacía.")

        for value in vector:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{label} debe contener solo números finitos.")

        return [float(value) for value in vector]

    query = validate_vector(query_vector, "query_vector")
    query_norm = math.sqrt(sum(value * value for value in query))

    if query_norm == 0:
        raise ValueError("query_vector no puede ser un vector cero.")

    candidates = filter_chunks(chunks, filters)
    scored_chunks = []

    for chunk in candidates:
        chunk_id = chunk.get("chunk_id")

        if chunk_id not in vectors_by_chunk_id:
            raise ValueError(f"Falta el vector del fragmento {chunk_id}.")

        vector = validate_vector(
            vectors_by_chunk_id[chunk_id],
            f"vector de {chunk_id}",
        )

        if len(vector) != len(query):
            raise ValueError(
                f"El vector de {chunk_id} tiene dimensión {len(vector)}; "
                f"se esperaba {len(query)}."
            )

        vector_norm = math.sqrt(sum(value * value for value in vector))
        if vector_norm == 0:
            raise ValueError(f"El vector de {chunk_id} no puede ser cero.")

        dot_product = sum(
            query_value * vector_value
            for query_value, vector_value in zip(query, vector)
        )
        score = dot_product / (query_norm * vector_norm)

        result = dict(chunk)
        result["score"] = score
        scored_chunks.append(result)

    scored_chunks.sort(key=lambda chunk: chunk["score"], reverse=True)
    return scored_chunks[:k]

