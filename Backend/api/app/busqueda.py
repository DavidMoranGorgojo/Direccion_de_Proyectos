"""Formato común de las búsquedas de CTR-002 (vectorial y léxica).

Las dos búsquedas de ``/conocimiento`` devuelven exactamente la misma respuesta
(``{"indice": ..., "resultados": [...]}``) y aceptan el mismo objeto ``filtros``.
Este módulo concentra ese formato para que los dos endpoints lo compartan y no
puedan divergir: el endpoint vectorial solo tiene que llamar a ``respuesta``.
"""

from datetime import date
from typing import Iterable

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

K_POR_DEFECTO = 30  # «Valor inicial 30»
K_MAXIMO = 200

# Metadatos obligatorios de cada chunk, sin ``score``; el embedding no viaja.
METADATOS = (
    "chunk_id", "texto", "documento", "seccion", "pagina", "versiones", "componente",
    "tipo_documento", "obsoleto", "sustituido_por", "vigente_para", "fecha_revision",
    "orden_en_seccion", "version_documento", "afectado_por", "ids_referenciados",
)
# Columnas de ``conocimiento.chunk`` que hay que leer para construir un resultado.
COLUMNAS = ", ".join(f"c.{campo}" for campo in METADATOS)


class Filtros(BaseModel):
    """Pre-filtro duro. Un filtro nulo u omitido no restringe."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    componente: str | None = None
    tipo_documento: str | None = None


class IndiceBusqueda(BaseModel):
    version: str
    modelo_embeddings: str


class Resultado(BaseModel):
    chunk_id: str
    score: float
    texto: str
    documento: str
    seccion: str
    pagina: int
    versiones: list[str]
    componente: str
    tipo_documento: str
    obsoleto: bool
    sustituido_por: str | None
    vigente_para: list[str]
    fecha_revision: date | None
    orden_en_seccion: int
    version_documento: str
    afectado_por: list[str]
    ids_referenciados: list[str]


class RespuestaBusqueda(BaseModel):
    indice: IndiceBusqueda
    resultados: list[Resultado]


def resultado(fila: dict, score: float) -> dict:
    """Un chunk con sus metadatos y el score crudo del motor. El texto va sin modificar."""
    return {"chunk_id": fila["chunk_id"], "score": score, **{c: fila[c] for c in METADATOS if c != "chunk_id"}}


def respuesta(indice: dict, filas_con_score: Iterable[tuple[dict, float]]) -> dict:
    """Respuesta común, ya ordenada por score descendente por quien llama."""
    return {
        "indice": {"version": indice["version"], "modelo_embeddings": indice["modelo_embeddings"]},
        "resultados": [resultado(fila, score) for fila, score in filas_con_score],
    }


def filtro_invalido(campo: str, valor: str, validos: Iterable[str]) -> HTTPException:
    """HTTP 400 con el campo y los valores válidos (CTR-002 §4)."""
    return HTTPException(400, detail={"codigo": "filtro_invalido", "campo": campo, "valor": valor,
                                       "valores_validos": sorted(validos)})
