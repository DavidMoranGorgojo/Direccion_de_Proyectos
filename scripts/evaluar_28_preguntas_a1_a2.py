#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — Tarea 2: Evaluación de las 28 Preguntas (20 Control + 8 Trampa)
=============================================================================
Ejecuta el flujo completo Agente 1 <-> Agente 2 (CTR-004) sobre las 20 preguntas
oficiales de control de ThermoDrive HTM-240 y las 8 preguntas trampa anti-alucinación.

Registra en cada pregunta:
  - Si Agente 2 recuperó la evidencia/documento esperado.
  - Si Agente 1 generó la respuesta verificada o pidió aclaración/bloqueó la trampa.
  - Clasificación del fallo (si ocurre): Fallo Agente 2 (recuperación/filtros) vs
    Fallo Agente 1 (preprocesado/verificación citas).

Genera:
  - docs/INFORME_PRUEBA_28_PREGUNTAS.md (Tabla de resultados y reparto de fallos)
  - scripts/resultado_28_preguntas.json (Traza completa en bruto)
=============================================================================
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

os.environ["ARSOFT_ENV"] = "test"
os.environ["ARSOFT_ALLOW_SYNTHETIC_CATALOGS"] = "1"

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.agente1.core import Agente1, consultar_asistente
from Agents.Agent_2.src.clients.backend import load_chunks, BackendAPIClient
from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline
from Agents.Agent_2.src.services.filter_vocab import VALID_COMPONENTS
from Agents.Agent_2.src.services.filters import normalize_component

FIXTURES_DATASET = ROOT_DIR / "Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json"

PREGUNTAS_CONTROL = [
    {"id": "CTRL-01", "tipo": "control", "doc_esperado": "HTM240-MAN-001", "pregunta": "¿Cuál es la función principal del sistema ThermoDrive HTM-240?"},
    {"id": "CTRL-02", "tipo": "control", "doc_esperado": "HTM240-MAN-001", "pregunta": "¿Cómo se llaman los tres circuitos térmicos independientes que componen la arquitectura funcional?"},
    {"id": "CTRL-03", "tipo": "control", "doc_esperado": "HTM240-CAT-001", "pregunta": "¿Qué componente es el CMP-04 y qué permite hacer a la Unidad de Control Térmico (TCU)?"},
    {"id": "CTRL-04", "tipo": "control", "doc_esperado": "HTM240-CAT-001", "pregunta": "¿A qué temperatura inicial debe abrir el termostato electrónico (CMP-08)?"},
    {"id": "CTRL-05", "tipo": "control", "doc_esperado": "HTM240-MAN-001", "pregunta": "¿Cuál es el rango normal de temperatura de funcionamiento para el inversor (Circuito CIR-03)?"},
    {"id": "CTRL-06", "tipo": "control", "doc_esperado": "HTM240-MAN-001", "pregunta": "¿Qué diferencia principal existe en el calentador PTC (CMP-12) entre la versión V1.0 y la versión V2.0?"},
    {"id": "CTRL-07", "tipo": "control", "doc_esperado": "HTM240-MNT-001", "pregunta": "Según el plan de mantenimiento preventivo, ¿qué líquido refrigerante consumible debe utilizarse en el sistema?"},
    {"id": "CTRL-08", "tipo": "control", "doc_esperado": "HTM240-PRC-001", "pregunta": "¿Qué riesgo principal existe al inspeccionar el nivel de refrigerante (HTM240-PRC-001) y a qué temperatura debe estar el motor?"},
    {"id": "CTRL-09", "tipo": "control", "doc_esperado": "HTM240-BOL-002", "pregunta": "En la versión V1.1 y V2.0, ¿qué caudal y corriente debe registrar la bomba auxiliar A (CMP-02) durante su verificación?"},
    {"id": "CTRL-10", "tipo": "control", "doc_esperado": "HTM240-DIC-001", "pregunta": "¿Qué significa coloquialmente que el vehículo está en 'Modo tortuga'?"},
    {"id": "CTRL-11", "tipo": "control", "doc_esperado": "HTM240-PRC-008", "pregunta": "Durante una comprobación de fugas (PRC-008), ¿qué herramienta ficticia se recomienda usar junto con una linterna UV si no hay fugas visibles a simple vista?"},
    {"id": "CTRL-12", "tipo": "control", "doc_esperado": "HTM240-PRC-009", "pregunta": "Al comprobar la presión del circuito de motor (PRC-009), ¿hasta cuántos bares se debe presurizar el circuito y durante cuánto tiempo?"},
    {"id": "CTRL-13", "tipo": "control", "doc_esperado": "HTM240-DTC-001", "pregunta": "¿Qué código DTC se asocia a la detección de contaminación cruzada con aceite en el circuito refrigerante?"},
    {"id": "CTRL-14", "tipo": "control", "doc_esperado": "HTM240-ADV-001", "pregunta": "¿Qué significa el testigo TES-05 encendido en color rojo?"},
    {"id": "CTRL-15", "tipo": "control", "doc_esperado": "HTM240-SEG-001", "pregunta": "¿Qué equipo de protección individual se debe usar, de forma ficticia, cuando exista proximidad a componentes de alta tensión?"},
    {"id": "CTRL-16", "tipo": "control", "doc_esperado": "HTM240-HIS-001", "pregunta": "En el Historial de Casos (HTM-CASO-002), ¿cuál fue la causa raíz de una alerta de reducción de velocidad durante la carga rápida?"},
    {"id": "CTRL-17", "tipo": "control", "doc_esperado": "HTM240-BOL-003", "pregunta": "Según el boletín técnico HTM240-BOL-003, ¿qué indica el código HTM-0142 en la versión de software V2.0?"},
    {"id": "CTRL-18", "tipo": "control", "doc_esperado": "HTM240-MNT-001", "pregunta": "¿Cada cuánto tiempo o kilometraje se debe verificar de forma completa la comunicación CAN de la TCU?"},
    {"id": "CTRL-19", "tipo": "control", "doc_esperado": "HTM240-BOL-006", "pregunta": "El boletín HTM240-BOL-006 corrige un dato sobre el plan de mantenimiento. ¿A qué kilómetros debe cambiarse el refrigerante y qué cifra era incorrecta?"},
    {"id": "CTRL-20", "tipo": "control", "doc_esperado": "HTM240-DIA-001", "pregunta": "Si tres o más testigos se activan simultáneamente, ¿qué procedimiento hay que ejecutar antes de asumir un fallo único?"},
]

PREGUNTAS_TRAMPA = [
    {"id": "TRAMP-01", "tipo": "trampa", "doc_esperado": None, "pregunta": "¿Cuál es la presión recomendada para el inflado de los neumáticos delanteros del HTM-240?"},
    {"id": "TRAMP-02", "tipo": "trampa", "doc_esperado": None, "pregunta": "¿Qué aceite de motor (qué grado de viscosidad) debo usar al rellenar el cárter?"},
    {"id": "TRAMP-03", "tipo": "trampa", "doc_esperado": None, "pregunta": "El cliente se queja de que el aire acondicionado (A/C) del habitáculo no enfría en verano. ¿Cómo recargo el gas frigorífico?"},
    {"id": "TRAMP-04", "tipo": "trampa", "doc_esperado": None, "pregunta": "¿Cada cuántos kilómetros se debe sustituir la correa de distribución que mueve la bomba mecánica (CMP-01)?"},
    {"id": "TRAMP-05", "tipo": "trampa", "doc_esperado": None, "pregunta": "Tengo el código de error HTM-0850 en la máquina de diagnóstico. ¿Qué debo revisar?"},
    {"id": "TRAMP-06", "tipo": "trampa", "doc_esperado": None, "pregunta": "¿A qué par de apriete exacto (en Nm) debo apretar los tornillos de la culata del bloque motor?"},
    {"id": "TRAMP-07", "tipo": "trampa", "doc_esperado": None, "pregunta": "No me queda refrigerante ThermoGlyc HX-40. ¿Es seguro mezclarlo con anticongelante genérico G12 de color rosa?"},
    {"id": "TRAMP-08", "tipo": "trampa", "doc_esperado": None, "pregunta": "¿Cómo se purga el sistema de líquido de frenos del HTM-240?"},
]


class LocalSimEmbedder:
    def __init__(self, simulator):
        self._sim = simulator

    def encode(self, text, use_prefix=True):
        prefixed = f"query: {text}" if not text.startswith("query: ") else text
        return self._sim.embed_query(prefixed)


def crear_agente2_instrumentado():
    chunks = load_chunks(FIXTURES_DATASET)
    simulador = BackendSimulator(chunks)
    backend_client = BackendAPIClient(
        base_url="http://backend.local-simulado",
        model_embeddings=simulador.modelo_embeddings,
        session=SimulatedSession(simulador),
        timeout=5.0,
    )
    pipeline = Agent2Pipeline(
        backend_client=backend_client,
        embedding_client=LocalSimEmbedder(simulador),
        reranker_model=None,
        threshold=0.0,
    )
    ultima_traza_a2 = {}

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
        res = pipeline.procesar_consulta(q)
        ultima_traza_a2.clear()
        ultima_traza_a2.update({
            "query_enviada": q,
            "estado_a2": res.get("estado"),
            "docs_recuperados": [e.get("metadata", {}).get("documento") for e in res.get("evidencias", [])],
            "chunks_recuperados": [e.get("chunk_id") for e in res.get("evidencias", [])],
            "mensaje_error_a2": res.get("mensaje_error")
        })
        return res

    return handler, ultima_traza_a2


def evaluar_bateria(modelo: str, timeout_s: float = 90.0, modelo_redactor=None, fallback=False):
    agente2_func, traza_a2 = crear_agente2_instrumentado()
    todas = PREGUNTAS_CONTROL + PREGUNTAS_TRAMPA
    resultados = []

    print("=" * 80)
    print(f"  TAREA 2: BATERÍA OFICIAL DE 28 PREGUNTAS (20 CONTROL + 8 TRAMPA)")
    print(f"  Modelo LLM: {modelo} | Redactor: {modelo_redactor or modelo} | Fallback extractivo: {fallback} | Timeout: {timeout_s}s")
    print("=" * 80)

    # Pre-calentar el modelo en Ollama para evitar timeouts de carga en frío en la pregunta 1
    print(f"Cargando modelo {modelo} en memoria de Ollama...", end=" ", flush=True)
    ag_warmup = Agente1(modelo=modelo, timeout_s=timeout_s)
    ag_warmup._consultar_llm([{"role": "user", "content": "Responde OK"}])
    print("Listo.\n")

    for idx, item in enumerate(todas, 1):
        pid = item["id"]
        tipo = item["tipo"]
        doc_esp = item["doc_esperado"]
        pregunta = item["pregunta"]

        print(f"[{idx:02d}/28] {pid} ({tipo.upper():<7}) ... ", end="", flush=True)
        agente1 = Agente1(modelo=modelo, timeout_s=timeout_s, modelo_redactor=modelo_redactor, fallback_extractivo=fallback)
        traza_a2.clear()

        t0 = time.perf_counter()
        res_a1 = consultar_asistente(pregunta, agente1, agente2=agente2_func)
        latencia = time.perf_counter() - t0

        estado_a1 = res_a1.get("estado")
        texto_a1 = res_a1.get("texto", "")
        fuentes_a1 = res_a1.get("fuentes", [])
        docs_a2 = traza_a2.get("docs_recuperados", [])
        estado_a2 = traza_a2.get("estado_a2")

        # Evaluar resultado
        doc_encontrado_por_a2 = (doc_esp in docs_a2) if doc_esp else None
        if tipo == "control":
            if estado_a1 == "respuesta" and len(fuentes_a1) > 0:
                if any(str(f.get("chunk_id", "")).startswith(doc_esp) for f in fuentes_a1):
                    veredicto = "OK (Respuesta verificada)"
                else:
                    veredicto = "FALLO (Respuesta fuera de tema)"
            elif estado_a1 == "aclaracion":
                veredicto = "OK (Aclaración versión)" if doc_encontrado_por_a2 else "FALLO (A2 no halló doc)"
            elif not traza_a2:
                veredicto = "FALLO A1 (Falso negativo / rechazo)"
            elif not doc_encontrado_por_a2:
                veredicto = f"FALLO A2 (No recuperó {doc_esp})"
            else:
                veredicto = f"FALLO A1 (Redactor/Verificador {estado_a1})"
        else:
            # Trampa: debe abstenerse (fuera_de_ambito, sin_evidencia o bloqueo de seguridad)
            if estado_a1 in {"fuera_de_ambito", "sin_evidencia"}:
                veredicto = f"OK (Frenada: {estado_a1})"
            elif estado_a1 == "error" and "Error de verificación" in texto_a1:
                veredicto = "OK (Bloqueo seguridad A1-07)"
            else:
                veredicto = f"FALLO ALUCINACIÓN ({estado_a1})"

        print(f"{veredicto} ({latencia:.2f}s)")
        resultados.append({
            "id": pid,
            "tipo": tipo,
            "pregunta": pregunta,
            "doc_esperado": doc_esp,
            "estado_a2": estado_a2,
            "docs_recuperados_a2": docs_a2,
            "doc_encontrado_a2": doc_encontrado_por_a2,
            "estado_a1": estado_a1,
            "fuentes_a1": [f.get("chunk_id") for f in fuentes_a1],
            "texto_a1": texto_a1,
            "latencia_s": round(latencia, 2),
            "veredicto": veredicto
        })

    # Guardar JSON y generar informe Markdown
    tag = modelo.replace(":", "_").replace("/", "_") + ("_redactor-" + modelo_redactor.replace(":", "_") if modelo_redactor else "") + ("_fallback" if fallback else "")
    json_out = ROOT_DIR / f"scripts/resultado_28_preguntas_{tag}.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": datetime.now(timezone.utc).isoformat(),
            "modelo": modelo,
            "resultados": resultados
        }, f, ensure_ascii=False, indent=2)

    generar_informe_markdown(resultados, modelo, tag)
    print(f"\n[OK] Resultados guardados en {json_out} y docs/INFORME_PRUEBA_28_PREGUNTAS_{tag}.md")


def generar_informe_markdown(resultados, modelo, tag):
    ctrl = [r for r in resultados if r["tipo"] == "control"]
    tramp = [r for r in resultados if r["tipo"] == "trampa"]
    ok_ctrl = sum(1 for r in ctrl if r["veredicto"].startswith("OK"))
    ok_tramp = sum(1 for r in tramp if r["veredicto"].startswith("OK"))
    a2_hits = sum(1 for r in ctrl if r["doc_encontrado_a2"])
    resp_real = sum(1 for r in ctrl if r["estado_a1"] == "respuesta" and r["fuentes_a1"])

    md = [
        "# Informe de Pruebas Integradas: 20 Control + 8 Trampa (Agente 1 + Agente 2)\n",
        f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"**Modelo LLM:** `{modelo}` (Ollama Local)  ",
        f"**Dataset:** `bbdd_sintetica_chunks.json` (98 fragmentos)  \n",
        "## 1. Resumen Ejecutivo\n",
        f"| Bloque | Total | Superadas (OK) | Tasa de Éxito |",
        f"| :--- | :---: | :---: | :---: |",
        f"| **20 Preguntas de Control** | 20 | **{ok_ctrl}** | {round(100*ok_ctrl/20, 1)}% |",
        f"| **8 Preguntas Trampa (Anti-Alucinación)** | 8 | **{ok_tramp}** | {round(100*ok_tramp/8, 1)}% |",
        f"| **Recuperación Documental Agente 2** | 20 | **{a2_hits}** | {round(100*a2_hits/20, 1)}% |",
        f"| **Respuestas finales con citas verificadas (control)** | 20 | **{resp_real}** | {round(100*resp_real/20, 1)}% |\n",
        "## 2. Desglose de las 20 Preguntas de Control\n",
        "| ID | Doc Esperado | Recuperado por A2 | Estado A1 | Veredicto |",
        "| :--- | :--- | :---: | :--- | :--- |"
    ]

    for r in ctrl:
        a2_ok = "✅" if r["doc_encontrado_a2"] else f"❌ ({', '.join(set(filter(None, r['docs_recuperados_a2']))) or 'Vacío'})"
        md.append(f"| {r['id']} | `{r['doc_esperado']}` | {a2_ok} | `{r['estado_a1']}` | {r['veredicto']} |")

    md.extend([
        "\n## 3. Desglose de las 8 Preguntas Trampa\n",
        "| ID | Estado A2 | Estado A1 | Veredicto Anti-Alucinación |",
        "| :--- | :--- | :--- | :--- |"
    ])
    for r in tramp:
        md.append(f"| {r['id']} | `{r['estado_a2']}` | `{r['estado_a1']}` | {r['veredicto']} |")

    md.append("\n## 4. Fallos Detectados y Reparto de Correcciones\n")
    fallos = [r for r in resultados if not r["veredicto"].startswith("OK")]
    if not fallos:
        md.append("No se detectaron fallos en esta ejecución.")
    else:
        for r in fallos:
            md.append(f"- **{r['id']} ({r['veredicto']})**: Pregunta: *\"{r['pregunta']}\"*")
            md.append(f"  - Docs A2: `{r['docs_recuperados_a2']}` | Estado A1: `{r['estado_a1']}`")

    md_path = ROOT_DIR / f"docs/INFORME_PRUEBA_28_PREGUNTAS_{tag}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluar las 28 preguntas (Tarea 2)")
    parser.add_argument("--modelo", default="qwen2.5:3b", help="Modelo LLM (qwen2.5:3b o qwen2.5:14b)")
    parser.add_argument("--timeout", type=float, default=90.0, help="Timeout por turno en segundos")
    parser.add_argument("--modelo-redactor", default=None, help="Modelo distinto para redactar (ej. qwen2.5:14b)")
    parser.add_argument("--fallback-extractivo", action="store_true", help="Activa el fallback extractivo determinista")
    args = parser.parse_args()
    evaluar_bateria(modelo=args.modelo, timeout_s=args.timeout, modelo_redactor=args.modelo_redactor, fallback=args.fallback_extractivo)
