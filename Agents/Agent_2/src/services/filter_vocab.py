"""Vocabulario canónico y adaptación de filtros del Agente 1."""

from __future__ import annotations

import re
from typing import Any

from .filters import (
    normalize_component,
    normalize_document_types,
    normalize_codes,
    normalize_version,
)

VALID_COMPONENTS = {
    "motor",
    "bateria",
    "electronica_potencia",
    "refrigeracion",
    "calefaccion",
    "control_tcu",
    "sistema",
    "general",
    "seguridad",
}

VALID_DOCUMENT_TYPES = {
    "codigo_averia",
    "mantenimiento",
    "catalogo",
    "boletin",
    "manual",
    "procedimiento",
    "diagnostico",
    "advertencia",
    "seguridad",
    "operacion",
    "casos_servicio",
    "esquemas",
    "diccionario",
}

# Tabla de traducción de valores del Agente 1 a valores canónicos del Backend.
AGENT1_TIPO_DOCUMENTO = {
    "manual": "manual",
    "procedimiento": "procedimiento",
    "ficha_tecnica": "catalogo",  # TODO(confirmar con Agente 1)
}


def adapt_explicit_filters(filtros: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapta y valida los filtros explícitos recibidos.

    Traduce lo traducible; lo que no pertenece al vocabulario se descarta
    y se devuelve en filtros_descartados.
    """
    if not isinstance(filtros, dict):
        return {}, {}

    validos: dict[str, Any] = {}
    descartados: dict[str, Any] = {}

    # 1. Version
    if "version" in filtros and filtros["version"] is not None:
        raw_v = filtros["version"]
        norm_v = normalize_version(raw_v)
        if norm_v and re.match(r"^V\d+\.\d+$", str(norm_v)):
            validos["version"] = norm_v
        else:
            descartados["version"] = raw_v

    # 2. Componente
    if "componente" in filtros and filtros["componente"] is not None:
        raw_comp = filtros["componente"]
        norm_comp = normalize_component(raw_comp)
        if norm_comp in VALID_COMPONENTS:
            validos["componente"] = norm_comp
        else:
            descartados["componente"] = raw_comp

    # 3. Tipo de documento
    if "tipo_documento" in filtros and filtros["tipo_documento"] is not None:
        raw_td = filtros["tipo_documento"]
        norm_tds = normalize_document_types(raw_td)
        if norm_tds:
            adapted = []
            for td in norm_tds:
                translated = AGENT1_TIPO_DOCUMENTO.get(td, td)
                if translated in VALID_DOCUMENT_TYPES:
                    if translated not in adapted:
                        adapted.append(translated)
                else:
                    descartados.setdefault("tipo_documento", []).append(td)
            if adapted:
                validos["tipo_documento"] = adapted if len(adapted) > 1 else adapted[0]
        else:
            descartados["tipo_documento"] = raw_td

    # 4. Codigos
    if "codigos" in filtros and filtros["codigos"] is not None:
        norm_c = normalize_codes(filtros["codigos"])
        if norm_c:
            validos["codigos"] = norm_c
        else:
            descartados["codigos"] = filtros["codigos"]

    # 5. Incluir obsoletos
    if "incluir_obsoletos" in filtros and filtros["incluir_obsoletos"] is not None:
        val = filtros["incluir_obsoletos"]
        if isinstance(val, bool):
            validos["incluir_obsoletos"] = val
        else:
            descartados["incluir_obsoletos"] = val

    return validos, descartados


__all__ = [
    "AGENT1_TIPO_DOCUMENTO",
    "VALID_COMPONENTS",
    "VALID_DOCUMENT_TYPES",
    "adapt_explicit_filters",
]
