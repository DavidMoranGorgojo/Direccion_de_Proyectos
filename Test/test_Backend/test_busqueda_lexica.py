"""Pruebas de la búsqueda léxica BM25 de CTR-002. Conexión simulada, por lo que no necesitan PostgreSQL

Ejecutar desde la raíz del repositorio con ``PYTHONPATH=shared:.``.
"""

import os
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from Backend.api.app import busqueda_lexica
from Backend.api.app.busqueda import METADATOS
from Backend.api.app.busqueda_lexica import IndiceLexico, tokenizar
from Backend.api.app.main import app

TOKEN = "arsoft-test"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
INDICE = {"version": "v1.0-bd", "modelo_embeddings": "BAAI/bge-m3", "tokenizador": "BAAI/bge-m3",
          "dimensiones": 1024, "n_chunks": 5}


def chunk(chunk_id, texto, *, componente="refrigeracion", tipo="codigo_averia", versiones=("V1.1", "V2.0"),
          obsoleto=False, vigente_para=(), sustituido_por=None):
    return {
        "chunk_id": chunk_id, "texto": texto, "documento": "HTM240-DTC-001", "seccion": "2.1", "pagina": 3,
        "versiones": list(versiones), "componente": componente, "tipo_documento": tipo, "obsoleto": obsoleto,
        "sustituido_por": sustituido_por, "vigente_para": list(vigente_para), "fecha_revision": date(2026, 9, 1),
        "orden_en_seccion": 1, "version_documento": "1.0", "afectado_por": ["BOL-003"],
        "ids_referenciados": ["HTM-0142"],
    }


CORPUS = [
    chunk("c1", "El testigo de temperatura HTM-0142 indica sobrecalentamiento del circuito de refrigeración."),
    chunk("c2", "Procedimiento de purga del circuito de refrigeración tras sustituir el radiador.",
          tipo="procedimiento"),
    chunk("c3", "Par de apriete de la culata en la versión inicial.", componente="culata", tipo="mantenimiento",
          versiones=("V1.0",), obsoleto=True, vigente_para=("V1.0",), sustituido_por="HTM240-PRC-003@2.0"),
    chunk("c4", "Par de apriete de la culata, edición vigente. Consulte CMP-18 y HTM-0142.", componente="culata",
          tipo="mantenimiento", versiones=("V1.1", "V2.0")),
    chunk("c5", "El circuito de refrigeración usa el testigo de temperatura del panel de instrumentos.",
          versiones=("V2.0",)),
]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, indice=INDICE, chunks=CORPUS):
        self.indice, self.chunks = indice, chunks
        self.chunk_queries = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if "FROM conocimiento.indice_version" in sql:
            return FakeResult([self.indice] if self.indice else [])
        if "FROM conocimiento.chunk" in sql:
            self.chunk_queries += 1
            return FakeResult(self.chunks)
        return FakeResult([])  # SET TRANSACTION


class Tokenizador(unittest.TestCase):
    def test_conserva_codigos_como_un_unico_termino(self):
        self.assertEqual(tokenizar("testigo HTM-0142 y CMP-18 en V1.1"),
                         ["testigo", "htm-0142", "y", "cmp-18", "en", "v1.1"])

    def test_normaliza_mayusculas_y_acentos(self):
        self.assertEqual(tokenizar("Refrigeración ÁCIDO"), ["refrigeracion", "acido"])

    def test_palabras_con_guion_sin_digitos_se_parten(self):
        self.assertEqual(tokenizar("anti-corrosión"), ["anti", "corrosion"])


class MotorBm25(unittest.TestCase):
    def setUp(self):
        self.motor = IndiceLexico(CORPUS)

    def ids(self, texto, filtros=None, k=30):
        return [fila["chunk_id"] for fila, _ in self.motor.buscar(texto, filtros or {}, k)]

    def test_codigo_exacto_entre_los_cinco_primeros(self):
        self.assertIn("c1", self.ids("testigo de temperatura HTM-0142 no arranca")[:5])
        self.assertEqual(self.ids("HTM-0142")[0], "c1")

    def test_scores_descendentes_y_positivos(self):
        scores = [s for _, s in self.motor.buscar("circuito de refrigeración", {}, 30)]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(s > 0 for s in scores))

    def test_sin_coincidencias_devuelve_lista_vacia(self):
        self.assertEqual(self.ids("neumatico trasero pinchado"), [])
        self.assertEqual(self.ids("¿¿??"), [])

    def test_k_limita_los_resultados(self):
        self.assertEqual(len(self.ids("circuito de refrigeración", k=1)), 1)

    def test_filtro_version_usa_vigencia(self):
        # c3 está sustituido pero sigue vigente para V1.0; c4 es la edición vigente para V1.1/V2.0
        self.assertEqual(self.ids("apriete culata", {"version": "V1.0"}), ["c3"])
        self.assertEqual(self.ids("apriete culata", {"version": "V1.1"}), ["c4"])

    def test_filtros_componente_y_tipo(self):
        self.assertEqual(set(self.ids("circuito de refrigeración", {"componente": "refrigeracion"})), {"c1", "c2", "c5"})
        self.assertEqual(self.ids("circuito de refrigeración", {"tipo_documento": "procedimiento"}), ["c2"])

    def test_filtro_duro_antes_de_puntuar(self):
        # El filtro no cambia el score de un chunk: las estadísticas son las de todo el índice
        sin_filtro = dict((f["chunk_id"], s) for f, s in self.motor.buscar("culata", {}, 30))
        con_filtro = dict((f["chunk_id"], s) for f, s in self.motor.buscar("culata", {"version": "V1.1"}, 30))
        self.assertEqual(set(con_filtro), {"c4"})
        self.assertAlmostEqual(con_filtro["c4"], sin_filtro["c4"])

    def test_valor_de_filtro_inexistente_da_400_con_valores_validos(self):
        with self.assertRaises(Exception) as ctx:
            self.motor.validar({"componente": "frenos"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["campo"], "componente")
        self.assertEqual(ctx.exception.detail["valores_validos"], ["culata", "refrigeracion"])


class EndpointLexica(unittest.TestCase):
    def setUp(self):
        busqueda_lexica._cache.update(clave=None, indice=None)
        self.env = patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN})
        self.env.start()
        self.addCleanup(self.env.stop)

    @contextmanager
    def servicio(self, conexion=None):
        conexion = conexion or FakeConnection()
        with patch("Backend.api.app.conocimiento.connect", return_value=conexion), TestClient(app) as client:
            yield client, conexion

    def test_requiere_token_de_servicio(self):
        with self.servicio() as (client, _):
            self.assertEqual(client.post("/conocimiento/lexica", json={"texto": "HTM-0142"}).status_code, 401)

    def test_respuesta_con_el_formato_del_contrato(self):
        with self.servicio() as (client, _):
            response = client.post("/conocimiento/lexica", headers=HEADERS, json={
                "texto": "testigo de temperatura HTM-0142 no arranca", "filtros": {"version": "V1.1"}, "k": 30})
        self.assertEqual(response.status_code, 200, response.text)
        cuerpo = response.json()
        self.assertEqual(set(cuerpo), {"indice", "resultados"})
        self.assertEqual(cuerpo["indice"], {"version": "v1.0-bd", "modelo_embeddings": "BAAI/bge-m3"})
        primero = cuerpo["resultados"][0]
        self.assertEqual(set(primero), {"score", *METADATOS})
        self.assertEqual(primero["chunk_id"], "c1")
        self.assertEqual(primero["texto"], CORPUS[0]["texto"])
        self.assertEqual(primero["fecha_revision"], "2026-09-01")
        self.assertNotIn("embedding", primero)

    def test_sin_resultados_es_200_con_lista_vacia(self):
        with self.servicio() as (client, _):
            response = client.post("/conocimiento/lexica", headers=HEADERS, json={"texto": "neumatico", "k": 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resultados"], [])

    def test_filtro_con_valor_inexistente_da_400(self):
        with self.servicio() as (client, _):
            response = client.post("/conocimiento/lexica", headers=HEADERS,
                                   json={"texto": "culata", "filtros": {"version": "V9.9"}})
        self.assertEqual(response.status_code, 400)
        cuerpo = response.json()
        self.assertEqual((cuerpo["codigo"], cuerpo["campo"]), ("filtro_invalido", "version"))
        self.assertIn("V1.1", cuerpo["valores_validos"])

    def test_filtros_nulos_no_restringen(self):
        with self.servicio() as (client, _):
            nulo = client.post("/conocimiento/lexica", headers=HEADERS, json={
                "texto": "culata", "filtros": {"version": None, "componente": None}})
            omitido = client.post("/conocimiento/lexica", headers=HEADERS, json={"texto": "culata"})
        self.assertEqual(nulo.json(), omitido.json())
        self.assertEqual(len(nulo.json()["resultados"]), 2)

    def test_peticiones_mal_formadas(self):
        with self.servicio() as (client, _):
            for cuerpo in ({}, {"texto": "   "}, {"texto": "culata", "k": 0}, {"texto": "culata", "k": 1000},
                           {"texto": "culata", "filtros": {"obsoleto": False}}):
                response = client.post("/conocimiento/lexica", headers=HEADERS, json=cuerpo)
                self.assertEqual(response.status_code, 422, cuerpo)

    def test_sin_indice_activo_da_503(self):
        with self.servicio(FakeConnection(indice=None)) as (client, _):
            response = client.post("/conocimiento/lexica", headers=HEADERS, json={"texto": "culata"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["codigo"], "indice_no_disponible")

    def test_el_indice_se_carga_una_vez_por_version(self):
        with self.servicio() as (client, conexion):
            for _ in range(3):
                client.post("/conocimiento/lexica", headers=HEADERS, json={"texto": "culata"})
        self.assertEqual(conexion.chunk_queries, 1)

    def test_info_publica_el_tokenizador_lexico(self):
        with self.servicio() as (client, _):
            response = client.get("/conocimiento/info", headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertIn("tokenizador_lexico", response.json())


if __name__ == "__main__":
    unittest.main()
