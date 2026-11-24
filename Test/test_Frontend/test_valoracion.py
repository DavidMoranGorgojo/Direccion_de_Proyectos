"""
Pruebas de la valoración de respuestas (👍 / 👎) y de los mensajes de error de login e historial.
===============================================================================================
- Capa de red: POST /valoracion (cuerpo, ruta y errores 401, 403, 404, 422, 429, 5xx, sin conexión).
- Interfaz: los botones solo aparecen en respuestas con estado "respuesta" y trace_id; marcar,
  cambiar la valoración, volver al valor anterior si falla y cierre de sesión si caduca.
- Errores nuevos de login (403, 500) y de historial (429, 500).

Ejecución:
    pytest Test/test_Frontend/test_valoracion.py
"""

from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
for path_dir in (str(ROOT_DIR / "Frontend"), str(ROOT_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from Test.test_Frontend import qt_test_harness

qt_test_harness.setup_qt_harness()

import config  # noqa: E402
from components.chat_message import ChatMessage  # noqa: E402
from models.conversation import Conversation  # noqa: E402
from models.message import Message, ROLE_BOT, ROLE_USER  # noqa: E402
from models.response import (STATUS_CLARIFY, STATUS_ERROR, STATUS_OK)  # noqa: E402
from services import api, auth, session  # noqa: E402
from Test.test_Frontend.test_conexion_simulada import BaseFrontendTestCase  # noqa: E402
from views.main_window import MainWindow  # noqa: E402


# ==============================================================================
# 1. CAPA DE RED: POST /valoracion
# ==============================================================================
class TestEnvioValoracion(BaseFrontendTestCase):

    def test_ruta_por_defecto(self):
        self.assertEqual(config.DEFAULTS["ARSOFT_VALORACION_PATH"], "/valoracion")
        self.assertEqual(api.VALORACION_PATH, config.VALORACION_PATH)

    def test_cuerpo_y_ruta_enviados(self):
        with patch("services.api.call", return_value=(200, {"trace_id": "t-1", "util": True})) as m:
            api.send_rating("t-1", True)
        m.assert_called_once_with("POST", api.VALORACION_PATH, {"trace_id": "t-1", "util": True})

    def test_valoracion_correcta_devuelve_el_valor_del_servidor(self):
        for util in (True, False):
            with patch("services.api.call", return_value=(200, {"trace_id": "t-1", "util": util})):
                res = api.send_rating("t-1", util)
            self.assertTrue(res.ok)
            self.assertIs(res.util, util)
            self.assertEqual(res.trace_id, "t-1")

    def test_simulador_acepta_valoracion(self):
        res = api.send_rating("t-demo", False)
        self.assertTrue(res.ok)
        self.assertIs(res.util, False)

    def test_simulador_rechaza_cuerpo_invalido(self):
        status, _ = api.call("POST", api.VALORACION_PATH, {"trace_id": "", "util": True})
        self.assertEqual(status, 422)

    def test_401_y_403_son_sesion_caducada(self):
        for status in (401, 403):
            with patch("services.api.call", return_value=(status, None)):
                res = api.send_rating("t-1", True)
            self.assertFalse(res.ok)
            self.assertTrue(res.session_expired)
            self.assertEqual(res.error, api.SESSION_EXPIRED)

    def test_404_respuesta_no_encontrada(self):
        with patch("services.api.call", return_value=(404, {"codigo_error": "respuesta_no_encontrada"})):
            res = api.send_rating("t-1", True)
        self.assertFalse(res.ok)
        self.assertFalse(res.session_expired)
        self.assertEqual(res.error, api.RATING_NOT_FOUND)

    def test_429_demasiadas_valoraciones(self):
        with patch("services.api.call", return_value=(429, {"codigo_error": "demasiadas_valoraciones"})):
            res = api.send_rating("t-1", True)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, api.RATING_TOO_MANY)

    def test_422_500_y_503_dan_mensaje_generico(self):
        for status in (422, 500, 503):
            with patch("services.api.call", return_value=(status, None)):
                res = api.send_rating("t-1", True)
            self.assertFalse(res.ok)
            self.assertFalse(res.session_expired)
            self.assertEqual(res.error, api.RATING_FAILED)

    def test_200_sin_util_booleano_es_error(self):
        for body in (None, {"trace_id": "t-1"}, {"trace_id": "t-1", "util": "true"}):
            with patch("services.api.call", return_value=(200, body)):
                self.assertFalse(api.send_rating("t-1", True).ok)

    def test_sin_conexion(self):
        with patch("services.api.call", side_effect=api.ConnectionFailed("sin red")):
            res = api.send_rating("t-1", True)
        self.assertFalse(res.ok)
        self.assertEqual(res.error, api.RATING_FAILED)

    def test_error_de_configuracion_se_muestra(self):
        with patch("services.api.call", side_effect=api.ConfigError(api.MISSING_URL)):
            res = api.send_rating("t-1", True)
        self.assertEqual(res.error, api.MISSING_URL)


# ==============================================================================
# 2. MENSAJES DE ERROR DE LOGIN E HISTORIAL
# ==============================================================================
class TestErroresLoginEHistorial(BaseFrontendTestCase):

    def test_login_403(self):
        with patch("services.api.call", return_value=(403, None)):
            res = auth.login("demo", "demo1234")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, auth.NO_PERMISSION)

    def test_login_500(self):
        with patch("services.api.call", return_value=(500, None)):
            res = auth.login("demo", "demo1234")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, auth.SERVER_ERROR)

    def test_historial_429(self):
        with patch("services.api.call", return_value=(429, None)):
            hist = api.fetch_history()
        self.assertFalse(hist.ok)
        self.assertFalse(hist.session_expired)
        self.assertEqual(hist.error, api.HISTORY_TOO_MANY)

    def test_historial_500(self):
        with patch("services.api.call", return_value=(500, None)):
            hist = api.fetch_history()
        self.assertFalse(hist.ok)
        self.assertEqual(hist.error, api.HISTORY_SERVER_ERROR)


# ==============================================================================
# 3. BOTONES 👍 / 👎 EN LA BURBUJA (ChatMessage)
# ==============================================================================
def _reset_signals() -> None:
    """En el arnés sin Qt las señales declaradas en la clase se comparten entre instancias: se vacían
    para que cada prueba parta de cero. Con PySide6 real cada objeto tiene las suyas."""
    for signal in (api.RatingWorker.done, ChatMessage.rating_requested, MainWindow.logged_out):
        if hasattr(signal, "_slots"):
            signal._slots.clear()


def _bot(status=STATUS_OK, trace_id="t-1", rating=None) -> Message:
    return Message(ROLE_BOT, "Comprueba el nivel en frío.", status, trace_id, rating=rating)


class TestBotonesValoracion(unittest.TestCase):

    def setUp(self):
        _reset_signals()

    def test_respuesta_con_trace_id_tiene_botones(self):
        w = ChatMessage(_bot())
        self.assertIsNotNone(w.btn_up)
        self.assertIsNotNone(w.btn_down)
        self.assertFalse(w.btn_up.isChecked())
        self.assertFalse(w.btn_down.isChecked())

    def test_no_hay_botones_fuera_de_estado_respuesta(self):
        self.assertIsNone(ChatMessage(_bot(status=STATUS_CLARIFY)).btn_up)
        self.assertIsNone(ChatMessage(_bot(status=STATUS_ERROR)).btn_up)

    def test_no_hay_botones_sin_trace_id(self):
        self.assertIsNone(ChatMessage(_bot(trace_id="")).btn_up)

    def test_no_hay_botones_en_usuario_ni_en_typing(self):
        self.assertIsNone(ChatMessage(Message(ROLE_USER, "hola", trace_id="t-1")).btn_up)
        self.assertIsNone(ChatMessage(None).btn_up)

    def test_se_muestra_la_valoracion_guardada(self):
        w = ChatMessage(_bot(rating=False))
        self.assertFalse(w.btn_up.isChecked())
        self.assertTrue(w.btn_down.isChecked())

    def test_set_rating_marca_solo_el_elegido(self):
        w = ChatMessage(_bot())
        w.set_rating(True)
        self.assertTrue(w.btn_up.isChecked())
        self.assertFalse(w.btn_down.isChecked())
        w.set_rating(None)
        self.assertFalse(w.btn_up.isChecked() or w.btn_down.isChecked())

    def test_error_discreto_se_muestra_y_se_oculta(self):
        w = ChatMessage(_bot())
        self.assertFalse(w.rating_error._visible)
        w.show_rating_error("No se pudo enviar tu valoración. Inténtalo de nuevo.")
        self.assertTrue(w.rating_error._visible)
        self.assertIn("No se pudo enviar", w.rating_error.text())
        w.clear_rating_error()
        self.assertFalse(w.rating_error._visible)
        self.assertEqual(w.rating_error.text(), "")


# ==============================================================================
# 4. VALORAR DESDE LA VENTANA (MainWindow)
# ==============================================================================
class TestValorarEnVentana(BaseFrontendTestCase):

    def setUp(self):
        super().setUp()
        _reset_signals()
        self.window = MainWindow("operario_taller")
        self.msg = _bot()
        conv = Conversation()
        conv.messages.append(self.msg)
        self.window.conversations = [conv]
        self.window.current = None
        self.window._select(conv.id)
        self.row = self.window._rows[-1]
        self.assertIsNotNone(self.row.btn_up)

    def test_valoracion_correcta_queda_guardada_y_marcada(self):
        with patch("services.api.call", return_value=(200, {"trace_id": "t-1", "util": True})) as m:
            self.window._rate(self.row, self.msg, True)
        m.assert_called_once_with("POST", api.VALORACION_PATH, {"trace_id": "t-1", "util": True})
        self.assertIs(self.msg.rating, True)
        self.assertTrue(self.row.btn_up.isChecked())
        self.assertTrue(self.row.btn_up.isEnabled() and self.row.btn_down.isEnabled())
        self.assertEqual(self.window._rating_workers, [])

    def test_se_puede_cambiar_la_valoracion(self):
        with patch("services.api.call", side_effect=[(200, {"trace_id": "t-1", "util": True}),
                                                     (200, {"trace_id": "t-1", "util": False})]) as m:
            self.window._rate(self.row, self.msg, True)
            self.window._rate(self.row, self.msg, False)
        self.assertEqual(m.call_count, 2)
        self.assertIs(self.msg.rating, False)
        self.assertTrue(self.row.btn_down.isChecked())
        self.assertFalse(self.row.btn_up.isChecked())

    def test_repetir_el_mismo_valor_no_envia_nada(self):
        self.msg.rating = True
        with patch("services.api.call") as m:
            self.window._rate(self.row, self.msg, True)
        m.assert_not_called()

    def test_si_falla_vuelve_al_valor_anterior_y_muestra_texto(self):
        self.msg.rating = True
        self.row.set_rating(True)
        with patch("services.api.call", return_value=(500, None)):
            self.window._rate(self.row, self.msg, False)
        self.assertIs(self.msg.rating, True)
        self.assertTrue(self.row.btn_up.isChecked())
        self.assertFalse(self.row.btn_down.isChecked())
        self.assertTrue(self.row.btn_up.isEnabled() and self.row.btn_down.isEnabled())
        self.assertTrue(self.row.rating_error._visible)
        self.assertEqual(self.row.rating_error.text(), api.RATING_FAILED)

    def test_un_nuevo_intento_borra_el_error_anterior(self):
        with patch("services.api.call", return_value=(429, None)):
            self.window._rate(self.row, self.msg, True)
        self.assertTrue(self.row.rating_error._visible)
        with patch("services.api.call", return_value=(200, {"trace_id": "t-1", "util": True})):
            self.window._rate(self.row, self.msg, True)
        self.assertFalse(self.row.rating_error._visible)
        self.assertIs(self.msg.rating, True)

    def test_sesion_caducada_cierra_sesion(self):
        emisiones = []
        self.window.logged_out.connect(lambda: emisiones.append(True))
        with patch("services.api.call", return_value=(401, None)):
            self.window._rate(self.row, self.msg, True)
        self.assertEqual(len(emisiones), 1)
        self.assertIsNone(self.msg.rating)

    def test_la_valoracion_sobrevive_al_cambiar_de_chat(self):
        with patch("services.api.call", return_value=(200, {"trace_id": "t-1", "util": False})):
            self.window._rate(self.row, self.msg, False)
        otro = Conversation()
        self.window.conversations.append(otro)
        self.window._select(otro.id)
        self.window._select(self.window.conversations[0].id)
        fila = self.window._rows[-1]
        self.assertTrue(fila.btn_down.isChecked())


if __name__ == "__main__":
    unittest.main()
