"""
Batería de Tests Unitarios y Regresión — Agente 1 (Preprocesamiento y Contratos)
================================================================================
Ejecución:
    pytest test_agente1.py
o bien:
    python3 -m unittest test_agente1.py
"""

import unittest
from agente1_core import (
    PreprocesadorAutomocion,
    simulador_agente_2,
    validar_esquema_query_json,
    verificar_citas,
)


class TestPreprocesadorRegresion(unittest.TestCase):
    """Casos de regresión exigidos en la revisión de código (PR)."""

    def test_refrigerante_no_se_modifica(self):
        """1. La palabra 'refrigerante' no debe convertirse en REF-rigerante."""
        res = PreprocesadorAutomocion.procesar("revisar nivel de refrigerante del motor")
        self.assertIn("refrigerante", res["texto_procesado"])
        self.assertNotIn("REF-", res["texto_procesado"])
        self.assertEqual(res["codigos_detectados"], [])

    def test_referencia_no_se_modifica(self):
        """Casos adicionales de palabras que empiezan por 'ref'."""
        res = PreprocesadorAutomocion.procesar("referencia de la pieza y refuerzo de chasis")
        self.assertIn("referencia", res["texto_procesado"])
        self.assertIn("refuerzo", res["texto_procesado"])
        self.assertNotIn("REF-", res["texto_procesado"])

    def test_ref_con_digitos_se_normaliza(self):
        """2. 'ref 123' debe pasar a 'REF-123' y detectarse como código."""
        res = PreprocesadorAutomocion.procesar("pieza con ref 123 para el alternador")
        self.assertIn("REF-123", res["texto_procesado"])
        self.assertIn("REF-123", res["codigos_detectados"])

    def test_clase_c_2019_no_se_modifica(self):
        """3. 'Clase C 2019' no debe convertirse en código DTC C2019."""
        res = PreprocesadorAutomocion.procesar("Mercedes Clase C 2019 mantenimiento")
        self.assertIn("Clase C 2019", res["texto_procesado"])
        self.assertNotIn("C2019", res["texto_procesado"])
        self.assertNotIn("C2019", res["codigos_detectados"])

    def test_serie_b_2015_no_se_modifica(self):
        """BMW Serie B 2015 no debe tratarse como código DTC B2015."""
        res = PreprocesadorAutomocion.procesar("BMW Serie B 2015")
        self.assertIn("Serie B 2015", res["texto_procesado"])
        self.assertNotIn("B2015", res["codigos_detectados"])

    def test_p0301_a_mayusculas(self):
        """4. 'p0301' en minúsculas debe normalizarse a 'P0301'."""
        res = PreprocesadorAutomocion.procesar("tengo fallo p0301 en el cilindro 1")
        self.assertIn("P0301", res["texto_procesado"])
        self.assertIn("P0301", res["codigos_detectados"])

    def test_golf_v_19_tdi_no_se_pega(self):
        """5. 'Golf V 1.9 TDI' no debe transformarse en 'Golf V1.9 TDI'."""
        res = PreprocesadorAutomocion.procesar("Manual del Golf V 1.9 TDI motor BXE")
        self.assertIn("Golf V 1.9 TDI", res["texto_procesado"])
        self.assertNotIn("Golf V1.9", res["texto_procesado"])

    def test_version_explicita_se_normaliza(self):
        """Versión explícita sí se normaliza."""
        res = PreprocesadorAutomocion.procesar("manual versión 1.2 del sistema")
        self.assertIn("V1.2", res["texto_procesado"])
        self.assertIn("V1.2", res["versiones_detectadas"])

    def test_buenas_tardes_se_limpia_completamente(self):
        """6. 'buenas tardes, ...' debe limpiarse por completo sin dejar 'tardes'."""
        res = PreprocesadorAutomocion.procesar("buenas tardes, necesito el par de apriete")
        self.assertFalse(res["texto_procesado"].startswith("tardes"))
        self.assertTrue(res["texto_procesado"].startswith("necesito") or "par de apriete" in res["texto_procesado"])

    def test_buenos_dias_se_limpia_completamente(self):
        """'buenos días' y 'buenos dias' con o sin tilde se limpian."""
        res1 = PreprocesadorAutomocion.procesar("buenos días, presión de frenos")
        self.assertEqual(res1["texto_procesado"], "presión de frenos")

        res2 = PreprocesadorAutomocion.procesar("buenos dias, presión de frenos")
        self.assertEqual(res2["texto_procesado"], "presión de frenos")


class TestSimuladorAgente2(unittest.TestCase):
    """Pruebas del mock/simulador del Agente 2."""

    def test_simulador_con_valores_null(self):
        """7. El simulador no debe lanzar AttributeError con filtros o query en null/None."""
        query_con_nulls = {
            "accion": "BUSCAR",
            "query_busqueda": None,
            "intencion": "especificacion",
            "filtros": None,
            "equipo": None
        }
        res = simulador_agente_2(query_con_nulls)
        self.assertEqual(res, [])

    def test_simulador_con_filtros_vacios(self):
        """Simulador con filtros como dict vacío."""
        query_vacia = {"query_busqueda": "", "filtros": {}}
        res = simulador_agente_2(query_vacia)
        self.assertEqual(res, [])

    def test_simulador_recupera_evidencia_culata(self):
        """Caso 1: Simulador devuelve evidencia vigente cuando busca culata."""
        query = {"query_busqueda": "par apriete culata", "filtros": {"componente": "culata"}}
        res = simulador_agente_2(query)
        self.assertEqual(res["estado"], "suficiente")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["chunk_id"], "chunk_01")
        self.assertEqual(res[0]["estado_documento"], "vigente")

    def test_simulador_caso_sin_evidencia(self):
        """Caso 2: Consulta sin manual devuelve estado sin_evidencia y lista vacía."""
        query = {"texto_busqueda": "manual de instalacion aleron de titanio", "filtros": {}}
        res = simulador_agente_2(query)
        self.assertEqual(res["estado"], "sin_evidencia")
        self.assertEqual(len(res["evidencias"]), 0)
        self.assertIsNone(res["mensaje_error"])

    def test_simulador_caso_varias_versiones(self):
        """Caso 3: Varias versiones devuelve estado ambiguo y chunks de distintas versiones."""
        query = {"texto_busqueda": "presion circuito primario", "filtros": {"version": None}}
        res = simulador_agente_2(query)
        self.assertEqual(res["estado"], "ambiguo")
        self.assertEqual(res["campo_ambiguo"], "version")
        versiones = [ev["metadata"]["version"] for ev in res["evidencias"]]
        self.assertIn("V1.0", versiones)
        self.assertIn("V1.1", versiones)

    def test_simulador_caso_documentos_obsoletos(self):
        """Caso 4: Devuelve documento obsoleto y vigente para que Agente 1 filtre."""
        query = {"texto_busqueda": "procedimiento refrigerante htm-0142", "filtros": {"codigos": ["HTM-0142"]}}
        res = simulador_agente_2(query)
        self.assertEqual(res["estado"], "suficiente")
        estados_doc = [ev["estado_documento"] for ev in res["evidencias"]]
        self.assertIn("obsoleto", estados_doc)
        self.assertIn("vigente", estados_doc)

    def test_simulador_caso_error_tecnico(self):
        """Caso 5: Error técnico devuelve estado error con mensaje y NUNCA se confunde con vacío."""
        query = {"texto_busqueda": "simular_error en busqueda", "filtros": {}}
        res = simulador_agente_2(query)
        self.assertEqual(res["estado"], "error")
        self.assertIsNotNone(res["mensaje_error"])
        self.assertIn("Error", res["mensaje_error"])


class TestValidacionEsquemaQueryJSON(unittest.TestCase):
    """Validación del contrato CTR-004."""

    def test_query_json_valido_ctr004(self):
        """Valida que un JSON con la estructura oficial CTR-004 pase correctamente."""
        query_valida = {
            "trace_id": "t-9f3a21",
            "conversacion_id": "c-0001",
            "texto_busqueda": "par apriete tornillos culata Golf 1.6 TDI",
            "pregunta_original": "cual es el par de apriete de culata golf 1.6",
            "intencion": "especificacion",
            "filtros": {
                "version": "V1.1",
                "componente": "culata",
                "tipo_documento": "ficha_tecnica",
                "codigos": ["HTM-0142"]
            },
            "opciones": {
                "top_k": 3,
                "incluir_obsoletos": True
            }
        }
        es_valido, error, data = validar_esquema_query_json(query_valida)
        self.assertTrue(es_valido, f"Error inesperado: {error}")
        self.assertIsNone(error)
        self.assertEqual(data["trace_id"], "t-9f3a21")
        self.assertEqual(data["filtros"]["codigos"], ["HTM-0142"])
        self.assertEqual(data["opciones"]["top_k"], 3)

    def test_query_json_invalido_texto_busqueda_vacio(self):
        """Texto de búsqueda vacío debe fallar validación."""
        query_invalida = {
            "trace_id": "t-123456",
            "conversacion_id": "c-0001",
            "texto_busqueda": "   ",
            "pregunta_original": "test",
            "intencion": "diagnostico"
        }
        es_valido, error, _ = validar_esquema_query_json(query_invalida)
        self.assertFalse(es_valido)
        self.assertIsNotNone(error)

    def test_query_json_invalido_intencion_desconocida(self):
        """Intención fuera del conjunto permitido debe fallar."""
        query_invalida = {
            "trace_id": "t-123456",
            "conversacion_id": "c-0001",
            "texto_busqueda": "test",
            "pregunta_original": "test",
            "intencion": "inventada"
        }
        es_valido, error, _ = validar_esquema_query_json(query_invalida)
        self.assertFalse(es_valido)

    def test_query_json_compatibilidad_query_busqueda(self):
        """Soporta retrocompatibilidad si viene query_busqueda en vez de texto_busqueda."""
        query_legacy = {
            "query_busqueda": "Golf 7 fallo P0301",
            "intencion": "diagnostico",
            "filtros": {"componente": "encendido"}
        }
        es_valido, error, data = validar_esquema_query_json(query_legacy)
        self.assertTrue(es_valido)
        self.assertIsNone(error)
        self.assertEqual(data["texto_busqueda"], "Golf 7 fallo P0301")


class TestVerificadorCitas(unittest.TestCase):
    """Pruebas del verificador determinista de citas (A1-07)."""

    def setUp(self):
        self.evidencias = [
            {"chunk_id": "chunk_01", "texto": "Apretar culata a 40 Nm"},
            {"chunk_id": "chunk_02", "texto": "Fase 2 a 90 grados"}
        ]

    def test_citas_validas(self):
        """El texto cita únicamente chunks presentes en las evidencias."""
        texto = "Procedimiento: Fase 1 a 40 Nm [chunk_01] y luego 90° [chunk_02]."
        res = verificar_citas(texto, self.evidencias)
        self.assertTrue(res["valido"])
        self.assertEqual(set(res["citas_validas"]), {"chunk_01", "chunk_02"})
        self.assertEqual(res["citas_falsas"], [])

    def test_citas_alucinadas_rechazadas(self):
        """Si el LLM cita un chunk inexistente, debe ser detectado como alucinación."""
        texto = "Procedimiento según manual [chunk_01] y apriete final [chunk_99]."
        res = verificar_citas(texto, self.evidencias)
        self.assertFalse(res["valido"])
        self.assertEqual(res["citas_validas"], ["chunk_01"])
        self.assertIn("chunk_99", res["citas_falsas"])

    def test_sin_citas_rechazado(self):
        """Si el texto no incluye ninguna cita entre corchetes, debe fallar."""
        texto = "Procedimiento: apretar la culata a 40 Nm sin especificar fuente."
        res = verificar_citas(texto, self.evidencias)
        self.assertFalse(res["valido"])
        self.assertEqual(res["citas_detectadas"], [])
        self.assertEqual(res["citas_validas"], [])


if __name__ == "__main__":
    unittest.main()

