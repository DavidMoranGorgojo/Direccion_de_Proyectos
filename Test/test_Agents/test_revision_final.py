"""Regresiones de la revisión final; sin red ni archivos de resultados persistentes."""
import contextlib
import io
import json
import os
import unittest
from unittest.mock import Mock, mock_open, patch

from Agents.agente1 import core
from Test.test_Agents.test_integracion_pr8_pr9 import agente, consulta, evidencia
from Test.test_Models.evaluar_benchmark import crear_pipeline_local

QUERY = json.dumps(consulta())
TEXTO = 'Valor de prueba: 20 Nm [c_1].'


def recuperar(q):
    return {'estado': 'suficiente', 'evidencias': [evidencia()]}


class RevisionFinal(unittest.TestCase):
    def setUp(self):
        self.registrar_real = core.registrar_turno_auditoria
        parche = patch.object(core, 'registrar_turno_auditoria')
        self.auditoria = parche.start()
        self.addCleanup(parche.stop)

    def test_audita_todos_los_resultados_una_vez_por_ruta(self):
        casos = [
            ((QUERY, TEXTO), recuperar, 'respuesta'),
            (('INVALIDA',), recuperar, 'fuera_de_ambito'),
            ((QUERY,), lambda q: {'estado': 'sin_evidencia', 'evidencias': []}, 'sin_evidencia'),
            (('¿Qué vehículo?',), recuperar, 'aclaracion'),
            ((None,), recuperar, 'error'),
            ((QUERY,), Mock(side_effect=TimeoutError('secreto')), 'error'),
            ((QUERY, '999 bar [c_1]', '999 bar [c_1]'), recuperar, 'error'),
        ]
        for ruta in (core.consultar_asistente, core.ejecutar_paso_a_paso):
            for respuestas, a2, esperado in casos:
                with self.subTest(ruta=ruta.__name__, esperado=esperado):
                    self.auditoria.reset_mock()
                    with contextlib.redirect_stdout(io.StringIO()):
                        ruta('consulta con secreto-no-registrable', agente(*respuestas), a2)
                    self.auditoria.assert_called_once()
                    registro = self.auditoria.call_args.args[0]
                    self.assertEqual(registro['estado'], esperado)
                    self.assertEqual(set(registro), {'trace_id', 'conversacion_id', 'estado',
                                     'codigo_error', 'estado_agente2', 'fuentes', 'latencia_ms'})
                    self.assertNotIn('secreto', json.dumps(registro))

    def test_jsonl_real_un_registro_por_turno(self):
        with patch.object(core, 'registrar_turno_auditoria', self.registrar_real), patch('builtins.open', mock_open()) as archivo:
            core.consultar_asistente('hola', agente('INVALIDA'))
            escrituras = archivo().write.call_args_list
            self.assertEqual(len(escrituras), 1)
            linea = escrituras[0].args[0]
            self.assertTrue(linea.endswith('\n'))
            self.assertEqual(json.loads(linea)['estado'], 'fuera_de_ambito')

    def test_dos_aclaraciones_a1_y_abstencion(self):
        obj = agente('¿Qué vehículo?', '¿Qué motor?', '¿Qué versión?')
        resultados = [core.consultar_asistente('respuesta incompleta', obj)['estado'] for _ in range(3)]
        self.assertEqual(resultados, ['aclaracion', 'aclaracion', 'sin_evidencia'])
        self.assertEqual(obj.historial, [])
        self.assertFalse(obj.consulta_pendiente)
        self.assertEqual(self.auditoria.call_count, 3)

    def test_dos_aclaraciones_a2_y_abstencion(self):
        obj = agente(QUERY, QUERY, QUERY)
        a2 = lambda q: {'estado': 'ambiguo', 'evidencias': [], 'campo_ambiguo': 'componente'}
        resultados = [core.consultar_asistente('respuesta incompleta', obj, a2)['estado'] for _ in range(3)]
        self.assertEqual(resultados, ['aclaracion', 'aclaracion', 'sin_evidencia'])
        self.assertIsNone(obj._query_pendiente)

    def test_limite_compartido_aclaraciones_a1_y_a2(self):
        obj = agente('¿Qué motor?', QUERY, QUERY)
        a2 = lambda q: {'estado': 'ambiguo', 'evidencias': [], 'campo_ambiguo': 'version'}
        self.assertEqual(core.consultar_asistente('culata', obj, a2)['estado'], 'aclaracion')
        self.assertEqual(core.consultar_asistente('Golf', obj, a2)['estado'], 'aclaracion')
        self.assertEqual(core.consultar_asistente('no sé', obj, a2)['estado'], 'sin_evidencia')

    def test_nueva_consulta_explicita_descarta_pendiente(self):
        obj = agente('¿Qué versión?', '¿Qué motor?')
        core.consultar_asistente('filtro anterior', obj)
        core.consultar_asistente('culata nueva', obj, nueva_consulta=True)
        self.assertEqual(obj.aclaraciones_consecutivas, 1)
        mensajes = obj._consultar_llm.call_args.args[0]
        self.assertNotIn('filtro anterior', json.dumps(mensajes))

    def test_marcador_natural_inicia_nueva_consulta(self):
        obj = agente('¿Qué versión?', '¿Qué motor?')
        core.consultar_asistente('filtro anterior', obj)
        core.consultar_asistente('Gracias, ahora otra duda: culata', obj)
        self.assertEqual(obj.aclaraciones_consecutivas, 1)
        self.assertNotIn('filtro anterior', json.dumps(obj._consultar_llm.call_args.args[0]))

    def test_aclaracion_resuelta_y_nueva_pregunta_no_mezclan_contexto(self):
        obj = agente('¿Qué vehículo?', QUERY, TEXTO, 'INVALIDA')
        core.consultar_asistente('par de culata anterior', obj)
        self.assertEqual(core.consultar_asistente('Golf 7', obj, recuperar)['estado'], 'respuesta')
        self.assertEqual(obj.historial, [])
        core.consultar_asistente('pregunta independiente', obj)
        self.assertEqual(len(obj._consultar_llm.call_args.args[0]), 2)

    def test_respuesta_version_conserva_query_y_codigos_pendientes(self):
        for entrada in ('Es la versión V1.1', 'V1.1', 'v1.1'):
            with self.subTest(entrada=entrada):
                query = json.dumps(consulta(filtros={'codigos': ['HTM-0142']}))
                obj = agente(query, TEXTO)
                recibidas = []
                def a2(q):
                    recibidas.append(q)
                    if len(recibidas) == 1:
                        return {'estado': 'ambiguo', 'evidencias': [], 'campo_ambiguo': 'version'}
                    return {'estado': 'suficiente', 'evidencias': [evidencia(version='V1.1')]}
                core.consultar_asistente('par culata HTM-0142', obj, a2)
                final = core.consultar_asistente(entrada, obj, a2)
                self.assertEqual(final['estado'], 'respuesta')
                self.assertEqual(recibidas[1]['texto_busqueda'], recibidas[0]['texto_busqueda'])
                self.assertEqual(recibidas[1]['filtros']['codigos'], ['HTM-0142'])
                self.assertEqual(recibidas[1]['filtros']['version'], 'V1.1')
                self.assertEqual(obj.historial, [])
                self.assertEqual(obj._consultar_llm.call_count, 2)

    def test_salida_terminal_limpia_memoria_en_errores_y_rechazo(self):
        for respuesta in ('INVALIDA', None, '{"texto_busqueda":'):
            obj = agente('¿Qué motor?', respuesta)
            core.consultar_asistente('culata', obj)
            core.consultar_asistente('respuesta incompleta', obj)
            self.assertEqual(obj.historial, [])
            self.assertEqual(obj.aclaraciones_consecutivas, 0)

    def test_malformados_controlados_en_ambas_rutas(self):
        casos = [None, [], {'estado': None, 'evidencias': []},
                 {'estado': 'suficiente', 'evidencias': None},
                 {'estado': [], 'evidencias': []}, {'estado': 'error', 'evidencias': [], 'extra': {1}},
                 {'estado': 'error', 'evidencias': [], 'extra': float('nan')}, {'estado': 'suficiente', 'evidencias': [{}]},
                 {'estado': 'suficiente', 'evidencias': []},
                 {'estado': 'ambiguo', 'evidencias': [], 'campo_ambiguo': []}]
        for ruta in (core.consultar_asistente, core.ejecutar_paso_a_paso):
            for respuesta in casos:
                with self.subTest(ruta=ruta.__name__, respuesta=respuesta):
                    self.auditoria.reset_mock()
                    with contextlib.redirect_stdout(io.StringIO()):
                        resultado = ruta('culata', agente(QUERY), lambda q: respuesta)
                    final = resultado if ruta is core.consultar_asistente else resultado['respuesta_ctr001']
                    self.assertEqual(final['estado'], 'error')
                    self.assertEqual(final['fuentes'], [])
                    self.assertTrue(final['codigo_error'])
                    self.auditoria.assert_called_once()

    def test_benchmark_controla_evidencias_none(self):
        pipeline = crear_pipeline_local(lambda: agente(QUERY),
                lambda q: {'estado': 'suficiente', 'evidencias': None}, simulado=True)
        res = pipeline({'pregunta_usuario': 'culata'})
        self.assertEqual(res['estado_agente2'], 'error')
        self.assertEqual(res['chunks_recuperados'], [])

    def test_identificador_duplicado_con_evidencias_distintas_es_error(self):
        res = core.resolver_evidencias('culata', {'estado': 'suficiente', 'evidencias':
              [evidencia(version='V1.0'), evidencia(version='V2.0')]}, agente())
        self.assertEqual(res['estado'], 'error')

    def test_version_solicitada_incompatible_no_se_redacta(self):
        obj = agente()
        res = core.resolver_evidencias('culata V1.1', recuperar(None), obj, version='V1.1')
        self.assertEqual(res['estado'], 'error')
        obj._consultar_llm.assert_not_called()

    def test_solo_version_compatible_se_entrega_al_redactor(self):
        obj = agente(TEXTO)
        res = core.resolver_evidencias('culata V1.1', {'estado': 'suficiente', 'evidencias':
                [evidencia('otra', version='V2.0'), evidencia(version='V1.1')]}, obj, version='V1.1')
        self.assertEqual(res['estado'], 'respuesta')
        self.assertNotIn('EVIDENCIA [otra]', obj._consultar_llm.call_args.args[0][1]['content'])

    def test_estado_obsoleto_con_metadatos_vigentes_es_error(self):
        self.assertEqual(core.resolver_evidencias('culata', {'estado': 'solo_obsoleto',
                         'evidencias': [evidencia()]}, agente())['estado'], 'error')

    def test_valor_inventado_con_id_real_se_abstiene(self):
        obj = agente('Valor de prueba: 999 Nm [c_1].', 'Valor de prueba: 999 Nm [c_1].')
        res = core.redactar_respuesta_con_verificacion('culata', [evidencia()], obj)
        self.assertEqual(res['estado'], 'error_verificacion')
        self.assertFalse(res['verificacion']['respaldo_extractivo'])
        self.assertEqual(res['fuentes'], [])

    def test_no_se_omite_negacion_condicion_signo_o_version(self):
        pares = [('No abrir el circuito caliente.', 'Abrir el circuito caliente [c_1].'),
                 ('Apretar a 20 Nm solo en frío.', 'Apretar a 20 Nm [c_1].'),
                 ('Temperatura mínima -10 °C.', 'Temperatura mínima 10 °C [c_1].'),
                 ('Aplicable a versión V1.1.', 'Aplicable a versión V2.0 [c_1].')]
        for fuente, texto in pares:
            with self.subTest(fuente=fuente):
                ev = evidencia()
                ev['texto'] = fuente
                self.assertFalse(core.verificar_respaldo_extractivo(texto, [ev]))

    def test_oracion_sin_cita_y_referencia_no_recuperada_fallan(self):
        self.assertFalse(core.verificar_respaldo_extractivo(TEXTO + ' Añadir aceite.', [evidencia()]))
        self.assertFalse(core.verificar_respaldo_extractivo('Valor de prueba: 20 Nm [no_recuperado].', [evidencia()]))

    def test_reintento_corrige_respaldo_y_encabezado_es_opcional(self):
        obj = agente('Valor de prueba: 999 Nm [c_1].', '**Procedimiento técnico**:\n' + TEXTO)
        res = core.redactar_respuesta_con_verificacion('culata', [evidencia()], obj)
        self.assertEqual(res['estado'], 'respuesta')
        self.assertEqual(res['reintentos'], 1)
        self.assertTrue(res['verificacion']['respaldo_extractivo'])

    def test_cita_agrupada_no_atribuye_afirmacion_a_fuente_ajena(self):
        otra = evidencia('c_2')
        otra['texto'] = 'La versión es V1.1.'
        self.assertFalse(core.verificar_respaldo_extractivo(
            'Valor de prueba: 20 Nm [c_1, c_2].', [evidencia(), otra]))

    def test_timeout_configurable_y_sdk_sin_reintentos(self):
        with patch.dict(os.environ, {'OLLAMA_TIMEOUT_S': '7'}), patch.object(core, 'OpenAI') as sdk:
            obj = core.Agente1()
            self.assertEqual(obj.timeout_s, 7)
            self.assertEqual(sdk.call_args.kwargs['timeout'], 7)
            self.assertEqual(sdk.call_args.kwargs['max_retries'], 0)
        with patch.object(core, 'OpenAI', None):
            self.assertEqual(core.Agente1(timeout_s=4).timeout_s, 4)
            for invalido in (0, -1, float('inf'), float('nan')):
                with self.assertRaises(ValueError):
                    core.Agente1(timeout_s=invalido)

    def test_fallbacks_no_renuevan_presupuesto(self):
        obj = agente()
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        reloj = [100.0]
        def timeout(req, *, timeout):
            reloj[0] += timeout
            raise TimeoutError('prueba')
        with patch.object(core.time, 'monotonic', side_effect=lambda: reloj[0]), patch.object(core.urllib.request, 'urlopen', side_effect=timeout) as llamada:
            with obj.presupuesto_llm():
                self.assertIsNone(obj._consultar_llm([]))
                self.assertIsNone(obj._consultar_llm([]))
            self.assertEqual(llamada.call_count, 1)
            self.assertEqual(llamada.call_args.kwargs['timeout'], 10)
            self.assertIsNone(obj._deadline_llm)

    def test_sdk_y_http_comparten_presupuesto_restante(self):
        obj = agente()
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        obj.cliente = Mock()
        reloj = [100.0]
        def sdk(**kwargs):
            reloj[0] += 6
            raise TimeoutError('prueba')
        def http(req, *, timeout):
            self.assertEqual(timeout, 4)
            reloj[0] += timeout
            raise TimeoutError('prueba')
        obj.cliente.chat.completions.create.side_effect = sdk
        with patch.object(core.time, 'monotonic', side_effect=lambda: reloj[0]), patch.object(core.urllib.request, 'urlopen', side_effect=http) as llamada:
            self.assertIsNone(obj._consultar_llm([]))
            self.assertEqual(llamada.call_count, 1)
            self.assertEqual(obj.cliente.chat.completions.create.call_args.kwargs['timeout'], 10)

    def test_clasificacion_y_redaccion_comparten_presupuesto(self):
        obj = agente()
        obj._consultar_llm = core.Agente1._consultar_llm.__get__(obj)
        reloj = [100.0]
        def http(req, *, timeout):
            payload = json.loads(req.data)
            respuesta = Mock()
            if len(payload['messages']) == 2 and 'Redactor' not in payload['messages'][0]['content']:
                reloj[0] += 6
                texto = QUERY
            else:
                self.assertEqual(timeout, 4)
                reloj[0] += timeout
                raise TimeoutError('prueba')
            respuesta.read.return_value = json.dumps({'choices': [{'message': {'content': texto}}]}).encode()
            contexto = Mock()
            contexto.__enter__ = Mock(return_value=respuesta)
            contexto.__exit__ = Mock(return_value=False)
            return contexto
        with patch.object(core.time, 'monotonic', side_effect=lambda: reloj[0]), patch.object(core.urllib.request, 'urlopen', side_effect=http) as llamada:
            resultado = core.consultar_asistente('culata', obj, recuperar)
            self.assertEqual(resultado['estado'], 'error')
            self.assertEqual(llamada.call_count, 2)
            self.assertEqual(reloj[0], 110)


if __name__ == '__main__':
    unittest.main()


class RedaccionExtractivaFallback(unittest.TestCase):
    """Fallback determinista: oraciones literales con cita, desactivado por defecto."""

    def _ev(self):
        ev = evidencia()
        ev['texto'] = 'Termostato electrónico CMP-08. Apertura inicial a 92 °C. Conector de 4 vías.'
        return ev

    def test_redaccion_extractiva_pasa_verificadores(self):
        ev = self._ev()
        texto = core.redaccion_extractiva('¿A qué temperatura abre el termostato CMP-08?', [ev])
        self.assertIn('92 °C', texto)
        self.assertTrue(core.verificar_citas(texto, [ev])['valido'])
        self.assertTrue(core.verificar_respaldo_extractivo(texto, [ev]))

    def test_sin_solape_no_inventa(self):
        self.assertIsNone(core.redaccion_extractiva('aceite de motor viscosidad', [self._ev()]))

    def test_fallback_desactivado_mantiene_error_de_verificacion(self):
        obj = agente('Texto libre sin cita.', 'Otro texto libre.')
        res = core.redactar_respuesta_con_verificacion('temperatura termostato', [self._ev()], obj)
        self.assertEqual(res['estado'], 'error_verificacion')

    def test_fallback_activado_responde_con_citas_verificadas(self):
        obj = agente('Texto libre sin cita.', 'Otro texto libre.')
        obj.fallback_extractivo = True
        res = core.redactar_respuesta_con_verificacion('temperatura termostato', [self._ev()], obj)
        self.assertEqual(res['estado'], 'respuesta')
        self.assertEqual(res['verificacion']['modo'], 'extractivo')
        self.assertEqual(res['fuentes'], ['c_1'])

    def test_distinta_edicion_pdf_con_version_vehiculo_comun_no_pide_aclaracion(self):
        ev1 = evidencia('c_1', version='1.0')
        ev1['metadata']['versiones'] = ['V1.0', 'V1.1', 'V2.0']
        ev2 = evidencia('c_2', version='1.1')
        ev2['texto'] = 'Segundo fragmento de prueba.'
        ev2['metadata']['versiones'] = ['V1.0', 'V1.1', 'V2.0']
        obj = agente(TEXTO)
        res = core.resolver_evidencias('culata', {'estado': 'suficiente', 'evidencias': [ev1, ev2]}, obj)
        self.assertEqual(res['estado'], 'respuesta')

    def test_versiones_vehiculo_incompatibles_piden_aclaracion(self):
        ev1 = evidencia('c_1', version='1.0')
        ev1['metadata']['versiones'] = ['V1.0']
        ev2 = evidencia('c_2', version='1.1')
        ev2['texto'] = 'Segundo fragmento distinto.'
        ev2['metadata']['versiones'] = ['V2.0']
        obj = agente()
        res = core.resolver_evidencias('culata', {'estado': 'suficiente', 'evidencias': [ev1, ev2]}, obj)
        self.assertEqual(res['estado'], 'aclaracion')
