#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Pruebas Unitarias del Conector Clúster Legio (GVIS - Universidad de León)
=============================================================================
Valida:
  1. Resolución segura de API Key (env y archivo) sin exposición en logs/repr.
  2. Mapeo estricto de roles de modelo ('rapido', 'potente') y prohibición
     estricta de 'texto' y de nombres concretos de modelos ('qwen2.5:14b', etc.).
  3. Detección y manejo de excepciones de red (túnel SSH cerrado, HTTP 401/403, timeout).
  4. Formato de payload compatible OpenAI (temperature=0.0, max_tokens=512, stream=False).
  5. Integración con Agente 1 (intención con 'rapido', redactor con 'potente').
  6. Cortocircuito ante consultas sin evidencia o incompletas (ahorro de llamadas).
=============================================================================
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Agents.agente1.cliente_cluster import (
    ClienteClusterLegio,
    ROL_RAPIDO,
    ROL_POTENTE,
    ROLES_VALIDOS,
    TunelClusterError,
    AutenticacionClusterError,
    TimeoutClusterError,
    ModeloNoValidoError,
    resolver_api_key,
)
from Agents.agente1.core import Agente1, redactar_respuesta_con_verificacion, consultar_asistente


class TestResolucionApiKey(unittest.TestCase):
    """Verifica que la clave se resuelva correctamente sin exponerse."""

    def test_resolver_desde_variable_entorno(self):
        with patch.dict(os.environ, {"LLM_KEY": "mock_env_token_abc123"}):
            clave = resolver_api_key()
            self.assertEqual(clave, "mock_env_token_abc123")

    def test_resolver_desde_archivo(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            archivo_clave = Path(tmpdir) / "api_key"
            archivo_clave.write_text("mock_file_token_xyz789\n", encoding="utf-8")
            
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop("LLM_KEY", None)
                clave = resolver_api_key(ruta_archivo=archivo_clave)
                self.assertEqual(clave, "mock_file_token_xyz789")

    def test_no_expone_clave_en_repr(self):
        cliente = ClienteClusterLegio(api_key="mock_secret_key_dummy")
        representacion = repr(cliente)
        self.assertNotIn("mock_secret_key_dummy", representacion)
        self.assertIn("key_configurada=True", representacion)
        self.assertIn("localhost:4000", representacion)

    def test_sin_credenciales_devuelve_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LLM_KEY", None)
            with patch.object(Path, "is_file", return_value=False):
                clave = resolver_api_key()
                self.assertIsNone(clave)


class TestRolesModelosCluster(unittest.TestCase):
    """Verifica la asignación de roles obligatorios y el bloqueo de 'texto' y modelos fijos."""

    def setUp(self):
        self.cliente = ClienteClusterLegio(api_key="mock_dummy_key")

    def test_roles_admitidos(self):
        self.assertEqual(self.cliente.resolver_nombre_modelo(ROL_RAPIDO), "rapido")
        self.assertEqual(self.cliente.resolver_nombre_modelo(ROL_POTENTE), "potente")

    def test_rol_texto_prohibido_lanza_excepcion(self):
        with self.assertRaises(ModeloNoValidoError) as ctx:
            self.cliente.resolver_nombre_modelo("texto")
        self.assertIn("no está permitido", str(ctx.exception).lower())

    def test_nombres_concretos_prohibidos_lanzan_excepcion(self):
        for nombre in ("qwen2.5:14b", "qwen2.5:3b", "qwen3.6-27b", "gpt-oss-20b", "llama3"):
            with self.subTest(modelo=nombre):
                with self.assertRaises(ModeloNoValidoError) as ctx:
                    self.cliente.resolver_nombre_modelo(nombre)
                self.assertIn("no se permite el uso de nombres concretos", str(ctx.exception).lower())

    def test_rol_desconocido_lanza_excepcion(self):
        with self.assertRaises(ModeloNoValidoError) as ctx:
            self.cliente.resolver_nombre_modelo("inventado_v1")
        self.assertIn("no reconocido", str(ctx.exception).lower())

    def test_personalizacion_nombres_modelo_por_entorno(self):
        with patch.dict(os.environ, {"LLM_ROL_RAPIDO": "rapido_custom", "LLM_ROL_POTENTE": "potente_custom"}):
            c = ClienteClusterLegio(api_key="mock_dummy_key")
            self.assertEqual(c.resolver_nombre_modelo("rapido"), "rapido_custom")
            self.assertEqual(c.resolver_nombre_modelo("potente"), "potente_custom")


class TestManejoExcepcionesRed(unittest.TestCase):
    """Verifica la gestión explícita de errores del clúster y del túnel SSH."""

    def setUp(self):
        self.cliente = ClienteClusterLegio(api_key="mock_dummy_key", timeout_s=5.0)

    @patch("Agents.agente1.cliente_cluster.OpenAI", None)
    @patch("urllib.request.urlopen")
    def test_tunel_cerrado_lanza_tunel_cluster_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("[WinError 10061] No se puede establecer una conexión")

        with self.assertRaises(TunelClusterError) as ctx:
            self.cliente.consultar([{"role": "user", "content": "hola"}], rol="rapido")
        
        mensaje = str(ctx.exception)
        self.assertIn("4000", mensaje)
        self.assertIn("ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97", mensaje)

    @patch("Agents.agente1.cliente_cluster.OpenAI", None)
    @patch("urllib.request.urlopen")
    def test_error_autenticacion_401_lanza_autenticacion_error(self, mock_urlopen):
        import urllib.error
        error_http = urllib.error.HTTPError("http://localhost:4000/v1", 401, "Unauthorized", {}, None)
        mock_urlopen.side_effect = error_http

        with self.assertRaises(AutenticacionClusterError) as ctx:
            self.cliente.consultar([{"role": "user", "content": "hola"}], rol="rapido")
        self.assertIn("401", str(ctx.exception))

    @patch("Agents.agente1.cliente_cluster.OpenAI", None)
    @patch("urllib.request.urlopen")
    def test_timeout_lanza_timeout_cluster_error(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")

        with self.assertRaises(TimeoutClusterError):
            self.cliente.consultar([{"role": "user", "content": "hola"}], rol="rapido")


class TestPayloadYFormatoHttp(unittest.TestCase):
    """Verifica que el payload enviado cumpla estrictamente con temperature=0.0, max_tokens=512, stream=False."""

    @patch("Agents.agente1.cliente_cluster.OpenAI", None)
    @patch("urllib.request.urlopen")
    def test_payload_estricto_y_headers(self, mock_urlopen):
        respuesta_mock = MagicMock()
        respuesta_mock.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Respuesta simulada con rol rapido"}}]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = respuesta_mock

        cliente = ClienteClusterLegio(api_key="mock_auth_token_sample")
        resultado = cliente.consultar(
            [{"role": "user", "content": "hola"}],
            rol="rapido",
            temperature=0.0,
            max_tokens=512,
        )

        self.assertEqual(resultado, "Respuesta simulada con rol rapido")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.headers.get("Authorization"), "Bearer mock_auth_token_sample")
        self.assertEqual(req.headers.get("Content-type"), "application/json")

        cuerpo = json.loads(req.data.decode("utf-8"))
        self.assertEqual(cuerpo["temperature"], 0.0)
        self.assertEqual(cuerpo["max_tokens"], 512)
        self.assertEqual(cuerpo["stream"], False)
        self.assertEqual(cuerpo["model"], "rapido")


class TestIntegracionAgente1Cluster(unittest.TestCase):
    """Verifica que Agente 1 utilice correctamente el conector del clúster."""

    def test_agente1_usa_roles_rapido_y_potente(self):
        mock_cliente_cluster = MagicMock()
        mock_cliente_cluster.modelo_rapido = "rapido"
        mock_cliente_cluster.modelo_potente = "potente"
        mock_cliente_cluster.base_url = "http://localhost:4000/v1"
        mock_cliente_cluster.consultar.return_value = json.dumps({
            "intencion": "especificacion",
            "texto_busqueda": "termostato apertura temperatura",
            "filtros": {"componente": "refrigeracion", "version": "V1.1", "codigos": []}
        })

        agente = Agente1(cliente_cluster=mock_cliente_cluster)
        self.assertEqual(agente.modelo, "rapido")
        self.assertEqual(agente.modelo_redactor, "potente")

        # 1. Consulta para intención -> debe pedir rol 'rapido'
        res = agente.procesar_consulta("temperatura apertura termostato V1.1")
        self.assertEqual(res["estado"], "valida")
        mock_cliente_cluster.consultar.assert_called()
        ultimos_kwargs = mock_cliente_cluster.consultar.call_args.kwargs
        self.assertEqual(ultimos_kwargs["rol"], "rapido")

    def test_redaccion_usa_rol_potente(self):
        mock_cliente_cluster = MagicMock()
        mock_cliente_cluster.modelo_rapido = "rapido"
        mock_cliente_cluster.modelo_potente = "potente"
        mock_cliente_cluster.base_url = "http://localhost:4000/v1"
        
        chunk = {
            "chunk_id": "HTM240-MAN-001@1.1_p10_man_001_01",
            "texto": "El termostato abre a 87 grados.",
            "metadata": {"documento": "Manual", "pagina": 10, "version": "V1.1"}
        }
        
        mock_cliente_cluster.consultar.return_value = (
            "El termostato abre a 87 grados. [HTM240-MAN-001@1.1_p10_man_001_01]"
        )

        agente = Agente1(cliente_cluster=mock_cliente_cluster)
        resultado = redactar_respuesta_con_verificacion(
            "temperatura termostato",
            [chunk],
            agente
        )

        self.assertEqual(resultado["estado"], "respuesta")
        self.assertIn("87 grados", resultado["texto"])
        self.assertEqual(resultado["fuentes"], ["HTM240-MAN-001@1.1_p10_man_001_01"])
        
        # Debe haber llamado con rol 'potente'
        ultimos_kwargs = mock_cliente_cluster.consultar.call_args.kwargs
        self.assertEqual(ultimos_kwargs["rol"], "potente")

    def test_cortocircuito_sin_evidencias_no_invoca_llm(self):
        mock_cliente_cluster = MagicMock()
        agente = Agente1(cliente_cluster=mock_cliente_cluster)

        # Si pasamos evidencias vacías directamente a redacción
        resultado = redactar_respuesta_con_verificacion("pregunta", [], agente)
        self.assertEqual(resultado["estado"], "sin_evidencia")
        # El LLM no debe haber sido llamado ni una sola vez
        mock_cliente_cluster.consultar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
