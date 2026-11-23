"""
Batería de Pruebas de Interfaz de Usuario (UI) y Flujos de Frontend
====================================================================
Pruebas funcionales de los componentes visuales y flujos de usuario:
- Formulario de Login: validación de entradas, errores visibles, alternancia de contraseña,
  estados de carga y bloqueo, emisión de señales y reseteo del formulario.
- Ventana Principal (MainWindow): renderizado de cabecera, estados vacíos, creación y reutilización
  de conversaciones, navegación en el historial, truncado automático de títulos en primer envío,
  estados de carga durante consulta, eliminación de burbuja de typing al responder y flujo de logout.
- Componentes visuales: ChatMessage (burbujas de usuario, bot y typing, badges de estado, fuentes),
  SourceCard (metadatos documentales y aviso de obsolescencia) y ConversationItem (formateo relativo de fechas).
- Coordinador de aplicación (App): ciclo de vida login -> chat -> logout -> login y gestión de sesión.

Ejecución:
    pytest Test/test_Frontend/test_interfaz_usuario.py
o bien:
    python -m unittest discover -s Test/test_Frontend -p "test_*.py"
"""

from __future__ import annotations
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Frontend/ y la raíz del repositorio en sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = ROOT_DIR / "Frontend"
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(1, str(ROOT_DIR))

from Test.test_Frontend import qt_test_harness

qt_test_harness.setup_qt_harness()
from PySide6.QtCore import Qt, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from components.chat_message import ChatMessage  # noqa: E402
from components.conversation_item import _fmt  # noqa: E402
from components.source_card import SourceCard  # noqa: E402
from models.conversation import Conversation  # noqa: E402
from models.message import Message, ROLE_USER, ROLE_BOT  # noqa: E402
from models.response import (  # noqa: E402
    Response,
    STATUS_OK,
    STATUS_CLARIFY,
    STATUS_NO_EVIDENCE,
    STATUS_OUT_OF_SCOPE,
    STATUS_ERROR,
)
from models.source import Source  # noqa: E402
from services import api, auth, session  # noqa: E402
from views.login_window import LoginWindow  # noqa: E402
from views.main_window import MainWindow, _EnterToSend  # noqa: E402


# ==============================================================================
# 1. PRUEBAS DEL FORMULARIO DE LOGIN (LoginWindow)
# ==============================================================================
class TestLoginWindowUI(unittest.TestCase):
    """Comprueba el comportamiento visible y la validación de la pantalla de Login."""

    def setUp(self):
        self._sleep_patcher = patch("time.sleep", return_value=None)
        self._sleep_patcher.start()
        session.clear()
        self.login = LoginWindow()

    def tearDown(self):
        self._sleep_patcher.stop()
        session.clear()

    def test_login_renderizado_inicial(self):
        """Verifica que los controles iniciales se renderizan con los valores y estados esperados."""
        self.assertIn("Iniciar sesión", self.login.windowTitle())
        self.assertEqual(self.login.btn_login.text(), "Entrar")
        self.assertTrue(self.login.btn_login.isEnabled())
        self.assertEqual(self.login.btn_show.text(), "Mostrar")
        self.assertFalse(self.login.btn_show.isChecked())
        self.assertEqual(self.login.edit_pass.echoMode(), QLineEdit.Password)
        self.assertEqual(self.login.error.text(), "")
        self.assertIn("Modo local simulado", self.login.mode.text())

    def test_login_validacion_campos_vacios_muestra_error(self):
        """Si usuario o contraseña están vacíos, _submit muestra error y no inicia autenticación."""
        # Ambos campos vacíos
        self.login.edit_user.setText("")
        self.login.edit_pass.setText("")
        self.login._submit()
        self.assertEqual(self.login.error.text(), "Introduce tu usuario y tu contraseña.")
        self.assertIsNone(self.login._worker)

        # Solo usuario relleno
        self.login.edit_user.setText("usuario_prueba")
        self.login.edit_pass.setText("")
        self.login._submit()
        self.assertEqual(self.login.error.text(), "Introduce tu usuario y tu contraseña.")
        self.assertIsNone(self.login._worker)

        # Solo contraseña rellena
        self.login.edit_user.setText("")
        self.login.edit_pass.setText("clave_secreta")
        self.login._submit()
        self.assertEqual(self.login.error.text(), "Introduce tu usuario y tu contraseña.")
        self.assertIsNone(self.login._worker)

    def test_login_limpieza_error_al_escribir(self):
        """Al escribir en editUser o editPassword, el mensaje de error anterior se borra."""
        self.login.error.setText("Error previo")
        self.login.edit_user.setText("nuevo_usuario")
        self.assertEqual(self.login.error.text(), "")

        self.login.error.setText("Otro error")
        self.login.edit_pass.setText("nueva_clave")
        self.assertEqual(self.login.error.text(), "")

    def test_login_toggle_visibilidad_contrasena(self):
        """El botón de mostrar contraseña alterna entre modo Password y Normal."""
        self.assertEqual(self.login.edit_pass.echoMode(), QLineEdit.Password)
        self.assertEqual(self.login.btn_show.text(), "Mostrar")

        # Activar visibilidad
        self.login.btn_show.setChecked(True)
        self.assertEqual(self.login.edit_pass.echoMode(), QLineEdit.Normal)
        self.assertEqual(self.login.btn_show.text(), "Ocultar")

        # Desactivar visibilidad
        self.login.btn_show.setChecked(False)
        self.assertEqual(self.login.edit_pass.echoMode(), QLineEdit.Password)
        self.assertEqual(self.login.btn_show.text(), "Mostrar")

    def test_login_estado_ocupado_durante_envio(self):
        """Durante el inicio de sesión, los controles se bloquean y el botón indica carga."""
        self.login.edit_user.setText("demo")
        self.login.edit_pass.setText("demo1234")

        with patch("services.auth.LoginWorker.start"):
            self.login._submit()
            self.assertFalse(self.login.btn_login.isEnabled())
            self.assertFalse(self.login.edit_user.isEnabled())
            self.assertFalse(self.login.edit_pass.isEnabled())
            self.assertEqual(self.login.btn_login.text(), "Entrando…")

    def test_login_resultado_exitoso_emite_senal_y_limpia_clave(self):
        """Una autenticación exitosa emite la señal authenticated y borra la contraseña introducida."""
        self.login.edit_user.setText("demo")
        self.login.edit_pass.setText("demo1234")
        emisiones = []
        self.login.authenticated.connect(lambda res: emisiones.append(res))

        resultado = auth.AuthResult(ok=True, user="demo", token="token-xyz", user_id="u-1")
        self.login._on_result(resultado)

        self.assertEqual(len(emisiones), 1)
        self.assertEqual(emisiones[0].user, "demo")
        self.assertEqual(self.login.edit_pass.text(), "")
        self.assertTrue(self.login.btn_login.isEnabled())
        self.assertEqual(self.login.btn_login.text(), "Entrar")

    def test_login_resultado_fallido_muestra_error_y_limpia_clave(self):
        """Una autenticación errónea muestra el error, borra la clave y permite reintentar."""
        self.login.edit_user.setText("demo")
        self.login.edit_pass.setText("clave_erronea")
        emisiones = []
        self.login.authenticated.connect(lambda res: emisiones.append(res))

        resultado = auth.AuthResult(ok=False, error="Credenciales inválidas")
        self.login._on_result(resultado)

        self.assertEqual(len(emisiones), 0)
        self.assertEqual(self.login.error.text(), "Credenciales inválidas")
        self.assertEqual(self.login.edit_pass.text(), "")
        self.assertTrue(self.login.btn_login.isEnabled())
        self.assertEqual(self.login.btn_login.text(), "Entrar")

    def test_login_reset_restaura_formulario_completo(self):
        """El método reset() limpia los campos, quita el error y devuelve los controles a su estado inicial."""
        self.login.edit_user.setText("admin")
        self.login.edit_pass.setText("clave")
        self.login.error.setText("Error temporal")
        self.login.btn_show.setChecked(True)
        self.login._set_busy(True)

        self.login.reset()

        self.assertEqual(self.login.edit_pass.text(), "")
        self.assertEqual(self.login.error.text(), "")
        self.assertFalse(self.login.btn_show.isChecked())
        self.assertEqual(self.login.btn_show.text(), "Mostrar")
        self.assertTrue(self.login.btn_login.isEnabled())
        self.assertEqual(self.login.btn_login.text(), "Entrar")


# ==============================================================================
# 2. PRUEBAS DE LA VENTANA PRINCIPAL (MainWindow)
# ==============================================================================
class TestMainWindowUI(unittest.TestCase):
    """Comprueba el renderizado, navegación, gestión de chats y estados de MainWindow."""

    def setUp(self):
        self._sleep_patcher = patch("time.sleep", return_value=None)
        self._sleep_patcher.start()
        session.clear()
        self.window = MainWindow("operario_taller")

    def tearDown(self):
        self._sleep_patcher.stop()
        session.clear()

    def test_main_window_renderizado_elementos_cabecera(self):
        """Comprueba que la ventana muestra el usuario conectado, la marca y el modo activo."""
        self.assertIn("Asistente técnico", self.window.windowTitle())
        self.assertEqual(self.window.user_label.text(), "👤 operario_taller")
        self.assertIn("MR", self.window.brand_label.text())
        self.assertIn("BOT", self.window.brand_label.text())
        self.assertIn("Modo simulado", self.window.mode_label.text())
        self.assertTrue(self.window.btn_send.isEnabled())

    def test_main_window_estado_vacio_al_abrir_chat_sin_mensajes(self):
        """Un chat sin mensajes renderiza el widget de estado vacío con las indicaciones iniciales."""
        self.window.new_chat()
        self.assertIsNotNone(self.window._empty)
        # Buscar el título del estado vacío
        empty_title = self.window._empty.findChild(None, "labelEmptyTitle")
        self.assertIsNotNone(empty_title)
        self.assertEqual(empty_title.text(), "¿En qué puedo ayudarte?")

    def test_main_window_nuevo_chat_reutiliza_vacio_existente(self):
        """Si ya hay un chat vacío, pulsar 'Nuevo chat' lo reutiliza en lugar de duplicarlo."""
        self.window.conversations.clear()
        self.window.new_chat()
        count_inicial = len(self.window.conversations)
        self.assertEqual(count_inicial, 1)

        # Pulsar de nuevo nuevo chat sin haber escrito nada
        self.window.new_chat()
        self.assertEqual(len(self.window.conversations), 1)

    def test_main_window_nuevo_chat_crea_uno_si_el_actual_tiene_mensajes(self):
        """Si la conversación actual ya tiene mensajes, pulsar 'Nuevo chat' añade una nueva conversación."""
        self.window.conversations.clear()
        self.window.new_chat()
        self.window.current.messages.append(Message(ROLE_USER, "¿Presión del turbo?"))

        self.window.new_chat()
        self.assertEqual(len(self.window.conversations), 2)
        self.assertEqual(len(self.window.current.messages), 0)

    def test_main_window_seleccion_conversacion_actualiza_interfaz(self):
        """Seleccionar una conversación de la lista actualiza el título y renderiza sus mensajes."""
        conv1 = Conversation(title="Chat Frenos")
        conv1.messages.append(Message(ROLE_USER, "¿Grosor de pastillas?"))
        conv2 = Conversation(title="Chat Embrague")
        conv2.messages.append(Message(ROLE_USER, "¿Purga de circuito?"))
        self.window.conversations = [conv1, conv2]

        self.window._select(conv1.id)
        self.assertEqual(self.window.current.id, conv1.id)
        self.assertEqual(self.window.title_label.text(), "Chat Frenos")
        self.assertEqual(len(self.window._rows), 1)

        self.window._select(conv2.id)
        self.assertEqual(self.window.current.id, conv2.id)
        self.assertEqual(self.window.title_label.text(), "Chat Embrague")
        self.assertEqual(len(self.window._rows), 1)

    def test_main_window_ordenacion_conversaciones_por_fecha(self):
        """Las conversaciones se ordenan de más reciente a más antigua según updated_at."""
        c_antigua = Conversation(title="Antigua", updated_at="2026-01-01T10:00:00Z")
        c_reciente = Conversation(title="Reciente", updated_at="2026-01-10T12:00:00Z")
        self.window.conversations = [c_antigua, c_reciente]

        self.window._refresh_list()
        self.assertEqual(self.window.conversations[0].title, "Reciente")
        self.assertEqual(self.window.conversations[1].title, "Antigua")

    def test_main_window_envio_ignora_texto_vacio(self):
        """Pulsar enviar con prompt vacío o solo espacios en blanco no envía nada."""
        self.window.new_chat()
        mensajes_iniciales = len(self.window.current.messages)
        self.window.prompt.setPlainText("    ")
        self.window.send()

        self.assertIsNone(self.window._worker)
        self.assertEqual(len(self.window.current.messages), mensajes_iniciales)

    def test_main_window_envio_mensaje_valido_y_generacion_titulo(self):
        """Al enviar el primer mensaje se quita el estado vacío, se actualiza el título y se añade la burbuja."""
        self.window.new_chat()
        self.window.prompt.setPlainText("Nivel de aceite del motor")

        with patch("services.api.ChatWorker.start"):
            self.window.send()

            # El mensaje se agregó a la conversación
            self.assertEqual(len(self.window.current.messages), 1)
            self.assertEqual(self.window.current.messages[0].text, "Nivel de aceite del motor")

            # Título actualizado automáticamente sin truncar si <= 40 caracteres
            self.assertEqual(self.window.title_label.text(), "Nivel de aceite del motor")
            self.assertIsNone(self.window._empty)
            self.assertEqual(self.window.prompt.toPlainText(), "")
            self.assertFalse(self.window.btn_send.isEnabled())

    def test_main_window_envio_mensaje_largo_recorta_titulo_con_puntos_suspensivos(self):
        """Si el primer mensaje supera los 40 caracteres, el título se trunca en 40 caracteres y añade '…'."""
        self.window.new_chat()
        pregunta_larga = "Procedimiento completo de purga del circuito de refrigeración del sistema secundario"
        self.window.prompt.setPlainText(pregunta_larga)

        with patch("services.api.ChatWorker.start"):
            self.window.send()
            esperado = pregunta_larga[:40] + "…"
            self.assertEqual(self.window.title_label.text(), esperado)

    def test_main_window_recepcion_respuesta_elimina_typing_y_actualiza_chat(self):
        """Al recibir la respuesta del asistente, desaparece el typing, se añade la respuesta y se libera el botón."""
        conv = Conversation()
        self.window.conversations = [conv]
        self.window.current = conv
        self.window._typing = ChatMessage(None)
        self.window._insert_row(self.window._typing)
        self.window._set_busy(True)

        resp = Response(
            texto="Comprueba el nivel en frío.",
            estado=STATUS_OK,
            trace_id="t-100",
            conversacion_id="server-conv-888"
        )
        self.window._on_response(conv, resp)

        self.assertIsNone(self.window._typing)
        self.assertTrue(self.window.btn_send.isEnabled())
        self.assertEqual(conv.server_id, "server-conv-888")
        self.assertEqual(len(conv.messages), 1)
        self.assertEqual(conv.messages[0].text, "Comprueba el nivel en frío.")

    def test_main_window_filtro_enter_y_shift_enter(self):
        """El filtro de eventos envía con Enter sin shift y permite salto de línea con Shift+Enter."""
        llamadas_send = []
        filtro = _EnterToSend(lambda: llamadas_send.append(True))

        # Enter solo -> interceptado y envía
        ev_enter = QEvent(QEvent.KeyPress, Qt.Key_Return, 0)
        ret = filtro.eventFilter(None, ev_enter)
        self.assertTrue(ret)
        self.assertEqual(len(llamadas_send), 1)

        # Shift + Enter -> no interceptado (permite salto de línea)
        ev_shift_enter = QEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier)
        ret_shift = filtro.eventFilter(None, ev_shift_enter)
        self.assertFalse(ret_shift)
        self.assertEqual(len(llamadas_send), 1)

    def test_main_window_logout_bloqueado_si_ocupado(self):
        """Si hay una petición en curso, _logout no emite logged_out."""
        emisiones = []
        self.window.logged_out.connect(lambda: emisiones.append(True))

        self.window._worker = MagicMock()
        self.window._logout()
        self.assertEqual(len(emisiones), 0)

        # Sin trabajadores -> emite salida
        self.window._worker = None
        self.window._logout()
        self.assertEqual(len(emisiones), 1)

    def test_main_window_historial_sesion_caducada_emite_logout(self):
        """Si la carga del historial responde con session_expired=True, la ventana emite logged_out."""
        emisiones = []
        self.window.logged_out.connect(lambda: emisiones.append(True))

        res = api.HistoryResult(ok=False, session_expired=True, error=api.SESSION_EXPIRED)
        self.window._on_history(res)
        self.assertEqual(len(emisiones), 1)


# ==============================================================================
# 3. PRUEBAS DE COMPONENTES VISUALES (ChatMessage, SourceCard, ConversationItem)
# ==============================================================================
class TestComponentesVisuales(unittest.TestCase):
    """Comprueba el renderizado y formateo de los widgets modulares de la interfaz."""

    def test_chat_message_burbuja_usuario(self):
        """Un mensaje de usuario se renderiza en la burbuja 'bubbleUser' con texto exacto."""
        msg = Message(ROLE_USER, "Consulta técnica sobre el sensor de presión")
        w = ChatMessage(msg)

        self.assertEqual(w.bubble.objectName(), "bubbleUser")
        self.assertEqual(w.label.text(), "Consulta técnica sobre el sensor de presión")
        self.assertEqual(w.bubble.findChildren(SourceCard), [])

    def test_chat_message_burbuja_escribiendo(self):
        """Una fila sin mensaje representa el indicador de 'Buscando en la documentación…'."""
        w = ChatMessage(None)
        self.assertEqual(w.bubble.objectName(), "bubbleBot")
        self.assertIn("Buscando en la documentación", w.label.text())

    def test_chat_message_badges_estados_asistente(self):
        """Cada estado controlado del asistente muestra su correspondiente badge visual descriptivo."""
        estados_esperados = {
            STATUS_CLARIFY: "Necesito más datos",
            STATUS_NO_EVIDENCE: "Sin evidencia en la documentación",
            STATUS_OUT_OF_SCOPE: "Fuera de ámbito",
            STATUS_ERROR: "Error",
        }
        for estado, texto_badge in estados_esperados.items():
            with self.subTest(estado=estado):
                msg = Message(ROLE_BOT, "Texto de respuesta", status=estado)
                w = ChatMessage(msg)
                self.assertEqual(w.bubble.objectName(), "bubbleBot")
                self.assertEqual(w.bubble.property("status"), estado)

                # Comprobar que existe el badge con el texto esperado
                badges = [b for b in w.bubble.findChildren(None, "badge") if b.text() == texto_badge]
                self.assertEqual(len(badges), 1)
                self.assertEqual(badges[0].property("kind"), estado)

    def test_chat_message_renderizado_fuentes(self):
        """Si el mensaje contiene citas, se añade la sección de fuentes con sus tarjetas SourceCard."""
        fuentes = [
            Source("Manual_Taller", "4.2", 89, ["V1.1"], False, "c_89"),
            Source("Boletin_01", "Avisos", 2, ["V1.0"], True, "c_02"),
        ]
        msg = Message(ROLE_BOT, "Respuesta con citas", status=STATUS_OK, sources=fuentes)
        w = ChatMessage(msg)

        # Encabezado FUENTES presente
        titulos_fuentes = [lbl for lbl in w.bubble.findChildren(None, "sourcesTitle") if lbl.text() == "FUENTES"]
        self.assertEqual(len(titulos_fuentes), 1)

        # Se crearon dos tarjetas SourceCard
        cards = w.bubble.findChildren(SourceCard)
        self.assertEqual(len(cards), 2)

    def test_source_card_visualizacion_completa(self):
        """SourceCard muestra el documento y concatena sección, página y versiones."""
        s = Source("Manual_Transmision", "1.4", 42, ["V2.0", "V2.1"], False, "c_42")
        card = SourceCard(s)

        doc_lbl = card.findChild(None, "sourceDoc")
        self.assertIsNotNone(doc_lbl)
        self.assertEqual(doc_lbl.text(), "Manual_Transmision")

        meta_lbl = card.findChild(None, "sourceMeta")
        self.assertIsNotNone(meta_lbl)
        self.assertIn("sección 1.4", meta_lbl.text())
        self.assertIn("pág. 42", meta_lbl.text())
        self.assertIn("versiones V2.0, V2.1", meta_lbl.text())

    def test_source_card_marca_documento_obsoleto(self):
        """Si la fuente es obsoleta, muestra la etiqueta de documento sustituido."""
        s_vigente = Source("Manual_Vigente", obsoleto=False)
        self.assertIsNone(SourceCard(s_vigente).findChild(None, "sourceObsolete"))

        s_obsoleto = Source("Manual_Antiguo", obsoleto=True)
        card_obs = SourceCard(s_obsoleto)
        obs_lbl = card_obs.findChild(None, "sourceObsolete")
        self.assertIsNotNone(obs_lbl)
        self.assertIn("obsoleto", obs_lbl.text().lower())

    def test_conversation_item_formato_fecha(self):
        """_fmt formatea como 'Hoy HH:MM' para fechas de hoy y 'DD/MM/AAAA' para fechas anteriores."""
        ahora = datetime.now()
        iso_hoy = ahora.isoformat()
        self.assertTrue(_fmt(iso_hoy).startswith("Hoy "))

        fecha_pasada = ahora - timedelta(days=5)
        iso_pasada = fecha_pasada.isoformat()
        self.assertEqual(_fmt(iso_pasada), fecha_pasada.strftime("%d/%m/%Y"))

        self.assertEqual(_fmt(""), "")
        self.assertEqual(_fmt("fecha_invalida"), "")


# ==============================================================================
# 4. PRUEBAS DEL COORDINADOR DE APLICACIÓN (App en main.py)
# ==============================================================================
class TestAppFlow(unittest.TestCase):
    """Comprueba el ciclo de vida login -> chat -> logout -> login en Frontend/main.py."""

    def setUp(self):
        self._sleep_patcher = patch("time.sleep", return_value=None)
        self._sleep_patcher.start()
        session.clear()

        import importlib.util
        frontend_main_path = FRONTEND_DIR / "main.py"
        spec = importlib.util.spec_from_file_location("frontend_main", str(frontend_main_path))
        frontend_main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frontend_main)
        self.app_flow = frontend_main.App(QApplication([]))

    def tearDown(self):
        self._sleep_patcher.stop()
        session.clear()

    def test_app_inicio_muestra_login(self):
        """Al iniciar la aplicación, se muestra la ventana de inicio de sesión."""
        self.app_flow.start()
        self.assertTrue(self.app_flow.login._visible)
        self.assertIsNone(self.app_flow.chat)

    def test_app_flujo_login_a_chat_y_logout(self):
        """Al autenticarse se crea MainWindow y se guarda la sesión; al cerrar sesión se restaura el login."""
        # 1. Login exitoso
        auth_res = auth.AuthResult(ok=True, user="mecanico_jefe", token="jwt-tok-123", user_id="u-42")
        self.app_flow._on_login(auth_res)

        # Sesión establecida en memoria
        self.assertEqual(session.user, "mecanico_jefe")
        self.assertEqual(session.token, "jwt-tok-123")
        self.assertEqual(session.user_id, "u-42")

        # Ventana de chat activa y login oculto
        self.assertIsNotNone(self.app_flow.chat)
        self.assertEqual(self.app_flow.chat.username, "mecanico_jefe")
        self.assertTrue(self.app_flow.chat._visible)
        self.assertFalse(self.app_flow.login._visible)

        # 2. Cierre de sesión (logout)
        self.app_flow._on_logout()

        # Sesión vaciada
        self.assertIsNone(session.user)
        self.assertIsNone(session.token)
        self.assertEqual(session.user_id, "")

        # Chat destruido y login de nuevo visible
        self.assertIsNone(self.app_flow.chat)
        self.assertTrue(self.app_flow.login._visible)


if __name__ == "__main__":
    unittest.main()
