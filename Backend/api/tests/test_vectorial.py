"""Pruebas de POST /conocimiento/vectorial (CTR-002 ed. 1.1 §4 y §6).

Las de validación no necesitan base de datos. Las demás requieren un PostgreSQL con pgvector:

    pip install fastapi httpx "psycopg[binary]" pytest
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/thermodrive_test
    cd Backend/api && python -m pytest

Crean el esquema `conocimiento` si no existe y cargan una versión de índice propia («test-api»),
que borran al terminar. No tocan otras versiones.
"""

import math
import os
import random
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.vectorial import busqueda, crear_router

DATABASE_URL = os.getenv("DATABASE_URL")
ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "init" / "01_conocimiento.sql"
VERSION = "test-api"
MODELO = "BAAI/bge-m3"
DIM = 1024

necesita_bd = pytest.mark.skipif(not DATABASE_URL, reason="define DATABASE_URL (PostgreSQL con pgvector)")


def vector(semilla: int):
    rnd = random.Random(semilla)
    v = [rnd.gauss(0, 1) for _ in range(DIM)]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


# chunk_id, doc_id, componente, tipo, versiones, vigente_para, obsoleto, sustituido_por, semilla
CHUNKS = [
    ("c1", "DOC-A@1.0", "bateria", "codigo_averia", ["V1.1", "V2.0"], [], False, None, 1),
    ("c2", "DOC-A@1.0", "motor", "codigo_averia", ["V1.0", "V1.1", "V2.0"], [], False, None, 2),
    ("c3", "DOC-B@2.0", "motor", "procedimiento", ["V1.1", "V2.0"], [], False, None, 3),
    ("c4", "DOC-B@1.0", "motor", "procedimiento", ["V1.0"], ["V1.0"], True, "DOC-B@2.0", 4),   # sustituido, vigente solo en V1.0
    ("c5", "DOC-C@1.0", "motor", "mantenimiento", ["V1.0", "V1.1"], ["V1.0", "V1.1"], True, "DOC-C@1.1", 5),  # sustituido, aún válido en V1.1
    ("c6", "DOC-D@1.0", "sistema", "boletin", ["V1.0", "V1.1"], [], True, "DOC-D@1.1", 6),     # sustituido, sin vigencia
    ("c7", "DOC-E@1.0", "refrigeracion_inexistente_en_v20", "boletin", ["V1.0"], [], False, None, 7),
]
DOCS = sorted({c[1] for c in CHUNKS})


@pytest.fixture(scope="module")
def bd():
    if not DATABASE_URL:
        pytest.skip("sin DATABASE_URL")
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(ESQUEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM conocimiento.indice_version WHERE version = %s", (VERSION,))
        conn.execute("UPDATE conocimiento.indice_version SET activo = false WHERE activo")
        conn.execute("INSERT INTO conocimiento.indice_version (version, modelo_embeddings, dimensiones, prefijo_passage, "
                     "n_chunks, activo) VALUES (%s, %s, %s, 'passage: ', %s, true)", (VERSION, MODELO, DIM, len(CHUNKS)))
        for doc in DOCS:
            conn.execute(
                "INSERT INTO conocimiento.documento (doc_id, codigo, tipo_documento, titulo, version_documento, obsoleto, "
                "versiones_vehiculo) VALUES (%s, %s, 'x', 't', '1.0', false, '{}') ON CONFLICT DO NOTHING",
                (doc, doc.split("@")[0]))
        for cid, doc, comp, tipo, vers, vig, obs, sust, sem in CHUNKS:
            conn.execute(
                """INSERT INTO conocimiento.chunk (indice_version, chunk_id, doc_id, documento, texto, seccion, pagina,
                   orden_en_seccion, versiones, componente, tipo_documento, obsoleto, sustituido_por, vigente_para,
                   fecha_revision, version_documento, afectado_por, ids_referenciados, embedding)
                   VALUES (%s,%s,%s,%s,%s,'2.1',3,1,%s,%s,%s,%s,%s,%s,'2025-09-15','1.0',%s,%s,%s::vector)""",
                (VERSION, cid, doc, doc.split("@")[0], f"texto original de {cid}", vers, comp, tipo, obs, sust, vig,
                 ["BOL-003"], ["HTM-0142", "CMP-18"], busqueda.vector_literal(vector(sem))))
        conn.execute("INSERT INTO conocimiento.catalogo (nombre, version, contenido, activo) VALUES "
                     "('vehiculos', %s, %s::jsonb, true) ON CONFLICT DO NOTHING",
                     (VERSION, '[{"version":"V1.0"},{"version":"V1.1"},{"version":"V2.0"}]'))
    yield
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("DELETE FROM conocimiento.indice_version WHERE version = %s", (VERSION,))


def conectar():
    """Igual que links.connect de integracion-api: filas como diccionario y sin autocommit."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def montar(abrir_conexion, acceso=None) -> TestClient:
    app = FastAPI()
    app.include_router(crear_router(abrir_conexion, acceso))
    return TestClient(app)


@pytest.fixture()
def cliente(bd):
    busqueda.limpiar_cache()
    return montar(conectar)


def pedir(cliente, sem=1, filtros=None, k=30, **extra):
    cuerpo = {"vector": vector(sem), "k": k, **extra}
    if filtros is not None:
        cuerpo["filtros"] = filtros
    return cliente.post("/conocimiento/vectorial", json=cuerpo)


def ids(r):
    return [x["chunk_id"] for x in r.json()["resultados"]]


@necesita_bd
def test_ordenado_por_score_y_el_identico_primero(cliente):
    r = pedir(cliente, sem=3)
    assert r.status_code == 200
    assert ids(r)[0] == "c3"
    scores = [x["score"] for x in r.json()["resultados"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(1.0, abs=1e-6)  # coseno de un vector consigo mismo


@necesita_bd
def test_k_limita_resultados(cliente):
    assert len(ids(pedir(cliente, k=2))) == 2


@necesita_bd
def test_formato_de_respuesta_del_contrato(cliente):
    cuerpo = pedir(cliente, sem=1, modelo_embeddings=MODELO).json()
    assert cuerpo["indice"] == {"version": VERSION, "modelo_embeddings": MODELO}
    esperado = {"chunk_id", "score", "texto", "documento", "seccion", "pagina", "versiones", "componente",
                "tipo_documento", "obsoleto", "sustituido_por", "vigente_para", "fecha_revision", "orden_en_seccion",
                "version_documento", "afectado_por", "ids_referenciados"}
    primero = cuerpo["resultados"][0]
    assert set(primero) == esperado  # y sin «embedding»
    assert primero["texto"] == "texto original de c1"       # sin prefijo passage:
    assert primero["fecha_revision"] == "2025-09-15"
    assert primero["afectado_por"] == ["BOL-003"] and primero["ids_referenciados"] == ["HTM-0142", "CMP-18"]


@necesita_bd
def test_filtros_nulos_o_omitidos_no_restringen(cliente):
    assert len(ids(pedir(cliente))) == len(CHUNKS)
    assert len(ids(pedir(cliente, filtros={"version": None, "componente": None, "tipo_documento": None}))) == len(CHUNKS)


@necesita_bd
def test_filtro_version_usa_vigente_para(cliente):
    v11 = set(ids(pedir(cliente, filtros={"version": "V1.1"})))
    assert v11 == {"c1", "c2", "c3", "c5"}      # c5: sustituido pero aún válido para V1.1; c4 y c6 fuera
    assert set(ids(pedir(cliente, filtros={"version": "V1.0"}))) == {"c2", "c4", "c5", "c7"}
    assert set(ids(pedir(cliente, filtros={"version": "V2.0"}))) == {"c1", "c2", "c3"}


@necesita_bd
def test_filtro_componente_y_tipo(cliente):
    assert set(ids(pedir(cliente, filtros={"componente": "motor"}))) == {"c2", "c3", "c4", "c5"}
    assert set(ids(pedir(cliente, filtros={"tipo_documento": "procedimiento"}))) == {"c3", "c4"}
    assert set(ids(pedir(cliente, filtros={"version": "V1.1", "componente": "motor", "tipo_documento": "procedimiento"}))) == {"c3"}


@necesita_bd
def test_sin_resultados_es_200_vacio_y_no_relaja_filtros(cliente):
    # V2.0 + componente «sistema» no tiene chunks; el Backend no amplía nada por su cuenta
    r = pedir(cliente, filtros={"version": "V2.0", "componente": "sistema"})
    assert r.status_code == 200 and r.json()["resultados"] == []


@necesita_bd
def test_filtro_con_valor_inexistente_es_400_con_valores_validos(cliente):
    r = pedir(cliente, filtros={"componente": "turbina"})
    assert r.status_code == 400
    cuerpo = r.json()
    assert cuerpo["campo"] == "componente" and "motor" in cuerpo["valores_validos"]
    assert pedir(cliente, filtros={"version": "V9.9"}).json()["valores_validos"] == ["V1.0", "V1.1", "V2.0"]


@necesita_bd
def test_modelo_distinto_es_409_modelo_incompatible(cliente):
    r = pedir(cliente, modelo_embeddings="otro/modelo")
    assert r.status_code == 409 and r.json()["codigo"] == "modelo_incompatible"


@necesita_bd
def test_sin_indice_activo_es_503(cliente):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("UPDATE conocimiento.indice_version SET activo = false WHERE version = %s", (VERSION,))
    try:
        r = pedir(cliente)
        assert r.status_code == 503 and r.json()["codigo"] == "indice_no_disponible"
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute("UPDATE conocimiento.indice_version SET activo = true WHERE version = %s", (VERSION,))


@necesita_bd
def test_indice_nuevo_en_carga_no_afecta_a_la_activa(cliente):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("INSERT INTO conocimiento.indice_version (version, modelo_embeddings, dimensiones) "
                     "VALUES ('test-api-nueva', 'otro/modelo', 1024)")
    try:
        r = pedir(cliente)
        assert r.status_code == 200 and r.json()["indice"]["version"] == VERSION
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute("DELETE FROM conocimiento.indice_version WHERE version = 'test-api-nueva'")


# --- Validación de la petición, acceso y caída de la base de datos (sin base de datos) ---

def sin_bd():
    raise AssertionError("no debería abrirse la conexión")


@pytest.fixture()
def cliente_sin_bd():
    return montar(sin_bd)


def test_acceso_protege_la_ruta():
    def denegar():
        raise HTTPException(401, detail={"codigo": "acceso_denegado"})

    protegido = montar(sin_bd, acceso=denegar)
    r = protegido.post("/conocimiento/vectorial", json={"vector": [0.1] * 1024, "k": 1})
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "acceso_denegado"


def test_base_de_datos_caida_es_503_indice_no_disponible():
    def caida():
        raise psycopg.OperationalError("sin conexión")

    r = montar(caida).post("/conocimiento/vectorial", json={"vector": [0.1] * 1024, "k": 1})
    assert r.status_code == 503 and r.json()["codigo"] == "indice_no_disponible"


@pytest.mark.parametrize("cuerpo", [
    {"vector": [0.1] * 1023, "k": 30},                                 # no son 1024 floats
    {"vector": [0.1] * 1025, "k": 30},
    {"k": 30},                                                          # falta el vector
    {"vector": [0.1] * 1024},                                           # falta k
    {"vector": [0.1] * 1024, "k": 0},
    {"vector": [0.1] * 1024, "k": 30, "filtros": {"codigos": ["HTM-0142"]}},  # los códigos no van en filtros
    {"vector": [0.1] * 1024, "k": 30, "filtros": {"versoin": "V1.1"}},        # un filtro mal escrito no se ignora
])
def test_peticion_invalida_es_400(cliente_sin_bd, cuerpo):
    r = cliente_sin_bd.post("/conocimiento/vectorial", json=cuerpo)
    assert r.status_code == 400 and r.json()["codigo"] == "peticion_invalida"
    assert "0.1" not in r.text  # no se devuelve el vector


def test_consulta_sql_solo_incluye_filtros_con_valor():
    def where(sql):
        return sql.split("WHERE")[1].split("ORDER BY")[0]

    sin = where(busqueda.construir_consulta({"version": None, "componente": None, "tipo_documento": None}))
    assert "vigente_para" not in sin and "componente" not in sin and "tipo_documento" not in sin
    con_sql = busqueda.construir_consulta({"version": "V1.1", "componente": "motor", "tipo_documento": None})
    con = where(con_sql)
    assert "vigente_para" in con and "c.componente = %(componente)s" in con and "tipo_documento" not in con
    assert "<=>" in con_sql and "LIMIT %(k)s" in con_sql
