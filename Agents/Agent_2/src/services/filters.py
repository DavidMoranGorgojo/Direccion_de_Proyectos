"""Filtros duros de recuperación (A2-10).

``version`` y ``componente`` son filtros duros: se aplican siempre y nunca se
relajan. Solo ``tipo_documento`` puede ampliarse, aceptando varios valores
canónicos. ``codigos`` restringe a fragmentos que referencian códigos exactos.

Los filtros no incluyen palabras libres del usuario: los valores de componente
y tipo de documento se normalizan contra un conjunto cerrado de valores.
"""

import re
import unicodedata


DOCUMENT_TYPE_ALIASES = {
    "manual": "manual",
    "manuales": "manual",
    "manual_de_taller": "manual",
    "manuales_de_taller": "manual",
    "manual_de_servicio": "manual",
    "procedimiento": "procedimiento",
    "procedimientos": "procedimiento",
    "prc": "procedimiento",
    "boletin": "boletin",
    "boletines": "boletin",
    "bol": "boletin",
    "catalogo": "catalogo",
    "catalogos": "catalogo",
    "cat": "catalogo",
    "mantenimiento": "mantenimiento",
    "plan_de_mantenimiento": "mantenimiento",
    "mnt": "mantenimiento",
    "codigo_averia": "codigo_averia",
    "codigo_de_averia": "codigo_averia",
    "codigos_de_averia": "codigo_averia",
    "dtc": "codigo_averia",
    "diagnostico": "diagnostico",
    "diagnosticos": "diagnostico",
    "arbol_de_diagnostico": "diagnostico",
    "arboles_de_diagnostico": "diagnostico",
    "advertencia": "advertencia",
    "advertencias": "advertencia",
    "adv": "advertencia",
    "seguridad": "seguridad",
    "documento_de_seguridad": "seguridad",
    "seg": "seguridad",
    "operacion": "operacion",
    "operaciones": "operacion",
    "ope": "operacion",
    "casos_servicio": "casos_servicio",
    "caso_de_servicio": "casos_servicio",
    "casos_de_servicio": "casos_servicio",
    "his": "casos_servicio",
    "esquemas": "esquemas",
    "esquema": "esquemas",
    "esq": "esquemas",
    "diccionario": "diccionario",
    "dic": "diccionario",
}


COMPONENT_ALIASES = {
    "motor": "motor",
    "motores": "motor",
    "circuito_motor": "motor",
    "circuito_de_motor": "motor",
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
    "sistema_de_seguridad": "seguridad",
    "componente_de_seguridad": "seguridad",
    "calefaccion": "calefaccion",
    "calentador_ptc": "calefaccion",
    "control_tcu": "control_tcu",
    "tcu": "control_tcu",
    "unidad_de_control_termico": "control_tcu",
}


_VERSION_RE = re.compile(r"[Vv]?(\d+)\.(\d+)")

_CODE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])("
    r"HTM240-[A-Z]{3}-\d{3}"
    r"|(?:HTM|CMP|CIR|TES|PRC|BOL|DIA|ADV|SEG|OPE|ESQ|DIC|HIS|CAT|MNT|MAN)"
    r"-?\d{2,4}(?:-[A-Z])?"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_key(value):
    """Minúsculas, sin acentos y con espacios/guiones convertidos en ``_``."""

    decomposed = unicodedata.normalize("NFD", value.casefold())
    without_accents = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[\s\-]+", "_", without_accents.strip()).strip("_")


def normalize_version(value):
    """Normaliza ``1.1``/``v1.1`` a ``V1.1``. No inventa versiones ambiguas."""

    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("version debe ser texto o None.")

    value = value.strip()
    if not value:
        return None

    match = _VERSION_RE.fullmatch(value)
    if match:
        return f"V{int(match.group(1))}.{int(match.group(2))}"

    return value


def normalize_component(value):
    """Normaliza un componente contra el conjunto cerrado de valores."""

    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("componente debe ser texto o None.")

    value = value.strip()
    if not value:
        return None

    key = normalize_key(value)
    return COMPONENT_ALIASES.get(key, key)


def normalize_document_type(value):
    """Normaliza un tipo de documento y sus sinónimos a su valor canónico."""

    if not isinstance(value, str):
        raise TypeError("cada tipo_documento debe ser texto.")

    value = value.strip()
    if not value:
        raise ValueError("tipo_documento no puede estar vacío.")

    key = normalize_key(value)
    return DOCUMENT_TYPE_ALIASES.get(key, key)


def normalize_document_types(value):
    """Acepta un tipo o una lista y devuelve la lista canónica sin duplicados."""

    if value is None:
        return None

    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise TypeError(
            "tipo_documento debe ser texto, una lista o None."
        )

    if not values:
        return None

    normalized = []
    for item in values:
        canonical = normalize_document_type(item)
        if canonical not in normalized:
            normalized.append(canonical)

    return normalized


def normalize_codes(value):
    """Acepta un código o una lista y devuelve la lista sin duplicados."""

    if value is None:
        return None

    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise TypeError("codigos debe ser texto, una lista o None.")

    if not values:
        return None

    codes = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("cada código debe ser texto no vacío.")

        code = item.strip()
        if code not in codes:
            codes.append(code)

    return codes


def code_key(value):
    """Clave de comparación de códigos: sin separadores y sin mayúsculas."""

    return re.sub(r"[\s\-_]+", "", value.casefold())


def extract_code_tokens(text):
    """Extrae códigos exactos del texto, sin normalizar su contenido."""

    if not isinstance(text, str):
        return []

    return [match.group(1) for match in _CODE_TOKEN.finditer(text)]


def _chunk_code_keys(chunk):
    values = []

    referenced = chunk.get("ids_referenciados")
    if isinstance(referenced, (list, tuple)):
        values.extend(
            item for item in referenced if isinstance(item, str)
        )

    for field in ("documento", "seccion", "chunk_id", "texto"):
        value = chunk.get(field)
        if isinstance(value, str):
            values.append(value)

    keys = set()
    for value in values:
        for token in extract_code_tokens(value):
            keys.add(code_key(token))

    return keys


def _matches_codes(chunk, codes):
    if codes is None:
        return True

    chunk_keys = _chunk_code_keys(chunk)
    return any(code_key(code) in chunk_keys for code in codes)


def filter_chunks(chunks, filters=None):
    filters = filters or {}

    if not isinstance(filters, dict):
        raise TypeError("filters debe ser un diccionario.")

    version = normalize_version(filters.get("version"))
    component = normalize_component(filters.get("componente"))
    document_types = normalize_document_types(filters.get("tipo_documento"))
    codes = normalize_codes(filters.get("codigos"))
    include_obsolete = filters.get("incluir_obsoletos", True)

    if not isinstance(include_obsolete, bool):
        raise TypeError("incluir_obsoletos debe ser booleano.")

    filtered_chunks = []

    for chunk in chunks:
        if version is not None:
            versiones = chunk.get("versiones") or []
            vigente_para = chunk.get("vigente_para") or []

            version_aplicable = version in versiones

            # Excepción: documentos sustituidos que siguen
            # siendo aplicables a versiones anteriores.
            if chunk.get("sustituido_por") is not None:
                version_aplicable = (
                    version_aplicable or version in vigente_para
                )

            if not version_aplicable:
                continue

        if component is not None:
            if chunk.get("componente") != component:
                continue

        if document_types is not None:
            if chunk.get("tipo_documento") not in document_types:
                continue

        if not _matches_codes(chunk, codes):
            continue

        if include_obsolete is False and chunk.get("obsoleto") is True:
            continue

        filtered_chunks.append(chunk)

    return filtered_chunks
