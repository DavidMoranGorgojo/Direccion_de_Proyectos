"""Contrato CTR-002: el cliente real del Agente 2 contra POST /conocimiento/lexica real del Backend.

Usa el motor BM25 real del Backend con la conexión simulada de test_busqueda_lexica (sin PostgreSQL).
Se omite mientras el Agente 2 no esté en el repositorio (Agents/Agent_2) o en AGENT2_DIR.
Ejecutar desde la raíz con ``PYTHONPATH=shared;.`` (``:`` en Linux/Mac).
"""
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

AGENT2 = Path(os.getenv("AGENT2_DIR") or Path(__file__).resolve().parents[2] / "Agents" / "Agent_2")
DISPONIBLE = (AGENT2 / "src" / "clients" / "backend.py").is_file()

if DISPONIBLE:
    sys.path.insert(0, str(AGENT2))
    from src.clients.backend import BackendAPIClient
    from src.core.errors import BackendRequestError

from Backend.api.app import busqueda_lexica
from Backend.api.app.main import app
from Test.test_Backend.test_busqueda_lexica import INDICE, FakeConnection, TOKEN


class _Respuesta:
    def __init__(self, r):
        self.status_code, self._r = r.status_code, r

    def json(self):
        return self._r.json()


class SesionTestClient:
    """requests.Session mínima que atiende las peticiones con el TestClient del Backend."""

    def __init__(self, client):
        self.client = client

    def post(self, url, json=None, timeout=None, headers=None):
        return _Respuesta(self.client.post(url.split("backend.test", 1)[1], json=json, headers=headers))

    def get(self, url, params=None, timeout=None, headers=None):
        return _Respuesta(self.client.get(url.split("backend.test", 1)[1], params=params, headers=headers))


@unittest.skipUnless(DISPONIBLE, "Requiere el Agente 2 (Agents/Agent_2 o AGENT2_DIR)")
class ContratoLexica(unittest.TestCase):
    def setUp(self):
        busqueda_lexica._cache.update(clave=None, indice=None)
        env = patch.dict(os.environ, {"ARSOFT_SERVICE_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)

    @contextmanager
    def cliente(self, token=TOKEN):
        with patch("Backend.api.app.conocimiento.connect", return_value=FakeConnection()), TestClient(app) as tc:
            yield BackendAPIClient("http://backend.test", INDICE["modelo_embeddings"],
                                   session=SesionTestClient(tc), token=token)

    def test_respuesta_se_parsea_y_conserva_codigo_exacto(self):
        with self.cliente() as c:
            r = c.search_lexical_candidates("testigo de temperatura HTM-0142", {"componente": "refrigeracion"}, k=5)
        self.assertEqual(r.indice.version, INDICE["version"])
        self.assertEqual(r.resultados[0].chunk_id, "c1")
        self.assertIn("HTM-0142", r.resultados[0].texto)
        self.assertTrue(all(x.metadatos.componente == "refrigeracion" for x in r.resultados))
        scores = [x.score_lexico for x in r.resultados]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(r.as_rrf_input()[0]["fecha_revision"], "2026-09-01")

    def test_filtros_internos_no_viajan_y_version_usa_vigencia(self):
        with self.cliente() as c:
            r = c.search_lexical_candidates("apriete culata",
                                            {"version": "V1.0", "codigos": ["HTM-0142"], "incluir_obsoletos": True})
        self.assertEqual([x.chunk_id for x in r.resultados], ["c3"])

    def test_sin_coincidencias_es_lista_vacia_no_error(self):
        with self.cliente() as c:
            r = c.search_lexical_candidates("neumatico trasero pinchado")
        self.assertEqual(r.resultados, [])

    def test_filtro_inexistente_se_mapea_a_entrada_invalida(self):
        with self.cliente() as c, self.assertRaises(BackendRequestError) as ctx:
            c.search_lexical_candidates("culata", {"componente": "frenos"})
        self.assertEqual(ctx.exception.codigo_error, "entrada_invalida")

    def test_token_de_servicio_incorrecto(self):
        with self.cliente(token="otro") as c, self.assertRaises(BackendRequestError) as ctx:
            c.search_lexical_candidates("culata")
        self.assertEqual(ctx.exception.codigo_error, "servicio_no_disponible")

    def test_modelo_de_embeddings_distinto_es_incompatible(self):
        with self.cliente() as c:
            c.model_embeddings = "otro/modelo"
            with self.assertRaises(BackendRequestError) as ctx:
                c.search_lexical_candidates("culata")
        self.assertEqual(ctx.exception.codigo_error, "modelo_incompatible")

    def test_k_maximo_del_backend(self):
        with self.cliente() as c, self.assertRaises(BackendRequestError) as ctx:
            c.search_lexical("culata", k=201)
        self.assertEqual(ctx.exception.codigo_error, "entrada_invalida")


if __name__ == "__main__":
    unittest.main()
