"""Pruebas de los adaptadores HTTP. PostgreSQL es opcional para la prueba de solo lectura."""

import os
import socket
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import uvicorn
from fastapi.testclient import TestClient

from Agents import service
from Backend.api.app.links import connect
from Backend.api.app.main import app, authorize_consultation

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
    def test_public_consultation_requires_real_session_validation(self):
        with TestClient(app) as client:
            body = {"conversacion_id": "", "pregunta": "Hola"}
            self.assertEqual(client.post("/consulta", json=body).status_code, 401)
            response = client.post("/consulta", json=body, headers={"Authorization": "Bearer dummy"})
            self.assertEqual(response.status_code, 503)

    def test_gateway_reaches_existing_agent_with_exact_question(self):
        original = "  ¿Qué significa HTM-0142?\nV1.1  "
        real_consultar = service.consultar_asistente
        with serve(service.app) as url, TestClient(app) as client, \
                patch.dict(os.environ, {"AGENTES_URL": url, "ARSOFT_SERVICE_TOKEN": TOKEN}), \
                patch.dict(app.dependency_overrides, {authorize_consultation: lambda: None}), \
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


if __name__ == "__main__":
    unittest.main()
