"""Carga en PostgreSQL + pgvector como nueva versión del índice (paso 5.8 del diseño de ingesta).

1. Se crea la versión, inactiva. 2. Se cargan documentos, chunks y catálogos.
3. Se valida el recuento por documento y la dimensión de los vectores.
4. Se activa la versión; la anterior queda inactiva pero se conserva.
Si algo falla, la transacción se deshace y la versión activa no cambia.
"""

import os
from collections import Counter
from pathlib import Path
from typing import Dict, List

import psycopg
from psycopg.types.json import Jsonb

from . import config

ESQUEMA_SQL = Path(os.getenv("INGESTA_ESQUEMA_SQL",
                             Path(__file__).resolve().parents[3] / "db" / "init" / "01_conocimiento.sql"))

COLUMNAS_CHUNK = [
    "indice_version", "chunk_id", "doc_id", "documento", "texto", "seccion", "pagina", "orden_en_seccion",
    "versiones", "componente", "tipo_documento", "obsoleto", "sustituido_por", "vigente_para",
    "fecha_revision", "version_documento", "afectado_por", "ids_referenciados", "embedding",
]


def vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


def crear_esquema(conn: psycopg.Connection, ruta: Path = ESQUEMA_SQL) -> None:
    conn.execute(ruta.read_text(encoding="utf-8"))
    conn.commit()


def cargar(database_url: str, version: str, documentos: List[dict], chunks: List[dict],
           catalogos: Dict[str, dict], tokenizador: str, activar: bool = True, esquema: bool = False) -> dict:
    with psycopg.connect(database_url) as conn:
        if esquema:
            crear_esquema(conn)
        with conn.transaction():
            fila = conn.execute("SELECT activo FROM conocimiento.indice_version WHERE version = %s", (version,)).fetchone()
            if fila and fila[0]:
                raise RuntimeError(f"La versión {version} está activa: usa otra versión para reindexar.")
            if fila:
                # Reejecución de una versión que no llegó a activarse: se rehace desde cero
                conn.execute("DELETE FROM conocimiento.indice_version WHERE version = %s", (version,))

            conn.execute(
                """INSERT INTO conocimiento.indice_version
                   (version, modelo_embeddings, dimensiones, prefijo_passage, tokenizador, n_chunks)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (version, config.MODELO_EMBEDDINGS, config.DIMENSIONES, config.PREFIJO_PASSAGE, tokenizador, len(chunks)),
            )
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO conocimiento.documento
                       (doc_id, codigo, tipo_documento, titulo, version_documento, fecha_revision,
                        obsoleto, sustituido_por, versiones_vehiculo, vigente_para)
                       VALUES (%(doc_id)s, %(codigo)s, %(tipo_documento)s, %(titulo)s, %(version_documento)s,
                               %(fecha_revision)s, %(obsoleto)s, %(sustituido_por)s, %(versiones_vehiculo)s, %(vigente_para)s)
                       ON CONFLICT (doc_id) DO UPDATE SET
                         codigo = EXCLUDED.codigo, tipo_documento = EXCLUDED.tipo_documento,
                         titulo = EXCLUDED.titulo, version_documento = EXCLUDED.version_documento,
                         fecha_revision = EXCLUDED.fecha_revision, obsoleto = EXCLUDED.obsoleto,
                         sustituido_por = EXCLUDED.sustituido_por,
                         versiones_vehiculo = EXCLUDED.versiones_vehiculo, vigente_para = EXCLUDED.vigente_para""",
                    documentos,
                )
                marcadores = ", ".join("%s::vector" if c == "embedding" else "%s" for c in COLUMNAS_CHUNK)
                cur.executemany(
                    f"INSERT INTO conocimiento.chunk ({', '.join(COLUMNAS_CHUNK)}) VALUES ({marcadores})",
                    [
                        [version if c == "indice_version" else vector_literal(ch["embedding"]) if c == "embedding" else ch[c]
                         for c in COLUMNAS_CHUNK]
                        for ch in chunks
                    ],
                )
                cur.executemany(
                    "INSERT INTO conocimiento.catalogo (nombre, version, contenido) VALUES (%s, %s, %s)",
                    [(nombre, version, Jsonb(cat["contenido"])) for nombre, cat in catalogos.items()],
                )

            # Validación dentro de la transacción: si no cuadra, no se activa nada
            esperado = Counter(ch["doc_id"] for ch in chunks)
            cargado = dict(conn.execute(
                "SELECT doc_id, count(*) FROM conocimiento.chunk WHERE indice_version = %s GROUP BY doc_id", (version,)
            ).fetchall())
            if cargado != dict(esperado):
                raise RuntimeError(f"Recuento por documento distinto del esperado: {cargado} != {dict(esperado)}")
            dims = conn.execute(
                "SELECT DISTINCT vector_dims(embedding) FROM conocimiento.chunk WHERE indice_version = %s", (version,)
            ).fetchall()
            if dims != [(config.DIMENSIONES,)]:
                raise RuntimeError(f"Dimensiones cargadas inesperadas: {dims}")

        if activar:
            with conn.transaction():
                conn.execute("UPDATE conocimiento.indice_version SET activo = false WHERE activo AND version <> %s", (version,))
                conn.execute("UPDATE conocimiento.indice_version SET activo = true WHERE version = %s", (version,))
                conn.execute("UPDATE conocimiento.catalogo SET activo = (version = %s)", (version,))

    return {"version": version, "chunks": len(chunks), "documentos": len(documentos), "activada": activar}
