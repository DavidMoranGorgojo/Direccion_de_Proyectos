import json
import warnings
from datetime import date
from pathlib import Path
from collections import Counter
import math
import re
import unicodedata

from ..services.filters import filter_chunks

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


def _invalid_chunk_fields(chunk):
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
    try:
        if not isinstance(fecha_revision, str):
            raise TypeError
        date.fromisoformat(fecha_revision)
    except (TypeError, ValueError):
        problems.append("fecha_revision debe tener formato YYYY-MM-DD")

    return problems


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