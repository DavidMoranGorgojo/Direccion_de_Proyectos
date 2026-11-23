"""Pruebas de la configuración centralizada del Frontend (Frontend/config.py)."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Reutiliza el arranque de las pruebas del Frontend (sys.path y shim de PySide6) antes de
# importar los servicios.
try:
    from .test_conexion_simulada import BaseFrontendTestCase, api, auth
except ImportError:                                   # unittest discover -s Test/test_Frontend
    from test_conexion_simulada import BaseFrontendTestCase, api, auth

import config


class TestLecturaEnv(unittest.TestCase):
    """Lectura de archivos .env y prioridad entre fuentes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_valores_por_defecto(self):
        s = config.load_settings(environ={}, env_files=())
        self.assertEqual(s, config.DEFAULTS)
        self.assertEqual(s["ARSOFT_CONSULTA_PATH"], "/consulta")
        self.assertEqual(s["ARSOFT_LOGIN_PATH"], "/auth/login")
        self.assertEqual(s["ARSOFT_HISTORIAL_PATH"], "/chats")
        self.assertEqual(s["ARSOFT_TIMEOUT_S"], "60")

    def test_parseo_env(self):
        path = self._env(".env", "\n".join([
            "# comentario",
            "",
            "ARSOFT_API_URL=https://api.ejemplo.com/",
            'export ARSOFT_MODO="real"',
            "ARSOFT_TIMEOUT_S=30  # segundos",
            "POSTGRES_PASSWORD=no-se-lee",
            "linea sin igual",
        ]))
        valores = config.parse_env_file(path)
        self.assertEqual(valores, {
            "ARSOFT_API_URL": "https://api.ejemplo.com/",
            "ARSOFT_MODO": "real",
            "ARSOFT_TIMEOUT_S": "30",
        })

    def test_archivo_inexistente(self):
        self.assertEqual(config.parse_env_file(self.dir / "no_existe.env"), {})

    def test_prioridad_entorno_frontend_raiz(self):
        frontend = self._env("frontend.env",
                             "ARSOFT_API_URL=https://frontend\nARSOFT_TIMEOUT_S=10\n")
        raiz = self._env("raiz.env", "ARSOFT_API_URL=https://raiz\nARSOFT_TIMEOUT_S=20\n"
                                     "ARSOFT_HISTORIAL_PATH=/historial\n")
        s = config.load_settings(environ={"ARSOFT_TIMEOUT_S": "5"}, env_files=(frontend, raiz))
        self.assertEqual(s["ARSOFT_TIMEOUT_S"], "5")              # entorno > Frontend/.env
        self.assertEqual(s["ARSOFT_API_URL"], "https://frontend")  # Frontend/.env > raíz
        self.assertEqual(s["ARSOFT_HISTORIAL_PATH"], "/historial")  # solo en la raíz
        self.assertEqual(s["ARSOFT_LOGIN_PATH"], "/auth/login")    # valor por defecto


class TestNormalizacion(unittest.TestCase):
    """Conversión de los valores leídos."""

    def test_timeout(self):
        self.assertEqual(config._timeout("15"), 15.0)
        self.assertEqual(config._timeout("2.5"), 2.5)
        for invalido in ("", "abc", "0", "-3"):
            self.assertEqual(config._timeout(invalido), 60.0, invalido)

    def test_rutas(self):
        self.assertEqual(config._path("chats", "/x"), "/chats")
        self.assertEqual(config._path("/chats", "/x"), "/chats")
        self.assertEqual(config._path("  ", "/x"), "/x")

    def test_modo(self):
        self.assertEqual(config._modo("Real"), config.MODO_REAL)
        self.assertEqual(config._modo("simulado"), config.MODO_SIMULADO)
        self.assertEqual(config._modo(""), config.MODO_AUTO)
        self.assertEqual(config._modo("otro"), config.MODO_AUTO)

    def test_flags(self):
        for si in ("1", "true", "SI", "sí"):
            self.assertTrue(config._flag(si), si)
        for no in ("", "0", "false", "no"):
            self.assertFalse(config._flag(no), no)


class TestModoEnServicios(BaseFrontendTestCase):
    """El modo configurado decide si se usa el simulador o el Backend."""

    def test_modo_automatico(self):
        self.assertTrue(api.is_mock())
        api.API_URL = "https://api.ejemplo.com"
        self.assertFalse(api.is_mock())

    def test_modo_simulado_forzado_con_url(self):
        api.API_URL = "https://api.ejemplo.com"
        api.MODO = config.MODO_SIMULADO
        self.assertTrue(api.is_mock())

    def test_modo_real_sin_url_no_cae_en_simulado(self):
        api.MODO = config.MODO_REAL
        self.assertFalse(api.is_mock())
        with self.assertRaises(api.ConfigError):
            api.call("GET", api.HISTORIAL_PATH)

    def test_modo_real_sin_url_muestra_motivo_en_login(self):
        api.MODO = config.MODO_REAL
        res = auth.login("demo", "demo1234")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, api.MISSING_URL)

    def test_http_no_local_bloqueado(self):
        api.API_URL = "http://api.ejemplo.com"
        with patch.object(config, "ALLOW_HTTP", False):
            res = auth.login("demo", "demo1234")
        self.assertFalse(res.ok)
        self.assertIn("HTTPS", res.error)


if __name__ == "__main__":
    unittest.main()
