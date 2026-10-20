"""Metadatos y relaciones de cada fragmento (paso 5.4 del diseño de ingesta)."""

import hashlib
import re
import unicodedata
from typing import List, Optional

from . import config

TIPOS = "|".join(config.TIPO_DOCUMENTO)
# HTM240-PRC-001, 005, 008 · DIA-001 > 4.3 · HTM240-DIA-001>4.1
RE_DOCUMENTO = re.compile(
    rf"\b(?:HTM240-)?({TIPOS})-(\d{{3}})\b(?:\s*>\s*(\d+(?:\.\d+)?))?((?:,\s*\d{{3}}\b)*)"
)
RE_DTC = re.compile(r"\bHTM-\d{4}\b")
RE_ENTIDAD = re.compile(r"\b(?:CMP|TES|CIR)-\d{2}\b")
RE_CMP = re.compile(r"\bCMP-\d{2}\b")


def ids_referenciados(texto: str, codigo_propio: str) -> List[str]:
    """Identificadores citados en el texto, en forma corta (PRC-003, DIA-001 > 4.3, HTM-0142, CMP-02)."""
    propio = codigo_propio.replace("HTM240-", "")
    ids = set(RE_DTC.findall(texto)) | set(RE_ENTIDAD.findall(texto))
    for tipo, numero, apartado, lista in RE_DOCUMENTO.findall(texto):
        ids.add(f"{tipo}-{numero} > {apartado}" if apartado else f"{tipo}-{numero}")
        # Listas abreviadas: «HTM240-PRC-001, 005, 008» cita también PRC-005 y PRC-008
        for otro in re.findall(r"\d{3}", lista):
            ids.add(f"{tipo}-{otro}")
    ids.discard(propio)
    return sorted(ids)


def componente(seccion: str, texto: str) -> Optional[str]:
    """Componente del fragmento: el CMP de la sección o, si el texto solo cita uno, ese.

    PROVISIONAL: CTR-002 no ha cerrado si el valor es un código CMP-xx o un nombre («refrigeracion»).
    """
    en_seccion = RE_CMP.findall(seccion)
    if en_seccion:
        return en_seccion[0]
    citados = set(RE_CMP.findall(texto))
    return citados.pop() if len(citados) == 1 else None


def afectado_por(doc_id: str, codigo: str, seccion: str, ids: List[str]) -> List[str]:
    boletines = set()
    for regla in config.REGLAS_BOLETINES:
        if regla["documento"] not in (doc_id, codigo):
            continue
        if "seccion" in regla and not seccion.startswith(regla["seccion"]):
            continue
        if "contiene" in regla and regla["contiene"] not in ids and regla["contiene"] not in seccion:
            continue
        boletines.add(regla["boletin"])
    return sorted(boletines)


def _slug(texto: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-").lower()[:40]


def chunk_id(doc_id: str, seccion: str, orden: int, texto: str) -> str:
    """Identificador estable: depende del documento, la sección, el orden y el contenido."""
    huella = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:8]
    return f"{doc_id}_{_slug(seccion)}_{orden:02d}_{huella}"
