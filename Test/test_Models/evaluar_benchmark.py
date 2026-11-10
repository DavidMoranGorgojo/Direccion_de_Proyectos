#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Sistema ThermoDrive HTM-240
Módulo de Evaluación y Métricas Automatizadas — Paquete de Trabajo CJ-02
=============================================================================
Evalúa de principio a fin el comportamiento del Asistente Conversacional
(Agente 1) contra el servicio de recuperación (Agente 2) utilizando la batería
oficial de 40 casos estructurados con Ground Truth.

Métricas calculadas:
  - Tasa global de acierto (Accuracy)
  - Desglose por categoría (Válidas, Versiones, Obsoletos, Códigos, Ambiguas, etc.)
  - Precisión y Cobertura de Citaciones de chunks (Anti-alucinación)
  - Tasa de detección de ambigüedad y solicitud de versión
  - Tasa de bloqueo / discriminación de documentos obsoletos
=============================================================================
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime

# Asegurar soporte utf-8 en consola de Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Regex para extraer citaciones de fragmentos en el texto de respuesta
# Soporta formato oficial {documento}@{version}_p{pag}_{slug} y formato corto c_XXX
CHUNK_CITATION_REGEX = re.compile(r"\[([A-Za-z0-9\-_]+(?:@[0-9\.]+_[A-Za-z0-9\-_]+)?)\]")

class EvaluadorBenchmarkCJ02:
    def __init__(self, benchmark_path: str):
        self.benchmark_path = Path(benchmark_path)
        if not self.benchmark_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de benchmark: {benchmark_path}")
        
        with open(self.benchmark_path, "r", encoding="utf-8-sig") as f:
            self.data = json.load(f)
        
        self.preguntas = self.data.get("preguntas", [])
        self.resultados = []

    def simular_agente_pipeline(self, caso: dict) -> dict:
        """
        Simulador de referencia que implementa la lógica contractual de Agente 1 y Agente 2
        (ARSOFT-CTR-003 y ARSOFT-CTR-004) para verificar la batería de forma autónoma.
        Si se conecta el Agente 1 real de un compañero, se sustituye esta llamada.
        """
        id_preg = caso["id_pregunta"]
        categoria = caso["categoria"]
        estado_esp = caso["estado_esperado_agente2"]
        campo_amb = caso.get("campo_aclaracion_esperado")
        chunks_esp = caso.get("chunks_esperados", [])
        gt = caso.get("respuesta_esperada_ground_truth", "")

        # Simulación de respuesta estructurada generada por Agente 1
        return {
            "trace_id": f"trace-{id_preg.lower()}-{int(time.time())}",
            "estado_agente2": estado_esp,
            "campo_aclaracion": campo_amb,
            "chunks_recuperados": chunks_esp,
            "respuesta_generada": gt,
            "latencia_ms": 142
        }

    def evaluar_caso(self, caso: dict, respuesta_sistema: dict) -> dict:
        """Verifica el cumplimiento estricto del caso contra las reglas del contrato."""
        id_preg = caso["id_pregunta"]
        categoria = caso["categoria"]
        estado_esp = caso["estado_esperado_agente2"]
        estado_act = respuesta_sistema.get("estado_agente2")
        texto_resp = respuesta_sistema.get("respuesta_generada", "")
        chunks_esp = set(caso.get("chunks_esperados", []))
        
        # 1. Verificación de Estado contractual (CTR-004)
        estado_ok = (estado_act == estado_esp)

        # 2. Verificación de Aclaraciones en casos ambiguos
        aclaracion_ok = True
        if estado_esp == "ambiguo":
            campo_esp = caso.get("campo_aclaracion_esperado")
            campo_act = respuesta_sistema.get("campo_aclaracion")
            aclaracion_ok = (campo_esp == campo_act)

        # 3. Verificación de Citaciones (Anti-alucinación)
        # Extraer todas las citas dentro de corchetes [chunk_id_1, chunk_id_2]
        citas_encontradas = set()
        for bloque in re.findall(r"\[([^\]]+)\]", texto_resp):
            partes = [p.strip() for p in bloque.split(",")]
            for p in partes:
                if "@" in p or p.startswith("c_") or "HTM240" in p:
                    citas_encontradas.add(p)

        if estado_esp == "ambiguo":
            # En preguntas ambiguas, el asistente formula una pregunta de aclaración, no cita evidencias
            citas_ok = True
            precision_citas = 1.0
            recall_citas = 1.0
        elif chunks_esp:
            interseccion = citas_encontradas.intersection(chunks_esp)
            precision_citas = len(interseccion) / len(citas_encontradas) if citas_encontradas else 0.0
            recall_citas = len(interseccion) / len(chunks_esp) if chunks_esp else 1.0
            citas_ok = (len(interseccion) > 0)
        else:
            # Si no se esperan chunks (fuera de ámbito o sin evidencia), no debe citar nada
            citas_ok = (len(citas_encontradas) == 0)
            precision_citas = 1.0 if citas_ok else 0.0
            recall_citas = 1.0 if citas_ok else 0.0

        # 4. Verificación de Información Obsoleta
        obsoleto_ok = True
        if categoria == "sustituido_obsoleto":
            # Si se menciona la cifra errónea de 80.000, debe ir acompañada explícitamente de aviso de obsoleto/errata
            if "80.000" in texto_resp:
                if not any(w in texto_resp.lower() for w in ["obsoleto", "errata", "sustituido", "incorrecto", "no debe"]):
                    obsoleto_ok = False

        # Veredicto global del caso
        pasado = estado_ok and aclaracion_ok and citas_ok and obsoleto_ok

        return {
            "id_pregunta": id_preg,
            "categoria": categoria,
            "pasado": pasado,
            "estado_ok": estado_ok,
            "aclaracion_ok": aclaracion_ok,
            "citas_ok": citas_ok,
            "obsoleto_ok": obsoleto_ok,
            "precision_citas": precision_citas,
            "recall_citas": recall_citas,
            "citas_detectadas": list(citas_encontradas),
            "estado_obtenido": estado_act,
            "estado_esperado": estado_esp
        }

    def ejecutar_benchmark(self, pipeline_fn=None):
        """Ejecuta los 40 casos y compila el informe de métricas."""
        print("\n" + "="*78)
        print(" ARSOFT RETO IA — EJECUTOR DE BENCHMARK CJ-02 (40 CASOS)")
        print("="*78)
        print(f" Dataset de pruebas : {self.benchmark_path.name}")
        print(f" Total de casos     : {len(self.preguntas)}")
        print(f" Fecha y hora       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*78 + "\n")

        self.resultados = []
        categorias_stats = {}

        for p in self.preguntas:
            cat = p["categoria"]
            if cat not in categorias_stats:
                categorias_stats[cat] = {"total": 0, "pasados": 0}
            categorias_stats[cat]["total"] += 1

            # Ejecutar con el pipeline real o con el simulador
            if pipeline_fn:
                resp = pipeline_fn(p)
            else:
                resp = self.simular_agente_pipeline(p)

            res = self.evaluar_caso(p, resp)
            self.resultados.append(res)

            if res["pasado"]:
                categorias_stats[cat]["pasados"] += 1
                icono = "OK"
            else:
                icono = "FAIL"

            citas_str = f"citas: {len(res['citas_detectadas'])}" if res['citas_detectadas'] else "sin citas"
            print(f" [{icono:4}] {res['id_pregunta']} | {cat[:22]:22} | Estado: {res['estado_obtenido']:12} | {citas_str}")

        # Compilar métricas globales
        total_casos = len(self.resultados)
        total_pasados = sum(1 for r in self.resultados if r["pasado"])
        tasa_global = (total_pasados / total_casos) * 100 if total_casos else 0

        avg_precision_citas = sum(r["precision_citas"] for r in self.resultados) / total_casos if total_casos else 0
        avg_recall_citas = sum(r["recall_citas"] for r in self.resultados) / total_casos if total_casos else 0

        print("\n" + "="*78)
        print(" RESUMEN DE MÉTRICAS GLOBALES (CJ-02)")
        print("="*78)
        print(f" Tasa Global de Éxito (Accuracy) : {tasa_global:.1f}% ({total_pasados}/{total_casos})")
        print(f" Precisión media de citas       : {avg_precision_citas*100:.1f}%")
        print(f" Cobertura media de citas       : {avg_recall_citas*100:.1f}%")
        print("-" * 78)
        print(" Desglose por categoría:")
        for cat, st in categorias_stats.items():
            pct = (st["pasados"] / st["total"]) * 100 if st["total"] else 0
            print(f"   • {cat:30} : {pct:5.1f}% ({st['pasados']}/{st['total']})")
        print("="*78 + "\n")

        # Exportar informe JSON de métricas
        salida_json = self.benchmark_path.parent / "metricas_cj02_resultado.json"
        reporte_final = {
            "fecha_evaluacion": datetime.now().isoformat(),
            "paquete": "CJ-02: Set de pruebas y métricas",
            "total_preguntas": total_casos,
            "total_pasadas": total_pasados,
            "accuracy_global_pct": round(tasa_global, 2),
            "precision_citas_pct": round(avg_precision_citas * 100, 2),
            "recall_citas_pct": round(avg_recall_citas * 100, 2),
            "desglose_por_categoria": categorias_stats,
            "detalle_casos": self.resultados
        }
        with open(salida_json, "w", encoding="utf-8") as f:
            json.dump(reporte_final, f, indent=2, ensure_ascii=False)
        print(f" [*] Informe de métricas guardado en: {salida_json.name}")

        return reporte_final


if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    benchmark_file = script_dir / "benchmark_completo_CJ02_40_preguntas.json"
    
    if not benchmark_file.exists():
        benchmark_file = Path("benchmark_completo_CJ02_40_preguntas.json")

    evaluador = EvaluadorBenchmarkCJ02(str(benchmark_file))
    evaluador.ejecutar_benchmark()
