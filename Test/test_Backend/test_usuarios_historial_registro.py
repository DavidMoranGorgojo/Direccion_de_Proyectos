"""Login (CTR-005), historial (CTR-006) y registro de consultas (CTR-003).

Las pruebas con base de datos necesitan un PostgreSQL de pruebas vacío en ARSOFT_TEST_DATABASE_URL
(cada prueba recrea el esquema «aplicacion» con Backend/db/init/02_usuarios.sql). Sin él se omiten.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
from fastapi.testclient import TestClient

from Backend.api.app import sesiones
from Backend.api.app.links import connect
from Backend.api.app.main import app

RAIZ = Path(__file__).resolve().parents[2]
SQL = (RAIZ / "Backend" / "db" / "init" / "02_usuarios.sql").read_text(encoding="utf-8")
TOKEN_SERVICIO = "arsoft-test"
DB = os.getenv("ARSOFT_TEST_DATABASE_URL")


class SinBaseDeDatos(unittest.TestCase):
    def test_consulta_sin_sesion_da_401(self):
        with TestClient(app) as client:
            r = client.post("/consulta", json={"conversacion_id": "", "pregunta": "Hola"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["codigo_error"], "sesion_caducada")

    def test_token_falso_da_401(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO}), TestClient(app) as client:
            for token in ("dummy", jwt.encode({"sub": "1"}, "otra-clave-que-no-es-la-de-backend-0000000", algorithm="HS256")):
                r = client.post("/consulta", json={"conversacion_id": "", "pregunta": "Hola"},
                                headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(r.status_code, 401, token)
                self.assertEqual(r.json()["codigo_error"], "sesion_caducada")
            self.assertEqual(client.get("/chats", headers={"Authorization": "Bearer dummy"}).status_code, 401)

    def test_sin_secreto_el_login_no_se_habilita(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ARSOFT_SERVICE_TOKEN", "ARSOFT_JWT_SECRET")}
        with patch.dict(os.environ, env, clear=True), TestClient(app) as client:
            r = client.post("/auth/login", json={"usuario": "admin", "contrasena": "admin123"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["codigo_error"], "servicio_no_disponible")

    def test_login_incompleto_da_422_con_formato_ctr005(self):
        with TestClient(app) as client:
            r = client.post("/auth/login", json={"usuario": "admin"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json(), {"estado": "no_autenticado", "codigo_error": "datos_incompletos",
                                    "mensaje": "Faltan datos o el formato es incorrecto."})

    def test_el_secreto_se_deriva_del_token_de_servicio(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO, "ARSOFT_JWT_SECRET": ""}):
            derivado = sesiones._secreto()
        self.assertTrue(derivado)
        self.assertNotEqual(derivado, TOKEN_SERVICIO)  # el token de servicio no firma sesiones tal cual


def respuesta_agentes(pregunta: str, cid: str) -> dict:
    if "refrigerante" in pregunta:
        return {"trace_id": "t-ok", "estado": "respuesta", "texto": "Cada 60.000 km o 48 meses.",
                "codigo_error": "",
                "fuentes": [{"chunk_id": "c45", "documento": "HTM240-MNT-001", "seccion": "2.1", "pagina": 2,
                             "versiones": ["V1.0", "V1.1", "V2.0"], "obsoleto": False}]}
    return {"trace_id": "t-acl", "estado": "aclaracion", "texto": "¿V1.0, V1.1 o V2.0?", "fuentes": [],
            "codigo_error": ""}


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
        self.recibidas = []
        self.agentes_caido = False
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.agents_client = httpx.AsyncClient(transport=httpx.MockTransport(self._agentes))

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()

    def _agentes(self, request: httpx.Request) -> httpx.Response:
        if self.agentes_caido:
            raise httpx.ConnectError("caído")
        if request.method == "DELETE":
            return httpx.Response(204)
        cuerpo = __import__("json").loads(request.content)
        self.recibidas.append(cuerpo)
        return httpx.Response(200, json=respuesta_agentes(cuerpo["pregunta"], cuerpo["conversacion_id"]))

    def login(self, usuario="usuario1", contrasena="usuario123"):
        r = self.client.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def preguntar(self, h, pregunta, cid=""):
        r = self.client.post("/consulta", json={"conversacion_id": cid, "pregunta": pregunta}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ------------------------------------------------------------- CTR-005
    def test_login_correcto_con_formato_de_frontend(self):
        r = self.client.post("/auth/login", json={"usuario": " Usuario1 ", "contrasena": "usuario123"})
        d = r.json()
        self.assertEqual(d["estado"], "autenticado")
        self.assertEqual(d["usuario"]["nombre_usuario"], "usuario1")
        self.assertIsInstance(d["usuario"]["id"], str)
        self.assertTrue(d["token"])
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {d['token']}"}).json()
        self.assertEqual(me["nombre_usuario"], "usuario1")

    def test_credenciales_invalidas_y_usuario_inactivo(self):
        for usuario, clave in (("usuario1", "mal"), ("noexiste", "x"), ("inactivo", "usuario123")):
            r = self.client.post("/auth/login", json={"usuario": usuario, "contrasena": clave})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json(), {"estado": "no_autenticado", "mensaje": "Usuario o contraseña incorrectos.",
                                        "codigo_error": "credenciales_invalidas"})

    def test_demasiados_intentos(self):
        for _ in range(sesiones.MAX_FALLOS):
            self.client.post("/auth/login", json={"usuario": "usuario1", "contrasena": "mal"})
        r = self.client.post("/auth/login", json={"usuario": "usuario1", "contrasena": "usuario123"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["codigo_error"], "demasiados_intentos")

    def test_usuario_desactivado_pierde_la_sesion(self):
        h = self.login()
        with connect() as conn:
            conn.execute("UPDATE aplicacion.usuario SET activo=false WHERE nombre_usuario='usuario1'")
        self.assertEqual(self.client.get("/chats", headers=h).status_code, 401)

    # ------------------------------------------------------------- CTR-001 + CTR-006
    def test_consulta_crea_el_chat_y_guarda_el_turno(self):
        h = self.login()
        d = self.preguntar(h, "¿Cada cuántos km se cambia el refrigerante?")
        cid = d["conversacion_id"]
        self.assertEqual(self.recibidas[-1], {"conversacion_id": cid,
                                              "pregunta": "¿Cada cuántos km se cambia el refrigerante?"})
        self.preguntar(h, "¿Y la bomba auxiliar?", cid)

        hist = self.client.get("/chats", headers=h).json()
        self.assertEqual(hist["total"], 1)
        chat = hist["chats"][0]
        self.assertEqual(chat["conversacion_id"], cid)
        self.assertEqual(chat["titulo"], "¿Cada cuántos km se cambia el refrigerante?")
        roles = [m["role"] for m in chat["mensajes"]]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])
        primero, respuesta = chat["mensajes"][0], chat["mensajes"][1]
        self.assertEqual(primero["trace_id"], respuesta["trace_id"])
        self.assertEqual(respuesta["estado"], "respuesta")
        self.assertEqual(respuesta["fuentes"][0]["chunk_id"], "c45")
        self.assertEqual(chat["mensajes"][3]["estado"], "aclaracion")
        self.assertTrue(chat["created_at"].endswith("Z"))

    def test_cada_usuario_ve_y_usa_solo_sus_chats(self):
        h1, h2 = self.login(), self.login("usuario2")
        cid = self.preguntar(h1, "refrigerante")["conversacion_id"]
        self.assertEqual(self.client.get("/chats", headers=h2).json(), {"chats": [], "total": 0})
        self.assertEqual(self.client.get(f"/chats/{cid}", headers=h2).status_code, 404)
        r = self.client.post("/consulta", json={"conversacion_id": cid, "pregunta": "hola"}, headers=h2)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["codigo_error"], "conversacion_no_encontrada")
        self.assertEqual(len(self.recibidas), 1)  # la pregunta ajena no llega a Agentes

    def test_renombrar_y_borrar_chat(self):
        h = self.login()
        cid = self.preguntar(h, "refrigerante")["conversacion_id"]
        r = self.client.patch(f"/chats/{cid}", json={"titulo": "Mantenimiento"}, headers=h)
        self.assertEqual(r.json()["titulo"], "Mantenimiento")
        self.assertEqual(self.client.delete(f"/chats/{cid}", headers=h).status_code, 204)
        self.assertEqual(self.client.get(f"/chats/{cid}", headers=h).status_code, 404)
        self.assertEqual(self.client.get("/chats", headers=h).json()["total"], 0)

    def test_paginacion_del_historial(self):
        h = self.login()
        for i in range(3):
            self.preguntar(h, f"refrigerante {i}")
        d = self.client.get("/chats", params={"limit": 2}, headers=h).json()
        self.assertEqual((d["total"], len(d["chats"])), (3, 2))
        self.assertEqual(d["chats"][0]["titulo"], "refrigerante 2")  # el más reciente primero

    # ------------------------------------------------------------- CTR-003
    def test_registro_de_consultas(self):
        h1, h2, ha = self.login(), self.login("usuario2"), self.login("admin", "admin123")
        cid = self.preguntar(h1, "refrigerante")["conversacion_id"]
        self.agentes_caido = True
        error = self.preguntar(h2, "otra pregunta")
        self.assertEqual(error["codigo_error"], "servicio_no_disponible")

        mias = self.client.get("/consultas/mias", headers=h1).json()["consultas"]
        self.assertEqual(len(mias), 1)
        self.assertEqual(mias[0]["conversacion_id"], cid)
        self.assertEqual((mias[0]["estado"], mias[0]["num_fuentes"], mias[0]["chunk_ids"]), ("respuesta", 1, ["c45"]))
        self.assertIsNotNone(mias[0]["latencia_ms"])

        self.assertEqual(self.client.get("/consultas", headers=h1).status_code, 403)
        todas = self.client.get("/consultas", headers=ha).json()["consultas"]
        self.assertEqual(len(todas), 2)
        errores = self.client.get("/consultas", params={"estado": "error"}, headers=ha).json()["consultas"]
        self.assertEqual([c["codigo_error"] for c in errores], ["servicio_no_disponible"])

    def test_si_falla_la_base_la_respuesta_llega_igual(self):
        h = self.login()
        with patch("Backend.api.app.main.guardar_turno", side_effect=__import__("psycopg").OperationalError("caída")):
            d = self.preguntar(h, "refrigerante")
        self.assertEqual(d["estado"], "respuesta")


if __name__ == "__main__":
    unittest.main()
