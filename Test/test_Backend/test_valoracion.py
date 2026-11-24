"""POST /valoracion (CTR-001): valoración de la utilidad de una respuesta.

Las pruebas con base de datos necesitan un PostgreSQL de pruebas vacío con pgvector en ARSOFT_TEST_DATABASE_URL
(cada prueba recrea el esquema «aplicacion» con Backend/db/init/01_conocimiento.sql). Sin él se omiten.
"""

import itertools
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
import psycopg
from fastapi.testclient import TestClient

from Backend.api.app import limite_consultas, sesiones
from Backend.api.app.links import connect
from Backend.api.app.main import app

RAIZ = Path(__file__).resolve().parents[2]
SQL = (RAIZ / "Backend" / "db" / "init" / "01_conocimiento.sql").read_text(encoding="utf-8")
TOKEN_SERVICIO = "arsoft-test"
DB = os.getenv("ARSOFT_TEST_DATABASE_URL")
SESION_CADUCADA = {"codigo_error": "sesion_caducada", "mensaje": "Tu sesión ha caducado."}


class SinBaseDeDatos(unittest.TestCase):
    def test_sin_sesion_da_401(self):
        with TestClient(app) as client:
            for cuerpo in ({"trace_id": "t-1", "util": True}, {}, {"trace_id": "t-1", "util": "no"}):
                r = client.post("/valoracion", json=cuerpo)
                self.assertEqual(r.status_code, 401, cuerpo)
                self.assertEqual(r.json(), SESION_CADUCADA)

    def test_token_falso_da_401(self):
        otra_clave = "otra-clave-que-no-es-la-de-backend-0000000"
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO}), TestClient(app) as client:
            for token in ("dummy", jwt.encode({"sub": "1"}, otra_clave, algorithm="HS256")):
                r = client.post("/valoracion", json={"trace_id": "t-1", "util": True},
                                headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(r.status_code, 401, token)
                self.assertEqual(r.json(), SESION_CADUCADA)

    def test_el_token_de_servicio_no_es_una_sesion(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO}), TestClient(app) as client:
            r = client.post("/valoracion", json={"trace_id": "t-1", "util": True},
                            headers={"Authorization": f"Bearer {TOKEN_SERVICIO}"})
        self.assertEqual(r.status_code, 401)

    def test_limite_de_valoraciones_es_independiente_del_de_consultas(self):
        limite_consultas.reiniciar()
        with patch.dict(os.environ, {"ARSOFT_VALORACIONES_POR_MINUTO": "2", "ARSOFT_CONSULTAS_POR_MINUTO": "1"}):
            self.assertEqual([limite_consultas.admitir(7, "valoracion") for _ in range(2)], [0, 0])
            self.assertGreaterEqual(limite_consultas.admitir(7, "valoracion"), 1)
            self.assertEqual(limite_consultas.admitir(7), 0)  # el ámbito de consultas no se ha tocado
        limite_consultas.reiniciar()


@unittest.skipUnless(DB, "Requiere un PostgreSQL de pruebas (ARSOFT_TEST_DATABASE_URL)")
class ConBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DATABASE_URL": DB, "ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO,
                                           "AGENTES_URL": "http://agentes.test"})
        self.env.start()
        with connect() as conn:
            conn.execute("DROP SCHEMA IF EXISTS aplicacion CASCADE")
            conn.execute(SQL)
            from Backend.api.app.usuarios_prueba import crear_usuarios_prueba
            crear_usuarios_prueba(conn)
        sesiones._fallos.clear()
        limite_consultas.reiniciar()
        self.contador = itertools.count(1)
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.agents_client = httpx.AsyncClient(transport=httpx.MockTransport(self._agentes))

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()

    def _agentes(self, request: httpx.Request) -> httpx.Response:
        """Cada consulta recibe un trace_id distinto. «aclaracion» en la pregunta da una aclaración."""
        if request.method == "DELETE":
            return httpx.Response(204)
        pregunta = json.loads(request.content)["pregunta"]
        trace = f"t-{next(self.contador)}"
        if "aclaracion" in pregunta:
            return httpx.Response(200, json={"trace_id": trace, "estado": "aclaracion", "texto": "¿V1.0 o V2.0?",
                                             "fuentes": [], "codigo_error": ""})
        return httpx.Response(200, json={
            "trace_id": trace, "estado": "respuesta", "texto": "Cada 60.000 km.", "codigo_error": "",
            "fuentes": [{"chunk_id": "c45", "documento": "HTM240-MNT-001", "seccion": "2.1", "pagina": 2,
                         "versiones": ["V1.0"], "obsoleto": False}]})

    def login(self, usuario="usuario1", contrasena="usuario123"):
        r = self.client.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def preguntar(self, h, pregunta="refrigerante"):
        r = self.client.post("/consulta", json={"conversacion_id": "", "pregunta": pregunta}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["trace_id"]

    def valorar(self, h, trace_id, util):
        return self.client.post("/valoracion", json={"trace_id": trace_id, "util": util}, headers=h)

    def filas(self):
        with connect() as conn:
            return conn.execute("SELECT trace_id, usuario_id, util FROM aplicacion.valoracion ORDER BY id").fetchall()

    def test_valoracion_correcta(self):
        h = self.login()
        trace = self.preguntar(h)
        r = self.valorar(h, trace, True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"trace_id": trace, "util": True})
        filas = self.filas()
        self.assertEqual([(f["trace_id"], f["util"]) for f in filas], [(trace, True)])
        yo = self.client.get("/auth/me", headers=h).json()
        self.assertEqual(str(filas[0]["usuario_id"]), yo["id"])

    def test_valoracion_negativa(self):
        h = self.login()
        trace = self.preguntar(h)
        self.assertEqual(self.valorar(h, trace, False).json(), {"trace_id": trace, "util": False})
        self.assertEqual([f["util"] for f in self.filas()], [False])

    def test_sin_sesion_da_401_y_no_guarda(self):
        trace = self.preguntar(self.login())
        r = self.client.post("/valoracion", json={"trace_id": trace, "util": True})
        self.assertEqual((r.status_code, r.json()), (401, SESION_CADUCADA))
        self.assertEqual(self.filas(), [])

    def test_trace_id_inexistente_da_404(self):
        h = self.login()
        r = self.valorar(h, "no-existe", True)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"codigo_error": "respuesta_no_encontrada", "mensaje": "La respuesta no existe."})
        self.assertEqual(self.filas(), [])

    def test_trace_id_de_otro_usuario_da_el_mismo_404_y_no_guarda(self):
        h1, h2 = self.login(), self.login("usuario2")
        ajeno = self.preguntar(h1)
        r_ajeno = self.valorar(h2, ajeno, True)
        r_inexistente = self.valorar(h2, "no-existe", True)
        self.assertEqual(r_ajeno.status_code, 404)
        self.assertEqual(r_ajeno.json(), r_inexistente.json())  # no se distingue «ajeno» de «no existe»
        self.assertEqual(self.filas(), [])
        self.assertEqual(self.valorar(h1, ajeno, True).status_code, 200)  # su dueño sí puede

    def test_solo_se_valoran_respuestas(self):
        h = self.login()
        aclaracion = self.preguntar(h, "aclaracion")
        r = self.valorar(h, aclaracion, True)
        self.assertEqual((r.status_code, r.json()["codigo_error"]), (404, "respuesta_no_encontrada"))
        self.assertEqual(self.filas(), [])

    def test_util_invalido_da_422(self):
        h = self.login()
        trace = self.preguntar(h)
        esperado = {"codigo_error": "entrada_invalida", "mensaje": "Faltan datos o el formato es incorrecto."}
        for cuerpo in ({"trace_id": trace, "util": "si"}, {"trace_id": trace, "util": 1},
                       {"trace_id": trace, "util": "true"}, {"trace_id": trace, "util": None},
                       {"trace_id": trace}, {"util": True}, {"trace_id": "", "util": True},
                       {"trace_id": "x" * 129, "util": True}, {"trace_id": 5, "util": True}):
            r = self.client.post("/valoracion", json=cuerpo, headers=h)
            self.assertEqual(r.status_code, 422, cuerpo)
            self.assertEqual(r.json(), esperado, cuerpo)
        self.assertEqual(self.filas(), [])

    def test_valorar_dos_veces_actualiza_sin_duplicar(self):
        h = self.login()
        trace = self.preguntar(h)
        self.assertEqual(self.valorar(h, trace, True).status_code, 200)
        r = self.valorar(h, trace, False)
        self.assertEqual((r.status_code, r.json()), (200, {"trace_id": trace, "util": False}))
        self.assertEqual(self.valorar(h, trace, False).status_code, 200)
        self.assertEqual([(f["trace_id"], f["util"]) for f in self.filas()], [(trace, False)])
        with connect() as conn:
            f = conn.execute("SELECT creado_en < actualizado_en AS cambia FROM aplicacion.valoracion").fetchone()
        self.assertTrue(f["cambia"])

    def test_cada_usuario_tiene_su_valoracion(self):
        h1, h2 = self.login(), self.login("usuario2")
        t1, t2 = self.preguntar(h1), self.preguntar(h2)
        self.valorar(h1, t1, True)
        self.valorar(h2, t2, False)
        self.assertEqual(sorted((f["trace_id"], f["util"]) for f in self.filas()), sorted([(t1, True), (t2, False)]))

    def test_usuario_desactivado_recibe_403(self):
        h = self.login()
        trace = self.preguntar(h)
        with connect() as conn:
            conn.execute("UPDATE aplicacion.usuario SET activo=false WHERE nombre_usuario='usuario1'")
        r = self.valorar(h, trace, True)
        self.assertEqual((r.status_code, r.json()["codigo_error"]), (403, "acceso_denegado"))
        self.assertEqual(self.filas(), [])

    def test_429_demasiadas_valoraciones(self):
        h1, h2 = self.login(), self.login("usuario2")
        trace, trace2 = self.preguntar(h1), self.preguntar(h2)
        with patch.dict(os.environ, {"ARSOFT_VALORACIONES_POR_MINUTO": "2"}):
            self.assertEqual(self.valorar(h1, trace, True).status_code, 200)
            self.assertEqual(self.valorar(h1, trace, False).status_code, 200)
            r = self.valorar(h1, trace, True)
            self.assertEqual((r.status_code, r.json()["codigo_error"]), (429, "demasiadas_valoraciones"))
            self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
            self.assertEqual([f["util"] for f in self.filas()], [False])  # la tercera no se guarda
            self.assertEqual(self.valorar(h2, trace2, True).status_code, 200)  # el límite es por usuario
            self.preguntar(h1)  # y no consume el cupo de consultas

    def test_500_con_formato_de_error(self):
        h = self.login()
        trace = self.preguntar(h)
        with patch("Backend.api.app.valoracion.guardar", side_effect=RuntimeError("fallo inesperado")), \
                TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/valoracion", json={"trace_id": trace, "util": True}, headers=h)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json(), {"codigo_error": "error_interno", "mensaje": "Error interno del servidor."})
        self.assertNotIn("fallo inesperado", r.text)

    def test_base_caida_da_503_con_formato_de_error(self):
        h = self.login()
        trace = self.preguntar(h)
        with patch("Backend.api.app.valoracion.connect", side_effect=psycopg.OperationalError("caída")):
            r = self.valorar(h, trace, True)
        self.assertEqual((r.status_code, r.json()["codigo_error"]), (503, "servicio_no_disponible"))
        self.assertIn("mensaje", r.json())

    def test_tabla_sin_migrar_da_503_y_queda_en_el_log(self):
        h = self.login()
        trace = self.preguntar(h)
        with connect() as conn:
            conn.execute("DROP TABLE aplicacion.valoracion")
        with self.assertLogs("arsoft.backend", level="ERROR") as log:
            r = self.valorar(h, trace, True)
        self.assertEqual((r.status_code, r.json()["codigo_error"]), (503, "servicio_no_disponible"))
        self.assertIn("valoracion", "\n".join(log.output))  # el motivo real se ve en el log, no en la respuesta
        self.assertNotIn("valoracion", r.text)

    def test_hay_indice_para_buscar_la_respuesta_por_usuario_y_trace_id(self):
        with connect() as conn:
            defs = [f["indexdef"] for f in conn.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname='aplicacion' AND tablename='registro_consulta'"
            ).fetchall()]
        self.assertTrue(any("(usuario_id, trace_id)" in d for d in defs), defs)


if __name__ == "__main__":
    unittest.main()
