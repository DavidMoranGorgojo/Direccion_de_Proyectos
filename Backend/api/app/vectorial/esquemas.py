"""Mensajes de la búsqueda vectorial (CTR-002 ed. 1.1, §3)."""

import math
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config


class Filtros(BaseModel):
    """Pre-filtro duro. Un filtro nulo u omitido no restringe. Los códigos de avería NO van aquí (§5.1)."""
    model_config = ConfigDict(extra="forbid")
    version: Optional[str] = None
    componente: Optional[str] = None
    tipo_documento: Optional[str] = None


class PeticionVectorial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vector: List[float] = Field(min_length=config.DIMENSIONES, max_length=config.DIMENSIONES)
    modelo_embeddings: Optional[str] = None
    filtros: Filtros = Field(default_factory=Filtros)
    k: int = Field(ge=1, le=config.K_MAX)

    @field_validator("vector")
    @classmethod
    def _finito(cls, v: List[float]) -> List[float]:
        if not all(math.isfinite(x) for x in v):
            raise ValueError("el vector contiene valores no finitos")
        return v


class IndiceInfo(BaseModel):
    version: str
    modelo_embeddings: str


class Resultado(BaseModel):
    chunk_id: str
    score: float
    texto: str
    documento: str
    seccion: str
    pagina: int
    versiones: List[str]
    componente: str
    tipo_documento: str
    obsoleto: bool
    sustituido_por: Optional[str]
    vigente_para: List[str]
    fecha_revision: Optional[date]
    orden_en_seccion: int
    version_documento: str
    afectado_por: List[str]
    ids_referenciados: List[str]


class RespuestaBusqueda(BaseModel):
    indice: IndiceInfo
    resultados: List[Resultado]
