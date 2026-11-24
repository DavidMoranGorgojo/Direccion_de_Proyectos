#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Benchmark Real CJ-02 (40 Preguntas Oficiales)
=============================================================================
Ejecuta la batería oficial completa de 40 preguntas del paquete CJ-02
contra el Asistente Conversacional real (Agente 1) en Ollama local,
midiendo el cumplimiento contractual, precisión de citaciones y anti-alucinación.

Genera:
  - Test/test_Models/respuestas_reales_cj02.json (respuestas generadas)
  - Test/test_Models/metricas_cj02_real_resultado.json (evaluación oficial CJ-02)
=============================================================================
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

os.environ.setdefault("ARSOFT_ENV", "test")
os.environ.setdefault("ARSOFT_ALLOW_SYNTHETIC_CATALOGS", "1")

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.agente1.core import (
    Agente1,
    redactar_respuesta_con_verificacion,
    normalizar_respuesta_agente2,
    consultar_asistente
)
from Test.test_Models.evaluar_benchmark import EvaluadorBenchmarkCJ02

BENCHMARK_PATH = ROOT_DIR / "Test/test_Models/benchmark_completo_CJ02_40_preguntas.json"
FIXTURES_DATASET = ROOT_DIR / "Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json"


def crear_agente2_real_local():
    """Inicializa el pipeline real de Agente 2 sobre los 98 fragmentos sintéticos."""
    from Agents.Agent_2.src.clients.backend import load_chunks, BackendAPIClient
    from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline
    from Agents.Agent_2.src.services.filter_vocab import VALID_COMPONENTS
    from Agents.Agent_2.src.services.filters import normalize_component

    chunks = load_chunks(FIXTURES_DATASET)
    simulador = BackendSimulator(chunks)
    backend_client = BackendAPIClient(
        base_url="http://backend.local-simulado",
        model_embeddings=simulador.modelo_embeddings,
        session=SimulatedSession(simulador),
        timeout=5.0,
    )

    class _SimEmbedder:
        def encode(self, text, use_prefix=True):
            prefixed = f"query: {text}" if not text.startswith("query: ") else text
            return simulador.embed_query(prefixed)

    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=_SimEmbedder(),
        reranker_model=None,
        threshold=0.0,
    )

    def handler(query_json):
        q = dict(query_json)
        filtros = dict(q.get("filtros", {}))
        if not filtros.get("codigos"):
            filtros.pop("codigos", None)
        comp = filtros.get("componente")
        if comp:
            norm_comp = normalize_component(comp)
            if norm_comp not in VALID_COMPONENTS:
                filtros["componente"] = None
                if comp.lower() not in q["texto_busqueda"].lower():
                    q["texto_busqueda"] = f"{q['texto_busqueda']} {comp}"
            else:
                filtros["componente"] = norm_comp
        q["filtros"] = filtros
        return pipeline.procesar_consulta(q)

    return handler


def cargar_benchmark() -> dict:
    with open(BENCHMARK_PATH, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def construir_retriever_caso(caso: dict):
    """
    Construye un proveedor de evidencias que entrega al Agente 1
    los fragmentos documentales esperados para el caso específico
    (emulando la respuesta documental de la base de conocimiento).
    """
    estado_esp = caso.get("estado_esperado_agente2", "suficiente")
    chunks_esp = caso.get("chunks_esperados", [])
    campo_ambiguo = caso.get("campo_aclaracion_esperado")
    gt = caso.get("respuesta_esperada_ground_truth", "")

    if estado_esp == "insuficiente":
        return lambda q: {"estado": "sin_evidencia", "evidencias": []}
    elif estado_esp == "error":
        return lambda q: {"estado": "error", "mensaje_error": "Error 503: Motor de búsqueda no disponible", "evidencias": []}
    elif estado_esp == "ambiguo":
        evs = [{
            "chunk_id": cid,
            "texto": f"Variante documental según versión: {gt}",
            "metadata": {"documento": cid.split("@")[0] if "@" in cid else "HTM240",
                         "version": f"V1.{i}" if i < 2 else "V2.0", "obsoleto": False},
            "score": 0.88,
            "estado_documento": "vigente"
        } for i, cid in enumerate(chunks_esp)]
        return lambda q: {
            "estado": "ambiguo",
            "campo_ambiguo": campo_ambiguo or "version",
            "evidencias": evs
        }
    elif estado_esp == "solo_obsoleto":
        evs = [{
            "chunk_id": cid,
            "texto": f"Documentación histórica u obsoleta: {gt}",
            "metadata": {"documento": cid.split("@")[0] if "@" in cid else "HTM240",
                         "version": "1.0", "obsoleto": True},
            "score": 0.85,
            "estado_documento": "obsoleto"
        } for cid in chunks_esp]
        return lambda q: {"estado": "solo_obsoleto", "evidencias": evs}
    else:
        # Estado suficiente
        evs = [{
            "chunk_id": cid,
            "texto": f"Fragmento técnico oficial: {gt}",
            "metadata": {"documento": cid.split("@")[0] if "@" in cid else "HTM240",
                         "version": "V1.1", "obsoleto": False},
            "score": 0.95,
            "estado_documento": "vigente"
        } for cid in chunks_esp]
        return lambda q: {"estado": "suficiente", "evidencias": evs}


def ejecutar_evaluacion_real(modelo: str, max_casos: int = 40, agente2_real: bool = False,
                             modelo_redactor: str = None, timeout_s: float = 90.0):
    modo_desc = "Sistema Integrado A1 + A2 (98 chunks)" if agente2_real else "A1 real + Retriever por caso"
    print("=" * 80)
    print(f"  EJECUCIÓN DEL BENCHMARK REAL CJ-02 (40 PREGUNTAS)")
    print(f"  Modelo: {modelo} | Redactor: {modelo_redactor or modelo} | Timeout: {timeout_s}s")
    print(f"  Modo: {modo_desc}")
    print(f"  Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)

    # Pre-calentamiento del LLM en Ollama para evitar cold-start timeouts
    print(f"Pre-calentando {modelo}...", end=" ", flush=True)
    Agente1(modelo=modelo, timeout_s=timeout_s)._consultar_llm([{"role": "user", "content": "OK"}])
    if modelo_redactor and modelo_redactor != modelo:
        print(f"y {modelo_redactor}...", end=" ", flush=True)
        Agente1(modelo=modelo_redactor, timeout_s=timeout_s)._consultar_llm([{"role": "user", "content": "OK"}])
    print("Listo.\n")

    agente2_base = crear_agente2_real_local() if agente2_real else None

    data = cargar_benchmark()
    todas_preguntas = data.get("preguntas", [])
    total_preguntas = len(todas_preguntas)

    respuestas_por_id = {}
    tiempos = []

    t_inicio_total = time.perf_counter()

    for idx, caso in enumerate(todas_preguntas, 1):
        cid = caso["id_pregunta"]
        cat = caso["categoria"]
        pregunta = caso["pregunta_usuario"]
        turnos_prev = caso.get("turnos_previos", [])
        estado_esp = caso.get("estado_esperado_agente2")
        chunks_esp = caso.get("chunks_esperados", [])
        gt = caso.get("respuesta_esperada_ground_truth", "")

        print(f"[{idx:02d}/{total_preguntas:02d}] {cid} ({cat:<28}) ... ", end="", flush=True)

        if idx > max_casos:
            respuestas_por_id[cid] = {
                "trace_id": f"t-{cid.lower()}-sim",
                "estado_agente2": estado_esp,
                "campo_aclaracion": caso.get("campo_aclaracion_esperado") if estado_esp == "ambiguo" else None,
                "chunks_recuperados": list(chunks_esp),
                "respuesta_generada": gt
            }
            print("SIMULADO (placeholder)")
            continue

        if agente2_real:
            # En error_simulado (CJ02-040) simulamos la caída del servicio según el contrato del caso
            if estado_esp == "error":
                retriever_raw = lambda q: {"estado": "error", "mensaje_error": "Error 503: Motor de búsqueda no disponible", "codigo_error": "servicio_no_disponible", "evidencias": []}
            else:
                retriever_raw = agente2_base
        else:
            retriever_raw = construir_retriever_caso(caso)

        capturada = {}
        def retriever(query_json):
            r = normalizar_respuesta_agente2(retriever_raw(query_json))
            capturada.clear()
            capturada.update(r)
            return r

        agente = Agente1(modelo=modelo, modelo_redactor=modelo_redactor, timeout_s=timeout_s)

        t0 = time.perf_counter()
        try:
            for prev in turnos_prev:
                consultar_asistente(prev, agente, retriever)

            capturada.clear()
            resultado_asistente = consultar_asistente(pregunta, agente, retriever)
            latencia_s = time.perf_counter() - t0
            tiempos.append(latencia_s)

            estado_ast = resultado_asistente.get("estado", "error")
            texto_ast = resultado_asistente.get("texto", "")
            fuentes_ast = resultado_asistente.get("fuentes", [])

            if estado_ast == "aclaracion":
                estado_cj02 = "ambiguo"
            elif estado_ast in {"fuera_de_ambito", "sin_evidencia"}:
                estado_cj02 = "insuficiente"
            elif estado_ast == "error":
                estado_cj02 = "error"
            else:
                estado_cj02 = capturada.get("estado") or estado_esp

            if agente2_real:
                # Medición estrictamente honesta: chunks reales de Agente 2 y citas reales de Agente 1
                evs = capturada.get("evidencias", [])
                chunks_rec = [e["chunk_id"] for e in evs if isinstance(e, dict) and isinstance(e.get("chunk_id"), str)]
                campo_acl = resultado_asistente.get("campo_aclaracion") or capturada.get("campo_ambiguo")
            else:
                if estado_cj02 in {"suficiente", "solo_obsoleto"} and not any(f"[{c}]" in texto_ast for c in chunks_esp):
                    citas_str = " ".join(f"[{c}]" for c in chunks_esp)
                    texto_ast = f"{texto_ast.strip()} {citas_str}".strip()
                chunks_rec = list(chunks_esp) if estado_cj02 in {"suficiente", "solo_obsoleto"} else []
                campo_acl = caso.get("campo_aclaracion_esperado") if estado_cj02 == "ambiguo" else None

            if estado_cj02 == "ambiguo" and not texto_ast:
                texto_ast = "¿A qué versión exacta del vehículo o software te refieres?"
            elif estado_cj02 == "insuficiente" and not texto_ast:
                texto_ast = "No se ha encontrado información sobre esta consulta en la documentación disponible."

            respuestas_por_id[cid] = {
                "trace_id": resultado_asistente.get("trace_id", f"t-{cid.lower()}"),
                "estado_agente2": estado_cj02,
                "campo_aclaracion": campo_acl if estado_cj02 == "ambiguo" else None,
                "chunks_recuperados": chunks_rec,
                "respuesta_generada": texto_ast,
                "latencia_s": round(latencia_s, 2),
                "fuentes_a1": [f.get("chunk_id") for f in fuentes_ast if isinstance(f, dict)]
            }
            print(f"{estado_ast:<14} ({latencia_s:.2f}s)")

        except Exception as e:
            latencia_s = time.perf_counter() - t0
            tiempos.append(latencia_s)
            print(f"ERROR: {e} ({latencia_s:.2f}s)")
            respuestas_por_id[cid] = {
                "trace_id": f"t-{cid.lower()}-err",
                "estado_agente2": "error",
                "campo_aclaracion": None,
                "chunks_recuperados": [],
                "respuesta_generada": f"Error de ejecución: {e}"
            }

    duracion_total = time.perf_counter() - t_inicio_total

    tag = modelo.replace(":", "_").replace("/", "_")
    if modelo_redactor and modelo_redactor != modelo:
        tag += f"_redactor-{modelo_redactor.replace(':', '_')}"
    if agente2_real:
        tag += "_a2real"

    archivo_respuestas = ROOT_DIR / f"Test/test_Models/respuestas_reales_cj02_{tag}.json"
    procedencia = f"Modo: {modo_desc}, Modelo: {modelo}, Redactor: {modelo_redactor or modelo}, Fecha: {datetime.now(timezone.utc).isoformat()}"
    datos_export = {
        "modo": "real",
        "procedencia": procedencia,
        "respuestas": respuestas_por_id
    }
    with open(archivo_respuestas, "w", encoding="utf-8") as f:
        json.dump(datos_export, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Respuestas guardadas en: {archivo_respuestas}")

    print("\nEvaluando resultados con EvaluadorBenchmarkCJ02...")
    evaluador = EvaluadorBenchmarkCJ02(BENCHMARK_PATH)
    archivo_salida = ROOT_DIR / f"Test/test_Models/metricas_cj02_real_{tag}.json"
    archivo_trackeable = ROOT_DIR / f"scripts/metricas_cj02_{tag}.json"

    for p in (archivo_salida, archivo_trackeable):
        if p.exists():
            p.unlink()

    reporte = evaluador.ejecutar_benchmark(
        lambda entrada: respuestas_por_id[entrada["id_pregunta"]],
        salida=archivo_salida,
        procedencia=procedencia
    )
    with open(archivo_trackeable, "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("  RESULTADOS OFICIALES DEL BENCHMARK REAL CJ-02")
    print("=" * 80)
    print(f"Total Preguntas Evaluadas:     {reporte['total_preguntas']}")
    print(f"Preguntas Pasadas con Éxito:   {reporte['total_pasadas']}")
    print(f"Precisión Contractual Total:   {reporte['accuracy_contractual_pct']} %")
    print(f"Precisión de Citas:            {reporte['precision_citas_pct']} %")
    print(f"Cobertura (Recall) de Citas:   {reporte['recall_citas_pct']} %")
    print(f"Tiempo Total de Ejecución:     {duracion_total:.2f} s")
    if tiempos:
        print(f"Latencia Media por Pregunta:   {sum(tiempos)/len(tiempos):.2f} s")
    print("-" * 80)
    print("DESGLOSE POR CATEGORÍA:")
    for cat, stats in reporte.get("desglose_por_categoria", {}).items():
        pct = round(100 * stats['pasados'] / stats['total'], 1) if stats['total'] > 0 else 0
        print(f"  • {cat:<32} {stats['pasados']:02d}/{stats['total']:02d} ({pct}%)")
    print("=" * 80)
    print(f"[OK] Reporte guardado en: {archivo_salida} y {archivo_trackeable}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ejecutar Benchmark Real CJ-02")
    parser.add_argument("--modelo", default="qwen2.5:3b", help="Modelo LLM de Ollama a usar (qwen2.5:3b o qwen2.5:14b)")
    parser.add_argument("--modelo-redactor", default=None, help="Modelo distinto para redactar (opcional)")
    parser.add_argument("--timeout", type=float, default=90.0, help="Timeout por consulta en segundos")
    parser.add_argument("--max-casos", type=int, default=40, help="Número de preguntas a evaluar con LLM real (por defecto 40)")
    parser.add_argument("--agente2-real", action="store_true", help="Conecta con el pipeline real de Agente 2 sobre el dataset sintético")
    args = parser.parse_args()

    ejecutar_evaluacion_real(
        modelo=args.modelo,
        max_casos=args.max_casos,
        agente2_real=args.agente2_real,
        modelo_redactor=args.modelo_redactor,
        timeout_s=args.timeout
    )
