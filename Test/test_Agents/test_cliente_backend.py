#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Sistema ThermoDrive HTM-240
Batería de Pruebas Automatizadas para el Cliente de Backend (A1-08)
Contratos: CTR-003 (Registro) y CTR-006 / CTR-007 (Historial)
=============================================================================
Responsable: Marco Barranco (Agente 1)
"""

import os
import sys
import json
import time
import unittest
from pathlib import Path

# Asegurar importación desde la raíz del repositorio
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Agents.agente1.cliente_backend import ClienteBackendAgentes
from Agents.agente1.simulador_backend import ServidorSimuladorBackend, ESTADO_GLOBAL


class TestClienteBackendAgentes(unittest.TestCase):
    """Suite de pruebas unitarias y de integración para el Cliente de Backend."""

    TEST_PORT = 8098
    TEST_URL = f"http://127.0.0.1:{TEST_PORT}"
    RUTA_OFFLINE_TEST = Path("test_offline_temp.jsonl")

    @classmethod
    def setUpClass(cls):
        cls.simulador = ServidorSimuladorBackend(port=cls.TEST_PORT)
        cls.simulador.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.simulador.stop()

    def setUp(self):
        ESTADO_GLOBAL.reset()
        if self.RUTA_OFFLINE_TEST.exists():
            self.RUTA_OFFLINE_TEST.unlink()
        self.cliente = ClienteBackendAgentes(
            base_url=self.TEST_URL,
            ruta_offline=str(self.RUTA_OFFLINE_TEST),
            timeout=1.0
        )

    def tearDown(self):
        if self.RUTA_OFFLINE_TEST.exists():
            self.RUTA_OFFLINE_TEST.unlink()

    def test_01_esquema_formal_ctr003(self):
        """Valida que formatear_registro_ctr003 genera todos los campos obligatorios del contrato."""
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-abc123",
            conversacion_id="c-0001",
            pregunta_original="par de apriete culata Golf 1.6",
            pregunta_limpia="par de apriete culata Golf 1.6",
            entidades={"componente": "culata", "version": "V1.1"},
            clasificacion="valida",
            query={"texto_busqueda": "culata apriete", "filtros": {"componente": "culata"}},
            estado_agente2="suficiente",
            chunks_usados=["chunk_01"],
            scores=[0.95],
            estado_respuesta="respuesta",
            respuesta="Fase 1 a 40 Nm [chunk_01].",
            citas_verificadas=True,
            latencia_ms=1250,
            modelo="qwen2.5:14b",
            version_prompt="v1.2"
        )

        campos_obligatorios = [
            "trace_id", "conversacion_id", "marca_tiempo", "pregunta_original",
            "pregunta_limpia", "entidades", "clasificacion", "query", "estado_agente2",
            "chunks_usados", "scores", "estado_respuesta", "respuesta",
            "citas_verificadas", "latencia_ms", "modelo", "version_prompt", "feedback"
        ]
        for c in campos_obligatorios:
            self.assertIn(c, reg, f"Falta el campo obligatorio CTR-003: {c}")

        self.assertEqual(reg["trace_id"], "t-abc123")
        self.assertEqual(reg["chunks_usados"], ["chunk_01"])
        self.assertAlmostEqual(reg["scores"][0], 0.95)
        self.assertTrue(reg["citas_verificadas"])

    def test_02_registro_online_post_registros_201(self):
        """Verifica que el registro se envía a POST /registros y devuelve HTTP 201."""
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-test01",
            conversacion_id="c-001",
            pregunta_original="test online",
            pregunta_limpia="test online",
            entidades={},
            clasificacion="valida",
            query={},
            estado_agente2="suficiente",
            chunks_usados=["c1"],
            scores=[0.9],
            estado_respuesta="respuesta",
            respuesta="ok",
            citas_verificadas=True,
            latencia_ms=100
        )

        res = self.cliente.registrar_turno(reg)
        self.assertTrue(res["enviado"])
        self.assertFalse(res["offline"])
        self.assertEqual(res["status_code"], 201)
        self.assertFalse(self.RUTA_OFFLINE_TEST.exists())

    def test_03_idempotencia_trace_id_200(self):
        """El reenvío del mismo trace_id debe retornar HTTP 200 sin duplicar registros."""
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-idempotente",
            conversacion_id="c-001",
            pregunta_original="test idempotencia",
            pregunta_limpia="test idempotencia",
            entidades={},
            clasificacion="valida",
            query={},
            estado_agente2="suficiente",
            chunks_usados=["c1"],
            scores=[0.85],
            estado_respuesta="respuesta",
            respuesta="ok",
            citas_verificadas=True,
            latencia_ms=50
        )

        res1 = self.cliente.registrar_turno(reg)
        self.assertEqual(res1["status_code"], 201)

        res2 = self.cliente.registrar_turno(reg)
        self.assertEqual(res2["status_code"], 200)
        self.assertEqual(len(ESTADO_GLOBAL.registros), 1)

    def test_04_error_400_no_se_guarda_en_offline(self):
        """Un error HTTP 400 (datos inválidos) NO debe guardarse en la cola offline para evitar bucles infinitos."""
        ESTADO_GLOBAL.simular_400 = True
        reg = {"trace_id": "t-error400", "campo_invalido": True}

        res = self.cliente.registrar_turno(reg)
        self.assertFalse(res["enviado"])
        self.assertFalse(res["offline"], "Un error 400 NO debe activar contingencia offline")
        self.assertEqual(res["status_code"], 400)
        self.assertFalse(self.RUTA_OFFLINE_TEST.exists(), "No debe crearse archivo offline ante HTTP 400")
        ESTADO_GLOBAL.simular_400 = False

    def test_05_error_503_activa_contingencia_offline(self):
        """Un error HTTP 503 (servidor caído) sí debe activar contingencia guardando en JSONL."""
        ESTADO_GLOBAL.simular_503 = True
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-503",
            conversacion_id="c-001",
            pregunta_original="test 503",
            pregunta_limpia="test 503",
            entidades={},
            clasificacion="valida",
            query={},
            estado_agente2="suficiente",
            chunks_usados=["c1"],
            scores=[0.8],
            estado_respuesta="respuesta",
            respuesta="ok",
            citas_verificadas=True,
            latencia_ms=50
        )

        res = self.cliente.registrar_turno(reg)
        self.assertFalse(res["enviado"])
        self.assertTrue(res["offline"])
        self.assertTrue(self.RUTA_OFFLINE_TEST.exists())

        with open(self.RUTA_OFFLINE_TEST, "r", encoding="utf-8") as f:
            lineas = f.readlines()
        self.assertEqual(len(lineas), 1)
        guardado = json.loads(lineas[0])
        self.assertEqual(guardado["trace_id"], "t-503")
        ESTADO_GLOBAL.simular_503 = False

    def test_06_resiliencia_conexion_caida(self):
        """Si el backend no está levantado, el cliente no bloquea y guarda offline."""
        cliente_caido = ClienteBackendAgentes(
            base_url="http://127.0.0.1:9997",
            ruta_offline=str(self.RUTA_OFFLINE_TEST),
            timeout=0.3
        )
        reg = {"trace_id": "t-caido", "pregunta_original": "consulta"}

        res = cliente_caido.registrar_turno(reg)
        self.assertFalse(res["enviado"])
        self.assertTrue(res["offline"])
        self.assertTrue(self.RUTA_OFFLINE_TEST.exists())

    def test_07_sincronizacion_pendientes_usa_post_registros(self):
        """sincronizar_pendientes reenvía los acumulados a POST /registros y limpia el archivo."""
        with open(self.RUTA_OFFLINE_TEST, "w", encoding="utf-8") as f:
            f.write(json.dumps({"trace_id": "t-pend1", "pregunta_original": "p1"}) + "\n")
            f.write(json.dumps({"trace_id": "t-pend2", "pregunta_original": "p2"}) + "\n")

        res = self.cliente.sincronizar_pendientes()
        self.assertEqual(res["procesados"], 2)
        self.assertEqual(res["enviados"], 2)
        self.assertEqual(res["pendientes"], 0)
        self.assertIn("t-pend1", ESTADO_GLOBAL.registros)
        self.assertIn("t-pend2", ESTADO_GLOBAL.registros)
        self.assertFalse(self.RUTA_OFFLINE_TEST.exists())

    def test_08_crear_chat_falla_sin_inventar_id(self):
        """Si el backend está caído, crear_chat debe lanzar excepción en lugar de inventar un ID falso con time.time()."""
        cliente_caido = ClienteBackendAgentes(
            base_url="http://127.0.0.1:9997",
            timeout=0.3
        )
        with self.assertRaises(ConnectionError):
            cliente_caido.crear_chat("Chat de prueba")

    def test_09_historial_chat_completo(self):
        """Creación de chat, agregado de mensajes y lectura de historial (CTR-006)."""
        chat = self.cliente.crear_chat("Sesión de diagnóstico HTM-240")
        chat_id = chat["id"]
        self.assertIsNotNone(chat_id)

        m1 = self.cliente.guardar_mensaje(chat_id, "usuario", "¿Par de apriete de culata?")
        self.assertTrue(m1["guardado"])

        m2 = self.cliente.guardar_mensaje(chat_id, "asistente", "Fase 1 a 40 Nm [chunk_01].", trace_id="t-100")
        self.assertTrue(m2["guardado"])

        historial = self.cliente.obtener_historial(chat_id)
        self.assertEqual(len(historial), 2)
        self.assertEqual(historial[0]["rol"], "usuario")
        self.assertEqual(historial[1]["rol"], "asistente")
        self.assertEqual(historial[1]["trace_id"], "t-100")

    def test_10_historial_limite_mensajes(self):
        """El parámetro limit restringe el número de mensajes devueltos en el historial."""
        chat = self.cliente.crear_chat("Chat largo")
        chat_id = chat["id"]

        for i in range(6):
            self.cliente.guardar_mensaje(chat_id, "usuario" if i % 2 == 0 else "asistente", f"Mensaje {i}")

        hist_3 = self.cliente.obtener_historial(chat_id, limit=3)
        self.assertEqual(len(hist_3), 3)
        self.assertEqual(hist_3[-1]["contenido"], "Mensaje 5")

    def test_11_login_exitoso_y_almacenamiento_token(self):
        """Verifica que login autentica contra CTR-005 y almacena el JWT en el cliente."""
        resp = self.cliente.login("admin", "admin123")
        self.assertEqual(resp["estado"], "autenticado")
        self.assertIn("simulated-jwt-token-admin", self.cliente.token_auth)
        self.assertEqual(self.cliente._headers()["Authorization"], f"Bearer {self.cliente.token_auth}")

    def test_12_login_credenciales_invalidas_lanza_error(self):
        """Verifica que credenciales incorrectas lanzan PermissionError."""
        with self.assertRaises(PermissionError):
            self.cliente.login("admin", "password_incorrecta")

    def test_13_obtener_consultas_mias_ctr003(self):
        """Verifica la consulta de registros propios vía GET /consultas/mias (CTR-003)."""
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-mias-01",
            conversacion_id="c-mias",
            pregunta_original="¿Presión aceite?",
            pregunta_limpia="presion aceite",
            entidades={},
            clasificacion="valida",
            query={},
            estado_agente2="suficiente",
            chunks_usados=["c-01"],
            scores=[0.9],
            estado_respuesta="respuesta",
            respuesta="1.5 bar",
            citas_verificadas=True,
            latencia_ms=45
        )
        self.cliente.registrar_turno(reg)
        consultas = self.cliente.obtener_consultas_mias()
        self.assertGreaterEqual(len(consultas), 1)
        self.assertEqual(consultas[0]["trace_id"], "t-mias-01")

    def test_14_obtener_todas_consultas_admin_ctr003(self):
        """Verifica la consulta global de registros para admin vía GET /consultas (CTR-003)."""
        reg = self.cliente.formatear_registro_ctr003(
            trace_id="t-admin-01",
            conversacion_id="c-admin",
            pregunta_original="¿Bomba agua?",
            pregunta_limpia="bomba agua",
            entidades={},
            clasificacion="valida",
            query={},
            estado_agente2="suficiente",
            chunks_usados=["c-02"],
            scores=[0.92],
            estado_respuesta="respuesta",
            respuesta="12V",
            citas_verificadas=True,
            latencia_ms=60
        )
        self.cliente.registrar_turno(reg)
        todas = self.cliente.obtener_todas_consultas(estado="respuesta")
        self.assertGreaterEqual(len(todas), 1)

    def test_15_restaurar_memoria_agente1_desde_backend_ctr007(self):
        """Verifica que Agente1 reconstruye su historial desde el Backend (CTR-007)."""
        from Agents.agente1.core import Agente1

        # Crear chat y mensajes en el simulador
        chat = self.cliente.crear_chat("Sesión multiturno previa")
        cid = str(chat["id"])
        self.cliente.guardar_mensaje(cid, "usuario", "¿Cada cuántos km se cambia el refrigerante?")
        self.cliente.guardar_mensaje(cid, "asistente", "Cada 60.000 km [chunk_ref_01].")

        # Nuevo agente con ese conversacion_id
        agente = Agente1(conversacion_id=cid)
        self.assertEqual(len(agente.historial), 0)

        # Restaurar memoria desde Backend
        cargados = agente.restaurar_memoria_desde_backend(cliente_backend=self.cliente)
        self.assertEqual(cargados, 2)
        self.assertEqual(len(agente.historial), 2)
        self.assertEqual(agente.historial[0]["role"], "user")
        self.assertEqual(agente.historial[0]["content"], "¿Cada cuántos km se cambia el refrigerante?")
        self.assertEqual(agente.historial[1]["role"], "assistant")
        self.assertEqual(agente.historial[1]["content"], "Cada 60.000 km [chunk_ref_01].")

    def test_16_integracion_automatica_restaurar_memoria_en_core(self):
        """Verifica que consultar_asistente llama automáticamente a restaurar_memoria_desde_backend."""
        from Agents.agente1.core import Agente1, consultar_asistente
        from unittest.mock import Mock

        chat = self.cliente.crear_chat("Sesión automática core")
        cid = str(chat["id"])
        self.cliente.guardar_mensaje(cid, "usuario", "¿Cuál es la presión nominal?")
        self.cliente.guardar_mensaje(cid, "asistente", "La presión nominal es de 1.2 bar [c1].")

        agente = Agente1(conversacion_id=cid, cliente_backend=self.cliente)
        agente._consultar_llm = Mock(return_value='{"texto_busqueda": "presion", "intencion": "especificacion", "filtros": {"version": "V1.0", "componente": null, "tipo_documento": null, "codigos": []}}')
        self.assertEqual(len(agente.historial), 0)

        # Al ejecutar un turno, el agente debe restaurar automáticamente la memoria
        consultar_asistente("¿Y en caliente?", agente)
        self.assertTrue(getattr(agente, "_memoria_restaurada", False))

    def test_17_integracion_automatica_registrar_turno_en_core(self):
        """Verifica que consultar_asistente llama automáticamente a cliente_backend.registrar_turno."""
        from Agents.agente1.core import Agente1, consultar_asistente
        from unittest.mock import Mock, patch

        agente = Agente1(conversacion_id="c-auto-reg", cliente_backend=self.cliente)
        agente._consultar_llm = Mock(return_value='{"texto_busqueda": "test", "intencion": "especificacion", "filtros": {"version": "V1.0", "componente": null, "tipo_documento": null, "codigos": []}}')

        with patch.object(self.cliente, "registrar_turno", wraps=self.cliente.registrar_turno) as mock_reg:
            consultar_asistente("¿Test automático?", agente)
            mock_reg.assert_called_once()
            args = mock_reg.call_args[0][0]
            self.assertEqual(args["conversacion_id"], "c-auto-reg")
            self.assertIn("trace_id", args)

    def test_18_integracion_automatica_service_restaurar_y_registrar(self):
        """Verifica que Agents.service.get_session restaura memoria y query registra el turno."""
        try:
            import fastapi
        except ImportError:
            self.skipTest("fastapi no instalado en este entorno local de pruebas")
        from Agents.service import get_session, query, Query
        from unittest.mock import patch, Mock

        chat = self.cliente.crear_chat("Sesión automática service")
        cid = str(chat["id"])
        self.cliente.guardar_mensaje(cid, "usuario", "Pregunta previa")
        self.cliente.guardar_mensaje(cid, "asistente", "Respuesta previa [c1].")

        with patch("Agents.agente1.cliente_backend.ClienteBackendAgentes", return_value=self.cliente):
            session = get_session(cid)
            self.assertIsNotNone(session.agent.cliente_backend)
            self.assertEqual(len(session.agent.historial), 2)

            with patch.object(session.agent, "_consultar_llm", return_value='{"texto_busqueda": "test", "intencion": "especificacion", "filtros": {"version": null, "componente": null, "tipo_documento": null, "codigos": []}}'):
                with patch.object(self.cliente, "registrar_turno", wraps=self.cliente.registrar_turno) as mock_reg:
                    resp = query(Query(conversacion_id=cid, pregunta="Consulta desde service"))
                    self.assertIn("trace_id", resp)
                    self.assertTrue(mock_reg.called)


if __name__ == "__main__":
    unittest.main()
