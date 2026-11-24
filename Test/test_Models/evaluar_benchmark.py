"""CJ-02: comprobaciones automáticas de contratos y citas; semántica pendiente.

La simulación copia el ground truth y SOLO prueba el evaluador. Una ejecución
externa recibe preguntas sin respuestas esperadas. No se declara calidad del LLM.
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def citas(texto):
    return set(p.strip() for b in re.findall(r'\[([^\]]+)\]', texto)
               for p in b.split(',') if re.fullmatch(r'[A-Za-z0-9_@.\-]+', p.strip()))


def chunks_equivalentes(c1: str, c2: str) -> bool:
    """Comprueba equivalencia exacta o por documento/sección entre identificadores sintéticos y del Backend real."""
    if c1 == c2:
        return True
    base1 = c1.split('@')[0] if '@' in c1 else c1.split('_')[0]
    base2 = c2.split('@')[0] if '@' in c2 else c2.split('_')[0]
    if base1 != base2:
        return False
    # Si comparten documento base, verificar sección/código clave
    # Sintético: ..._p4_htm0405 -> "htm0405"
    # Real Backend: ..._htm-0405_01_e1e430db -> "htm0405"
    partes1 = [p for p in c1.split('_') if p and not p.startswith('p') and not re.match(r'^[0-9a-f]{8}$', p)]
    partes2 = [p for p in c2.split('_') if p and not p.startswith('p') and not re.match(r'^[0-9a-f]{8}$', p)]
    slug1 = ''.join(re.sub(r'[^a-zA-Z0-9]', '', p) for p in partes1).lower()
    slug2 = ''.join(re.sub(r'[^a-zA-Z0-9]', '', p) for p in partes2).lower()
    return bool(slug1 and slug2 and (slug1 in slug2 or slug2 in slug1))


def crear_pipeline_local(agente_factory, agente2, *, simulado):
    """Adapta CTR-001/004 al vocabulario CJ-02, sin entregar el ground truth.

    agente_factory crea una sesión aislada por caso. turnos_previos, si los aporta
    un escenario revisado, es una lista de preguntas; no se inventa contexto.
    simulado declara si alguno de los participantes es un doble de prueba.
    """
    from Agents.agente1.core import consultar_asistente, normalizar_respuesta_agente2

    def pipeline(entrada):
        agente = agente_factory()
        capturada = {}

        def recuperar(query):
            respuesta = normalizar_respuesta_agente2(agente2(query))
            capturada.clear()
            capturada.update(respuesta)
            return respuesta

        for pregunta in entrada.get('turnos_previos', []):
            consultar_asistente(pregunta, agente, recuperar)
        capturada.clear()
        final = consultar_asistente(entrada['pregunta_usuario'], agente, recuperar)
        if final['estado'] == 'error':
            estado = 'error'
        elif final['estado'] == 'aclaracion':
            estado = 'ambiguo'
        elif final['estado'] in {'fuera_de_ambito', 'sin_evidencia'}:
            estado = 'insuficiente'
        else:
            estado = capturada.get('estado', 'error')
        evidencias = capturada.get('evidencias', [])
        return {'trace_id': final['trace_id'], 'estado_agente2': estado,
                'campo_aclaracion': capturada.get('campo_ambiguo'),
                'chunks_recuperados': [e['chunk_id'] for e in evidencias
                                      if isinstance(e, dict) and isinstance(e.get('chunk_id'), str)],
                'respuesta_generada': final['texto'], 'simulado': simulado}
    return pipeline


class EvaluadorBenchmarkCJ02:
    def __init__(self, benchmark_path, modo_matching='exacto'):
        self.benchmark_path = Path(benchmark_path)
        self.modo_matching = modo_matching
        self.data = json.loads(self.benchmark_path.read_text(encoding='utf-8-sig'))
        self.preguntas = self.data.get('preguntas', [])
        ids = [p['id_pregunta'] for p in self.preguntas]
        if len(ids) != 40 or len(set(ids)) != 40 or self.data.get('total_preguntas') != 40:
            raise ValueError('CJ-02 requiere exactamente 40 preguntas con IDs únicos')
        self.resultados = []

    def simular_agente_pipeline(self, caso):
        """Oráculo circular de referencia. NO ejecuta los agentes ni mide su latencia."""
        return {'estado_agente2': caso['estado_esperado_agente2'],
                'campo_aclaracion': caso.get('campo_aclaracion_esperado'),
                'chunks_recuperados': list(caso.get('chunks_esperados', [])),
                'respuesta_generada': caso['respuesta_esperada_ground_truth'],
                'simulado': True}

    def evaluar_caso(self, caso, respuesta_sistema):
        if not isinstance(respuesta_sistema, dict):
            respuesta_sistema = {}
        estado_esp = caso['estado_esperado_agente2']
        texto = respuesta_sistema.get('respuesta_generada')
        recuperados = respuesta_sistema.get('chunks_recuperados')
        contrato_ok = (isinstance(texto, str) and bool(texto.strip())
                       and isinstance(recuperados, list)
                       and all(isinstance(c, str) for c in recuperados)
                       and isinstance(respuesta_sistema.get('estado_agente2'), str)
                       and not respuesta_sistema.get('error_ejecucion'))
        texto = texto if isinstance(texto, str) else ''
        recuperados = set(recuperados) if isinstance(recuperados, list) and all(isinstance(c, str) for c in recuperados) else set()
        detectadas = citas(texto)
        esperadas = set(caso.get('chunks_esperados', []))
        if self.modo_matching == 'documento_seccion':
            inter = {d for d in detectadas if any(chunks_equivalentes(d, e) for e in esperadas)}
            esperadas_cubiertas = {e for e in esperadas if any(chunks_equivalentes(d, e) for d in detectadas)}
            citas_recuperadas = {d for d in detectadas if any(chunks_equivalentes(d, r) for r in recuperados)}
            precision = len(inter) / len(detectadas) if detectadas else (0.0 if esperadas else 1.0)
            recall = len(esperadas_cubiertas) / len(esperadas) if esperadas else (0.0 if detectadas else 1.0)
            citas_ok = (len(inter) == len(detectadas) and len(citas_recuperadas) == len(detectadas)
                        and (bool(inter) if esperadas else not detectadas))
        else:
            inter = detectadas & esperadas
            precision = len(inter) / len(detectadas) if detectadas else (0.0 if esperadas else 1.0)
            recall = len(inter) / len(esperadas) if esperadas else (0.0 if detectadas else 1.0)
            # Una cita correcta no compensa otra inventada; no aceptar citas no recuperadas.
            citas_ok = (detectadas <= esperadas and detectadas <= recuperados
                        and (bool(inter) if esperadas else not detectadas))
        aclaracion_ok = (respuesta_sistema.get('campo_aclaracion') == caso.get('campo_aclaracion_esperado')
                         if estado_esp == 'ambiguo' else True)
        if estado_esp == 'ambiguo':
            citas_ok = not detectadas
        estado_ok = respuesta_sistema.get('estado_agente2') == estado_esp
        obsoleto_ok = True
        if caso['categoria'] == 'sustituido_obsoleto' and re.search(r'80[.\s,]?000', texto):
            obsoleto_ok = any(w in texto.lower() for w in ('obsolet', 'errata', 'sustituid', 'incorrect', 'no debe'))
        # Regla histórica limitada: no demuestra por sí sola corrección de obsolescencia.
        return {'id_pregunta': caso['id_pregunta'], 'categoria': caso['categoria'],
                'pasado': contrato_ok and estado_ok and aclaracion_ok and citas_ok and obsoleto_ok,
                'contrato_ok': contrato_ok, 'estado_ok': estado_ok, 'aclaracion_ok': aclaracion_ok,
                'citas_ok': citas_ok, 'obsoleto_ok': obsoleto_ok,
                'precision_citas': precision, 'recall_citas': recall,
                'citas_detectadas': sorted(detectadas),
                'estado_obtenido': respuesta_sistema.get('estado_agente2'),
                'estado_esperado': estado_esp}

    def ejecutar_benchmark(self, pipeline_fn=None, *, simulacion=False, salida=None, procedencia=None):
        if simulacion and pipeline_fn is not None:
            raise ValueError('Elegir simulación o pipeline externo')
        if not simulacion and (pipeline_fn is None or not procedencia):
            raise ValueError('La evaluación externa exige pipeline y procedencia; simulación debe ser explícita')
        modo = 'simulacion_oraculo' if simulacion else 'evaluacion_externa'
        self.resultados = []
        for caso in self.preguntas:
            inicio = time.perf_counter()
            try:
                # Nunca entregar ground truth, categoría ni chunks esperados al sistema evaluado.
                entrada = {k: caso[k] for k in ('id_pregunta', 'pregunta_usuario', 'turnos_previos') if k in caso}
                resp = self.simular_agente_pipeline(caso) if simulacion else pipeline_fn(entrada)
                if not simulacion and isinstance(resp, dict) and resp.get('simulado'):
                    raise ValueError('Respuesta simulada en evaluación externa')
                res = self.evaluar_caso(caso, resp)
            except Exception as exc:
                res = self.evaluar_caso(caso, {})
                res['error_ejecucion'] = f'{type(exc).__name__}: {exc}'
            res['duracion_evaluador_ms'] = round((time.perf_counter() - inicio) * 1000, 3)
            self.resultados.append(res)
        categorias = {}
        for res in self.resultados:
            stats = categorias.setdefault(res['categoria'], {'total': 0, 'pasados': 0})
            stats['total'] += 1
            stats['pasados'] += int(res['pasado'])
        total = len(self.resultados)
        pasados = sum(r['pasado'] for r in self.resultados)
        reporte = {'fecha_evaluacion': datetime.now(timezone.utc).isoformat(),
                   'modo': modo, 'procedencia': procedencia,
                   'certifica_modelo_real': False,
                   'alcance': 'Contratos, citas y regla histórica limitada de obsolescencia; no corrección técnica.',
                   'limitaciones': ['Faltan turnos previos explícitos de CJ02-033 a CJ02-036.',
                                    'Ground truth y documentos fuente no verificados contra un corpus.',
                                    'Versiones, valores técnicos y criterios semánticos requieren revisión humana.'],
                   'total_preguntas': total, 'total_pasadas': pasados,
                   'accuracy_contractual_pct': round(100 * pasados / total, 2),
                   'precision_citas_pct': round(100 * sum(r['precision_citas'] for r in self.resultados) / total, 2),
                   'recall_citas_pct': round(100 * sum(r['recall_citas'] for r in self.resultados) / total, 2),
                   'desglose_por_categoria': categorias, 'detalle_casos': self.resultados}
        if salida is not None:
            destino = Path(salida)
            if destino.resolve() == self.benchmark_path.resolve():
                raise ValueError('No sobrescribir el dataset')
            # No destruir informes de otra ejecución por accidente.
            with destino.open('x', encoding='utf-8') as archivo:
                json.dump(reporte, archivo, ensure_ascii=False, indent=2)
        return reporte


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--simulacion', action='store_true')
    grupo.add_argument('--respuestas', type=Path, help='JSON archivado: procedencia y respuestas por ID')
    parser.add_argument('--salida', type=Path, required=True, help='Archivo nuevo; no sobrescribe')
    parser.add_argument('--modo-matching', choices=['exacto', 'documento_seccion'], default='exacto',
                        help='Modo de comprobación de citas: exacto (sintético) o documento_seccion (Backend real)')
    args = parser.parse_args()
    evaluador = EvaluadorBenchmarkCJ02(
        Path(__file__).with_name('benchmark_completo_CJ02_40_preguntas.json'),
        modo_matching=args.modo_matching
    )
    if args.simulacion:
        reporte = evaluador.ejecutar_benchmark(simulacion=True, salida=args.salida)
    else:
        datos = json.loads(args.respuestas.read_text(encoding='utf-8-sig'))
        if datos.get('modo') != 'real' or not datos.get('procedencia'):
            parser.error('El archivo debe declarar modo real y procedencia (modelo, corpus y fecha)')
        respuestas = datos['respuestas']
        ids = {p['id_pregunta'] for p in evaluador.preguntas}
        if set(respuestas) != ids:
            parser.error('Deben aportarse exactamente las respuestas de los 40 IDs')
        reporte = evaluador.ejecutar_benchmark(lambda entrada: respuestas[entrada['id_pregunta']],
                    salida=args.salida, procedencia=datos['procedencia'])
    print(f"{reporte['modo']}: {reporte['total_pasadas']}/{reporte['total_preguntas']} comprobaciones contractuales; no certifica el modelo")


if __name__ == '__main__':
    main()
