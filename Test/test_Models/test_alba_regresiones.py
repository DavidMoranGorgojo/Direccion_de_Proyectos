import unittest
from unittest.mock import MagicMock
import requests

from Agents.Agent_2.src.services.filters import (
    extract_code_tokens,
    normalize_component,
    COMPONENT_ALIASES,
)
from Agents.Agent_2.src.services.filter_inference import (
    infer_codes,
    infer_component,
    infer_document_types,
    infer_filters,
)
from Agents.Agent_2.src.core.errors import BackendRequestError


class TestAlbaRegresiones(unittest.TestCase):
    def test_alb_1_falso_codigo_htm240(self):
        """HTM-240 es el producto, no un código de avería."""
        tokens = extract_code_tokens("¿Par de apriete de la culata del ThermoDrive HTM-240?")
        self.assertNotIn("HTM-240", tokens)
        self.assertNotIn("HTM240", tokens)

        tokens_validos = extract_code_tokens("Fallo HTM-0101 en HTM240-SEG-001 y CMP-02 con CIR-01")
        self.assertIn("HTM-0101", tokens_validos)
        self.assertIn("HTM240-SEG-001", tokens_validos)
        self.assertIn("CMP-02", tokens_validos)
        self.assertIn("CIR-01", tokens_validos)

    def test_alb_2_inferencia_componente_conservadora(self):
        """'motor' suelto no debe fijar componente='motor' en electroventilador."""
        comp = infer_component("El motor del electroventilador no arranca")
        self.assertIsNone(comp)

        # normalize_component acepta sistema y general
        self.assertEqual(normalize_component("sistema"), "sistema")
        self.assertEqual(normalize_component("general"), "general")

    def test_alb_3_inferencia_tipo_documento_conservadora(self):
        """Palabras comunes como 'operacion', 'manual', 'seg' no deben fijar tipo_documento."""
        tipos = infer_document_types("operación de purga según el manual")
        self.assertIsNone(tipos)

    def test_alb_4_adapt_explicit_filters(self):
        """Vocabulario Agente 1 adaptado y filtros no reconocidos descartados."""
        from Agents.Agent_2.src.services.filter_vocab import adapt_explicit_filters, VALID_COMPONENTS
        self.assertIn("sistema", VALID_COMPONENTS)
        self.assertIn("general", VALID_COMPONENTS)

        validos, descartados = adapt_explicit_filters({"tipo_documento": "ficha_tecnica", "componente": "culata"})
        self.assertEqual(validos.get("tipo_documento"), "catalogo")
        self.assertNotIn("componente", validos)
        self.assertEqual(descartados.get("componente"), "culata")

    def test_alb_5_ambiguedad_componente_con_codigo(self):
        """Si el usuario nombra CMP-02 en V1.1 no debe marcarse ambiguo de componente."""
        from Agents.Agent_2.src.services.vigencia import classify_state
        candidatos = [
            {"chunk_id": "c1", "componente": "refrigeracion", "versiones": ["V1.1"], "obsoleto": False},
            {"chunk_id": "c2", "componente": "sistema", "versiones": ["V1.1"], "obsoleto": False},
            {"chunk_id": "c3", "componente": "bateria", "versiones": ["V1.1"], "obsoleto": False},
        ]
        decision = classify_state(candidatos, filters={"version": "V1.1", "codigos": ["CMP-02"]})
        self.assertEqual(decision.estado, "suficiente")

    def test_alb_6_chunk_valido(self):
        """Chunk valido segun campos requeridos de CTR-002."""
        from Agents.Agent_2.src.clients.backend import _invalid_chunk_fields
        chunk = {
            "chunk_id": "c1",
            "texto": "valido",
            "documento": "HTM240-DTC-001",
            "seccion": "1.0",
            "componente": "refrigeracion",
            "tipo_documento": "codigo_averia",
            "version_documento": "1.0",
            "pagina": 1,
            "orden_en_seccion": 1,
            "versiones": ["V1.1"],
            "obsoleto": False,
            "vigente_para": ["V1.1"],
            "fecha_revision": "2026-01-01",
            "afectado_por": [],
            "ids_referenciados": [],
        }
        problems = _invalid_chunk_fields(chunk)
        self.assertEqual(problems, [])

    def test_alb_7_split_ctr002_requests_y_post_conocimiento(self):
        """split_ctr002_requests divide múltiples tipo_documento y get_chunk captura fallos."""
        from Agents.Agent_2.src.clients.backend import split_ctr002_requests, BackendAPIClient
        reqs = split_ctr002_requests({"tipo_documento": ["manual", "operacion"], "version": "V1.1"})
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0]["tipo_documento"], "manual")
        self.assertEqual(reqs[1]["tipo_documento"], "operacion")
        self.assertEqual(reqs[0]["version"], "V1.1")
        self.assertEqual(reqs[1]["version"], "V1.1")

        # Test error handling en get_chunk
        session_mock = MagicMock()
        session_mock.get.side_effect = requests.ConnectionError("Backend down")
        client = BackendAPIClient("http://fake", "BAAI/bge-m3", session=session_mock)
        with self.assertRaises(BackendRequestError) as ctx:
            client.get_chunk("c1")
        self.assertEqual(ctx.exception.codigo_error, "servicio_no_disponible")

        session_mock.get.side_effect = requests.Timeout("Timeout")
        with self.assertRaises(BackendRequestError) as ctx:
            client.get_chunk("c1")
        self.assertEqual(ctx.exception.codigo_error, "tiempo_agotado")

    def test_alb_8_lexical_rrf_compatibility(self):
        """LexicalCandidate.to_rrf_dict() produce diccionarios planos aptos para rrf()."""
        from Agents.Agent_2.src.models.lexical import LexicalCandidate, LexicalMetadata
        from Agents.Agent_2.src.services.fusion import rrf

        meta = LexicalMetadata(
            documento="DOC-1",
            seccion="1.0",
            pagina=2,
            versiones=["V1.1"],
            componente="refrigeracion",
            tipo_documento="manual",
            obsoleto=False,
            sustituido_por=None,
            vigente_para=["V1.1"],
            fecha_revision="2026-01-01",
            orden_en_seccion=1,
            version_documento="1.0",
            afectado_por=[],
            ids_referenciados=["CMP-01"],
        )
        cand = LexicalCandidate(chunk_id="c1", texto="texto", score_lexico=12.5, metadatos=meta)
        rrf_dict = cand.to_rrf_dict()
        self.assertEqual(rrf_dict["chunk_id"], "c1")
        self.assertEqual(rrf_dict["score_bm25"], 12.5)
        self.assertEqual(rrf_dict["documento"], "DOC-1")

        fused = rrf([], [rrf_dict])
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["chunk_id"], "c1")


    def test_bge_m3_encode_soporta_query_y_passages(self):
        from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client

        class FakeEncoder:
            def encode(self, texts, **kwargs):
                return {"dense_vecs": [[0.1, 0.2] for _ in texts]}

        client = BgeM3Client(FakeEncoder(), use_prefix=True)
        # Codificación de query
        vec = client.encode("consulta de prueba")
        self.assertEqual(len(vec), 2)
        # Codificación de passages
        vecs = client.encode(["texto uno", "texto dos"])
        self.assertEqual(len(vecs), 2)
        # Codificación sin prefijo
        vec_no_prefix = client.encode("consulta", use_prefix=False)
        self.assertEqual(len(vec_no_prefix), 2)
