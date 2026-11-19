"""Inferencia de filtros duros a partir de la consulta (A2-10).

La inferencia es conservadora:

* ``version`` solo se infiere cuando aparece una única versión explícita.
* ``componente`` solo se infiere a partir de alias inequívocos. No se infiere con
  la palabra suelta ``motor``/``motores`` ni ``sistema``/``general``.
* ``tipo_documento`` infiere solo con formas explícitas y poco ambiguas
  (boletín, catálogo, manual de taller/servicio, plan de mantenimiento...).
* ``codigos`` conserva los códigos canónicos exactos del catálogo.
"""

from __future__ import annotations

import json
import os
import threading
import time
import re
from functools import lru_cache
from pathlib import Path

from ..core import config
from ..core.errors import BackendRequestError
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
from .filter_vocab import adapt_explicit_filters


_VERSION_RE = re.compile(
    r"\b(?:v|versi[oó]n)\s*([12])\s*[.,]\s*(\d)\b",
    re.IGNORECASE,
)

# Alias seguros para inferir componente (excluye palabras genéricas sueltas como "motor").
INFERRED_COMPONENT_ALIASES = {
    "circuito_motor": "motor",
    "circuito_de_motor": "motor",
    "circuito_del_motor": "motor",
    "bateria": "bateria",
    "baterias": "bateria",
    "bateria_de_alta_tension": "bateria",
    "circuito_bateria": "bateria",
    "circuito_de_bateria": "bateria",
    "refrigeracion": "refrigeracion",
    "refrigerante": "refrigeracion",
    "circuito_de_refrigeracion": "refrigeracion",
    "electronica_de_potencia": "electronica_potencia",
    "electronica_potencia": "electronica_potencia",
    "inversor": "electronica_potencia",
    "calefaccion": "calefaccion",
    "calentador_ptc": "calefaccion",
    "calefactor_ptc": "calefaccion",
    "control_tcu": "control_tcu",
    "tcu": "control_tcu",
    "unidad_de_control_termico": "control_tcu",
    "sistema_de_seguridad": "seguridad",
    "componente_de_seguridad": "seguridad",
}

# Alias inequívocos para inferir tipo_documento (excluye siglas cortas y sustantivos ambiguos sueltos).
INFERRED_DOCUMENT_TYPE_ALIASES = {
    "manual_de_taller": "manual",
    "manuales_de_taller": "manual",
    "manual_de_servicio": "manual",
    "manuales_de_servicio": "manual",
    "procedimiento": "procedimiento",
    "procedimientos": "procedimiento",
    "boletin": "boletin",
    "boletines": "boletin",
    "boletin_tecnico": "boletin",
    "catalogo": "catalogo",
    "catalogos": "catalogo",
    "catalogo_de_piezas": "catalogo",
    "plan_de_mantenimiento": "mantenimiento",
    "planes_de_mantenimiento": "mantenimiento",
    "codigo_averia": "codigo_averia",
    "codigo_de_averia": "codigo_averia",
    "codigos_de_averia": "codigo_averia",
    "dtc": "codigo_averia",
    "arbol_de_diagnostico": "diagnostico",
    "arboles_de_diagnostico": "diagnostico",
    "documento_de_seguridad": "seguridad",
    "caso_de_servicio": "casos_servicio",
    "casos_de_servicio": "casos_servicio",
    "esquema_electrico": "esquemas",
    "esquemas_electricos": "esquemas",
    "diccionario_tecnico": "diccionario",
}


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


def _extract_items(data, key):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


def _build_catalog_maps(codigos_raw, componentes_raw):
    code_items = _extract_items(codigos_raw, "codigos")
    comp_items = _extract_items(componentes_raw, "componentes")

    code_by_key = {}
    for item in code_items:
        if isinstance(item, dict):
            code = item.get("codigo")
            if isinstance(code, str) and code.strip():
                code_by_key[code_key(code)] = code

    component_id_by_key = {}
    for item in comp_items:
        if isinstance(item, dict):
            cid = item.get("id") or item.get("codigo")
            if isinstance(cid, str) and cid.strip():
                component_id_by_key[code_key(cid)] = cid

    return {
        "code_by_key": code_by_key,
        "component_id_by_key": component_id_by_key,
    }


@lru_cache(maxsize=None)
def _load_catalogs_cached(path_str):
    path = Path(path_str)

    codigos = json.loads(
        (path / "codigos.json").read_text(encoding="utf-8-sig")
    )
    componentes = json.loads(
        (path / "componentes.json").read_text(encoding="utf-8-sig")
    )

    return _build_catalog_maps(codigos, componentes)


class CatalogCacheEntry(dict):
    """Entrada de caché de catálogos que almacena los mapeos y metadatos de versión y tiempo."""

    def __init__(self, maps, *, timestamp=None, versions=None, backend_id=None):
        super().__init__(maps)
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.versions = dict(versions or {})
        self.backend_id = backend_id

    def is_expired(self, ttl):
        if ttl is None:
            return False
        if ttl <= 0:
            return True
        return (time.time() - self.timestamp) > ttl


_CATALOG_CACHE_LOCK = threading.RLock()
_BACKEND_CATALOG_CACHE = {}
DEFAULT_CATALOG_CACHE_TTL = float(os.getenv("AGENT2_CATALOG_CACHE_TTL", "300.0"))


def _backend_cache_key(backend_client):
    """Calcula la clave de identidad única del Backend a partir de su configuración."""
    base_url = str(getattr(backend_client, "base_url", "default")).rstrip("/")
    token = getattr(backend_client, "token", None)
    model = getattr(backend_client, "model_embeddings", None)
    return (base_url, token, model)


def invalidate_backend_catalog_cache(backend_client=None):
    """Invalida explícitamente la caché de catálogos en memoria.

    Si backend_client es None, invalida todas las entradas registradas.
    Si se proporciona un cliente, invalida únicamente su clave correspondiente.
    """
    with _CATALOG_CACHE_LOCK:
        if backend_client is None:
            _BACKEND_CATALOG_CACHE.clear()
        else:
            key = _backend_cache_key(backend_client)
            _BACKEND_CATALOG_CACHE.pop(key, None)


def load_catalogs_from_backend(
    backend_client,
    *,
    use_cache=True,
    force_reload=False,
    ttl=None,
    stale_if_error=False,
):
    """Descarga y parsea los catálogos desde el Backend vía CTR-002 §2.

    Contempla:
    1. Identidad del Backend: clave compuesta (base_url, token, model_embeddings).
    2. Versión de catálogo o índice: almacena versiones anunciadas por Backend.
    3. Invalidación explícita: force_reload=True o invalidate_backend_catalog_cache().
    4. Caducidad configurable (TTL): parámetro ttl o AGENT2_CATALOG_CACHE_TTL.
    5. Concurrencia: protegida por threading.RLock.
    6. Comportamiento controlado si falla la actualización: propaga el error sin
       corromper la caché previa (o devuelve la previa si stale_if_error=True).
    """
    if backend_client is None:
        raise ValueError("backend_client no puede ser None.")

    cache_key = _backend_cache_key(backend_client)
    effective_ttl = ttl if ttl is not None else DEFAULT_CATALOG_CACHE_TTL

    with _CATALOG_CACHE_LOCK:
        entry = _BACKEND_CATALOG_CACHE.get(cache_key)

        # Si hay caché válida no expirada y no se fuerza recarga, reutilizar
        if use_cache and not force_reload and entry is not None:
            if not entry.is_expired(effective_ttl):
                return entry

        # Descargar catálogos frescos del Backend
        try:
            codigos_resp = backend_client.get_catalogo("codigos")
            componentes_resp = backend_client.get_catalogo("componentes")
        except Exception:
            if stale_if_error and entry is not None:
                return entry
            raise

        codigos_raw = (
            codigos_resp.get("contenido", codigos_resp)
            if isinstance(codigos_resp, dict)
            else codigos_resp
        )
        componentes_raw = (
            componentes_resp.get("contenido", componentes_resp)
            if isinstance(componentes_resp, dict)
            else componentes_resp
        )

        versions = {
            "codigos": codigos_resp.get("version") if isinstance(codigos_resp, dict) else None,
            "componentes": componentes_resp.get("version") if isinstance(componentes_resp, dict) else None,
        }

        # No cachear un catálogo malformado como un catálogo vacío válido.
        for name, raw in (("codigos", codigos_raw), ("componentes", componentes_raw)):
            items = raw if isinstance(raw, list) else raw.get(name) if isinstance(raw, dict) else None
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("codigo") or item.get("id"), str)
                or not (item.get("codigo") or item.get("id")).strip()
                for item in items
            ):
                raise BackendRequestError("servicio_no_disponible", f"Catálogo {name} malformado.")

        maps = _build_catalog_maps(codigos_raw, componentes_raw)
        new_entry = CatalogCacheEntry(
            maps,
            timestamp=time.time(),
            versions=versions,
            backend_id=cache_key,
        )

        if use_cache:
            _BACKEND_CATALOG_CACHE[cache_key] = new_entry

        return new_entry


FIXTURE_CATALOG_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "catalogos"


def load_catalogs(
    catalog_dir=None,
    *,
    allow_synthetic=None,
    backend_client=None,
    force_reload=False,
    ttl=None,
):
    """Carga los catálogos usados para validar códigos exactos.

    Orden de precedencia seguro:
    1. Si se proporciona backend_client, se consultan los catálogos vía API Backend (CTR-002).
    2. Si se proporciona catalog_dir o existen archivos reales en config.CATALOG_DIR,
       se cargan desde el sistema de archivos local.
    3. Si faltan los catálogos reales obligatorios:
       - En producción (ARSOFT_ENV=production), está estrictamente prohibido el uso de fixtures.
       - En entorno no especificado, se aplica comportamiento seguro (error controlado).
       - En test (ARSOFT_ENV=test) o desarrollo con opt-in (ARSOFT_ALLOW_SYNTHETIC_CATALOGS=1),
         se permite fallback a fixtures/catalogos.
    """
    if backend_client is not None and hasattr(backend_client, "get_catalogo"):
        try:
            return load_catalogs_from_backend(
                backend_client,
                force_reload=force_reload,
                ttl=ttl,
            )
        except Exception:
            env = os.getenv("ARSOFT_ENV", "").strip().casefold()
            if env in {"production", "prod"}:
                raise
    if catalog_dir is not None:
        path = Path(catalog_dir)
        environment = os.getenv("ARSOFT_ENV", "").strip().casefold()
        if environment in {"production", "prod"} and path.resolve() == FIXTURE_CATALOG_DIR.resolve():
            raise FileNotFoundError("En producción no se pueden utilizar catálogos sintéticos.")
        return _load_catalogs_cached(str(path))

    path = Path(config.CATALOG_DIR)
    codigos_file = path / "codigos.json"
    componentes_file = path / "componentes.json"

    if codigos_file.exists() and componentes_file.exists():
        return _load_catalogs_cached(str(path))

    # Nunca recurrir a fixtures en producción, ni siquiera si la variable de
    # autorización quedó activada por error en el entorno de despliegue.
    environment = os.getenv("ARSOFT_ENV", "").strip().casefold()
    explicit_opt_in = os.getenv("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "0").strip().casefold() in ("1", "true", "yes")
    if environment in {"production", "prod"}:
        allow_synthetic = False
    elif allow_synthetic is None:
        allow_synthetic = environment == "test" or (environment in {"development", "dev"} and explicit_opt_in)

    if allow_synthetic:
        if (FIXTURE_CATALOG_DIR / "codigos.json").exists() and (FIXTURE_CATALOG_DIR / "componentes.json").exists():
            return _load_catalogs_cached(str(FIXTURE_CATALOG_DIR))

    raise FileNotFoundError(
        f"Catálogos reales obligatorios no encontrados en '{path}'. "
        "En modo de producción no está permitido el uso silencioso de catálogos sintéticos. "
        "Instale los catálogos de producción o habilite ARSOFT_ALLOW_SYNTHETIC_CATALOGS para pruebas."
    )


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
    """Infiere un componente solo a partir de alias inequívocos."""
    normalized = normalize_key(_require_text(text))
    candidates = set()

    for alias, canonical in INFERRED_COMPONENT_ALIASES.items():
        if _alias_matches(normalized, alias):
            candidates.add(canonical)

    # "motor de la batería" no significa necesariamente la batería como
    # componente de la avería. Ante referencias cruzadas es más seguro no
    # imponer un filtro hasta obtener aclaración del Agente 1.
    if "bateria" in candidates and re.search(r"(?:^|_)motor(?:es)?(?:_|$)", normalized):
        return None

    if len(candidates) == 1:
        return candidates.pop()

    return None


def infer_document_types(text):
    """Devuelve los tipos de documento mencionados con formas explícitas."""
    normalized = normalize_key(_require_text(text))
    found = []

    for alias, canonical in INFERRED_DOCUMENT_TYPE_ALIASES.items():
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


def infer_filters(text, catalog_dir=None, backend_client=None):
    """Construye los filtros inferidos a partir del texto de la consulta."""
    if not isinstance(text, str):
        raise TypeError("text debe ser texto.")

    if not text.strip():
        return {}

    catalogs = load_catalogs(catalog_dir, backend_client=backend_client)
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

    unknown = set(explicit) - {"version", "componente", "tipo_documento", "codigos", "incluir_obsoletos"}
    if unknown:
        raise ValueError(f"Campos de filtro no admitidos: {', '.join(sorted(unknown))}")

    for field in ("version", "componente"):
        if field in explicit and explicit[field] is not None and not isinstance(explicit[field], str):
            raise TypeError(f"{field} debe ser texto.")
    if "tipo_documento" in explicit and explicit["tipo_documento"] is not None:
        td = explicit["tipo_documento"]
        if not isinstance(td, (str, list, tuple)):
            raise TypeError("tipo_documento debe ser texto o lista de textos.")
        if isinstance(td, (list, tuple)) and any(not isinstance(x, str) for x in td):
            raise TypeError("tipo_documento debe contener solo textos.")
    if "codigos" in explicit and explicit["codigos"] is not None:
        c = explicit["codigos"]
        if not isinstance(c, (str, list, tuple)):
            raise TypeError("codigos debe ser texto o lista de textos.")
        if isinstance(c, (list, tuple)) and any(not isinstance(x, str) for x in c):
            raise TypeError("codigos debe contener solo textos.")
    if "incluir_obsoletos" in explicit and explicit["incluir_obsoletos"] is not None:
        if not isinstance(explicit["incluir_obsoletos"], bool):
            raise TypeError("incluir_obsoletos debe ser booleano.")

    # Ninguna restricción explícita inválida puede desaparecer silenciosamente.
    # De lo contrario la consulta se ampliaría sin autorización del Agente 1.
    adapted_explicit, discarded = adapt_explicit_filters(explicit)
    discarded = {
        key: val for key, val in discarded.items()
        if not (val is None or (isinstance(val, str) and not val.strip()))
    }
    if discarded:
        raise ValueError(f"Filtros explícitos no admitidos: {', '.join(sorted(discarded))}")

    merged = dict(inferred)

    for field, normalizer in (
        ("version", normalize_version),
        ("componente", normalize_component),
    ):
        value = adapted_explicit.get(field)

        # Un valor explícito ausente o en blanco deja actuar a la inferencia.
        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        merged[field] = normalizer(value)

    explicit_types = normalize_document_types(
        adapted_explicit.get("tipo_documento")
    )
    inferred_types = normalize_document_types(
        inferred.get("tipo_documento")
    )

    if explicit_types is not None or inferred_types is not None:
        merged["tipo_documento"] = _union(
            explicit_types,
            inferred_types,
        )

    explicit_codes = normalize_codes(adapted_explicit.get("codigos"))
    inferred_codes = normalize_codes(inferred.get("codigos"))

    if explicit_codes is not None or inferred_codes is not None:
        merged["codigos"] = _union(explicit_codes, inferred_codes)

    if "incluir_obsoletos" in adapted_explicit:
        include_obsolete = adapted_explicit["incluir_obsoletos"]
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
    "load_catalogs_from_backend",
    "invalidate_backend_catalog_cache",
    "CatalogCacheEntry",
    "merge_filters",
]
