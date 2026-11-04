"""Regresiones de integración PR8/PR9. Dobles locales: no requieren red ni LLM."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch, mock_open

from Agents.agente1 import core
from Test.test_Models.evaluar_benchmark import EvaluadorBenchmarkCJ02, crear_pipeline_local

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'Test/test_Models/benchmark_completo_CJ02_40_preguntas.json'


def agente(*respuestas):
    with patch.object(core, 'OpenAI', None):
        obj = core.Agente1(conversacion_id='c-test')
    obj._consultar_llm = Mock(side_effect=respuestas)
    return obj


def consulta(**extra):
    return {'texto_busqueda': 'par culata', 'intencion': 'especificacion', **extra}


def evidencia(cid='c_1', version='V2.0', **extra):
    return {'chunk_id': cid, 'texto': 'Valor de prueba: 20 Nm.',
            'metadata': {'documento': 'doc-test', 'pagina': 2, 'seccion': 'prueba',
                         'version': version, 'obsoleto': False}, **extra}


class PreprocesadoIntegracion(unittest.TestCase):
    def test_version_prefijada_sin_doble_v(self):
        for entrada in ('versión V1.1', 'version v1.1', 'ver. 1.1'):
            with self.subTest(entrada=entrada):
                res = core.PreprocesadorAutomocion.procesar(entrada)
                self.assertEqual(res['texto_procesado'], 'V1.1')
                self.assertEqual(res['versiones_detectadas'], ['V1.1'])

    def test_version_completa(self):
        self.assertEqual(core.PreprocesadorAutomocion.procesar('versión 1.2.3')['versiones_detectadas'], ['V1.2.3'])

    def test_motor_no_es_version(self):
        self.assertEqual(core.PreprocesadorAutomocion.procesar('motor V6 y V8')['versiones_detectadas'], [])
        self.assertEqual(core.PreprocesadorAutomocion.procesar('versión V6')['versiones_detectadas'], ['V6'])

    def test_saludo_no_corrompe_palabra(self):
        self.assertEqual(core.PreprocesadorAutomocion.procesar('Holanda')['texto_procesado'], 'Holanda')

    def test_codigos_orden_y_duplicados(self):
        res = core.PreprocesadorAutomocion.procesar('p0301 ref ab12 htm 0142 P0301')
        self.assertEqual(res['codigos_detectados'], ['P0301', 'REF-AB12', 'HTM-0142'])


class ContratosIntegracion(unittest.TestCase):
    def test_rechaza_tipos_y_rangos(self):
        casos = [consulta(opciones={'top_k': k}) for k in (0, -1, True, '3', 1.5)]
        casos += [consulta(opciones={'incluir_obsoletos': b}) for b in ('false', 0, None)]
        casos += [consulta(filtros=f) for f in (None, [], {'codigos': 'P0301'}, {'codigos': [1]}, {'version': 2})]
        casos += [consulta(opciones=[]), consulta(trace_id=[]), consulta(pregunta_original=3), []]
        for caso in casos:
            with self.subTest(caso=caso):
                valido, error, data = core.validar_esquema_query_json(caso)
                self.assertFalse(valido)
                self.assertIsNotNone(error)
                self.assertIsNone(data)

    def test_alias_canonico(self):
        entrada = {'query_busqueda': 'P0301', 'intencion': 'dtc'}
        ok, _, data = core.validar_esquema_query_json(entrada)
        self.assertTrue(ok)
        self.assertEqual(data['texto_busqueda'], 'P0301')
        self.assertEqual(data['intencion'], 'diagnostico')
        self.assertNotIn('texto_busqueda', entrada)
        self.assertEqual(set(data), {'trace_id', 'conversacion_id', 'texto_busqueda', 'pregunta_original', 'intencion', 'filtros', 'opciones'})

    @unittest.skipUnless(core.HAS_PYDANTIC, 'Pydantic v2 opcional no instalado')
    def test_paridad_pydantic_y_respaldo(self):
        entrada = consulta(trace_id='t-test', pregunta_original='culata')
        primero = core.validar_esquema_query_json(entrada)
        with patch.object(core, 'HAS_PYDANTIC', False):
            segundo = core.validar_esquema_query_json(entrada)
        self.assertEqual(primero, segundo)

    def test_simulador_errores_entrada(self):
        for query in ([], {'texto_busqueda': 2}, {'filtros': []}, {'opciones': {'top_k': False}}):
            with self.subTest(query=query):
                self.assertEqual(core.simulador_agente_2(query)['estado'], 'error')

    def test_simulador_filtra_version_explicita(self):
        for version in ('V1.0', 'V1.1'):
            res = core.simulador_agente_2(consulta(texto_busqueda='presion circuito primario', filtros={'version': version}))
            self.assertEqual(res['estado'], 'suficiente')
            self.assertEqual({e['metadata']['version'] for e in res['evidencias']}, {version})
        res = core.simulador_agente_2(consulta(texto_busqueda='presion circuito primario', filtros={'version': 'V9.9'}))
        self.assertEqual(res['estado'], 'sin_evidencia')

    def test_simulador_no_oculta_ambiguedad_por_topk(self):
        res = core.simulador_agente_2(consulta(texto_busqueda='presion circuito primario', opciones={'top_k': 1}))
        self.assertEqual(res['estado'], 'ambiguo')
        self.assertEqual(len(res['evidencias']), 2)

    def test_simulador_excluye_obsoletos_y_serializa_json(self):
        res = core.simulador_agente_2(consulta(texto_busqueda='refrigerante', opciones={'incluir_obsoletos': False, 'top_k': 1}))
        self.assertEqual(len(res['evidencias']), 1)
        self.assertFalse(core.es_obsoleta(res['evidencias'][0]))
        self.assertEqual(json.loads(json.dumps(res))['estado'], 'suficiente')
        vacio = core.simulador_agente_2(consulta(texto_busqueda='desconocido'))
        self.assertEqual(json.loads(json.dumps(vacio))['estado'], 'sin_evidencia')


class OrquestacionIntegracion(unittest.TestCase):
    def setUp(self):
        self.parche_auditoria = patch.object(core, 'registrar_turno_auditoria')
        self.parche_auditoria.start()
        self.addCleanup(self.parche_auditoria.stop)

    def test_json_truncado_no_es_aclaracion(self):
        self.assertEqual(agente('{"texto_busqueda": "culata"').procesar_consulta('culata')['estado'], 'error')

    def test_entrada_vacia_no_invoca_modelo(self):
        obj = agente()
        for pregunta in (' ', None, 3):
            self.assertEqual(obj.procesar_consulta(pregunta)['estado'], 'error')
        obj._consultar_llm.assert_not_called()

    def test_modelo_inaccesible(self):
        self.assertEqual(agente(None).procesar_consulta('culata')['estado'], 'error')

    def test_version_regex_prevalece_y_codigos_se_conservan(self):
        obj = agente(json.dumps(consulta(filtros={'version': 'V9.9', 'codigos': ['REF-A1']})))
        res = obj.procesar_consulta('par culata versión V1.1 p0301')
        self.assertEqual(res['estado'], 'valida')
        self.assertEqual(res['query_json']['filtros']['version'], 'V1.1')
        self.assertEqual(res['query_json']['filtros']['codigos'], ['REF-A1', 'P0301'])
        self.assertEqual(res['query_json']['conversacion_id'], 'c-test')

    def test_varias_versiones_piden_aclaracion(self):
        res = agente(json.dumps(consulta())).procesar_consulta('comparar V1.0 y V1.1')
        self.assertEqual(res['estado'], 'aclaracion')

    def test_modelo_con_contrato_invalido(self):
        for datos in (consulta(filtros=[]), consulta(filtros={'codigos': [{}]}), consulta(opciones=[])):
            with self.subTest(datos=datos):
                self.assertEqual(agente(json.dumps(datos)).procesar_consulta('culata')['estado'], 'error')

    def test_historial_limitado_y_reset_aislado(self):
        obj = agente('¿Qué vehículo?', json.dumps(consulta()))
        obj.max_turnos = 1
        obj.procesar_consulta('par culata')
        obj.procesar_consulta('Golf 7')
        self.assertEqual(len(obj.historial), 2)
        self.assertIn('¿Qué vehículo?', [m['content'] for m in obj._consultar_llm.call_args.args[0]])
        otro = agente()
        obj.reset()
        self.assertEqual(obj.historial, [])
        self.assertEqual(otro.historial, [])

    def test_rechazo_adaptado_ctr001(self):
        res = core.consultar_asistente('receta', agente('INVALIDA'))
        self.assertEqual(res['estado'], 'fuera_de_ambito')
        self.assertEqual(res['fuentes'], [])

    def test_ctr001_compatible_frontend_y_agente2_sustituible(self):
        ev = evidencia()
        doble = Mock(return_value={'estado': 'suficiente', 'evidencias': [ev]})
        obj = agente(json.dumps(consulta()), 'Valor de prueba: 20 Nm [c_1].')
        res = core.consultar_asistente('par culata', obj, doble)
        self.assertEqual(res['estado'], 'respuesta')
        self.assertEqual(set(res), {'trace_id', 'estado', 'texto', 'fuentes', 'codigo_error'})
        self.assertEqual(res['fuentes'][0], {'chunk_id': 'c_1', 'documento': 'doc-test', 'seccion': 'prueba', 'pagina': 2, 'versiones': ['V2.0'], 'obsoleto': False})
        self.assertEqual(doble.call_args.args[0]['texto_busqueda'], 'par culata')
        # Cargar los modelos reales de frontend sin arrancar Qt ni modificar su código.
        with patch.dict(sys.modules):
            sys.path.insert(0, str(ROOT / 'Frontend'))
            try:
                from models.response import Response
                parsed = Response.from_dict(json.loads(json.dumps(res)))
                self.assertEqual(parsed.estado, 'respuesta')
                self.assertEqual(parsed.fuentes[0].chunk_id, 'c_1')
            finally:
                sys.path.pop(0)

    def test_excepcion_agente2_no_es_sin_evidencia(self):
        with self.assertLogs('Agente1', level='ERROR'):
            res = core.consultar_asistente('culata', agente(json.dumps(consulta())), Mock(side_effect=TimeoutError))
        self.assertEqual(res['estado'], 'error')
        self.assertTrue(res['codigo_error'])

    def test_aclaracion_dinamica_sin_evidencias(self):
        obj = agente()
        res = core.resolver_evidencias('presion', {'estado': 'ambiguo', 'evidencias': [], 'campo_ambiguo': 'componente'}, obj)
        self.assertEqual(res['estado'], 'aclaracion')
        self.assertIn('componente', res['texto'])
        self.assertNotIn('V1.0', res['texto'])
        obj._consultar_llm.assert_not_called()

    def test_aclaracion_versiones_reales(self):
        res = core.resolver_evidencias('presion', {'estado': 'ambiguo', 'evidencias': [evidencia('c_3', version='V3.0'), evidencia('c_4', version='V4.0')]}, agente())
        self.assertIn('V3.0', res['texto'])
        self.assertIn('V4.0', res['texto'])

    def test_estados_a2_sin_modelo(self):
        for estado, esperado in (('error', 'error'), ('sin_evidencia', 'sin_evidencia'), ('insuficiente', 'sin_evidencia'), ('desconocido', 'error')):
            obj = agente()
            res = core.resolver_evidencias('culata', {'estado': estado, 'evidencias': []}, obj)
            self.assertEqual(res['estado'], esperado)
            obj._consultar_llm.assert_not_called()

    def test_evidencias_malformadas(self):
        for respuesta in ([], {'estado': [], 'evidencias': []}, {'estado': 'suficiente', 'evidencias': ['error']}, {'estado': 'suficiente', 'evidencias': [{}]}):
            self.assertEqual(core.resolver_evidencias('culata', respuesta, agente())['estado'], 'error')

    def test_fuentes_json_rechazan_metadatos_invalidos(self):
        for campos in ({'pagina': True}, {'pagina': -1}, {'documento': []},
                       {'versiones': [None]}, {'obsoleto': 'false'}, {'sustituido_por': {}}):
            with self.subTest(campos=campos):
                ev = evidencia()
                ev['metadata'].update(campos)
                obj = agente()
                res = core.resolver_evidencias('culata', {'estado': 'suficiente', 'evidencias': [ev]}, obj)
                self.assertEqual(res['estado'], 'error')
                obj._consultar_llm.assert_not_called()

    def test_solo_obsoleto_avisa_y_mixto_filtra(self):
        viejo = evidencia('old', estado_documento='sustituido')
        for evidencias, texto, fuentes in (([viejo], 'Valor de prueba: 20 Nm [old]', ['old']), ([viejo, evidencia()], 'Valor de prueba: 20 Nm [c_1]', ['c_1'])):
            obj = agente(texto)
            res = core.resolver_evidencias('culata', {'estado': 'suficiente', 'evidencias': evidencias}, obj)
            self.assertEqual(res['fuentes'], fuentes)
            self.assertEqual('OBSOLETA' in res['texto'], len(evidencias) == 1)
            if len(evidencias) > 1:
                self.assertNotIn('EVIDENCIA [old]', obj._consultar_llm.call_args.args[0][1]['content'])

    def test_obsoleto_metadata_y_sustitucion(self):
        for meta in ({'obsoleto': True}, {'sustituido_por': 'doc-new'}):
            ev = evidencia()
            ev['metadata'].update(meta)
            self.assertTrue(core.es_obsoleta(ev))

    def test_consola_reutiliza_decision_sin_estado_documento(self):
        obj = agente(json.dumps(consulta()), 'Valor de prueba: 20 Nm [c_1]')
        with contextlib.redirect_stdout(io.StringIO()), patch.object(core, 'registrar_turno_auditoria') as auditoria:
            res = core.ejecutar_paso_a_paso('culata', obj, lambda q: {'estado': 'suficiente', 'evidencias': [evidencia()]})
        self.assertEqual(res['respuesta_final']['estado'], 'respuesta')
        auditoria.assert_called_once()

    def test_auditoria_tolerante_y_jsonl(self):
        self.parche_auditoria.stop()
        with patch('builtins.open', mock_open()) as archivo:
            core.registrar_turno_auditoria({'trace_id': 't-test'})
            self.assertEqual(json.loads(archivo().write.call_args.args[0]), {'trace_id': 't-test'})
        with patch('builtins.open', side_effect=OSError), self.assertLogs('Agente1', level='WARNING'):
            core.registrar_turno_auditoria({})


class ClienteHTTPIntegracion(unittest.TestCase):
    def test_cliente_nativo_v1_configuracion(self):
        obj = agente()
        # Recuperar el método real en lugar del doble del helper.
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        respuesta = Mock()
        respuesta.read.return_value = json.dumps({'choices': [{'message': {'content': 'INVALIDA'}}]}).encode()
        with patch.object(core.urllib.request, 'urlopen') as peticion:
            peticion.return_value.__enter__.return_value = respuesta
            self.assertEqual(obj._consultar_llm([{'role': 'user', 'content': 'hola'}]), 'INVALIDA')
            req = peticion.call_args.args[0]
            self.assertEqual(req.full_url, 'http://localhost:11434/v1/chat/completions')
            self.assertEqual(json.loads(req.data)['max_tokens'], 512)
            self.assertGreater(peticion.call_args.kwargs['timeout'], 0)
            self.assertLessEqual(peticion.call_args.kwargs['timeout'], 60)

    def test_fallback_ollama_nativo_sin_red(self):
        obj = agente()
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        respuesta = Mock()
        respuesta.read.return_value = b'{"message":{"content":"INVALIDA"}}'
        contexto = Mock()
        contexto.__enter__ = Mock(return_value=respuesta)
        contexto.__exit__ = Mock(return_value=False)
        with patch.object(core.urllib.request, 'urlopen', side_effect=[TimeoutError('prueba'), contexto]) as peticion:
            self.assertEqual(obj._consultar_llm([]), 'INVALIDA')
            req = peticion.call_args.args[0]
            self.assertEqual(req.full_url, 'http://localhost:11434/api/chat')
            self.assertEqual(json.loads(req.data)['options']['num_predict'], 512)

    def test_error_en_ambos_endpoints(self):
        obj = agente()
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        with patch.object(core.urllib.request, 'urlopen', side_effect=TimeoutError('prueba')) as peticion:
            self.assertIsNone(obj._consultar_llm([]))
            self.assertEqual(peticion.call_count, 2)


class CitasIntegracion(unittest.TestCase):
    def test_cita_desconocida_no_se_ignora(self):
        for falsa in ('c_999', 'ABC', 'otro-id', 'chunk_99', 'HTM240@1.0_p1'):
            with self.subTest(falsa=falsa):
                res = core.verificar_citas(f'Dato [c_1] [{falsa}]', [evidencia()])
                self.assertFalse(res['valido'])
                self.assertIn(falsa, res['citas_falsas'])

    def test_citas_agrupadas(self):
        self.assertTrue(core.verificar_citas('Dato [c_1, c_2]', [evidencia(), evidencia('c_2')])['valido'])

    def test_reintento_correcto(self):
        obj = agente('Dato [c_999]', 'Valor de prueba: 20 Nm [c_1]')
        res = core.redactar_respuesta_con_verificacion('culata', [evidencia()], obj)
        self.assertEqual(res['estado'], 'respuesta')
        self.assertEqual(res['reintentos'], 1)
        self.assertEqual(obj._consultar_llm.call_count, 2)

    def test_reintento_fallido_informa_ultima_verificacion(self):
        obj = agente('Dato [c_999]', 'Dato [c_888]')
        res = core.redactar_respuesta_con_verificacion('culata', [evidencia()], obj)
        self.assertEqual(res['estado'], 'error_verificacion')
        self.assertEqual(res['verificacion']['citas_falsas'], ['c_888'])
        self.assertEqual(res['fuentes'], [])

    def test_redactor_inaccesible_y_sin_evidencias(self):
        self.assertEqual(core.redactar_respuesta_con_verificacion('culata', [evidencia()], agente(None))['estado'], 'error')
        obj = agente()
        self.assertEqual(core.redactar_respuesta_con_verificacion('culata', [], obj)['estado'], 'sin_evidencia')
        obj._consultar_llm.assert_not_called()


class BenchmarkIntegracion(unittest.TestCase):
    def setUp(self):
        parche = patch.object(core, 'registrar_turno_auditoria')
        parche.start()
        self.addCleanup(parche.stop)
        self.evaluador = EvaluadorBenchmarkCJ02(DATASET)
        self.caso = self.evaluador.preguntas[1]

    def test_adaptador_local_vincula_pipeline_con_benchmark(self):
        pipeline = crear_pipeline_local(lambda: agente(json.dumps(consulta()), 'Valor de prueba: 20 Nm [c_1]'),
                                       lambda q: {'estado': 'suficiente', 'evidencias': [evidencia()]},
                                       simulado=True)
        res = pipeline({'pregunta_usuario': 'par culata'})
        self.assertEqual(res['estado_agente2'], 'suficiente')
        self.assertEqual(res['chunks_recuperados'], ['c_1'])
        self.assertTrue(res['simulado'])

    def test_adaptador_local_normaliza_sin_evidencia(self):
        pipeline = crear_pipeline_local(lambda: agente(json.dumps(consulta())),
                                       lambda q: {'estado': 'sin_evidencia', 'evidencias': []}, simulado=True)
        self.assertEqual(pipeline({'pregunta_usuario': 'par culata'})['estado_agente2'], 'insuficiente')

    def test_dataset_40_ids_unicos(self):
        self.assertEqual(len({p['id_pregunta'] for p in self.evaluador.preguntas}), 40)

    def test_simulacion_debe_ser_explicita(self):
        with self.assertRaises(ValueError):
            self.evaluador.ejecutar_benchmark()
        res = self.evaluador.ejecutar_benchmark(simulacion=True)
        self.assertEqual(res['modo'], 'simulacion_oraculo')
        self.assertFalse(res['certifica_modelo_real'])
        self.assertEqual(res['total_preguntas'], 40)

    def test_pipeline_no_recibe_ground_truth_y_excepciones_cuentan(self):
        entradas = []
        def pipeline(entrada):
            entradas.append(entrada)
            raise TimeoutError('doble de prueba')
        reporte = self.evaluador.ejecutar_benchmark(pipeline, procedencia='doble local de prueba, sin LLM')
        self.assertEqual(reporte['total_pasadas'], 0)
        self.assertEqual(len(entradas), 40)
        self.assertTrue(all(set(e) == {'id_pregunta', 'pregunta_usuario'} for e in entradas))
        self.assertTrue(all('error_ejecucion' in r for r in reporte['detalle_casos']))

    def test_cita_falsa_no_se_compensa_con_correcta(self):
        respuesta = self.evaluador.simular_agente_pipeline(self.caso)
        respuesta['respuesta_generada'] += ' [c_999]'
        self.assertFalse(self.evaluador.evaluar_caso(self.caso, respuesta)['pasado'])

    def test_cita_debe_haber_sido_recuperada(self):
        respuesta = self.evaluador.simular_agente_pipeline(self.caso)
        respuesta['chunks_recuperados'] = []
        self.assertFalse(self.evaluador.evaluar_caso(self.caso, respuesta)['citas_ok'])

    def test_ambiguo_no_acepta_citas_inventadas(self):
        caso = next(p for p in self.evaluador.preguntas if p['estado_esperado_agente2'] == 'ambiguo')
        respuesta = self.evaluador.simular_agente_pipeline(caso)
        respuesta['respuesta_generada'] = '¿Qué versión? [c_999]'
        self.assertFalse(self.evaluador.evaluar_caso(caso, respuesta)['pasado'])
        respuesta['respuesta_generada'] = '¿Qué versión?'
        respuesta['campo_aclaracion'] = 'otro'
        self.assertFalse(self.evaluador.evaluar_caso(caso, respuesta)['pasado'])

    def test_contrato_de_respuesta_malformada(self):
        for datos in (None, [], {'respuesta_generada': 2}, {'chunks_recuperados': [{}]}):
            self.assertFalse(self.evaluador.evaluar_caso(self.caso, datos)['pasado'])

    def test_oraculo_no_se_admite_como_externo(self):
        res = self.evaluador.ejecutar_benchmark(lambda e: {'simulado': True}, procedencia='doble de prueba')
        self.assertEqual(res['total_pasadas'], 0)

    def test_informes_no_sobrescriben_dataset_o_ejecuciones(self):
        with self.assertRaises(ValueError):
            self.evaluador.ejecutar_benchmark(simulacion=True, salida=DATASET)
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / 'simulacion.json'
            self.evaluador.ejecutar_benchmark(simulacion=True, salida=destino)
            self.assertEqual(json.loads(destino.read_text(encoding='utf-8'))['modo'], 'simulacion_oraculo')
            with self.assertRaises(FileExistsError):
                self.evaluador.ejecutar_benchmark(simulacion=True, salida=destino)


if __name__ == '__main__':
    unittest.main()
