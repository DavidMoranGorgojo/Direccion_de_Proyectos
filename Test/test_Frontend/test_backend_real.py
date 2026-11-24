"""
Pruebas del Frontend contra el Backend REAL (login, historial, consulta y errores 401/403/429/500)
==================================================================================================
Complementan a test_conexion_simulada.py (que usa el modo simulado del Frontend). Aquí el cliente
del Frontend (services/api.py y services/auth.py) habla por HTTP con el Backend de verdad.

Dos niveles:

1. TestFrontendContraBackendReal (se ejecuta siempre)
   - Levanta la aplicación FastAPI del Backend (Backend/api/app/main.py) en un uvicorn real en
     127.0.0.1 y apunta el Frontend a esa URL (ARSOFT_API_URL).
   - Es el código real del Backend: rutas, JWT, límite de intentos, validación, manejadores de error
     y validación de la respuesta de Agentes.
   - Solo se sustituyen las dos dependencias externas: PostgreSQL (por una base en memoria que
     responde a las consultas SQL que usa el Backend) y el servicio de Agentes (por un transporte
     httpx simulado, como hacen las pruebas del propio Backend).

2. TestDespliegueReal (de principio a fin, solo si se define ARSOFT_E2E_URL)
   - Contra un despliegue completo ya levantado (Backend + PostgreSQL + Agentes + LLM).
   - Variables: ARSOFT_E2E_URL (obligatoria), ARSOFT_E2E_USUARIO / ARSOFT_E2E_CONTRASENA
     (por defecto usuario1 / usuario123, los usuarios de prueba de Backend/readme.md) y
     ARSOFT_E2E_PROBAR_429=1 para provocar el bloqueo por intentos (cuenta para la IP 5 minutos).

Ejecución:
    pytest Test/test_Frontend/test_backend_real.py
    ARSOFT_E2E_URL=http://127.0.0.1:8000 pytest Test/test_Frontend/test_backend_real.py -k Despliegue
"""

from __future__ import annotations
import json
import os
import socket
import sys
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "Frontend"
SHARED_DIR = ROOT_DIR / "shared"  # arsoft_http, que el Backend importa como módulo de primer nivel
for path_dir in (str(SHARED_DIR), str(ROOT_DIR), str(FRONTEND_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from Test.test_Frontend import qt_test_harness

qt_test_harness.setup_qt_harness()

from models.conversation import Conversation  # noqa: E402
from models.message import ROLE_BOT, ROLE_USER  # noqa: E402
from models.response import (  # noqa: E402
    GENERIC_ERROR,
    STATUS_CLARIFY,
    STATUS_ERROR,
    STATUS_NO_EVIDENCE,
    STATUS_OK,
    STATUS_OUT_OF_SCOPE,
    STATUSES,
)
from services import api, auth, session  # noqa: E402

try:
    import httpx
    import psycopg
    import uvicorn
    from Backend.api.app import historial, registro, sesiones
    from Backend.api.app import main as backend
    FALTA_BACKEND = ""
except ImportError as error:  # dependencias de Backend/api/requirements.txt no instaladas
    FALTA_BACKEND = f"Faltan dependencias del Backend ({error}): pip install -r Backend/api/requirements.txt"

TOKEN_SERVICIO = "arsoft-test-frontend"
PREGUNTA_OK = "¿Cada cuánto se cambia el refrigerante?"


# ----------------------------------------------------------------------------- PostgreSQL en memoria
class _Cursor:
    def __init__(self, filas: list[dict]):
        self._filas = filas

    def fetchone(self):
        return self._filas[0] if self._filas else None

    def fetchall(self):
        return list(self._filas)


class BaseDatosEnMemoria:
    """Sustituye a PostgreSQL. Responde SOLO a las sentencias que ejecuta el Backend en login,
    sesión, /chats, /consulta y el registro; cualquier otra hace fallar la prueba."""

    def __init__(self, usuarios: list[dict]):
        self.usuarios = {u["id"]: dict(u) for u in usuarios}
        self.chats: dict[str, dict] = {}
        self.mensajes: list[dict] = []
        self.registro: list[tuple] = []
        self.fallo: Exception | None = None  # si se fija, connect() lo lanza

    def connect(self):
        if self.fallo is not None:
            raise self.fallo
        return _ConexionEnMemoria(self)


class _ConexionEnMemoria:
    def __init__(self, db: BaseDatosEnMemoria):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple = ()):  # noqa: C901 - tabla de sentencias conocidas
        q = " ".join(sql.split())
        db = self.db
        ahora = datetime.now(timezone.utc)
        if q.startswith("SELECT") and "FROM aplicacion.usuario WHERE nombre_usuario=%s" in q:
            filas = [u for u in db.usuarios.values() if u["nombre_usuario"] == params[0]]
        elif q.startswith("SELECT") and "FROM aplicacion.usuario WHERE id=%s" in q:
            filas = [u for u in db.usuarios.values() if u["id"] == params[0]]
        elif q.startswith("UPDATE aplicacion.usuario SET ultimo_login"):
            filas = []
        elif q.startswith("SELECT count(*) AS n FROM aplicacion.chat WHERE usuario_id=%s"):
            filas = [{"n": sum(c["usuario_id"] == params[0] for c in db.chats.values())}]
        elif q.startswith("SELECT * FROM aplicacion.chat WHERE usuario_id=%s"):
            usuario_id, limit, offset = params
            propios = sorted((c for c in db.chats.values() if c["usuario_id"] == usuario_id),
                             key=lambda c: c["updated_at"], reverse=True)
            filas = propios[offset:offset + limit]
        elif q.startswith("SELECT * FROM aplicacion.chat WHERE conversacion_id=%s AND usuario_id=%s"):
            chat = db.chats.get(params[0])
            filas = [chat] if chat and chat["usuario_id"] == params[1] else []
        elif "FROM aplicacion.mensaje WHERE conversacion_id = ANY(%s)" in q:
            filas = [m for m in db.mensajes if m["conversacion_id"] in params[0]]
        elif q.startswith("INSERT INTO aplicacion.chat"):
            cid, usuario_id, titulo = params
            chat = db.chats.get(cid)
            if chat is None:
                db.chats[cid] = {"conversacion_id": cid, "usuario_id": usuario_id, "titulo": titulo,
                                 "created_at": ahora, "updated_at": ahora}
                filas = [{"conversacion_id": cid}]
            elif chat["usuario_id"] == usuario_id:
                chat["updated_at"] = ahora
                filas = [{"conversacion_id": cid}]
            else:  # ON CONFLICT ... WHERE usuario_id: chat de otro usuario, no se toca
                filas = []
        elif q.startswith("INSERT INTO aplicacion.mensaje"):
            if "'user'" in q:
                cid, trace, contenido, estado = params
                rol, codigo, fuentes = "user", "", []
            else:
                cid, trace, contenido, estado, codigo, fuentes = params
                rol, fuentes = "assistant", getattr(fuentes, "obj", fuentes)  # Jsonb(...)
            db.mensajes.append({"conversacion_id": cid, "message_id": f"m-{len(db.mensajes) + 1}",
                                "trace_id": trace, "role": rol, "contenido": contenido, "estado": estado,
                                "codigo_error": codigo, "fuentes": fuentes, "timestamp": ahora})
            filas = []
        elif q.startswith("INSERT INTO aplicacion.registro_consulta"):
            trace_id, usuario_id, conversacion_id, tipo, pregunta, estado, codigo_error, num_fuentes, chunk_ids, latencia_ms = params
            db.registro.append({
                "id": len(db.registro) + 1, "trace_id": trace_id, "usuario_id": usuario_id,
                "conversacion_id": conversacion_id, "tipo": tipo, "pregunta": pregunta,
                "estado": estado, "codigo_error": codigo_error, "num_fuentes": num_fuentes,
                "chunk_ids": chunk_ids, "latencia_ms": latencia_ms, "creado_en": ahora,
            })
            filas = []
        elif q.startswith("SELECT") and "FROM aplicacion.registro_consulta" in q:
            filas = list(db.registro)
        else:
            raise AssertionError(f"Sentencia SQL no prevista en la base en memoria: {q[:90]}")
        return _Cursor(filas)


# ----------------------------------------------------------------------------- Agentes simulado
def respuesta_agentes(pregunta: str) -> dict:
    """Respuestas CTR-001 de Agentes, pequeñas y representativas de cada estado."""
    texto = pregunta.lower()
    base = {"trace_id": f"t-{uuid.uuid4().hex[:8]}", "fuentes": [], "codigo_error": ""}
    if "refrigerante" in texto:
        return {**base, "estado": "respuesta", "texto": "Cada 60.000 km o 48 meses [c45].",
                "fuentes": [{"chunk_id": "c45", "documento": "HTM240-MNT-001", "seccion": "2.1",
                             "pagina": 2, "versiones": ["V1.1", "V2.0"], "obsoleto": False},
                            {"chunk_id": "c12", "documento": "BOL-014", "seccion": "Comprobaciones",
                             "pagina": 3, "versiones": ["V1.0"], "obsoleto": True}]}
    if "receta" in texto:
        return {**base, "estado": "fuera_de_ambito",
                "texto": "Solo respondo sobre la documentación técnica del vehículo."}
    if len(texto.split()) <= 2:
        return {**base, "estado": "aclaracion", "texto": "¿V1.0, V1.1 o V2.0?"}
    return {**base, "estado": "sin_evidencia", "texto": "No hay evidencia suficiente en la documentación."}


@contextmanager
def servidor(asgi):
    """Levanta una app ASGI en un uvicorn real (hilo aparte) y devuelve su URL."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        # log_level critical: los 500 provocados a propósito no ensucian la salida de pytest
        server = uvicorn.Server(uvicorn.Config(asgi, log_level="critical", access_log=False))
        hilo = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        hilo.start()
        try:
            for _ in range(250):
                if server.started:
                    break
                time.sleep(0.02)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            hilo.join(5)


# ============================================================================= 1. Backend real local
@unittest.skipIf(FALTA_BACKEND, FALTA_BACKEND)
class TestFrontendContraBackendReal(unittest.TestCase):
    """Cliente del Frontend ⇄ Backend real por HTTP (PostgreSQL y Agentes sustituidos)."""

    @classmethod
    def setUpClass(cls):
        cls._env = patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN_SERVICIO, "ARSOFT_JWT_SECRET": "",
                                           "AGENTES_URL": "http://agentes.test"})
        cls._env.start()
        # Hash bcrypt una sola vez: es lento a propósito y no aporta nada repetirlo en cada prueba
        clave = sesiones.hash_password("usuario123")
        cls.usuarios = [
            {"id": 1, "nombre_usuario": "admin", "nombre": "Admin", "rol": "admin", "activo": True,
             "password_hash": sesiones.hash_password("admin123")},
            {"id": 2, "nombre_usuario": "usuario1", "nombre": "Usuario 1", "rol": "usuario", "activo": True,
             "password_hash": clave},
            {"id": 3, "nombre_usuario": "usuario2", "nombre": "Usuario 2", "rol": "usuario", "activo": True,
             "password_hash": clave},
            {"id": 4, "nombre_usuario": "inactivo", "nombre": "Inactivo", "rol": "usuario", "activo": False,
             "password_hash": clave},
        ]
        cls.db = BaseDatosEnMemoria(cls.usuarios)
        cls._patches = [patch.object(modulo, "connect", lambda: cls.db.connect())
                        for modulo in (sesiones, historial, registro, backend)]
        for p in cls._patches:
            p.start()
        cls._servidor = servidor(backend.app)
        cls.url = cls._servidor.__enter__()
        # El lifespan del Backend ya creó su cliente hacia Agentes: se cambia por uno simulado
        backend.app.state.agents_client = httpx.AsyncClient(transport=httpx.MockTransport(cls._agentes))

    @classmethod
    def tearDownClass(cls):
        cls._servidor.__exit__(None, None, None)
        for p in cls._patches:
            p.stop()
        cls._env.stop()
        api.API_URL = ""
        session.clear()

    def setUp(self):
        from Backend.api.app import limite_consultas
        type(self).db = BaseDatosEnMemoria(self.usuarios)
        type(self).modo_agentes = "normal"
        type(self).recibidas = []
        sesiones._fallos.clear()
        limite_consultas.reiniciar()
        session.clear()
        api.API_URL = self.url
        self._orig_consulta_path = api.CONSULTA_PATH
        api.CONSULTA_PATH = "/consulta"

    def tearDown(self):
        api.API_URL = ""
        api.CONSULTA_PATH = self._orig_consulta_path
        session.clear()
        sesiones._fallos.clear()

    @classmethod
    def _agentes(cls, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":  # el Backend pide olvidar la conversación tras un timeout
            return httpx.Response(204)
        cuerpo = json.loads(request.content)
        cls.recibidas.append(cuerpo)
        if cls.modo_agentes == "caido":
            raise httpx.ConnectError("Agentes caído", request=request)
        if cls.modo_agentes == "lento":
            raise httpx.ReadTimeout("Agentes no responde", request=request)
        if cls.modo_agentes == "500":
            return httpx.Response(500, text="Internal Server Error")
        if cls.modo_agentes == "json_roto":
            return httpx.Response(200, content=b'{"estado": "respuesta", "texto": ',
                                  headers={"content-type": "application/json"})
        if cls.modo_agentes == "respuesta_sin_fuentes":
            return httpx.Response(200, json={**respuesta_agentes(PREGUNTA_OK), "fuentes": []})
        return httpx.Response(200, json=respuesta_agentes(cuerpo["pregunta"]))

    # ---------------------------------------------------------------- utilidades
    def entrar(self, usuario: str = "usuario1", clave: str | None = None) -> auth.AuthResult:
        """Login como lo hace la App (main.py): auth.login y, si va bien, session.start."""
        if clave is None:
            clave = "admin123" if usuario == "admin" else "usuario123"
        res = auth.login(usuario, clave)
        self.assertTrue(res.ok, res.error)
        session.start(res.user, res.token, res.user_id)
        return res

    # ============================================================ CTR-005 · login
    def test_login_correcto_devuelve_usuario_y_token_jwt(self):
        res = auth.login("usuario1", "usuario123")

        self.assertTrue(res.ok)
        self.assertEqual(res.user, "usuario1")
        self.assertEqual(res.user_id, "2")
        self.assertEqual(res.error, "")
        self.assertEqual(len(res.token.split(".")), 3, "El token de CTR-005 es un JWT")

    def test_login_admite_mayusculas_y_espacios_en_el_usuario(self):
        res = auth.login("  Usuario1 ", "usuario123")
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.user, "usuario1")

    def test_login_401_credenciales_invalidas_o_usuario_inactivo(self):
        for usuario, clave in (("usuario1", "mala"), ("noexiste", "x"), ("inactivo", "usuario123")):
            with self.subTest(usuario=usuario):
                res = auth.login(usuario, clave)
                self.assertFalse(res.ok)
                self.assertIsNone(res.token)
                self.assertEqual(res.error, "Usuario o contraseña incorrectos.")

    def test_login_422_campos_vacios(self):
        res = auth.login("", "")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "Faltan datos o el formato es incorrecto.")

    def test_login_429_tras_cinco_fallos_bloquea_incluso_la_clave_buena(self):
        for _ in range(sesiones.MAX_FALLOS):
            self.assertFalse(auth.login("usuario1", "mala").ok)

        res = auth.login("usuario1", "usuario123")

        self.assertFalse(res.ok)
        self.assertIn("Demasiados intentos", res.error)
        self.assertTrue(auth.login("usuario2", "usuario123").ok, "El bloqueo es por usuario e IP")

    def test_login_con_base_de_datos_caida_informa_servicio_no_disponible(self):
        self.db.fallo = psycopg.OperationalError("PostgreSQL caído")
        res = auth.login("usuario1", "usuario123")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, "El servicio no está disponible. Inténtalo más tarde.")

    # ============================================================ CTR-006 · historial
    def test_historial_vacio_de_un_usuario_sin_chats(self):
        self.entrar()
        hist = api.fetch_history()
        self.assertTrue(hist.ok, hist.error)
        self.assertEqual(hist.conversations, [])

    def test_historial_recupera_la_conversacion_creada_por_una_consulta(self):
        self.entrar()
        resp = api.send_message("", PREGUNTA_OK)

        hist = api.fetch_history()

        self.assertTrue(hist.ok, hist.error)
        self.assertEqual(len(hist.conversations), 1)
        conv = hist.conversations[0]
        self.assertEqual(conv.id, resp.conversacion_id)
        self.assertEqual(conv.title, PREGUNTA_OK)
        self.assertEqual([m.role for m in conv.messages], [ROLE_USER, ROLE_BOT])
        self.assertEqual(conv.messages[0].text, PREGUNTA_OK)
        bot = conv.messages[1]
        self.assertEqual(bot.status, STATUS_OK)
        self.assertEqual(bot.trace_id, resp.trace_id)
        self.assertEqual([(s.documento, s.pagina, s.obsoleto) for s in bot.sources],
                         [("HTM240-MNT-001", 2, False), ("BOL-014", 3, True)])

    def test_continuar_un_chat_del_historial_usa_su_conversacion_id(self):
        """Al continuar un chat del historial enviando su conversacion_id (conv.id), el Backend
        continúa el mismo hilo y no abre uno nuevo."""
        self.entrar()
        primera = api.send_message("", PREGUNTA_OK)
        conv = api.fetch_history().conversations[0]
        self.assertEqual(conv.id, primera.conversacion_id)

        segunda = api.send_message(conv.id, "Gracias, ¿y el líquido de frenos?")

        self.assertEqual(segunda.conversacion_id, primera.conversacion_id)
        hist = api.fetch_history()
        self.assertEqual(len(hist.conversations), 1)
        self.assertEqual(len(hist.conversations[0].messages), 4)

    def test_ruta_interna_de_agentes_no_es_publica(self):
        """La ruta interna de Agentes no sustituye al endpoint público de CTR-001."""
        self.entrar()
        with patch.object(api, "CONSULTA_PATH", "/agentes/consulta"):
            resp = api.send_message("", PREGUNTA_OK)
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, api.CONVERSATION_NOT_FOUND)

    def test_historial_aislado_entre_usuarios(self):
        self.entrar("usuario1")
        resp = api.send_message("", PREGUNTA_OK)
        self.entrar("usuario2")
        self.recibidas.clear()

        self.assertEqual(api.fetch_history().conversations, [])
        ajena = api.send_message(resp.conversacion_id, "Quiero leer ese chat")

        self.assertEqual(ajena.estado, STATUS_ERROR)  # 404 conversacion_no_encontrada
        self.assertEqual(ajena.texto, api.CONVERSATION_NOT_FOUND)
        self.assertEqual(self.recibidas, [], "Un chat ajeno no debe llegar a Agentes")

    def test_historial_401_sin_token_token_falso_o_usuario_desactivado(self):
        self.entrar()
        token_valido = session.token
        casos = {"sin token": None, "token falso": "no-es-un-jwt", "usuario desactivado": token_valido}
        for caso, token in casos.items():
            with self.subTest(caso=caso):
                if caso == "usuario desactivado":
                    self.db.usuarios[2]["activo"] = False
                session.start("usuario1", token, "2")
                hist = api.fetch_history()
                self.assertFalse(hist.ok)
                self.assertTrue(hist.session_expired)
                self.assertEqual(hist.error, api.SESSION_EXPIRED)

    # ============================================================ CTR-001 · consulta
    def test_consulta_envia_el_cuerpo_exacto_y_lee_cada_estado(self):
        self.entrar()
        casos = [(PREGUNTA_OK, STATUS_OK), ("  motor  ", STATUS_CLARIFY),
                 ("Dame una receta de paella", STATUS_OUT_OF_SCOPE),
                 ("¿Cómo se calibra el sensor de lluvia?", STATUS_NO_EVIDENCE)]
        for pregunta, estado in casos:
            with self.subTest(estado=estado):
                self.recibidas.clear()
                resp = api.send_message("", pregunta)
                self.assertEqual(resp.estado, estado)
                self.assertTrue(resp.trace_id)
                self.assertTrue(resp.conversacion_id, "El Backend genera el id si llega vacío")
                self.assertEqual(bool(resp.fuentes), estado == STATUS_OK)
                # A Agentes llega {conversacion_id, pregunta}, con la pregunta tal cual se escribió
                self.assertEqual(self.recibidas, [{"conversacion_id": resp.conversacion_id,
                                                   "pregunta": pregunta}])

    def test_consulta_con_id_del_frontend_lo_conserva(self):
        self.entrar()
        resp = api.send_message("chat-local-123", PREGUNTA_OK)
        self.assertEqual(resp.conversacion_id, "chat-local-123")

    def test_consulta_401_sin_sesion(self):
        resp = api.send_message("", PREGUNTA_OK)
        self.assertEqual(resp.estado, STATUS_ERROR)
        self.assertEqual(resp.codigo_error, "sesion_caducada")
        self.assertEqual(resp.texto, api.SESSION_EXPIRED)
        self.assertEqual(self.recibidas, [])

    def test_consulta_demasiado_larga_muestra_el_aviso_del_backend(self):
        self.entrar()
        resp = api.send_message("", "x" * 2001)
        self.assertEqual(resp.estado, STATUS_ERROR)
        self.assertEqual(resp.codigo_error, "entrada_invalida")
        self.assertIn("2000", resp.texto)
        self.assertEqual(self.recibidas, [])

    def test_consulta_queda_en_el_registro_que_ve_el_admin(self):
        self.entrar()
        api.send_message("", PREGUNTA_OK)
        self.assertEqual(len(self.db.registro), 1)
        item = self.db.registro[0]
        self.assertEqual((item["usuario_id"], item["tipo"], item["pregunta"], item["estado"]),
                         (2, "consulta", PREGUNTA_OK, STATUS_OK))
        self.assertTrue(item["trace_id"])

    # ============================================================ errores de Agentes (vía Backend)
    def test_fallos_de_agentes_llegan_como_error_controlado(self):
        """El Backend responde 200 con estado «error» y el Frontend muestra el texto genérico."""
        self.entrar()
        casos = {"caido": "servicio_no_disponible", "500": "servicio_no_disponible",
                 "json_roto": "servicio_no_disponible", "respuesta_sin_fuentes": "servicio_no_disponible",
                 "lento": "tiempo_agotado"}
        for modo, codigo in casos.items():
            with self.subTest(agentes=modo):
                type(self).modo_agentes = modo
                resp = api.send_message("", PREGUNTA_OK)
                self.assertEqual(resp.estado, STATUS_ERROR)
                self.assertEqual(resp.codigo_error, codigo)
                self.assertEqual(resp.texto, GENERIC_ERROR)
                self.assertEqual(resp.fuentes, [])

    # ============================================================ 403 y 500 del Backend
    def test_403_acceso_denegado_real_del_backend(self):
        """El Backend solo usa 403 en rutas de administración (acceso_denegado). Fallo F-02: el
        Frontend trata cualquier 403 como «sesión caducada»; se deja documentado aquí."""
        self.entrar("usuario1")
        status, cuerpo = api.call("GET", "/consultas")
        self.assertEqual(status, 403)
        self.assertEqual(cuerpo["codigo_error"], "acceso_denegado")

        with patch.object(api, "HISTORIAL_PATH", "/consultas"):
            hist = api.fetch_history()
        self.assertFalse(hist.ok)
        self.assertTrue(hist.session_expired)  # comportamiento actual (F-02)

        self.entrar("admin")
        status, cuerpo = api.call("GET", "/consultas")
        self.assertEqual(status, 200)
        self.assertIn("consultas", cuerpo)

    def test_500_no_controlado_del_backend_no_rompe_el_frontend(self):
        """Un error inesperado en el Backend devuelve 500 JSON estructurado sin detalles internos."""
        self.entrar()
        self.db.fallo = RuntimeError("fallo inesperado")

        status, cuerpo = api.call("GET", api.HISTORIAL_PATH)
        self.assertEqual(status, 500)
        self.assertEqual(cuerpo, {"codigo_error": "error_interno", "mensaje": "Error interno del servidor."})

        hist = api.fetch_history()
        self.assertFalse(hist.ok)
        self.assertFalse(hist.session_expired)
        self.assertEqual(hist.error, api.HISTORY_SERVER_ERROR)

        resp = api.send_message("", PREGUNTA_OK)
        self.assertEqual((resp.estado, resp.texto), (STATUS_ERROR, GENERIC_ERROR))

        session.clear()
        login = auth.login("usuario1", "usuario123")
        self.assertFalse(login.ok)
        self.assertEqual(login.error, auth.SERVER_ERROR)

    def test_503_base_de_datos_caida_en_historial(self):
        self.entrar()
        self.db.fallo = psycopg.OperationalError("PostgreSQL caído")
        hist = api.fetch_history()
        self.assertFalse(hist.ok)
        self.assertFalse(hist.session_expired)
        self.assertEqual(hist.error, api.HISTORY_SERVER_ERROR)

    def test_servidor_apagado_da_error_de_conexion(self):
        with socket.socket() as sock:  # puerto libre en el que no escucha nadie
            sock.bind(("127.0.0.1", 0))
            puerto = sock.getsockname()[1]
        api.API_URL = f"http://127.0.0.1:{puerto}"
        self.assertEqual(auth.login("usuario1", "usuario123").error, "No se pudo conectar con el servidor.")
        self.assertEqual(api.fetch_history().error, "No se ha podido contactar con el servidor.")
        self.assertEqual(api.send_message("", PREGUNTA_OK).texto, GENERIC_ERROR)


# ============================================================================= 2. Despliegue completo
E2E_URL = os.environ.get("ARSOFT_E2E_URL", "").rstrip("/")


@unittest.skipUnless(E2E_URL, "Prueba de principio a fin: define ARSOFT_E2E_URL con el despliegue completo")
class TestDespliegueReal(unittest.TestCase):
    """Frontend ⇄ Backend ⇄ PostgreSQL ⇄ Agentes reales. No modifica nada salvo crear chats."""

    usuario = os.environ.get("ARSOFT_E2E_USUARIO", "usuario1")
    clave = os.environ.get("ARSOFT_E2E_CONTRASENA", "usuario123")

    def setUp(self):
        session.clear()
        api.API_URL = E2E_URL
        self._orig_consulta_path = api.CONSULTA_PATH
        api.CONSULTA_PATH = "/consulta"

    def tearDown(self):
        api.API_URL = ""
        api.CONSULTA_PATH = self._orig_consulta_path
        session.clear()

    def entrar(self) -> None:
        res = auth.login(self.usuario, self.clave)
        self.assertTrue(res.ok, f"Login de {self.usuario} falló: {res.error}")
        session.start(res.user, res.token, res.user_id)

    def test_salud_del_backend_y_sus_dependencias(self):
        status, cuerpo = api.call("GET", "/health")
        self.assertEqual(status, 200)
        status, cuerpo = api.call("GET", "/ready")
        self.assertEqual(status, 200, f"/ready no está listo: {cuerpo} (postgres/agentes)")

    def test_login_401_y_login_correcto(self):
        self.assertEqual(auth.login(self.usuario, "clave-incorrecta-e2e").error,
                         "Usuario o contraseña incorrectos.")
        self.entrar()
        self.assertTrue(session.token)

    def test_consulta_real_y_aparece_en_el_historial(self):
        self.entrar()
        resp = api.send_message("", PREGUNTA_OK)

        self.assertIn(resp.estado, STATUSES)
        self.assertNotEqual(resp.estado, STATUS_ERROR,
                            f"La cadena Backend→Agentes devolvió error: {resp.codigo_error}")
        self.assertTrue(resp.trace_id)
        self.assertTrue(resp.conversacion_id)
        if resp.estado == STATUS_OK:
            self.assertTrue(resp.fuentes, "Una respuesta fundamentada debe traer fuentes")

        hist = api.fetch_history()
        self.assertTrue(hist.ok, hist.error)
        conv = next((c for c in hist.conversations if c.id == resp.conversacion_id), None)
        self.assertIsInstance(conv, Conversation, "La conversación no aparece en GET /chats")
        self.assertEqual(conv.messages[-2].text, PREGUNTA_OK)
        self.assertEqual(conv.messages[-1].trace_id, resp.trace_id)

    def test_401_con_token_invalido(self):
        session.start(self.usuario, "token-invalido", "")
        self.assertTrue(api.fetch_history().session_expired)
        self.assertEqual(api.send_message("", PREGUNTA_OK).codigo_error, "sesion_caducada")

    def test_403_ruta_de_administracion_con_usuario_normal(self):
        self.entrar()
        status, cuerpo = api.call("GET", "/consultas")
        if status == 200:
            self.skipTest(f"{self.usuario} es administrador: no se puede provocar 403")
        self.assertEqual(status, 403)
        self.assertEqual((cuerpo or {}).get("codigo_error"), "acceso_denegado")

    @unittest.skipUnless(os.environ.get("ARSOFT_E2E_PROBAR_429") == "1",
                         "Define ARSOFT_E2E_PROBAR_429=1 (suma 6 fallos a tu IP durante 5 minutos)")
    def test_429_tras_varios_fallos_de_login(self):
        usuario = f"e2e-{uuid.uuid4().hex[:8]}"  # usuario inventado: no bloquea a nadie real
        errores = [auth.login(usuario, "x").error for _ in range(6)]
        self.assertIn("Demasiados intentos", errores[-1], errores)


if __name__ == "__main__":
    unittest.main()
