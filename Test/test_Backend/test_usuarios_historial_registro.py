"""Login (CTR-005), historial (CTR-006) y registro de consultas (CTR-003).

Las pruebas con base de datos necesitan un PostgreSQL de pruebas vacío en ARSOFT_TEST_DATABASE_URL
(cada prueba recrea el esquema «aplicacion» con Backend/db/init/02_usuarios.sql). Sin él se omiten.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import jwt
import uvicorn
from fastapi.testclient import TestClient

from Backend.api.app import limite_consultas, sesiones
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

    def test_token_sin_exp_o_sin_sub_da_401(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO, "ARSOFT_JWT_SECRET": ""}):
            clave = sesiones._secreto()
            futuro = datetime.now(timezone.utc) + timedelta(hours=1)
            tokens = {"sin exp": jwt.encode({"sub": "1"}, clave, algorithm="HS256"),
                      "sin sub": jwt.encode({"exp": futuro}, clave, algorithm="HS256"),
                      "caducado": jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                                             clave, algorithm="HS256")}
            with TestClient(app) as client:
                for caso, token in tokens.items():
                    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
                    self.assertEqual(r.status_code, 401, caso)

    def test_minutos_de_sesion_no_validos_usan_el_valor_por_defecto(self):
        for valor, esperado in (("abc", 480), ("", 480), ("0", 480), ("-5", 480), ("60", 60)):
            with patch.dict(os.environ, {"ARSOFT_SESSION_MINUTES": valor}):
                self.assertEqual(sesiones._minutos_sesion(), esperado, valor)

    def test_limite_de_intentos_purga_y_tiene_tope(self):
        sesiones._fallos.clear()
        with patch.object(sesiones, "VENTANA_S", 0.05):
            sesiones._anotar_fallo("a", "1.1.1.1")
            time.sleep(0.1)
            self.assertFalse(sesiones._bloqueado("a", "1.1.1.1"))
            self.assertEqual(len(sesiones._fallos), 0)  # las claves caducadas se borran
        with patch.object(sesiones, "MAX_CLAVES", 50):
            for i in range(500):  # nombres de usuario inventados por el cliente
                sesiones._anotar_fallo(f"u{i}", f"10.0.0.{i % 7}")
            self.assertLessEqual(len(sesiones._fallos), 50)
        sesiones._fallos.clear()

    def test_router_vectorial_montado_y_protegido(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO}), TestClient(app) as client:
            r = client.post("/conocimiento/vectorial", json={"vector": [0.1] * 1024, "k": 1})
        self.assertEqual(r.status_code, 401)  # existe (no 404) y exige el token de servicio

    def test_usuarios_prueba_exige_desarrollo(self):
        r = subprocess.run([sys.executable, "-m", "Backend.api.app.usuarios_prueba"], cwd=RAIZ,
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": f"{RAIZ}{os.pathsep}{RAIZ / 'shared'}",
                                "DATABASE_URL": "postgresql://nadie@127.0.0.1:1/nada"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--desarrollo", r.stderr)

    def test_el_secreto_se_deriva_del_token_de_servicio(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO, "ARSOFT_JWT_SECRET": ""}):
            derivado = sesiones._secreto()
        self.assertTrue(derivado)
        self.assertNotEqual(derivado, TOKEN_SERVICIO)  # el token de servicio no firma sesiones tal cual


@contextmanager
def serve(asgi):
    """Levanta la app en un uvicorn real (hilo aparte) y devuelve su URL."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(asgi, log_level="error", access_log=False))
        hilo = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        hilo.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.02)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            hilo.join(5)


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
        limite_consultas.reiniciar()
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

    def test_limite_por_ip_aunque_cambie_el_usuario(self):
        for i in range(sesiones.MAX_FALLOS_IP):
            self.client.post("/auth/login", json={"usuario": f"inventado{i}", "contrasena": "x"})
        r = self.client.post("/auth/login", json={"usuario": "usuario1", "contrasena": "usuario123"})
        self.assertEqual(r.status_code, 429)

    def test_demasiados_intentos(self):
        for _ in range(sesiones.MAX_FALLOS):
            self.client.post("/auth/login", json={"usuario": "usuario1", "contrasena": "mal"})
        r = self.client.post("/auth/login", json={"usuario": "usuario1", "contrasena": "usuario123"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["codigo_error"], "demasiados_intentos")

    def test_usuario_desactivado_recibe_403(self):
        h = self.login()
        with connect() as conn:
            conn.execute("UPDATE aplicacion.usuario SET activo=false WHERE nombre_usuario='usuario1'")
        for r in (self.client.get("/chats", headers=h),
                  self.client.post("/consulta", json={"conversacion_id": "", "pregunta": "hola"}, headers=h)):
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["codigo_error"], "acceso_denegado")
        self.assertEqual(self.recibidas, [])

    def test_429_demasiadas_consultas_por_usuario(self):
        h1, h2 = self.login(), self.login("usuario2")
        with patch.dict(os.environ, {"ARSOFT_CONSULTAS_POR_MINUTO": "3"}):
            for i in range(3):
                self.preguntar(h1, f"refrigerante {i}")
            r = self.client.post("/consulta", json={"conversacion_id": "", "pregunta": "otra"}, headers=h1)
            self.assertEqual(r.status_code, 429)
            self.assertEqual(r.json()["codigo_error"], "demasiadas_consultas")
            self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
            self.assertEqual(len(self.recibidas), 3)  # la cuarta no llega a Agentes
            self.preguntar(h2, "refrigerante")  # el límite es por usuario

    def test_500_con_formato_de_error(self):
        h = self.login()
        with patch("Backend.api.app.main.consultar_agentes", side_effect=RuntimeError("fallo inesperado")), \
                TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/consulta", json={"conversacion_id": "", "pregunta": "hola"}, headers=h)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json(), {"codigo_error": "error_interno", "mensaje": "Error interno del servidor."})
        self.assertNotIn("fallo inesperado", r.text)

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

    def test_carrera_por_el_mismo_conversacion_id(self):
        from Backend.api.app.historial import ConversacionAjena, reservar_chat
        with connect() as conn:
            ids = {f["nombre_usuario"]: f["id"] for f in
                   conn.execute("SELECT id, nombre_usuario FROM aplicacion.usuario").fetchall()}
        resultados, barrera = {}, threading.Barrier(2)

        def reservar(nombre):
            barrera.wait()
            try:
                with connect() as conn:
                    reservar_chat(conn, usuario_id=ids[nombre], conversacion_id="cid-compartido", pregunta="hola")
                resultados[nombre] = "ok"
            except ConversacionAjena:
                resultados[nombre] = "ajena"

        hilos = [threading.Thread(target=reservar, args=(n,)) for n in ("usuario1", "usuario2")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(sorted(resultados.values()), ["ajena", "ok"])
        ganador = next(n for n, r in resultados.items() if r == "ok")
        with connect() as conn:
            dueno = conn.execute("SELECT usuario_id FROM aplicacion.chat WHERE conversacion_id='cid-compartido'"
                                 ).fetchone()["usuario_id"]
        self.assertEqual(dueno, ids[ganador])
        # Por la API: el perdedor recibe 404 y su pregunta no llega a Agentes ni se guarda
        perdedor = "usuario2" if ganador == "usuario1" else "usuario1"
        r = self.client.post("/consulta", json={"conversacion_id": "cid-compartido", "pregunta": "intruso"},
                             headers=self.login(perdedor))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.recibidas, [])
        with connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM aplicacion.mensaje").fetchone()["n"], 0)

    def test_la_base_no_bloquea_el_event_loop(self):
        """Con /consulta esperando a una base lenta, /health sigue respondiendo al momento."""
        from Backend.api.app import main as modulo_main
        h = self.login()
        lento = threading.Event()

        def reservar_lento(*args):
            lento.set()
            time.sleep(1.5)

        with patch.object(modulo_main, "reservar", reservar_lento), serve(app) as url:
            hilo = threading.Thread(target=lambda: httpx.post(
                f"{url}/consulta", json={"conversacion_id": "", "pregunta": "refrigerante"}, headers=h, timeout=10))
            hilo.start()
            self.assertTrue(lento.wait(5))
            inicio = time.perf_counter()
            self.assertEqual(httpx.get(f"{url}/health", timeout=5).status_code, 200)
            self.assertLess(time.perf_counter() - inicio, 0.5)
            hilo.join()

    # ------------------------------------------------------------- CTR-007
    def test_agentes_leen_el_historial_con_su_cliente_real(self):
        """CTR-007 con Agents/agente1/cliente_backend.py contra el Backend levantado con uvicorn."""
        from Agents.agente1.cliente_backend import ClienteBackendAgentes
        h = self.login()
        cid = self.preguntar(h, "¿Cada cuántos km se cambia el refrigerante?")["conversacion_id"]
        self.preguntar(h, "¿Y la bomba auxiliar?", cid)
        with serve(app) as url:
            agentes = ClienteBackendAgentes(base_url=url, token_auth=TOKEN_SERVICIO, timeout=5)
            todos = agentes.obtener_historial(cid)
            ultimos = agentes.obtener_historial(cid, limit=2)
            self.assertEqual(agentes.obtener_historial("no-existe"), [])
            sin_token = ClienteBackendAgentes(base_url=url, token_auth="otro-token", timeout=5)
            self.assertEqual(sin_token.obtener_historial(cid), [])
        self.assertEqual([m["role"] for m in todos], ["user", "assistant", "user", "assistant"])
        self.assertEqual(todos[0]["contenido"], "¿Cada cuántos km se cambia el refrigerante?")
        self.assertEqual([m["contenido"] for m in ultimos], [m["contenido"] for m in todos[-2:]])

    def test_token_de_servicio_solo_lee_un_chat(self):
        h = self.login()
        cid = self.preguntar(h, "refrigerante")["conversacion_id"]
        servicio = {"Authorization": f"Bearer {TOKEN_SERVICIO}"}
        self.assertEqual(self.client.get(f"/chats/{cid}", headers=servicio).status_code, 200)
        self.assertEqual(self.client.get("/chats", headers=servicio).status_code, 401)  # no lista chats
        self.assertEqual(self.client.delete(f"/chats/{cid}", headers=servicio).status_code, 401)
        self.assertEqual(self.client.patch(f"/chats/{cid}", json={"titulo": "x"}, headers=servicio).status_code, 401)
        r = self.client.post("/consulta", json={"conversacion_id": "", "pregunta": "hola"}, headers=servicio)
        self.assertEqual(r.status_code, 401)  # el token de servicio no es una sesión de usuario

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
