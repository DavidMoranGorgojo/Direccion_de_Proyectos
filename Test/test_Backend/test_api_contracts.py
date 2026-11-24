"""Pruebas de los adaptadores HTTP. PostgreSQL es opcional para la prueba de solo lectura."""

import asyncio
import os
import socket
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import uvicorn
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from Agents import service
from Backend.api.app.links import connect
from Backend.api.app.main import RespuestaAgentes, app, authorize_consultation, consultar_agentes

TOKEN = "arsoft-test"


@contextmanager
def serve(asgi):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(asgi, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.02)
            else:
                raise RuntimeError("El servidor de prueba no arrancó.")
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(5)


class Links(unittest.TestCase):
    def test_root_serves_responsive_web_client(self):
        with TestClient(app) as client:
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("<html lang=\"es\">", response.text)
            self.assertIn('name="viewport"', response.text)
            self.assertIn("/consulta", response.text)

    def test_public_consultation_requires_real_session_validation(self):
        with TestClient(app) as client, patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN}):
            body = {"conversacion_id": "", "pregunta": "Hola"}
            self.assertEqual(client.post("/consulta", json=body).status_code, 401)
            # CTR-005 ya valida la sesión: un token que no emitió Backend se rechaza
            response = client.post("/consulta", json=body, headers={"Authorization": "Bearer dummy"})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["codigo_error"], "sesion_caducada")

    def test_gateway_reaches_existing_agent_with_exact_question(self):
        original = "  ¿Qué significa HTM-0142?\nV1.1  "
        real_consultar = service.consultar_asistente
        with serve(service.app) as url, TestClient(app) as client, \
                patch.dict(os.environ, {"AGENTES_URL": url, "ARSOFT_SERVICE_TOKEN": TOKEN}), \
                patch.dict(app.dependency_overrides, {authorize_consultation: lambda: {"id": 1}}), \
                patch("Backend.api.app.main.reservar"), patch("Backend.api.app.main.guardar"), \
                patch.object(service.Agente1, "_consultar_llm", return_value="INVALIDA"), \
                patch("Agents.agente1.core.registrar_turno_auditoria"), \
                patch.object(service, "consultar_asistente", wraps=real_consultar) as consulted:
            first = client.post("/consulta", json={"conversacion_id": "", "pregunta": original})
            self.assertEqual(first.status_code, 200, first.text)
            cid = first.json()["conversacion_id"]
            self.assertTrue(cid)
            self.assertEqual(first.json()["estado"], "fuera_de_ambito")
            self.assertEqual(consulted.call_args.args[0], original)
            second = client.post("/consulta", json={"conversacion_id": cid, "pregunta": "Otro turno"})
            self.assertEqual(second.json()["conversacion_id"], cid)
            self.assertIs(consulted.call_args_list[0].args[1], consulted.call_args_list[1].args[1])

    @unittest.skipUnless(os.getenv("ARSOFT_TEST_DATABASE_URL"), "Requiere un PostgreSQL de pruebas")
    def test_read_only_knowledge_link(self):
        env = {"DATABASE_URL": os.environ["ARSOFT_TEST_DATABASE_URL"], "ARSOFT_SERVICE_TOKEN": TOKEN}
        with patch.dict(os.environ, env), TestClient(app) as client:
            with connect() as conn:
                index = conn.execute("SELECT version FROM conocimiento.indice_version WHERE activo").fetchone()
            self.assertEqual(client.get("/conocimiento/info").status_code, 401)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            response = client.get("/conocimiento/info", headers=headers)
            self.assertEqual(response.status_code, 200 if index else 503)
            if index:
                self.assertEqual(response.json()["version"], index["version"])


class ServiceBoundary(unittest.TestCase):
    def test_agentes_exige_bearer_de_servicio(self):
        with patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN}), TestClient(service.app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"]["codigo"], "acceso_denegado")
            invalid = client.get("/health", headers={"Authorization": "Bearer incorrecto"})
            self.assertEqual(invalid.status_code, 401)
            self.assertEqual(invalid.json()["detail"]["codigo"], "acceso_denegado")

    def test_agentes_retorna_503_si_falta_el_token_configurado(self):
        env = {key: value for key, value in os.environ.items() if key != "ARSOFT_SERVICE_TOKEN"}
        with patch.dict(os.environ, env, clear=True), TestClient(service.app) as client:
            response = client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["codigo"], "servicio_no_disponible")

    def test_timeout_devuelve_tiempo_agotado_y_cierra_conversacion(self):
        metodos = []

        def handler(request):
            metodos.append(request.method)
            if request.method == "POST":
                raise httpx.ReadTimeout("lectura agotada", request=request)
            return httpx.Response(204)

        async def llamada():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch("Backend.api.app.main.agents_url", return_value="http://agents.test"), \
                     patch("Backend.api.app.main.service_headers", return_value={"Authorization": "Bearer test"}):
                    return await consultar_agentes("chat-timeout", "pregunta", client)

        result = asyncio.run(llamada())
        self.assertEqual((result.estado, result.codigo_error), ("error", "tiempo_agotado"))
        self.assertEqual(result.fuentes, [])
        self.assertEqual(metodos, ["POST", "DELETE"])


class CTR001ResponseValidation(unittest.TestCase):
    def respuesta(self, **cambios):
        base = {
            "trace_id": "trace-test",
            "estado": "respuesta",
            "texto": "El par de apriete es 20 Nm.",
            "fuentes": [{
                "chunk_id": "chunk-1", "documento": "HTM240-MAN-001", "seccion": "Culata",
                "pagina": 4, "versiones": ["V1.1"], "obsoleto": False,
            }],
            "codigo_error": "",
        }
        base.update(cambios)
        return base

    def test_acepta_respuesta_con_referencia_completa(self):
        result = RespuestaAgentes.model_validate(self.respuesta())
        self.assertEqual(result.fuentes[0].pagina, 4)

    def test_rechaza_pagina_cero_y_metadatos_incompletos(self):
        for field, value in (("pagina", 0), ("documento", " "),
                             ("documento", "DOC_DESCONOCIDO"), ("seccion", " ")):
            with self.subTest(field=field, value=value):
                body = self.respuesta()
                body["fuentes"][0][field] = value
                with self.assertRaises(ValidationError):
                    RespuestaAgentes.model_validate(body)

    def test_respuesta_vacia_o_sin_fuentes_no_puede_ser_verificada(self):
        for changes in ({"texto": "  "}, {"fuentes": []}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RespuestaAgentes.model_validate(self.respuesta(**changes))


if __name__ == "__main__":
    unittest.main()
