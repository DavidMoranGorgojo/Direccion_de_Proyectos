from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "Test" / "fixtures" / "agent2"

sys.path.insert(0, str(REPO_ROOT))

from Agents.Agent_2.src.services.candidate_adapter import to_fusion_candidates
from Agents.Agent_2.src.services.vector_parser import parse_vector_response

CAMPOS_ESPERADOS = {
    "chunk_id",
    "texto",
    "score_vectorial",
    "documento",
    "seccion",
    "pagina",
    "versiones",
    "componente",
    "tipo_documento",
    "obsoleto",
    "sustituido_por",
    "vigente_para",
    "fecha_revision",
    "orden_en_seccion",
    "version_documento",
    "afectado_por",
    "ids_referenciados",
}

CAMPOS_DE_ETAPAS_POSTERIORES = {
    "score",
    "score_bm25",
    "rrf_score",
    "rerank_score",
    "score_final",
}


class CandidateAdapterTests(unittest.TestCase):
    def _candidates(self):
        with (FIXTURES_DIR / "vectorial_correcto.json").open(
            encoding="utf-8"
        ) as fixture:
            payload = json.load(fixture)

        return parse_vector_response(payload).resultados

    def test_convierte_un_candidato(self):
        candidates = self._candidates()[:1]

        adaptados = to_fusion_candidates(candidates)

        self.assertEqual(len(adaptados), 1)
        self.assertIsInstance(adaptados[0], dict)

    def test_convierte_varios_candidatos(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        self.assertEqual(len(adaptados), 3)

    def test_chunk_id_en_nivel_superior(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        self.assertEqual(adaptados[0]["chunk_id"], candidates[0].chunk_id)
        self.assertNotIn("chunk_id", adaptados[0].get("metadatos", {}))

    def test_texto_en_nivel_superior(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        self.assertEqual(adaptados[0]["texto"], candidates[0].texto)
        self.assertNotIn("texto", adaptados[0].get("metadatos", {}))

    def test_todos_los_metadatos_en_nivel_superior(self):
        candidates = self._candidates()
        metadatos = candidates[0].metadatos

        adaptado = to_fusion_candidates(candidates)[0]

        self.assertEqual(set(adaptado), CAMPOS_ESPERADOS)
        self.assertNotIn("metadatos", adaptado)
        self.assertEqual(adaptado["documento"], metadatos.documento)
        self.assertEqual(adaptado["seccion"], metadatos.seccion)
        self.assertEqual(adaptado["pagina"], metadatos.pagina)
        self.assertEqual(adaptado["versiones"], metadatos.versiones)
        self.assertEqual(adaptado["componente"], metadatos.componente)
        self.assertEqual(adaptado["tipo_documento"], metadatos.tipo_documento)
        self.assertEqual(adaptado["obsoleto"], metadatos.obsoleto)
        self.assertEqual(adaptado["sustituido_por"], metadatos.sustituido_por)
        self.assertEqual(adaptado["vigente_para"], metadatos.vigente_para)
        self.assertEqual(adaptado["fecha_revision"], metadatos.fecha_revision)
        self.assertEqual(
            adaptado["orden_en_seccion"],
            metadatos.orden_en_seccion,
        )
        self.assertEqual(
            adaptado["version_documento"],
            metadatos.version_documento,
        )
        self.assertEqual(adaptado["afectado_por"], metadatos.afectado_por)
        self.assertEqual(
            adaptado["ids_referenciados"],
            metadatos.ids_referenciados,
        )

    def test_conserva_score_vectorial(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        for candidate, adaptado in zip(candidates, adaptados):
            self.assertEqual(
                adaptado["score_vectorial"],
                candidate.score_vectorial,
            )

    def test_conserva_listas_y_valores_nulos(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        self.assertIsNone(adaptados[0]["sustituido_por"])
        self.assertEqual(adaptados[1]["afectado_por"], [])
        self.assertEqual(adaptados[2]["ids_referenciados"], [])
        self.assertEqual(adaptados[2]["sustituido_por"], "HTM240-BOL-009")

    def test_conserva_el_orden(self):
        candidates = self._candidates()

        adaptados = to_fusion_candidates(candidates)

        self.assertEqual(
            [adaptado["chunk_id"] for adaptado in adaptados],
            ["c45", "c46", "c47"],
        )

    def test_lista_vacia(self):
        self.assertEqual(to_fusion_candidates([]), [])

    def test_no_muta_los_objetos_originales(self):
        candidates = self._candidates()
        originales = copy.deepcopy(candidates)

        to_fusion_candidates(candidates)

        self.assertEqual(candidates, originales)

    def test_las_listas_adaptadas_no_comparten_referencias(self):
        candidates = self._candidates()
        adaptados = to_fusion_candidates(candidates)

        adaptados[0]["versiones"].append("V9.9")
        adaptados[1]["afectado_por"].append("BOL-999")
        adaptados[2]["ids_referenciados"].append("CMP-999")

        self.assertNotIn("V9.9", candidates[0].metadatos.versiones)
        self.assertNotIn("BOL-999", candidates[1].metadatos.afectado_por)
        self.assertNotIn("CMP-999", candidates[2].metadatos.ids_referenciados)

    def test_no_crea_scores_de_etapas_posteriores(self):
        adaptados = to_fusion_candidates(self._candidates())

        for adaptado in adaptados:
            self.assertTrue(
                CAMPOS_DE_ETAPAS_POSTERIORES.isdisjoint(adaptado)
            )

    def test_no_pierde_ningun_metadato(self):
        candidates = self._candidates()
        adaptados = to_fusion_candidates(candidates)

        for candidate, adaptado in zip(candidates, adaptados):
            metadatos = candidate.metadatos
            esperado = {
                "chunk_id": candidate.chunk_id,
                "texto": candidate.texto,
                "score_vectorial": candidate.score_vectorial,
                "documento": metadatos.documento,
                "seccion": metadatos.seccion,
                "pagina": metadatos.pagina,
                "versiones": metadatos.versiones,
                "componente": metadatos.componente,
                "tipo_documento": metadatos.tipo_documento,
                "obsoleto": metadatos.obsoleto,
                "sustituido_por": metadatos.sustituido_por,
                "vigente_para": metadatos.vigente_para,
                "fecha_revision": metadatos.fecha_revision,
                "orden_en_seccion": metadatos.orden_en_seccion,
                "version_documento": metadatos.version_documento,
                "afectado_por": metadatos.afectado_por,
                "ids_referenciados": metadatos.ids_referenciados,
            }

            self.assertEqual(adaptado, esperado)


if __name__ == "__main__":
    unittest.main(verbosity=2)
