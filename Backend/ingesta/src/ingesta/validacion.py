"""Validación previa a la carga (paso 5.7 del diseño de ingesta)."""

from collections import Counter
from typing import List, Tuple

from . import config

CAMPOS_OBLIGATORIOS = [
    "chunk_id", "doc_id", "documento", "version_documento", "fecha_revision", "obsoleto", "sustituido_por",
    "versiones", "vigente_para", "tipo_documento", "componente", "seccion", "pagina", "orden_en_seccion",
    "afectado_por", "ids_referenciados", "texto",
]


def _motivo(chunk: dict, contar_tokens) -> str:
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in chunk]
    if faltan:
        return f"Faltan campos: {', '.join(faltan)}"
    if not chunk["texto"].strip():
        return "Texto vacío"
    if not chunk["documento"] or not chunk["seccion"] or chunk["pagina"] < 1:
        return "Sin documento, sección o página (trazabilidad obligatoria, CTR-002 §5.4)"
    if not chunk["versiones"] or not set(chunk["versiones"]) <= set(config.VERSIONES_VEHICULO):
        return f"Versiones de vehículo no válidas: {chunk['versiones']}"
    if chunk["obsoleto"] and not chunk["sustituido_por"]:
        return "Documento sustituido sin sustituido_por"
    if chunk["tipo_documento"] not in config.TIPO_DOCUMENTO.values():
        return f"tipo_documento desconocido: {chunk['tipo_documento']}"
    if contar_tokens(chunk["texto"]) > config.MAX_TOKENS:
        return f"Supera {config.MAX_TOKENS} tokens"
    if "embedding" in chunk and len(chunk["embedding"]) != config.DIMENSIONES:
        return f"El embedding no tiene {config.DIMENSIONES} dimensiones"
    return ""


def validar(chunks: List[dict], contar_tokens) -> Tuple[List[dict], List[dict], List[str]]:
    """Devuelve (válidos, rechazados con motivo, errores globales que impiden cargar)."""
    validos, rechazados = [], []
    for chunk in chunks:
        motivo = _motivo(chunk, contar_tokens)
        if motivo:
            rechazados.append({"chunk_id": chunk.get("chunk_id"), "documento": chunk.get("documento"), "motivo": motivo})
        else:
            validos.append(chunk)

    errores = []
    duplicados = [c for c, n in Counter(ch["chunk_id"] for ch in validos).items() if n > 1]
    if duplicados:
        errores.append(f"chunk_id duplicados: {duplicados}")
    compilados = [ch["chunk_id"] for ch in validos if ch["documento"] in config.COMPILADOS]
    if compilados:
        errores.append("El compilado figura en el índice")
    return validos, rechazados, errores
