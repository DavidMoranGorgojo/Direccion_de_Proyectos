"""Sesión caducada durante una consulta: la ventana avisa y cierra la sesión sola (como con el historial).

Necesita Qt real. test_conexion_simulada.py sustituye PySide6.QtCore por un shim en el mismo proceso;
si es el caso, este módulo se relanza en un proceso aparte para no depender del orden de las pruebas.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[2]
QT_CON_SHIM = "PySide6.QtCore" in sys.modules and not hasattr(sys.modules["PySide6.QtCore"], "__file__")

if not QT_CON_SHIM:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(RAIZ / "Frontend"))
    from PySide6.QtWidgets import QApplication, QMessageBox

    from models.response import Response
    from services import api
    from views.main_window import MainWindow

    _app = QApplication.instance() or QApplication([])


@unittest.skipIf(QT_CON_SHIM, "Qt sustituido por el shim: se comprueba en un proceso aparte")
class SesionCaducadaEnConsulta(unittest.TestCase):
    def setUp(self):
        with patch.object(api, "API_URL", ""):          # modo simulado: sin red
            self.win = MainWindow("demo")
        if self.win._hist_worker is not None:
            self.win._hist_worker.wait(3000)
        _app.processEvents()
        self.addCleanup(self.win.close)
        self.cerrada = []
        self.win.logged_out.connect(lambda: self.cerrada.append(True))
        self.conv = self.win.current

    def test_sesion_caducada_avisa_y_cierra_sesion(self):
        resp = Response.error(api.SESSION_EXPIRED, "sesion_caducada")
        with patch.object(QMessageBox, "information") as aviso:
            self.win._on_response(self.conv, resp)
        aviso.assert_called_once()
        self.assertEqual(self.cerrada, [True])

    def test_otros_errores_no_cierran_sesion(self):
        with patch.object(QMessageBox, "information") as aviso:
            self.win._on_response(self.conv, Response.error())
            self.win._on_response(self.conv, Response.error(api.TOO_MANY_REQUESTS, "demasiadas_consultas"))
        aviso.assert_not_called()
        self.assertEqual(self.cerrada, [])


@unittest.skipUnless(QT_CON_SHIM, "Qt real en este proceso: se ejecuta directamente")
class SesionCaducadaEnProcesoAparte(unittest.TestCase):
    def test_ventana_con_qt_real(self):
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        env["PYTHONPATH"] = os.pathsep.join(
            [str(RAIZ / "shared"), str(RAIZ), str(RAIZ / "Frontend"), env.get("PYTHONPATH", "")])
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", str(Path(__file__))],
                           cwd=RAIZ, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
