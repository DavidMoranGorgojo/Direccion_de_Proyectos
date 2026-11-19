from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "Test" / "fixtures" / "agent2"

sys.path.insert(0, str(REPO_ROOT))

from Agents.Agent_2.src.models.ctr_002 import IndexInfo, VectorCandidate
from Agents.Agent_2.src.services.vector_parser import (
    VectorContractError,
    VectorParserError,
    VectorValidationError,
    parse_vector_response,
)


class VectorParserTests(unittest.TestCase):
    def _load(self, name: str) -> dict:
        with (FIXTURES_DIR / name).open(encoding="utf-8") as fixture:
            return json.load(fixture)

    def _valid_payload(self) -> dict:
        return self._load("vectorial_correcto.json")

    def test_respuesta_valida_con_varios_resultados(self):
        payload = self._valid_payload()

        parsed = parse_vector_response(payload)

        self.assertEqual(len(parsed.resultados), 3)
        self.assertIsInstance(parsed.resultados[0], VectorCandidate)

    def test_conserva_el_orden(self):
        parsed = parse_vector_response(self._valid_payload())

        self.assertEqual(
            [candidate.chunk_id for candidate in parsed.resultados],
            ["c45", "c46", "c47"],
        )

    def test_conserva_el_indice(self):
        payload = self._valid_payload()

        parsed = parse_vector_response(payload)

        self.assertEqual(
            parsed.indice,
            IndexInfo(
                version=payload["indice"]["version"],
                modelo_embeddings=payload["indice"]["modelo_embeddings"],
            ),
        )

    def test_convierte_score_a_score_vectorial(self):
        parsed = parse_vector_response(self._valid_payload())

        self.assertEqual(parsed.resultados[0].score_vectorial, 0.8324)
        self.assertIsInstance(parsed.resultados[0].score_vectorial, float)

    def test_resultados_vacios_es_valido(self):
        parsed = parse_vector_response(self._load("vectorial_vacio.json"))

        self.assertEqual(parsed.resultados, [])

    def test_ausencia_de_indice(self):
        payload = self._valid_payload()
        del payload["indice"]

        with self.assertRaisesRegex(VectorContractError, r"indice"):
            parse_vector_response(payload)

    def test_ausencia_de_resultados(self):
        payload = self._valid_payload()
        del payload["resultados"]

        with self.assertRaisesRegex(VectorContractError, r"resultados"):
            parse_vector_response(payload)

    def test_resultados_null(self):
        payload = self._valid_payload()
        payload["resultados"] = None

        with self.assertRaisesRegex(VectorValidationError, r"resultados"):
            parse_vector_response(payload)

    def test_respuesta_no_es_diccionario(self):
        with self.assertRaises(VectorContractError):
            parse_vector_response([])

    def test_candidato_no_es_diccionario(self):
        payload = self._valid_payload()
        payload["resultados"][0] = "no es un objeto"

        with self.assertRaisesRegex(VectorContractError, r"resultados\[0\]"):
            parse_vector_response(payload)

    def test_chunk_id_ausente_o_vacio(self):
        casos = [
            ("ausente", None, VectorContractError),
            ("vacio", "", VectorValidationError),
            ("solo_espacios", "   ", VectorValidationError),
        ]

        for nombre, valor, error_esperado in casos:
            with self.subTest(caso=nombre):
                payload = self._valid_payload()
                if valor is None:
                    del payload["resultados"][0]["chunk_id"]
                else:
                    payload["resultados"][0]["chunk_id"] = valor

                with self.assertRaisesRegex(
                    error_esperado,
                    r"resultados\[0\]\.chunk_id",
                ):
                    parse_vector_response(payload)

    def test_chunk_id_duplicado(self):
        with self.assertRaisesRegex(
            VectorValidationError,
            r"resultados\[1\]\.chunk_id",
        ):
            parse_vector_response(self._load("vectorial_chunk_duplicado.json"))

    def test_texto_ausente_o_vacio(self):
        casos = [
            ("ausente", None),
            ("vacio", ""),
            ("solo_espacios", "   "),
        ]

        for nombre, valor in casos:
            with self.subTest(caso=nombre):
                payload = self._valid_payload()
                if valor is None:
                    del payload["resultados"][0]["texto"]
                else:
                    payload["resultados"][0]["texto"] = valor

                with self.assertRaisesRegex(
                    VectorParserError,
                    r"resultados\[0\]\.texto",
                ):
                    parse_vector_response(payload)

    def test_score_string_y_booleano(self):
        with self.assertRaisesRegex(
            VectorValidationError,
            r"resultados\[0\]\.score",
        ):
            parse_vector_response(self._load("vectorial_score_invalido.json"))

        payload = self._valid_payload()
        payload["resultados"][0]["score"] = True

        with self.assertRaisesRegex(
            VectorValidationError,
            r"resultados\[0\]\.score",
        ):
            parse_vector_response(payload)

    def test_score_nan_e_infinito(self):
        for valor in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=valor):
                payload = self._valid_payload()
                payload["resultados"][0]["score"] = valor

                with self.assertRaisesRegex(
                    VectorValidationError,
                    r"resultados\[0\]\.score",
                ):
                    parse_vector_response(payload)

    def test_score_sin_rango_arbitrario(self):
        for valor in (5.0, -1.25):
            with self.subTest(score=valor):
                payload = self._valid_payload()
                payload["resultados"][0]["score"] = valor

                parsed = parse_vector_response(payload)

                self.assertEqual(parsed.resultados[0].score_vectorial, valor)

    def test_campos_obligatorios_del_resultado(self):
        campos = [
            "chunk_id",
            "score",
            "texto",
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
        ]

        for campo in campos:
            with self.subTest(campo=campo):
                payload = self._valid_payload()
                del payload["resultados"][0][campo]

                with self.assertRaisesRegex(
                    VectorContractError,
                    rf"resultados\[0\]\.{campo}",
                ):
                    parse_vector_response(payload)

    def test_campos_obligatorios_del_indice(self):
        casos = [
            ("version_ausente", "del"),
            ("version_vacia", ""),
            ("modelo_ausente", None),
            ("modelo_vacio", ""),
        ]

        for nombre, valor in casos:
            with self.subTest(caso=nombre):
                payload = self._valid_payload()
                if nombre.startswith("version"):
                    campo = "version"
                else:
                    campo = "modelo_embeddings"

                if valor == "del":
                    del payload["indice"][campo]
                else:
                    payload["indice"][campo] = valor

                with self.assertRaisesRegex(
                    VectorParserError,
                    rf"indice\.{campo}",
                ):
                    parse_vector_response(payload)

    def test_indice_no_es_objeto(self):
        payload = self._valid_payload()
        payload["indice"] = []

        with self.assertRaisesRegex(VectorValidationError, r"indice"):
            parse_vector_response(payload)

    def test_tipos_incorrectos_en_metadatos(self):
        casos = [
            ("documento", 3),
            ("seccion", None),
            ("pagina", "3"),
            ("pagina", True),
            ("versiones", "V1.1"),
            ("versiones", [1]),
            ("componente", None),
            ("tipo_documento", 1),
            ("orden_en_seccion", "3"),
            ("orden_en_seccion", False),
            ("version_documento", 1.0),
            ("fecha_revision", 20261015),
            ("afectado_por", "BOL-003"),
            ("afectado_por", [1]),
            ("ids_referenciados", None),
            ("sustituido_por", 3),
            ("vigente_para", "V1.1"),
            ("vigente_para", None),
            ("vigente_para", ["V1.1", 2]),
        ]

        for campo, valor in casos:
            with self.subTest(campo=campo, valor=valor):
                payload = self._valid_payload()
                payload["resultados"][0][campo] = valor

                with self.assertRaisesRegex(
                    VectorValidationError,
                    rf"resultados\[0\]\.{campo}",
                ):
                    parse_vector_response(payload)

    def test_obsoleto_distinto_de_booleano(self):
        for valor in (0, 1, "false"):
            with self.subTest(valor=valor):
                payload = self._valid_payload()
                payload["resultados"][0]["obsoleto"] = valor

                with self.assertRaisesRegex(
                    VectorValidationError,
                    r"resultados\[0\]\.obsoleto",
                ):
                    parse_vector_response(payload)

    def test_sustituido_por_null_permitido(self):
        parsed = parse_vector_response(self._valid_payload())

        self.assertIsNone(parsed.resultados[0].metadatos.sustituido_por)

    def test_vigente_para_independiente_de_versiones(self):
        """CTR-002: vigente_para es un campo propio, no una copia de versiones."""
        payload = self._valid_payload()
        payload["resultados"][2]["versiones"] = ["V1.1", "V2.0"]
        payload["resultados"][2]["vigente_para"] = ["V2.0"]

        metadatos = parse_vector_response(payload).resultados[2].metadatos

        self.assertEqual(metadatos.versiones, ["V1.1", "V2.0"])
        self.assertEqual(metadatos.vigente_para, ["V2.0"])

    def test_listas_vacias_permitidas(self):
        parsed = parse_vector_response(self._valid_payload())

        self.assertEqual(parsed.resultados[1].metadatos.afectado_por, [])
        self.assertEqual(parsed.resultados[2].metadatos.ids_referenciados, [])

    def test_fecha_invalida(self):
        for valor in ("2026-02-30", "2026-13-01", "15-10-2026", "20261015"):
            with self.subTest(fecha=valor):
                payload = self._valid_payload()
                payload["resultados"][0]["fecha_revision"] = valor

                with self.assertRaisesRegex(
                    VectorValidationError,
                    r"resultados\[0\]\.fecha_revision",
                ):
                    parse_vector_response(payload)

    def test_fecha_null_se_conserva_como_dato_ausente(self):
        """La API acepta fecha_revision nullable sin inventar una fecha."""
        payload = self._valid_payload()
        payload["resultados"][0]["fecha_revision"] = None
        parsed = parse_vector_response(payload)
        self.assertIsNone(parsed.resultados[0].metadatos.fecha_revision)

    def test_no_muta_el_payload_de_entrada(self):
        payload = self._valid_payload()
        original = copy.deepcopy(payload)

        parse_vector_response(payload)

        self.assertEqual(payload, original)

    def test_conserva_todos_los_metadatos(self):
        payload = self._valid_payload()
        esperado = payload["resultados"][0]

        metadatos = parse_vector_response(payload).resultados[0].metadatos

        self.assertEqual(metadatos.documento, esperado["documento"])
        self.assertEqual(metadatos.seccion, esperado["seccion"])
        self.assertEqual(metadatos.pagina, esperado["pagina"])
        self.assertEqual(metadatos.versiones, esperado["versiones"])
        self.assertEqual(metadatos.componente, esperado["componente"])
        self.assertEqual(metadatos.tipo_documento, esperado["tipo_documento"])
        self.assertEqual(metadatos.obsoleto, esperado["obsoleto"])
        self.assertEqual(metadatos.sustituido_por, esperado["sustituido_por"])
        self.assertEqual(metadatos.vigente_para, esperado["vigente_para"])
        self.assertEqual(metadatos.fecha_revision, esperado["fecha_revision"])
        self.assertEqual(
            metadatos.orden_en_seccion,
            esperado["orden_en_seccion"],
        )
        self.assertEqual(
            metadatos.version_documento,
            esperado["version_documento"],
        )
        self.assertEqual(metadatos.afectado_por, esperado["afectado_por"])
        self.assertEqual(
            metadatos.ids_referenciados,
            esperado["ids_referenciados"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
