"""
Batería de Pruebas Unitarias y de Integración — Frontend (Conexión Simulada / Mock)
===================================================================================
Pruebas de la capa de comunicación y contratos del Frontend:
- Lectura de respuestas según CTR-001 (estados: respuesta, aclaracion, fuera_de_ambito, sin_evidencia).
- Lectura de respuestas según CTR-006 (historial de chats y modo historial vacío).
- Gestión de errores HTTP: 401, 403, 429 y 500.
- Manejo de JSON no válido y respuestas corruptas.
- Envío de consultas al asistente y preservación de la pregunta exacta.

Ejecución:
    pytest Test/test_Frontend/test_conexion_simulada.py
o bien:
    python -m unittest discover -s Test/test_Frontend -p "test_*.py"
"""

from __future__ import annotations

from copy import deepcopy
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Frontend/ y la raíz del repositorio en sys.path (los módulos del Frontend se importan como
# «models.*» y «services.*», igual que cuando se ejecuta Frontend/main.py)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "Frontend"
for path_dir in (str(FRONTEND_DIR), str(ROOT_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from Test.test_Frontend import qt_test_harness

qt_test_harness.setup_qt_harness()

from models.conversation import Conversation, DEFAULT_TITLE
from models.dates import parse as parse_date
from models.message import Message, ROLE_BOT, ROLE_USER
from models.response import (
    GENERIC_ERROR,
    STATUS_CLARIFY,
    STATUS_ERROR,
    STATUS_NO_EVIDENCE,
    STATUS_OK,
    STATUS_OUT_OF_SCOPE,
    Response,
)
from models.source import Source
from services import api, auth, session
import config

MOCK_CHATS_BASELINE = deepcopy(api._MOCK_CHATS)


class BaseFrontendTestCase(unittest.TestCase):
    """Configuración base para aislar las pruebas de variables de entorno y retardos."""

    def setUp(self):
        api._MOCK_CHATS[:] = deepcopy(MOCK_CHATS_BASELINE)
        # Desactivar ARSOFT_API_URL para forzar el modo simulado por defecto
        self._orig_api_url = os.environ.get("ARSOFT_API_URL")
        if "ARSOFT_API_URL" in os.environ:
            del os.environ["ARSOFT_API_URL"]
        api.API_URL = ""
        # Ignorar el ARSOFT_MODO que pueda haber en el .env local del desarrollador
        self._orig_modo = api.MODO
        api.MODO = config.MODO_AUTO

        # Evitar los 1.2 segundos de sleep intencionales del mock en los tests
        self._sleep_patcher = patch("time.sleep", return_value=None)
        self._sleep_patcher.start()

        # Limpiar la sesión
        session.clear()

    def tearDown(self):
        self._sleep_patcher.stop()
        api._MOCK_CHATS[:] = deepcopy(MOCK_CHATS_BASELINE)
        if self._orig_api_url is not None:
            os.environ["ARSOFT_API_URL"] = self._orig_api_url
            api.API_URL = self._orig_api_url.rstrip("/")
        else:
            api.API_URL = ""
        api.MODO = self._orig_modo
        session.clear()


# ==============================================================================
# 1. LECTURA DE RESPUESTAS CTR-001 (Consulta al Asistente)
# ==============================================================================
class TestCTR001LecturaRespuestas(BaseFrontendTestCase):
    """Comprueba la lectura, parseo y estructura de respuestas según CTR-001."""

    def test_ctr001_respuesta_fundamentada_con_fuentes(self):
        """Consulta técnica con respuesta OK: debe devolver texto, trace_id y fuentes."""
        res = api.send_message("conv-001", "temperatura alta en motor y refrigerante")

        self.assertIsInstance(res, Response)
        self.assertEqual(res.estado, STATUS_OK)
        self.assertEqual(res.trace_id, "t-demo")

        self.assertEqual(res.codigo_error, "")
        self.assertIn("refrigerante", res.texto.lower())

        # Validación estricta de las fuentes documentales
        self.assertGreaterEqual(len(res.fuentes), 1)
        fuente = res.fuentes[0]
        self.assertIsInstance(fuente, Source)
        self.assertEqual(fuente.documento, "Manual_ejemplo")
        self.assertEqual(fuente.seccion, "2.1")
        self.assertEqual(fuente.pagina, 128)
        self.assertIn("V1.1", fuente.versiones)
        self.assertFalse(fuente.obsoleto)
        self.assertEqual(fuente.chunk_id, "c45")

    def test_ctr001_error_tecnico_en_simulador(self):
        """El simulador conserva la respuesta de error técnico del Agente 2."""
        res = api.send_message("conv-error", "Consulta con simular_error en el motor de búsqueda")

        self.assertEqual(res.estado, STATUS_ERROR)
        self.assertEqual(res.codigo_error, "error")
        self.assertIn("503", res.texto)

    def test_ctr001_servidor_caido_en_simulador(self):
        """El simulador representa una caída del servicio con el error contractual."""
        res = api.send_message("conv-down", "simular servidor_caido")

        self.assertEqual(res.estado, STATUS_ERROR)
        self.assertEqual(res.codigo_error, "servicio_no_disponible")
        self.assertEqual(res.texto, GENERIC_ERROR)

    def test_ctr001_aclaracion_por_pregunta_demasiado_corta(self):
        """Preguntas de dos o menos palabras provocan repregunta (estado aclaracion)."""
        res = api.send_message("conv-002", "motor fallo")

        self.assertEqual(res.estado, STATUS_CLARIFY)
        self.assertEqual(res.trace_id, "t-demo")
        self.assertIn("código", res.texto.lower())
        self.assertEqual(res.fuentes, [])

    def test_ctr001_fuera_de_ambito(self):
        """Consultas no relacionadas con el manual devuelven estado fuera_de_ambito."""
        res_tiempo = api.send_message("conv-003", "¿Qué tiempo va a hacer mañana?")
        self.assertEqual(res_tiempo.estado, STATUS_OUT_OF_SCOPE)
        self.assertEqual(res_tiempo.fuentes, [])

        res_receta = api.send_message("conv-004", "Dame una receta de cocina")
        self.assertEqual(res_receta.estado, STATUS_OUT_OF_SCOPE)

    def test_ctr001_sin_evidencia(self):
        """Consultas sin documentación técnica disponible devuelven sin_evidencia."""
        res = api.send_message("conv-005", "Instalación de techo solar panorámico abatible")

        self.assertEqual(res.estado, STATUS_NO_EVIDENCE)
        self.assertIn("no hay evidencia", res.texto.lower())
        self.assertEqual(res.fuentes, [])

    def test_ctr001_contrato_mock_call_formato_exacto(self):
        """Verifica que _mock_call devuelve exactamente los campos especificados en CTR-001.

        El Backend devuelve también el conversacion_id de la consulta (ver services/api.py).
        """
        status, data = api._mock_call("POST", api.CONSULTA_PATH, {
            "conversacion_id": "test-conv",
            "pregunta": "revisar refrigerante en el motor"
        })

        self.assertEqual(status, 200)
        self.assertIsInstance(data, dict)
        # El Backend añade conversacion_id a los campos de CTR-001
        campos_esperados = {"trace_id", "conversacion_id", "estado", "texto", "fuentes", "codigo_error"}
        self.assertEqual(set(data.keys()), campos_esperados)
        self.assertEqual(data["conversacion_id"], "test-conv")
        self.assertIsInstance(data["fuentes"], list)

        # Campos de cada fuente
        campos_fuente = {"chunk_id", "documento", "seccion", "pagina", "versiones", "obsoleto"}
        for f in data["fuentes"]:
            self.assertEqual(set(f.keys()), campos_fuente)

    def test_ctr001_response_from_dict(self):
        """Construcción de modelo Response a partir de diccionario completo."""
        raw = {
            "trace_id": "t-12345",
            "estado": STATUS_OK,
            "texto": "Par de apriete: 25 Nm",
            "fuentes": [
                {
                    "chunk_id": "c-01",
                    "documento": "Manual_Taller",
                    "seccion": "4.2",
                    "pagina": 55,
                    "versiones": ["V1.0"],
                    "obsoleto": False
                }
            ],
            "codigo_error": ""
        }
        resp = Response.from_dict(raw)
        self.assertEqual(resp.trace_id, "t-12345")
        self.assertEqual(resp.estado, STATUS_OK)
        self.assertEqual(resp.texto, "Par de apriete: 25 Nm")
        self.assertEqual(len(resp.fuentes), 1)
        self.assertEqual(resp.fuentes[0].documento, "Manual_Taller")


# ==============================================================================
# 2. LECTURA DE RESPUESTAS CTR-006 (Historial de Conversaciones)
# ==============================================================================
class TestCTR006LecturaHistorial(BaseFrontendTestCase):
    """Comprueba la lectura y parseo del historial de conversaciones."""

    def test_ctr006_lectura_historial_por_defecto(self):
        """En modo simulado, fetch_history devuelve los chats de demostración."""
        hist = api.fetch_history()

        self.assertTrue(hist.ok)
        self.assertFalse(hist.session_expired)
        self.assertEqual(hist.error, "")
        self.assertGreaterEqual(len(hist.conversations), 1)

        conv = hist.conversations[0]
        self.assertEqual(conv.id, "demo-chat-001")
        self.assertEqual(conv.title, "Temperatura del motor")
        self.assertGreaterEqual(len(conv.messages), 2)

        # Mensaje de usuario
        m_user = conv.messages[0]
        self.assertEqual(m_user.role, ROLE_USER)
        self.assertIn("temperatura", m_user.text.lower())

        # Mensaje de asistente con fuentes
        m_bot = conv.messages[1]
        self.assertEqual(m_bot.role, ROLE_BOT)
        self.assertGreaterEqual(len(m_bot.sources), 1)
        self.assertEqual(m_bot.sources[0].chunk_id, "c45")

    def test_ctr006_historial_vacio_por_entorno(self):
        """Con ARSOFT_MOCK_EMPTY_HISTORY=1 el simulador devuelve lista vacía."""
        with patch.object(api, "_MOCK_EMPTY_HISTORY", True):
            hist = api.fetch_history()
            self.assertTrue(hist.ok)
            self.assertEqual(hist.conversations, [])
            self.assertFalse(hist.session_expired)

    def test_ctr006_mock_call_formato_exacto(self):
        """El endpoint GET /chats en el simulador devuelve {'chats': [...], 'total': n}."""
        status, data = api._mock_call("GET", api.HISTORIAL_PATH, None)

        self.assertEqual(status, 200)
        self.assertIsInstance(data, dict)
        self.assertIn("chats", data)
        self.assertIn("total", data)
        self.assertEqual(len(data["chats"]), data["total"])

    def test_ctr006_renombrar_chat_usa_patch_y_parsea_respuesta(self):
        response = {
            "conversacion_id": "chat-1",
            "titulo": "Nuevo título",
            "updated_at": "2026-11-24T10:00:00Z",
            "mensajes": [],
        }
        with patch("services.api.call", return_value=(200, response)) as request:
            result = api.rename_chat("chat-1", "Nuevo título")

        request.assert_called_once_with("PATCH", "/chats/chat-1", {"titulo": "Nuevo título"})
        self.assertTrue(result.ok)
        self.assertEqual(result.conversation.title, "Nuevo título")

    def test_ctr006_eliminar_chat_usa_delete_y_acepta_204(self):
        with patch("services.api.call", return_value=(204, None)) as request:
            result = api.delete_chat("chat-1")

        request.assert_called_once_with("DELETE", "/chats/chat-1")
        self.assertTrue(result.ok)

    def test_ctr006_renombrar_rechaza_titulo_vacio_o_demasiado_largo(self):
        with patch("services.api.call") as request:
            empty = api.rename_chat("chat-1", "  ")
            long = api.rename_chat("chat-1", "x" * 201)

        request.assert_not_called()
        self.assertFalse(empty.ok)
        self.assertFalse(long.ok)

    def test_ctr006_acciones_del_simulador_persisten_en_el_historial(self):
        chats = [{
            "conversacion_id": "chat-demo",
            "titulo": "Anterior",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-15T10:00:00Z",
            "mensajes": [],
        }]
        with patch.object(api, "_MOCK_CHATS", chats):
            renamed = api._mock_call("PATCH", "/chats/chat-demo", {"titulo": "Nuevo"})
            history = api._mock_call("GET", api.HISTORIAL_PATH, None)
            deleted = api._mock_call("DELETE", "/chats/chat-demo", None)
            empty_history = api._mock_call("GET", api.HISTORIAL_PATH, None)

        self.assertEqual(renamed[0], 200)
        self.assertEqual(renamed[1]["titulo"], "Nuevo")
        self.assertEqual(history[1]["chats"][0]["titulo"], "Nuevo")
        self.assertEqual(deleted, (204, None))
        self.assertEqual(empty_history[1]["chats"], [])

    def test_ctr006_conversation_deserializacion(self):
        """Comprueba el parseo de Conversation mediante from_dict conservando campos y mensajes."""
        d = {
            "conversacion_id": "conv-test-99",
            "titulo": "Prueba de motor",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-15T10:05:00Z",
            "mensajes": [
                {
                    "role": "user",
                    "contenido": "¿Nivel de aceite?",
                    "estado": "respuesta",
                    "trace_id": "t-oil",
                    "fuentes": [],
                    "timestamp": "2026-01-15T10:00:00Z"
                }
            ]
        }
        conv_recuperada = Conversation.from_dict(d)
        self.assertEqual(conv_recuperada.id, "conv-test-99")
        self.assertEqual(conv_recuperada.title, "Prueba de motor")
        self.assertEqual(len(conv_recuperada.messages), 1)
        self.assertEqual(conv_recuperada.messages[0].text, "¿Nivel de aceite?")

    def test_ctr006_continuar_chat_con_su_conversacion_id(self):
        """Un chat del historial se continúa con su propio conversacion_id (no con ID vacío)."""
        d = {"conversacion_id": "abc123", "titulo": "Prueba de motor",
             "created_at": "2026-01-15T10:00:00Z", "updated_at": "2026-01-15T10:03:00Z",
             "mensajes": [{"message_id": "m1", "trace_id": "t1", "role": "user",
                           "contenido": "¿Nivel de aceite?", "estado": "respuesta",
                           "timestamp": "2026-01-15T10:00:00Z", "fuentes": []}]}
        conv = Conversation.from_dict(d)
        self.assertEqual(conv.id, "abc123")
        self.assertEqual(conv.server_id, "abc123")
        self.assertEqual(conv.title, "Prueba de motor")
        self.assertEqual(len(conv.messages), 1)

    def test_chat_nuevo_envia_conversacion_id_vacio(self):
        """CTR-001: la primera pregunta de un chat nuevo lleva conversacion_id vacío."""
        self.assertEqual(Conversation().server_id, "")

    def test_ctr006_conversation_from_dict(self):
        """Comprueba la lectura de un chat de CTR-006 con Conversation.from_dict.

        El historial lo gestiona el Backend, así que el Frontend solo lee chats (no los serializa).
        """
        raw = {
            "conversacion_id": "conv-aceite",
            "titulo": "Prueba de motor",
            "created_at": "2026-11-16T10:00:00",
            "updated_at": "2026-11-16T10:05:00",
            "mensajes": [
                {"role": ROLE_USER, "contenido": "¿Nivel de aceite?", "message_id": "m-1"},
            ],
        }
        conv = Conversation.from_dict(raw)

        self.assertEqual(conv.id, "conv-aceite")
        self.assertEqual(conv.title, "Prueba de motor")
        self.assertEqual(conv.created_at, "2026-11-16T10:00:00")
        self.assertEqual(conv.updated_at, "2026-11-16T10:05:00")
        self.assertEqual(len(conv.messages), 1)
        self.assertEqual(conv.messages[0].role, ROLE_USER)
        self.assertEqual(conv.messages[0].text, "¿Nivel de aceite?")

    def test_ctr006_conversation_from_dict_sin_titulo(self):
        """Un chat de CTR-006 sin título usa el título por defecto."""
        conv = Conversation.from_dict({"conversacion_id": "conv-sin-titulo"})

        self.assertEqual(conv.title, DEFAULT_TITLE)
        self.assertEqual(conv.messages, [])

    def test_ctr006_message_from_dict_sin_message_id(self):
        """Un mensaje sin `message_id` se lee igualmente, con identificador vacío."""
        conv = Conversation.from_dict({
            "conversacion_id": "conv-sin-mid",
            "mensajes": [
                {"role": ROLE_USER, "contenido": "¿Presión de aceite?"},
                {"role": ROLE_BOT, "contenido": "Entre 2 y 4 bar.", "estado": "respuesta"},
            ],
        })

        self.assertEqual(len(conv.messages), 2)
        self.assertTrue(all(m.message_id == "" for m in conv.messages))
        self.assertEqual(conv.messages[0].text, "¿Presión de aceite?")
        self.assertEqual(conv.messages[1].text, "Entre 2 y 4 bar.")

    def test_ctr006_message_from_dict_fuentes_ausentes(self):
        """`fuentes` ausente, nulo o vacío produce una lista de fuentes vacía."""
        base = {"role": ROLE_BOT, "contenido": "Respuesta", "estado": "respuesta"}
        casos = {
            "clave ausente": dict(base),
            "valor null": {**base, "fuentes": None},
            "lista vacía": {**base, "fuentes": []},
        }
        for nombre, raw in casos.items():
            with self.subTest(nombre):
                self.assertEqual(Message.from_dict(raw).sources, [])

        # Un chat completo con mensajes sin fuentes tampoco debe fallar.
        conv = Conversation.from_dict({"conversacion_id": "c", "mensajes": [dict(base)]})
        self.assertEqual(conv.messages[0].sources, [])

    def test_ctr006_fechas_con_sufijo_z(self):
        """Las fechas con sufijo Z (formato que emite el Backend) se conservan y se interpretan."""
        conv = Conversation.from_dict({
            "conversacion_id": "conv-z",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-15T10:03:00Z",
            "mensajes": [{"role": ROLE_USER, "contenido": "Hola",
                          "timestamp": "2026-01-15T10:00:00Z"}],
        })

        # El modelo guarda el texto tal cual lo emite el Backend...
        self.assertEqual(conv.created_at, "2026-01-15T10:00:00Z")
        self.assertEqual(conv.updated_at, "2026-01-15T10:03:00Z")
        self.assertEqual(conv.messages[0].timestamp, "2026-01-15T10:00:00Z")

        # ...y `dates.parse` lo convierte a hora local sin zona, respetando el orden.
        creada, actualizada = parse_date(conv.created_at), parse_date(conv.updated_at)
        self.assertIsNotNone(creada)
        self.assertIsNone(creada.tzinfo)
        self.assertEqual(actualizada - creada, timedelta(minutes=3))
        self.assertEqual(parse_date("2026-01-15T10:00:00Z"), parse_date("2026-01-15T10:00:00+00:00"))

    def test_fechas_vacias_o_invalidas_no_rompen(self):
        """Una fecha vacía o ilegible devuelve None en lugar de lanzar excepción."""
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("no-es-una-fecha"))


# ==============================================================================
# 3. ENVÍO DE CONSULTAS AL ASISTENTE
# ==============================================================================
class TestEnvioConsulta(BaseFrontendTestCase):
    """Comprueba el envío de consultas y cumplimiento de contratos del frontend."""

    def test_envio_consulta_exitosa(self):
        """Envío básico de consulta en modo simulado con texto técnico descriptivo."""
        resp = api.send_message("chat-100", "¿Qué debo hacer si sube la temperatura del motor?")
        self.assertIsInstance(resp, Response)
        self.assertEqual(resp.estado, STATUS_OK)
        self.assertIn("refrigerante", resp.texto.lower())

    def test_ruta_de_consulta_es_post_consulta(self):
        """El Frontend habla con el Backend en POST /consulta, no con la ruta interna de Agentes."""
        self.assertEqual(api.CONSULTA_PATH, "/consulta")
        with patch("services.api.call") as mock_call:
            mock_call.return_value = (200, {"trace_id": "t", "estado": STATUS_OK, "texto": "Ok",
                                            "fuentes": [], "codigo_error": "", "conversacion_id": "nuevo-1"})
            resp = api.send_message("", "primera pregunta")
        mock_call.assert_called_once_with("POST", "/consulta",
                                          {"conversacion_id": "", "pregunta": "primera pregunta"})
        self.assertEqual(resp.conversacion_id, "nuevo-1")

    def test_envio_consulta_preserva_texto_exacto(self):
        """CTR-001 exige que la pregunta se envíe EXACTAMENTE como se escribió (sin strip)."""
        pregunta_exacta = "   espacios antes y despues con Mayúsculas   "
        with patch("services.api.call") as mock_call:
            mock_call.return_value = (200, {
                "trace_id": "t-1",
                "estado": STATUS_OK,
                "texto": "Ok",
                "fuentes": [],
                "codigo_error": ""
            })

            api.send_message("conv-preserve", pregunta_exacta)

            mock_call.assert_called_once_with(
                "POST",
                api.CONSULTA_PATH,
                {"conversacion_id": "conv-preserve", "pregunta": pregunta_exacta}
            )

    def test_envio_consulta_con_error_de_conexion(self):
        """Si no se puede contactar con el servidor se lanza ConnectionFailed y devuelve error."""
        with patch("services.api.call", side_effect=api.ConnectionFailed("Sin red")):
            resp = api.send_message("c-err", "alguna pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, GENERIC_ERROR)
            self.assertEqual(resp.codigo_error, "servicio_no_disponible")

    def test_envio_consulta_con_tiempo_agotado(self):
        """Un timeout de red conserva el error estructurado del contrato."""
        with patch("services.api.call",
                   side_effect=api.ConnectionFailed("Tiempo agotado", "tiempo_agotado")):
            resp = api.send_message("c-timeout", "alguna pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, GENERIC_ERROR)
            self.assertEqual(resp.codigo_error, "tiempo_agotado")

    def test_envio_consulta_con_error_de_configuracion(self):
        """Una configuración inválida (p. ej. modo real sin URL) se muestra al usuario, no el error genérico."""
        with patch("services.api.call", side_effect=api.ConfigError(api.MISSING_URL)):
            resp = api.send_message("c-cfg", "alguna pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, api.MISSING_URL)
            self.assertEqual(resp.codigo_error, "configuracion")

    def test_envio_consulta_modo_real_sin_url(self):
        """ARSOFT_MODO=real sin ARSOFT_API_URL: la consulta explica que falta el servidor."""
        orig_modo = api.MODO
        api.MODO = config.MODO_REAL
        try:
            resp = api.send_message("c-sin-url", "alguna pregunta")
        finally:
            api.MODO = orig_modo
        self.assertEqual(resp.estado, STATUS_ERROR)
        self.assertEqual(resp.texto, api.MISSING_URL)

    def test_envio_consulta_chat_worker(self):
        """El ChatWorker ejecuta la consulta en segundo plano y emite finished_ok."""
        worker = api.ChatWorker("conv-async", "¿Cómo comprobar el nivel de refrigerante?")
        resultado_emision = []

        worker.finished_ok.connect(lambda r: resultado_emision.append(r))
        worker.run()

        self.assertEqual(len(resultado_emision), 1)
        self.assertIsInstance(resultado_emision[0], Response)
        self.assertEqual(resultado_emision[0].estado, STATUS_OK)


# ==============================================================================
# 4. GESTIÓN DE ERRORES HTTP (401, 403, 429, 500)
# ==============================================================================
class TestErroresHTTP(BaseFrontendTestCase):
    """Comprueba el tratamiento de errores HTTP según los contratos de la API."""

    # --- 401 Unauthorized ---
    def test_error_401_en_consulta_indica_sesion_caducada(self):
        """HTTP 401 en CTR-001 debe devolver Response con código 'sesion_caducada'."""
        with patch("services.api.call", return_value=(401, {"mensaje": "No autenticado"})):
            resp = api.send_message("c-401", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.codigo_error, "sesion_caducada")
            self.assertEqual(resp.texto, api.SESSION_EXPIRED)

    def test_error_401_en_historial_indica_sesion_caducada(self):
        """HTTP 401 en CTR-006 debe activar la bandera session_expired en HistoryResult."""
        with patch("services.api.call", return_value=(401, None)):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)
            self.assertTrue(hist.session_expired)
            self.assertEqual(hist.error, api.SESSION_EXPIRED)

    def test_error_401_en_login_credenciales_invalidas(self):
        """Credenciales incorrectas devuelven 401 y AuthResult(ok=False)."""
        res = auth.login("usuario_falso", "clave_falsa")
        self.assertFalse(res.ok)
        self.assertIn("incorrectos", res.error.lower())

    # --- 403 Forbidden ---
    def test_error_403_en_consulta_indica_sesion_caducada(self):
        """HTTP 403 en CTR-001 se trata como sesión caducada."""
        with patch("services.api.call", return_value=(403, None)):
            resp = api.send_message("c-403", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.codigo_error, "sesion_caducada")
            self.assertEqual(resp.texto, api.SESSION_EXPIRED)

    def test_error_403_en_historial_indica_sesion_caducada(self):
        """HTTP 403 en CTR-006 marca la sesión como caducada."""
        with patch("services.api.call", return_value=(403, None)):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)
            self.assertTrue(hist.session_expired)

    # --- 429 Too Many Requests ---
    def test_error_429_en_login_simulado(self):
        """El usuario 'rate_limit' provoca HTTP 429 en el simulador."""
        res = auth.login("rate_limit", "cualquiera")
        self.assertFalse(res.ok)
        self.assertIn("Demasiados intentos", res.error)

    def test_error_429_en_consulta(self):
        """HTTP 429 en CTR-001 pide esperar, sin llamarlo «asistente no disponible»."""
        with patch("services.api.call", return_value=(429, {"mensaje": "Rate limit"})):
            resp = api.send_message("c-429", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.codigo_error, "demasiadas_consultas")
            self.assertEqual(resp.texto, api.TOO_MANY_REQUESTS)
            self.assertNotEqual(resp.texto, GENERIC_ERROR)

    def test_error_404_en_consulta_conversacion_no_encontrada(self):
        """HTTP 404 en CTR-001: el chat no existe o no es del usuario."""
        body = {"codigo_error": "conversacion_no_encontrada", "mensaje": "La conversación no existe."}
        with patch("services.api.call", return_value=(404, body)):
            resp = api.send_message("c-404", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.codigo_error, "conversacion_no_encontrada")
            self.assertEqual(resp.texto, api.CONVERSATION_NOT_FOUND)

    def test_error_422_en_consulta_entrada_invalida(self):
        """HTTP 422 en CTR-001: formato de entrada incorrecto."""
        with patch("services.api.call", return_value=(422, {"codigo_error": "entrada_invalida"})):
            resp = api.send_message("c-422", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.codigo_error, "entrada_invalida")
            self.assertEqual(resp.texto, api.INVALID_INPUT)

    def test_error_429_en_historial(self):
        """HTTP 429 en CTR-006 devuelve HistoryResult no exitoso."""
        with patch("services.api.call", return_value=(429, None)):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)
            self.assertFalse(hist.session_expired)
            self.assertEqual(hist.error, api.HISTORY_TOO_MANY)

    # --- 500 Internal Server Error ---
    def test_error_500_en_consulta(self):
        """HTTP 500 en CTR-001 devuelve error genérico sin propagar excepciones."""
        with patch("services.api.call", return_value=(500, {"error": "crash"})):
            resp = api.send_message("c-500", "pregunta")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, GENERIC_ERROR)

    def test_error_500_en_historial(self):
        """HTTP 500 en CTR-006 devuelve HistoryResult con error controlado."""
        with patch("services.api.call", return_value=(500, None)):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)
            self.assertEqual(hist.error, api.HISTORY_SERVER_ERROR)

    def test_error_500_en_login(self):
        """HTTP 500 en CTR-005 informa de un problema del servidor."""
        with patch("services.api.call", return_value=(500, None)):
            res = auth.login("demo", "demo1234")
            self.assertFalse(res.ok)
            self.assertEqual(res.error, auth.SERVER_ERROR)


# ==============================================================================
# 5. MANEJO DE JSON NO VÁLIDO Y RESPUESTAS CORRUPTAS
# ==============================================================================
class TestJSONNoValidoYCorrupcion(BaseFrontendTestCase):
    """Comprueba la robustez ante respuestas que no son JSON o tienen formato inválido."""

    def test_json_no_valido_en_api_call_modo_real(self):
        """Cuando el backend responde con HTML o texto no JSON, call devuelve (status, None)."""
        api.API_URL = "http://localhost:8000"
        with patch.object(api, "is_mock", return_value=False), \
             patch.object(api, "_insecure", return_value=False):

            mock_response = MagicMock()
            mock_response.status = 502
            mock_response.read.return_value = b"<html>502 Bad Gateway</html>"
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                status, data = api.call("GET", "/test-bad-json")
                self.assertEqual(status, 502)
                self.assertIsNone(data)

    def test_json_sintacticamente_corrupto(self):
        """Si la respuesta HTTP trae JSON truncado o incompleto, call devuelve None."""
        api.API_URL = "http://localhost:8000"
        with patch.object(api, "is_mock", return_value=False), \
             patch.object(api, "_insecure", return_value=False):

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b'{"estado": "ok", "texto": '
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                status, data = api.call("POST", api.CONSULTA_PATH)
                self.assertEqual(status, 200)
                self.assertIsNone(data)

    def test_json_valido_pero_no_diccionario(self):
        """Si la respuesta HTTP es JSON pero devuelve una lista o número, call devuelve None."""
        api.API_URL = "http://localhost:8000"
        with patch.object(api, "is_mock", return_value=False), \
             patch.object(api, "_insecure", return_value=False):

            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = b'[1, 2, 3]'
            mock_response.__enter__.return_value = mock_response

            with patch("urllib.request.urlopen", return_value=mock_response):
                status, data = api.call("GET", "/chats")
                self.assertEqual(status, 200)
                self.assertIsNone(data)

    def test_send_message_con_data_none(self):
        """Si status es 200 pero data es None (JSON corrupto), send_message devuelve error."""
        with patch("services.api.call", return_value=(200, None)):
            resp = api.send_message("c-corrupt", "¿Hola?")
            self.assertEqual(resp.estado, STATUS_ERROR)
            self.assertEqual(resp.texto, GENERIC_ERROR)

    def test_fetch_history_con_estructura_invalida(self):
        """Si data no contiene la lista 'chats' o contiene elementos corruptos, fetch_history no falla."""
        with patch("services.api.call", return_value=(200, {"chats": "no-es-una-lista"})):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)
            self.assertEqual(hist.conversations, [])

        # Lista con un elemento que provoca TypeError / KeyError en Conversation.from_dict
        with patch("services.api.call", return_value=(200, {"chats": [{"invalido": True}] * 3})):
            hist = api.fetch_history()
            self.assertFalse(hist.ok)

    def test_login_con_data_invalida(self):
        """Si el backend responde 200 pero el JSON no contiene el objeto usuario, login falla."""
        with patch("services.api.call", return_value=(200, {"estado": "autenticado", "usuario": None})):
            res = auth.login("demo", "demo1234")
            self.assertFalse(res.ok)

    def test_ctr001_estado_desconocido_en_response(self):
        """Si el backend devuelve un estado no admitido en el contrato, se reporta estado_desconocido."""
        raw = {
            "trace_id": "t-err",
            "estado": "estado_inventado_por_ia",
            "texto": "Respuesta alucinada",
            "fuentes": [],
            "codigo_error": ""
        }
        resp = Response.from_dict(raw)
        self.assertEqual(resp.estado, STATUS_ERROR)
        self.assertEqual(resp.codigo_error, "estado_desconocido")


if __name__ == "__main__":
    unittest.main()
