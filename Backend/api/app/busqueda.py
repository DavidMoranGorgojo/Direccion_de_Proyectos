"""Búsqueda vectorial exacta sobre pgvector (CTR-002 ed. 1.1).

Reglas del contrato que se cumplen aquí:
- Backend compara el vector recibido con los chunks (similitud coseno) y devuelve la lista cruda
  ordenada por score. No fusiona (RRF), no reordena, no redacta (§5.2).
- Prefijos (§5.4): Agentes vectoriza la consulta con «query: » y Backend indexó cada chunk con
  «passage: » (ver ingesta/embeddings.py y indice_version.prefijo_passage). Esta función recibe
  el vector ya hecho, y el texto de los chunks se guarda y se devuelve sin prefijo.
- filtros = WHERE duro antes del cálculo (§5.3). Un filtro nulo u omitido no restringe.
  Backend NO relaja filtros: sin resultados devuelve HTTP 200 con lista vacía y es Agentes quien
  reintenta ampliando solo tipo_documento (§4).
- Vigencia por versión con vigente_para: un chunk aplica a la versión V si V está en vigente_para o
  si el documento no está sustituido y V está en versiones.
- Siempre se consulta la versión activa del índice; una nueva versión en carga no afecta (§5.4).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from .errores import ErrorContrato, indice_no_disponible
from .esquemas import PeticionVectorial

CAMPOS_RESULTADO = (
    "chunk_id", "texto", "documento", "seccion", "pagina", "versiones", "componente", "tipo_documento",
    "obsoleto", "sustituido_por", "vigente_para", "fecha_revision", "orden_en_seccion",
    "version_documento", "afectado_por", "ids_referenciados",
)

# Valores válidos de los filtros por versión de índice. Una versión activa no se recarga (ingesta
# exige una versión nueva), así que se puede conservar en memoria.
_VALIDOS: Dict[str, Dict[str, List[str]]] = {}


def limpiar_cache() -> None:
    _VALIDOS.clear()


@dataclass(frozen=True)
class Indice:
    version: str
    modelo_embeddings: str
    dimensiones: int


def indice_activo(conn: psycopg.Connection) -> Optional[Indice]:
    fila = conn.execute(
        "SELECT version, modelo_embeddings, dimensiones FROM conocimiento.indice_version WHERE activo"
    ).fetchone()
    return Indice(*fila) if fila else None


def valores_validos(conn: psycopg.Connection, indice: Indice) -> Dict[str, List[str]]:
    if indice.version in _VALIDOS:
        return _VALIDOS[indice.version]
    fila = conn.execute(
        "SELECT contenido FROM conocimiento.catalogo WHERE nombre = 'vehiculos' AND version = %s", (indice.version,)
    ).fetchone()
    if fila:
        versiones = sorted(v["version"] for v in fila[0])
    else:
        versiones = [r[0] for r in conn.execute(
            "SELECT DISTINCT unnest(versiones) AS v FROM conocimiento.chunk WHERE indice_version = %s ORDER BY 1",
            (indice.version,)).fetchall()]
    # Componente y tipo de documento: la lista cerrada que usa el índice cargado
    valores = {"version": versiones}
    for campo in ("componente", "tipo_documento"):
        valores[campo] = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {campo} FROM conocimiento.chunk WHERE indice_version = %s ORDER BY 1",
            (indice.version,)).fetchall()]
    _VALIDOS[indice.version] = valores
    return valores


def vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def construir_consulta(filtros: Dict[str, Optional[str]]) -> str:
    """SQL con los filtros no nulos como WHERE duro; el resto de filtros no restringe."""
    condiciones = ["c.indice_version = %(indice)s"]
    if filtros.get("version"):
        condiciones.append("(%(version)s = ANY(c.vigente_para) OR (NOT c.obsoleto AND %(version)s = ANY(c.versiones)))")
    if filtros.get("componente"):
        condiciones.append("c.componente = %(componente)s")
    if filtros.get("tipo_documento"):
        condiciones.append("c.tipo_documento = %(tipo_documento)s")
    columnas = ", ".join(f"c.{campo}" for campo in CAMPOS_RESULTADO)
    return (
        f"SELECT {columnas}, 1 - (c.embedding <=> %(vector)s::vector) AS score "
        "FROM conocimiento.chunk c "
        f"WHERE {' AND '.join(condiciones)} "
        # El desempate por chunk_id hace estable el orden cuando dos scores coinciden
        "ORDER BY c.embedding <=> %(vector)s::vector, c.chunk_id "
        "LIMIT %(k)s"
    )


def _validar_filtros(conn: psycopg.Connection, indice: Indice, filtros: Dict[str, Optional[str]]) -> None:
    validos = None
    for campo, valor in filtros.items():
        if valor is None:
            continue
        validos = validos or valores_validos(conn, indice)
        if valor not in validos[campo]:
            raise ErrorContrato(400, "filtro_invalido", f"El valor «{valor}» no existe para el filtro {campo}.",
                                campo=campo, valores_validos=validos[campo])


def buscar_vectorial(conn: psycopg.Connection, peticion: PeticionVectorial) -> dict:
    indice = indice_activo(conn)
    if indice is None:
        raise indice_no_disponible("No hay una versión de índice activa.")

    if (peticion.modelo_embeddings and peticion.modelo_embeddings != indice.modelo_embeddings) \
            or len(peticion.vector) != indice.dimensiones:
        raise ErrorContrato(
            409, "modelo_incompatible",
            "El modelo o la dimensión del vector no coincide con el índice.",
            modelo_indice=indice.modelo_embeddings, dimensiones_indice=indice.dimensiones,
            modelo_recibido=peticion.modelo_embeddings, dimensiones_recibidas=len(peticion.vector))

    filtros = peticion.filtros.model_dump()
    _validar_filtros(conn, indice, filtros)

    parametros = {**{k: v for k, v in filtros.items() if v}, "indice": indice.version,
                  "vector": vector_literal(peticion.vector), "k": peticion.k}
    with conn.cursor(row_factory=dict_row) as cur:
        filas = cur.execute(construir_consulta(filtros), parametros).fetchall()

    return {
        "indice": {"version": indice.version, "modelo_embeddings": indice.modelo_embeddings},
        "resultados": filas,
    }
