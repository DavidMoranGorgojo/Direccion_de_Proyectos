"""Acceso de solo lectura al índice PostgreSQL creado por la ingesta."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .busqueda import K_MAXIMO, K_POR_DEFECTO, Filtros, RespuestaBusqueda, respuesta
from .busqueda_lexica import TOKENIZADOR, indice_lexico
from .links import connect, service_access

router = APIRouter(tags=["Conocimiento"], dependencies=[Depends(service_access)])
FIELDS = """c.chunk_id, c.texto, c.documento, c.seccion, c.pagina, c.versiones,
c.componente, c.tipo_documento, c.obsoleto, c.sustituido_por, c.vigente_para,
c.fecha_revision, c.orden_en_seccion, c.version_documento, c.afectado_por, c.ids_referenciados"""


def active(conn):
    index = conn.execute("""
        SELECT version, modelo_embeddings, tokenizador, dimensiones, n_chunks
        FROM conocimiento.indice_version WHERE activo
    """).fetchone()
    if not index:
        raise HTTPException(503, detail={"codigo": "indice_no_disponible"})
    return index


@router.get("/conocimiento/info")
def info():
    with connect() as conn:
        return {**active(conn), "tokenizador_lexico": TOKENIZADOR}


class BusquedaLexica(BaseModel):
    """Petición de búsqueda léxica: texto sin tokenizar, filtros duros y k."""

    texto: str
    filtros: Filtros | None = None
    k: int = Field(default=K_POR_DEFECTO, ge=1, le=K_MAXIMO)

    @field_validator("texto")
    @classmethod
    def texto_con_contenido(cls, texto: str) -> str:
        if not texto.strip():
            raise ValueError("texto vacío")
        return texto


@router.post("/conocimiento/lexica", response_model=RespuestaBusqueda)
def lexica(peticion: BusquedaLexica):
    filtros = peticion.filtros.model_dump() if peticion.filtros else {}
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        index = active(conn)
        motor = indice_lexico(conn, index)
    motor.validar(filtros)
    return respuesta(index, motor.buscar(peticion.texto, filtros, peticion.k))


@router.get("/conocimiento/chunks/{chunk_id}")
def chunk(chunk_id: str, vecinos: int = Query(default=0, ge=0, le=1)):
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        index = active(conn)
        row = conn.execute(f"""
            SELECT {FIELDS}, c.doc_id FROM conocimiento.chunk c
            WHERE c.indice_version=%s AND c.chunk_id=%s
        """, (index["version"], chunk_id)).fetchone()
        if not row:
            raise HTTPException(404, detail={"codigo": "recurso_no_encontrado"})
        document_id = row.pop("doc_id")
        adjacent = []
        if vecinos:
            adjacent = conn.execute(f"""
                SELECT {FIELDS} FROM conocimiento.chunk c
                WHERE c.indice_version=%s AND c.doc_id=%s AND c.seccion=%s
                  AND c.orden_en_seccion BETWEEN %s AND %s AND c.chunk_id<>%s
                ORDER BY c.orden_en_seccion, c.chunk_id
            """, (index["version"], document_id, row["seccion"], row["orden_en_seccion"] - 1,
                  row["orden_en_seccion"] + 1, chunk_id)).fetchall()
    return {"indice": {"version": index["version"]}, "chunk": row, "vecinos": adjacent}


@router.get("/catalogos/{nombre}")
def catalogo(nombre: Literal["codigos", "terminos", "vehiculos", "componentes"]):
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        index = active(conn)
        row = conn.execute("SELECT nombre, version, contenido FROM conocimiento.catalogo WHERE nombre=%s AND version=%s",
                           (nombre, index["version"])).fetchone()
    if not row:
        raise HTTPException(404, detail={"codigo": "recurso_no_encontrado"})
    return row
