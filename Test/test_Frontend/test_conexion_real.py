"""Frontend contra el Backend REAL (uvicorn + PostgreSQL) en modo real, sin simulador del Frontend.

Cubre lo que pide la integración: ruta POST /consulta, conversacion_id vacío en el primer mensaje, sesión
(token Bearer, caducada, manipulada), historial real, continuación de un chat antiguo y errores
(401, 429, Agentes caído, tiempo agotado, conversación ajena).

Necesita un PostgreSQL de pruebas vacío con pgvector en ARSOFT_TEST_DATABASE_URL (se recrean «aplicacion» y los datos de
«conocimiento»); sin él se omite. Ejecutar desde la raíz con ``PYTHONPATH=shared;.`` (``:`` en Linux/Mac).

Agentes se sustituye por un servicio mínimo con el mismo contrato (CTR-001 interno). Si AGENT2_DIR apunta a
``Agents/Agent_2`` (rama del Agente 2), ese servicio busca con el BackendAPIClient REAL del Agente 2 contra
POST /conocimiento/lexica del Backend; si no, devuelve fuentes fijas.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

DB = os.getenv("ARSOFT_TEST_DATABASE_URL")
RAIZ = Path(__file__).resolve().parents[2]
TOKEN_SERVICIO = "arsoft-e2e-service-token"

if DB:
    for ruta in (RAIZ, RAIZ / "shared", RAIZ / "Frontend"):
        if str(ruta) not in sys.path:
            sys.path.insert(0, str(ruta))
    if os.getenv("AGENT2_DIR"):
        sys.path.insert(0, os.environ["AGENT2_DIR"])

SQL_ESQUEMA = (RAIZ / "Backend" / "db" / "init" / "01_conocimiento.sql").read_text(encoding="utf-8")


@contextmanager
def serve(asgi):
    import uvicorn
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(asgi, log_level="error", access_log=False))
        hilo = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        hilo.start()
        try:
            for _ in range(300):
                if server.started:
                    break
                time.sleep(.02)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            hilo.join(5)


def crear_agentes(backend_url: str):
    """Servicio de Agentes mínimo con el contrato interno CTR-001 (POST /agentes/consulta)."""
    from fastapi import FastAPI, Header, HTTPException

    recibidas: list[dict] = []
    agente2 = None
    if os.getenv("AGENT2_DIR"):
        from src.clients.backend import BackendAPIClient
        agente2 = BackendAPIClient(backend_url, "BAAI/bge-m3", token=TOKEN_SERVICIO, timeout=10)

    app = FastAPI()

    @app.post("/agentes/consulta")
    def consulta(datos: dict, authorization: str = Header(default="")):
        if authorization != f"Bearer {TOKEN_SERVICIO}":
            raise HTTPException(401)
        recibidas.append(datos)
        p = datos["pregunta"]
        if "lent" in p:
            time.sleep(3)
        if "ambigua" in p:
            return {"trace_id": "t-acl", "estado": "aclaracion", "texto": "¿V1.0, V1.1 o V2.0?",
                    "fuentes": [], "codigo_error": ""}
        if "tiempo" in p and "motor" not in p:
            return {"trace_id": "t-fa", "estado": "fuera_de_ambito", "texto": "Solo documentación técnica.",
                    "fuentes": [], "codigo_error": ""}
        if agente2 is not None:
            candidatos = agente2.search_lexical_candidates(p, k=3).resultados
            if not candidatos:
                return {"trace_id": "t-se", "estado": "sin_evidencia", "texto": "Sin evidencia.",
                        "fuentes": [], "codigo_error": ""}
            fuentes = [{"chunk_id": c.chunk_id, "documento": c.metadatos.documento,
                        "seccion": c.metadatos.seccion, "pagina": c.metadatos.pagina,
                        "versiones": c.metadatos.versiones, "obsoleto": c.metadatos.obsoleto}
                       for c in candidatos]
            return {"trace_id": "t-ok", "estado": "respuesta", "texto": candidatos[0].texto,
                    "fuentes": fuentes, "codigo_error": ""}
        if "nada" in p:
            return {"trace_id": "t-se", "estado": "sin_evidencia", "texto": "Sin evidencia.",
                    "fuentes": [], "codigo_error": ""}
        return {"trace_id": "t-ok", "estado": "respuesta", "texto": "Cada 60.000 km.",
                "fuentes": [{"chunk_id": "c1", "documento": "HTM240-DTC-001", "seccion": "2.1", "pagina": 3,
                             "versiones": ["V1.1", "V2.0"], "obsoleto": False}], "codigo_error": ""}

    @app.delete("/agentes/conversaciones/{cid}", status_code=204)
    def cerrar(cid: str):
        return None

    app.recibidas = recibidas
    return app


def sembrar_conocimiento(conn) -> None:
    conn.execute("DELETE FROM conocimiento.indice_version")      # arrastra los chunks (ON DELETE CASCADE)
    conn.execute("DELETE FROM conocimiento.documento")
    conn.execute("INSERT INTO conocimiento.indice_version (version, modelo_embeddings, dimensiones, tokenizador,"
                 " n_chunks, activo) VALUES ('v1.0-e2e', 'BAAI/bge-m3', 1024, 'bm25', 3, true)")
    conn.execute("INSERT INTO conocimiento.documento (doc_id, codigo, tipo_documento, titulo, version_documento,"
                 " fecha_revision, obsoleto, versiones_vehiculo) VALUES ('HTM240-DTC-001@1.0', 'HTM240-DTC-001',"
                 " 'codigo_averia', 'Códigos', '1.0', '2026-09-01', false, ARRAY['V1.1','V2.0'])")
    filas = [("c1", "El testigo de temperatura HTM-0142 indica sobrecalentamiento del circuito de refrigeración.", 1),
             ("c2", "Procedimiento de purga del circuito de refrigeración tras sustituir el radiador.", 2),
             ("c3", "Par de apriete de la culata, edición vigente. Consulte CMP-18.", 3)]
    for chunk_id, texto, orden in filas:
        conn.execute("""INSERT INTO conocimiento.chunk (indice_version, chunk_id, doc_id, documento, texto, seccion,
            pagina, orden_en_seccion, versiones, componente, tipo_documento, obsoleto, vigente_para, fecha_revision,
            version_documento, embedding) VALUES ('v1.0-e2e', %s, 'HTM240-DTC-001@1.0', 'HTM240-DTC-001', %s, '2.1',
            3, %s, ARRAY['V1.1','V2.0'], 'refrigeracion', 'codigo_averia', false, '{}', '2026-09-01', '1.0',
            array_fill(0.0::real, ARRAY[1024])::vector)""", (chunk_id, texto, orden))


@unittest.skipUnless(DB, "Requiere un PostgreSQL de pruebas (ARSOFT_TEST_DATABASE_URL)")
class FrontendContraBackendReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, {"DATABASE_URL": DB, "ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO,
                                          "ARSOFT_JWT_SECRET": "", "ARSOFT_ALLOW_HTTP": "1"})
        cls.env.start()
        from Backend.api.app import busqueda_lexica, main, sesiones
        from Backend.api.app.links import connect
        from Backend.api.app.usuarios_prueba import crear_usuarios_prueba
        with connect() as conn:
            conn.execute("DROP SCHEMA IF EXISTS aplicacion CASCADE")
            conn.execute(SQL_ESQUEMA)
            crear_usuarios_prueba(conn)
            sembrar_conocimiento(conn)
        busqueda_lexica._cache.update(clave=None, indice=None)
        sesiones._fallos.clear()
        cls.ctx = []
        main.AGENT_TIMEOUT_SECONDS = 1.5          # para provocar tiempo_agotado sin esperar 25 s
        cls.backend_cm = serve(main.app)
        cls.backend_url = cls.backend_cm.__enter__()
        cls.agentes_app = crear_agentes(cls.backend_url)
        cls.agentes_cm = serve(cls.agentes_app)
        os.environ["AGENTES_URL"] = cls.agentes_cm.__enter__()
        # api.API_URL se lee en cada llamada: basta con apuntarlo al Backend de prueba (sin recargar módulos)
        from models.conversation import Conversation
        from services import api, auth, session
        cls.api_url = patch.object(api, "API_URL", cls.backend_url)
        cls.api_url.start()
        cls.api, cls.auth, cls.session, cls.Conversation = api, auth, session, Conversation

    @classmethod
    def tearDownClass(cls):
        cls.api_url.stop()
        cls.agentes_cm.__exit__(None, None, None)
        cls.backend_cm.__exit__(None, None, None)
        cls.env.stop()

    def setUp(self):
        from Backend.api.app import sesiones
        sesiones._fallos.clear()
        from Backend.api.app.links import connect
        with connect() as conn:                      # cada prueba parte sin chats
            conn.execute("DELETE FROM aplicacion.chat")
        self.session.clear()
        self.agentes_app.recibidas.clear()

    def entrar(self, usuario="usuario1", clave="usuario123"):
        res = self.auth.login(usuario, clave)
        self.assertTrue(res.ok, res.error)
        self.session.start(res.user, res.token, res.user_id)
        return res

    # ------------------------------------------------------------------ CTR-005
    def test_login_correcto_devuelve_token_y_usuario(self):
        res = self.entrar()
        self.assertEqual(res.user, "usuario1")
        self.assertTrue(res.token)
        self.assertTrue(res.user_id)

    def test_login_credenciales_incorrectas(self):
        res = self.auth.login("usuario1", "mal")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "Usuario o contraseña incorrectos.")
        self.assertIsNone(res.token)

    def test_login_429_tras_demasiados_intentos(self):
        for _ in range(5):
            self.auth.login("usuario1", "mal")
        res = self.auth.login("usuario1", "usuario123")
        self.assertFalse(res.ok)
        self.assertIn("Demasiados intentos", res.error)

    # ------------------------------------------------------------------ CTR-001 + CTR-006
    def test_primer_mensaje_con_id_vacio_historial_y_continuacion(self):
        api = self.api
        self.entrar()
        self.assertEqual(api.fetch_history().conversations, [])      # historial vacío al empezar

        nuevo = self.Conversation()
        self.assertEqual(nuevo.server_id, "")                         # chat nuevo: ID vacío
        r1 = api.send_message(nuevo.server_id, "¿Qué significa el testigo HTM-0142?")
        self.assertEqual(r1.estado, "respuesta", r1.texto)
        self.assertTrue(r1.conversacion_id)                           # el Backend genera el ID
        self.assertEqual(self.agentes_app.recibidas[-1]["conversacion_id"], r1.conversacion_id)
        self.assertEqual(self.agentes_app.recibidas[-1]["pregunta"], "¿Qué significa el testigo HTM-0142?")
        self.assertTrue(r1.fuentes)

        h = api.fetch_history()
        self.assertTrue(h.ok)
        self.assertEqual([c.id for c in h.conversations], [r1.conversacion_id])
        self.assertEqual(len(h.conversations[0].messages), 2)

        # Chat cargado del historial: se continúa con su ID, no se crea otro
        cargado = h.conversations[0]
        self.assertEqual(cargado.server_id, r1.conversacion_id)
        r2 = api.send_message(cargado.server_id, "otra pregunta de culata CMP-18")
        self.assertEqual(r2.conversacion_id, r1.conversacion_id)
        h2 = api.fetch_history()
        self.assertEqual(len(h2.conversations), 1)
        self.assertEqual(len(h2.conversations[0].messages), 4)

    def test_todos_los_estados_de_respuesta(self):
        self.entrar()
        self.assertEqual(self.api.send_message("", "pregunta ambigua").estado, "aclaracion")
        self.assertEqual(self.api.send_message("", "qué tiempo hace").estado, "fuera_de_ambito")
        self.assertEqual(self.api.send_message("", "quark zzyzx nada").estado, "sin_evidencia")

    def test_pregunta_se_conserva_exacta(self):
        self.entrar()
        exacta = "  espacios y Mayúsculas  HTM-0142 "
        self.api.send_message("", exacta)
        self.assertEqual(self.agentes_app.recibidas[-1]["pregunta"], exacta)

    # ------------------------------------------------------------------ sesión
    def test_sin_sesion_consulta_e_historial_dan_sesion_caducada(self):
        r = self.api.send_message("", "hola técnico")
        self.assertEqual((r.estado, r.codigo_error), ("error", "sesion_caducada"))
        h = self.api.fetch_history()
        self.assertFalse(h.ok)
        self.assertTrue(h.session_expired)

    def test_token_manipulado_da_sesion_caducada(self):
        self.entrar()
        self.session.token = self.session.token[:-3] + "abc"
        self.assertEqual(self.api.send_message("", "hola técnico").codigo_error, "sesion_caducada")
        self.assertTrue(self.api.fetch_history().session_expired)

    def test_chat_de_otro_usuario_no_se_puede_usar(self):
        self.entrar("usuario1")
        cid = self.api.send_message("", "pregunta de culata CMP-18").conversacion_id
        self.session.clear()
        self.entrar("usuario2")
        r = self.api.send_message(cid, "intento ajeno")
        self.assertEqual(r.estado, "error")                           # 404 → error genérico
        self.assertEqual(self.api.fetch_history().conversations, [])

    # ------------------------------------------------------------------ errores de Agentes
    def test_tiempo_agotado_llega_como_error_estructurado(self):
        self.entrar()
        r = self.api.send_message("", "pregunta lenta")
        self.assertEqual((r.estado, r.codigo_error), ("error", "tiempo_agotado"))
        self.assertTrue(r.conversacion_id)

    def test_agentes_caido(self):
        self.entrar()
        with patch.dict(os.environ, {"AGENTES_URL": "http://127.0.0.1:1"}):
            r = self.api.send_message("", "hola técnico")
        # En Windows un puerto cerrado tarda ~2 s en rechazar la conexión, más que el timeout de prueba
        self.assertEqual(r.estado, "error")
        self.assertIn(r.codigo_error, ("servicio_no_disponible", "tiempo_agotado"))

    def test_backend_caido_da_error_de_conexion(self):
        self.entrar()
        with patch.object(self.api, "API_URL", "http://127.0.0.1:1"):
            self.assertEqual(self.api.send_message("", "hola técnico").estado, "error")
            self.assertFalse(self.api.fetch_history().ok)


if __name__ == "__main__":
    unittest.main()
