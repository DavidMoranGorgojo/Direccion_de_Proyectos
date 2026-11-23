"""POST /valoracion: valoración de utilidad de una respuesta (CTR-003 §5.3).

Las pruebas con base de datos necesitan un PostgreSQL de pruebas vacío en ARSOFT_TEST_DATABASE_URL,
igual que test_usuarios_historial_registro.py. Sin él se omiten.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import psycopg
from fastapi.testclient import TestClient

from Backend.api.app import limite_consultas, sesiones
from Backend.api.app.links import connect
from Backend.api.app.main import app

RAIZ = Path(__file__).resolve().parents[2]
SQL = (RAIZ / "Backend" / "db" / "init" / "02_usuarios.sql").read_text(encoding="utf-8")
TOKEN_SERVICIO = "arsoft-test"
DB = os.getenv("ARSOFT_TEST_DATABASE_URL")


class SinBaseDeDatos(unittest.TestCase):
    def test_sin_sesion_da_401_aunque_el_cuerpo_sea_invalido(self):
        with TestClient(app) as client:
            for cuerpo in ({"trace_id": "t-1", "util": True}, {}, {"util": "si"}):
                r = client.post("/valoracion", json=cuerpo)
                self.assertEqual(r.status_code, 401, cuerpo)
                self.assertEqual(r.json()["codigo_error"], "sesion_caducada")

    def test_ruta_montada_y_documentada(self):
        self.assertIn("/valoracion", app.openapi()["paths"])

    def test_base_caida_da_503_con_formato_de_error(self):
        from Backend.api.app.valoracion import valorar, Valoracion
        from fastapi import HTTPException
        with patch("Backend.api.app.valoracion.connect", side_effect=psycopg.OperationalError("caída")):
            with self.assertRaises(HTTPException) as error:
                valorar(Valoracion(trace_id="t-1", util=True), {"id": 1})
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.detail["codigo_error"], "servicio_no_disponible")


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
        self.turno = 0
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.agents_client = httpx.AsyncClient(transport=httpx.MockTransport(self._agentes))

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()

    def _agentes(self, request: httpx.Request) -> httpx.Response:
        self.turno += 1
        cuerpo = json.loads(request.content)
        return httpx.Response(200, json={
            "trace_id": f"t-{self.turno}", "estado": "respuesta", "texto": "Cada 60.000 km.", "codigo_error": "",
            "fuentes": [{"chunk_id": "c45", "documento": "HTM240-MNT-001", "seccion": "2.1", "pagina": 2,
                         "versiones": ["V1.0"], "obsoleto": False}],
            "conversacion_id": cuerpo["conversacion_id"]})

    def login(self, usuario="usuario1", contrasena="usuario123"):
        r = self.client.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def preguntar(self, h, pregunta="¿Cada cuánto se cambia el refrigerante?"):
        r = self.client.post("/consulta", json={"conversacion_id": "", "pregunta": pregunta}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["trace_id"]

    def valorar(self, h, **cuerpo):
        return self.client.post("/valoracion", json=cuerpo, headers=h)

    def test_primera_valoracion_201_y_reenvio_200_sin_duplicar(self):
        h = self.login()
        trace = self.preguntar(h)
        r = self.valorar(h, trace_id=trace, util=True, comentario="  Me ha servido  ")
        self.assertEqual(r.status_code, 201, r.text)
        d = r.json()
        self.assertEqual((d["trace_id"], d["util"], d["comentario"]), (trace, True, "Me ha servido"))
        self.assertTrue(d["actualizado_en"].endswith("Z"))

        r = self.valorar(h, trace_id=trace, util=False)  # cambia de opinión: se sobrescribe
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["util"], r.json()["comentario"]), (False, None))
        with connect() as conn:
            filas = conn.execute("SELECT util FROM aplicacion.valoracion").fetchall()
        self.assertEqual(filas, [{"util": False}])

    def test_comentario_vacio_se_guarda_como_nulo(self):
        h = self.login()
        r = self.valorar(h, trace_id=self.preguntar(h), util=True, comentario="   ")
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(r.json()["comentario"])

    def test_no_se_puede_valorar_un_turno_ajeno_ni_inexistente(self):
        h1, h2 = self.login(), self.login("usuario2")
        trace = self.preguntar(h1)
        for h, t in ((h2, trace), (h1, "t-no-existe")):
            r = self.valorar(h, trace_id=t, util=True)
            self.assertEqual(r.status_code, 404, t)
            self.assertEqual(r.json(), {"codigo_error": "consulta_no_encontrada",
                                        "mensaje": "La consulta no existe."})
        with connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM aplicacion.valoracion").fetchone()["n"], 0)

    def test_entrada_invalida_da_422(self):
        h = self.login()
        trace = self.preguntar(h)
        for cuerpo in ({"util": True}, {"trace_id": trace}, {"trace_id": "", "util": True},
                       {"trace_id": "   ", "util": True}, {"trace_id": trace, "util": "si"},
                       {"trace_id": trace, "util": 1}, {"trace_id": "x" * 129, "util": True},
                       {"trace_id": trace, "util": True, "comentario": "x" * 1001}):
            r = self.valorar(h, **cuerpo)
            self.assertEqual(r.status_code, 422, cuerpo)
            self.assertEqual(r.json()["codigo_error"], "entrada_invalida")

    def test_el_registro_muestra_la_valoracion_del_turno(self):
        h = self.login()
        valorado, sin_valorar = self.preguntar(h), self.preguntar(h, "¿Y la bomba auxiliar?")
        self.valorar(h, trace_id=valorado, util=False, comentario="No era mi versión")

        mias = {c["trace_id"]: c for c in self.client.get("/consultas/mias", headers=h).json()["consultas"]}
        self.assertEqual((mias[valorado]["util"], mias[valorado]["comentario_valoracion"]),
                         (False, "No era mi versión"))
        self.assertIsNone(mias[sin_valorar]["util"])

        todas = self.client.get("/consultas", headers=self.login("admin", "admin123")).json()["consultas"]
        self.assertEqual({c["trace_id"]: c["util"] for c in todas}, {valorado: False, sin_valorar: None})

    def test_usuario_desactivado_recibe_403(self):
        h = self.login()
        trace = self.preguntar(h)
        with connect() as conn:
            conn.execute("UPDATE aplicacion.usuario SET activo=false WHERE nombre_usuario='usuario1'")
        r = self.valorar(h, trace_id=trace, util=True)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["codigo_error"], "acceso_denegado")


if __name__ == "__main__":
    unittest.main()
