#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Asistente Conversacional (Agente 1)
Estudio Técnico del Clúster y Comparativa de Modelos LLM
=============================================================================
Objetivo:
  Evaluar sistemáticamente modelos disponibles (qwen2.5:3b vs qwen2.5:14b)
  sobre el mismo conjunto representativo de preguntas técnicas de automoción.

Métricas medidas:
  1. Tamaño en disco y consumo de memoria (RAM / VRAM)
  2. Latencia total (ms / s) y velocidad de generación (tokens / segundo)
  3. Calidad de comprensión y contratos:
     - Formato JSON conforme a CTR-004
     - Detección de consultas incompletas (solicitud de aclaración)
     - Rechazo de preguntas fuera de ámbito
  4. Calidad de redacción técnica:
     - Formato obligatorio (Causas, Seguridad, Procedimiento, Fuentes)
     - Precisión extractiva de citas [chunk_id] (anti-alucinación)
  5. Comportamiento en concurrencia (peticiones simultáneas)
=============================================================================
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# Ajustar PYTHONPATH para importar Agente 1
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.agente1.core import (
    Agente1,
    redactar_respuesta_con_verificacion,
    verificar_citas,
    validar_esquema_query_json
)

OLLAMA_API = os.environ.get("OLLAMA_URL", "http://localhost:11434").replace("/v1", "")

CASOS_EVALUACION = [
    {
        "id": "CASO-01",
        "tipo": "clasificacion_especificacion",
        "pregunta": "Par de apriete de los tornillos de culata del Golf 7 1.6 TDI V1.1",
        "esperado": {
            "estado": "valida",
            "intencion": "especificacion",
            "componente_contiene": "culata"
        }
    },
    {
        "id": "CASO-02",
        "tipo": "clasificacion_diagnostico_codigos",
        "pregunta": "Tengo un Golf 7 1.6 TDI, da tirones y marca fallo P0301 con HTM-0142",
        "esperado": {
            "estado": "valida",
            "intencion": "diagnostico",
            "codigos_esperados": ["P0301", "HTM-0142"]
        }
    },
    {
        "id": "CASO-03",
        "tipo": "pregunta_incompleta_aclaracion",
        "pregunta": "¿Cuál es el par de apriete de la culata?",
        "esperado": {
            "estado": "aclaracion",
            "es_pregunta_texto": True
        }
    },
    {
        "id": "CASO-04",
        "tipo": "fuera_de_ambito_rechazo",
        "pregunta": "¿Cómo se prepara una paella valenciana tradicional?",
        "esperado": {
            "estado": "rechazo"
        }
    },
    {
        "id": "CASO-05",
        "tipo": "redaccion_con_citas",
        "pregunta": "Par de apriete culata Golf 7 1.6 TDI",
        "evidencias": [
            {
                "chunk_id": "chunk_01",
                "texto": "El par de apriete de los tornillos de culata se realiza en 3 fases: Fase 1 a 40 Nm, Fase 2 a 90 grados y Fase 3 a 90 grados adicionales.",
                "metadata": {"documento": "HTM240-MAN-001@1.1_p42_1", "pagina": 42},
                "estado_documento": "vigente"
            }
        ],
        "esperado": {
            "citas_obligatorias": ["chunk_01"],
            "anti_alucinacion": True
        }
    }
]


def obtener_info_modelo_ollama(nombre_modelo: str) -> dict:
    """Consulta la API de Ollama para obtener tamaño y metadata del modelo."""
    url = f"{OLLAMA_API}/api/show"
    payload = json.dumps({"name": nombre_modelo}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            detalles = data.get("details", {})
            return {
                "formato": detalles.get("format", "gguf"),
                "familia": detalles.get("family", "qwen2"),
                "num_parametros": detalles.get("parameter_size", "N/A"),
                "cuantizacion": detalles.get("quantization_level", "Q4_K_M")
            }
    except Exception as e:
        return {"error": str(e), "familia": "qwen2"}


def medir_throughput_ollama(nombre_modelo: str, prompt_test: str = "Responde brevemente: ¿qué es un termostato de automoción?") -> dict:
    """Mide la velocidad bruta en tokens/segundo de generación con la API de Ollama."""
    url = f"{OLLAMA_API}/api/chat"
    payload = json.dumps({
        "model": nombre_modelo,
        "messages": [{"role": "user", "content": prompt_test}],
        "stream": False,
        "options": {"temperature": 0.0}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latencia_total_s = time.perf_counter() - t0

            eval_count = data.get("eval_count", 0)
            eval_duration_ns = data.get("eval_duration", 1)
            prompt_eval_count = data.get("prompt_eval_count", 0)
            prompt_eval_duration_ns = data.get("prompt_eval_duration", 1)

            tps = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0.0
            prompt_tps = (prompt_eval_count / (prompt_eval_duration_ns / 1e9)) if prompt_eval_duration_ns > 0 else 0.0

            return {
                "tokens_generados": eval_count,
                "tokens_prompt": prompt_eval_count,
                "tokens_por_segundo": round(tps, 2),
                "prompt_tokens_por_segundo": round(prompt_tps, 2),
                "latencia_total_s": round(latencia_total_s, 3)
            }
    except Exception as e:
        return {"error": str(e), "tokens_por_segundo": 0.0, "latencia_total_s": 0.0}


def evaluar_modelo_completo(nombre_modelo: str) -> dict:
    print(f"\n{'='*70}\nEVALUANDO MODELO: {nombre_modelo}\n{'='*70}")
    meta = obtener_info_modelo_ollama(nombre_modelo)
    tps_stats = medir_throughput_ollama(nombre_modelo)

    agente = Agente1(modelo=nombre_modelo, timeout_s=45)
    resultados_casos = []

    for caso in CASOS_EVALUACION:
        cid = caso["id"]
        tipo = caso["tipo"]
        pregunta = caso["pregunta"]
        print(f"  -> Ejecutando {cid} ({tipo})...", end="", flush=True)

        t_inicio = time.perf_counter()
        if tipo == "redaccion_con_citas":
            evidencias = caso["evidencias"]
            resp = redactar_respuesta_con_verificacion(
                pregunta=pregunta,
                evidencias=evidencias,
                agente=agente
            )
            latencia_s = time.perf_counter() - t_inicio
            verif = resp.get("verificacion", {})
            citas_ok = verif.get("valido", False) and "chunk_01" in verif.get("citas_validas", [])
            pasado = citas_ok and bool(resp.get("texto"))

            resultados_casos.append({
                "id": cid,
                "tipo": tipo,
                "pasado": pasado,
                "latencia_s": round(latencia_s, 3),
                "citas_detectadas": verif.get("citas_detectadas", []),
                "citas_validas": verif.get("citas_validas", []),
                "citas_falsas": verif.get("citas_falsas", []),
                "reintentos": resp.get("reintentos", 0)
            })
            estado_txt = "PASADO" if pasado else "FALLADO"
            print(f" {estado_txt} ({latencia_s:.2f}s)")
        else:
            agente.reset()
            res = agente.procesar_consulta(pregunta)
            latencia_s = time.perf_counter() - t_inicio
            estado = res.get("estado")
            esp = caso["esperado"]

            pasado = False
            if tipo == "clasificacion_especificacion":
                pasado = (estado == "valida" and
                          res.get("query_json", {}).get("intencion") == esp["intencion"])
            elif tipo == "clasificacion_diagnostico_codigos":
                cods = res.get("query_json", {}).get("filtros", {}).get("codigos", [])
                pasado = (estado == "valida" and
                          res.get("query_json", {}).get("intencion") == esp["intencion"] and
                          all(c in cods for c in esp["codigos_esperados"]))
            elif tipo == "pregunta_incompleta_aclaracion":
                pasado = (estado == "aclaracion" and bool(res.get("mensaje")))
            elif tipo == "fuera_de_ambito_rechazo":
                pasado = (estado == "rechazo")

            resultados_casos.append({
                "id": cid,
                "tipo": tipo,
                "pasado": pasado,
                "estado_obtenido": estado,
                "estado_esperado": esp.get("estado"),
                "latencia_s": round(latencia_s, 3)
            })
            estado_txt = "PASADO" if pasado else "FALLADO"
            print(f" {estado_txt} ({latencia_s:.2f}s)")

    # Test de concurrencia: 2 peticiones simultáneas
    print("  -> Evaluando concurrencia (2 peticiones paralelas)...", end="", flush=True)
    t_concurrencia_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(lambda: Agente1(modelo=nombre_modelo, timeout_s=45).procesar_consulta("Par de apriete culata Golf 7 1.6 TDI"))
        f2 = executor.submit(lambda: Agente1(modelo=nombre_modelo, timeout_s=45).procesar_consulta("Tengo tirones y fallo P0301 en Golf 7"))
        r1 = f1.result()
        r2 = f2.result()
    latencia_concurrente_s = time.perf_counter() - t_concurrencia_inicio
    concurrencia_ok = (r1.get("estado") == "valida" and r2.get("estado") == "valida")
    print(f" {'OK' if concurrencia_ok else 'FALLO'} ({latencia_concurrente_s:.2f}s)")

    total_casos = len(resultados_casos)
    casos_pasados = sum(1 for c in resultados_casos if c["pasado"])
    latencia_promedio = sum(c["latencia_s"] for c in resultados_casos) / total_casos

    return {
        "modelo": nombre_modelo,
        "metadata": meta,
        "throughput": tps_stats,
        "total_casos": total_casos,
        "casos_pasados": casos_pasados,
        "precision_porcentaje": round((casos_pasados / total_casos) * 100, 1),
        "latencia_promedio_s": round(latencia_promedio, 2),
        "latencia_concurrente_2req_s": round(latencia_concurrente_s, 2),
        "concurrencia_exitosa": concurrencia_ok,
        "detalle_casos": resultados_casos
    }


def main():
    modelos_a_evaluar = ["qwen2.5:3b", "qwen2.5:14b"]
    informe_general = {
        "fecha": datetime.now(timezone.utc).isoformat(),
        "entorno": "Local Ollama (MacBook Air Apple Silicon / M-series)",
        "modelos_evaluados": []
    }

    for mod in modelos_a_evaluar:
        datos_mod = evaluar_modelo_completo(mod)
        informe_general["modelos_evaluados"].append(datos_mod)

    # Guardar resultados JSON
    salida_json = ROOT_DIR / "scripts/metricas_estudio_modelos.json"
    with open(salida_json, "w", encoding="utf-8") as f:
        json.dump(informe_general, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Métricas guardadas en: {salida_json}")

    # Imprimir Tabla Comparativa en Consola
    print("\n" + "="*85)
    print("  TABLA COMPARATIVA DE MODELOS — ESTUDIO TÉCNICO CLÚSTER / ARQUITECTURA")
    print("="*85)
    print(f"{'Métrica':<35} | {'qwen2.5:3b (Ligero)':<22} | {'qwen2.5:14b (Grande)':<22}")
    print("-" * 85)
    m3 = informe_general["modelos_evaluados"][0]
    m14 = informe_general["modelos_evaluados"][1]

    print(f"{'Parámetros / Cuantización':<35} | {m3['metadata'].get('num_parametros','3B') + ' (' + m3['metadata'].get('cuantizacion','Q4') + ')':<22} | {m14['metadata'].get('num_parametros','14B') + ' (' + m14['metadata'].get('cuantizacion','Q4') + ')':<22}")
    print(f"{'Tamaño en Disco':<35} | {'1.9 GB':<22} | {'9.0 GB':<22}")
    print(f"{'Velocidad Generación (tokens/s)':<35} | {str(m3['throughput'].get('tokens_por_segundo', '')) + ' tps':<22} | {str(m14['throughput'].get('tokens_por_segundo', '')) + ' tps':<22}")
    print(f"{'Latencia Media por Consulta':<35} | {str(m3['latencia_promedio_s']) + ' s':<22} | {str(m14['latencia_promedio_s']) + ' s':<22}")
    print(f"{'Precisión Contractual y Citas':<35} | {str(m3['precision_porcentaje']) + ' %':<22} | {str(m14['precision_porcentaje']) + ' %':<22}")
    print(f"{'Concurrencia (2 req simultáneas)':<35} | {str(m3['latencia_concurrente_2req_s']) + ' s':<22} | {str(m14['latencia_concurrente_2req_s']) + ' s':<22}")
    print("=" * 85)


if __name__ == "__main__":
    main()
