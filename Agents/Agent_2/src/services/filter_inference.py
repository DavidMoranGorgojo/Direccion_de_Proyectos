"""Inferencia de filtros duros a partir de la consulta (A2-10).

La inferencia es conservadora:

* ``version`` solo se infiere cuando aparece una única versión explícita.
* ``componente`` solo se infiere a partir de un conjunto cerrado de componentes
  (motor, batería, refrigeración, electrónica de potencia, calefacción y control
  TCU). No se deduce del componente de un código porque un mismo código puede
  aparecer en documentos clasificados en otro componente.
* ``tipo_documento`` puede devolver varios valores: es el único filtro que se
  amplía.
* ``codigos`` conserva los códigos canónicos exactos del catálogo.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from ..core.config import CATALOG_DIR
from .filters import (
    COMPONENT_ALIASES,
    DOCUMENT_TYPE_ALIASES,
    code_key,
    extract_code_tokens,
    normalize_component,
    normalize_codes,
    normalize_document_types,
    normalize_key,
    normalize_version,
)


_VERSION_RE = re.compile(
    r"\b(?:v|versi[oó]n)\s*([12])\s*[.,]\s*(\d)\b",
    re.IGNORECASE,
)


def _alias_matches(normalized_text, alias):
    parts = alias.split("_")
    pattern = (
        r"(?<![a-z0-9])"
        + r"[\s_\-]+".join(re.escape(part) for part in parts)
        + r"(?![a-z0-9])"
    )
    return re.search(pattern, normalized_text) is not None


def _require_text(value):
    if not isinstance(value, str):
        raise TypeError("text debe ser texto.")

    return value


@lru_cache(maxsize=None)
def _load_catalogs_cached(path_str):
    path = Path(path_str)

    codigos = json.loads(
        (path / "codigos.json").read_text(encoding="utf-8-sig")
    )
    componentes = json.loads(
        (path / "componentes.json").read_text(encoding="utf-8-sig")
    )

    code_by_key = {}
    for item in codigos.get("codigos", []):
        code = item.get("codigo")
        if isinstance(code, str) and code.strip():
            code_by_key[code_key(code)] = code

    component_id_by_key = {}
    for item in componentes.get("componentes", []):
        component_id = item.get("id")
        if isinstance(component_id, str) and component_id.strip():
            component_id_by_key[code_key(component_id)] = component_id

    return {
        "code_by_key": code_by_key,
        "component_id_by_key": component_id_by_key,
    }


def load_catalogs(catalog_dir=None):
    """Carga los catálogos usados para validar códigos exactos."""

    path = Path(catalog_dir) if catalog_dir is not None else CATALOG_DIR
    return _load_catalogs_cached(str(path))


def infer_version(text):
    """Devuelve la versión solo si la consulta menciona exactamente una."""

    text = _require_text(text)
    versions = {
        f"V{int(match.group(1))}.{int(match.group(2))}"
        for match in _VERSION_RE.finditer(text)
    }

    if len(versions) == 1:
        return versions.pop()

    return None


def infer_component(text):
    """Infiere un componente a partir de un conjunto cerrado de componentes."""

    normalized = normalize_key(_require_text(text))
    candidates = set()

    for alias, canonical in COMPONENT_ALIASES.items():
        if _alias_matches(normalized, alias):
            candidates.add(canonical)

    if len(candidates) == 1:
        return candidates.pop()

    return None


def infer_document_types(text):
    """Devuelve los tipos de documento mencionados, sin duplicados."""

    normalized = normalize_key(_require_text(text))
    found = []

    for alias, canonical in DOCUMENT_TYPE_ALIASES.items():
        if (
            _alias_matches(normalized, alias)
            and canonical not in found
        ):
            found.append(canonical)

    return found or None


def _canonical_code(token, catalogs):
    key = code_key(token)

    if key in catalogs["code_by_key"]:
        return catalogs["code_by_key"][key]

    if key in catalogs["component_id_by_key"]:
        return catalogs["component_id_by_key"][key]

    return token.upper()


def infer_codes(text, catalogs=None):
    """Extrae códigos exactos y los normaliza a su forma canónica."""

    catalogs = catalogs or load_catalogs()
    codes = []

    for token in extract_code_tokens(_require_text(text)):
        canonical = _canonical_code(token, catalogs)
        if canonical not in codes:
            codes.append(canonical)

    return codes or None


def infer_filters(text, catalog_dir=None):
    """Construye los filtros inferidos a partir del texto de la consulta."""

    if not isinstance(text, str):
        raise TypeError("text debe ser texto.")

    if not text.strip():
        return {}

    catalogs = load_catalogs(catalog_dir)
    filters = {}

    version = infer_version(text)
    if version is not None:
        filters["version"] = version

    component = infer_component(text)
    if component is not None:
        filters["componente"] = component

    document_types = infer_document_types(text)
    if document_types is not None:
        filters["tipo_documento"] = document_types

    codes = infer_codes(text, catalogs)
    if codes is not None:
        filters["codigos"] = codes

    return filters


def _union(first, second):
    result = []

    for values in (first or [], second or []):
        for value in values:
            if value not in result:
                result.append(value)

    return result


def merge_filters(explicit=None, inferred=None):
    """Combina filtros explícitos e inferidos respetando la dureza de cada uno.

    ``version`` y ``componente`` explícitos sustituyen a los inferidos y nunca
    se combinan entre sí. ``tipo_documento`` y ``codigos`` se amplían por unión.
    """

    explicit = explicit or {}
    inferred = inferred or {}

    if not isinstance(explicit, dict):
        raise TypeError("explicit debe ser un diccionario o None.")

    if not isinstance(inferred, dict):
        raise TypeError("inferred debe ser un diccionario o None.")

    merged = dict(inferred)

    for field, normalizer in (
        ("version", normalize_version),
        ("componente", normalize_component),
    ):
        value = explicit.get(field)

        # Un valor explícito ausente o en blanco deja actuar a la inferencia.
        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        merged[field] = normalizer(value)

    explicit_types = normalize_document_types(
        explicit.get("tipo_documento")
    )
    inferred_types = normalize_document_types(
        inferred.get("tipo_documento")
    )

    if explicit_types is not None or inferred_types is not None:
        merged["tipo_documento"] = _union(
            explicit_types,
            inferred_types,
        )

    explicit_codes = normalize_codes(explicit.get("codigos"))
    inferred_codes = normalize_codes(inferred.get("codigos"))

    if explicit_codes is not None or inferred_codes is not None:
        merged["codigos"] = _union(explicit_codes, inferred_codes)

    if "incluir_obsoletos" in explicit:
        include_obsolete = explicit["incluir_obsoletos"]
        if not isinstance(include_obsolete, bool):
            raise TypeError("incluir_obsoletos debe ser booleano.")
        merged["incluir_obsoletos"] = include_obsolete

    return merged


def build_filters(text, explicit=None, catalog_dir=None):
    """Infiere filtros del texto y los combina con los explícitos."""

    return merge_filters(
        explicit,
        infer_filters(text, catalog_dir),
    )


__all__ = [
    "build_filters",
    "infer_codes",
    "infer_component",
    "infer_document_types",
    "infer_filters",
    "infer_version",
    "load_catalogs",
    "merge_filters",
]
