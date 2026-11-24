#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — Tarea 1: Flujo Completo Integrado Agente 1 + Agente 2
=============================================================================
Conecta de extremo a extremo:
  1. Agente 1 (Comprensión, Intención y Contrato CTR-004)
  2. Agente 2 (Búsqueda híbrida BM25 + Vectorial + Fusión RRF + Vigencia)
  3. Agente 1 (Redactor técnico, Citas extractivas y Verificador de seguridad A1-07)

Uso:
  python3 scripts/probar_flujo_completo.py
  python3 scripts/probar_flujo_completo.py --pregunta "¿A qué temperatura inicial abre el termostato CMP-08?"
=============================================================================
"""

import os
import sys
import time
import argparse
from pathlib import Path

# Entorno de pruebas para catálogos y dataset sintético
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


class LocalSimEmbedder:
    """Vectorizador local por hash para BGE-M3 (CTR-002 §5.4)."""
    def __init__(self, simulator):
        self._sim = simulator

    def encode(self, text, use_prefix=True):
        prefixed = f"query: {text}" if not text.startswith("query: ") else text
        return self._sim.embed_query(prefixed)


def construir_agente2_local():
    """Inicializa el pipeline del Agente 2 conectado al dataset de 98 fragmentos."""
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
    
    def agente2_handler(query_json):
        """Adaptador de compatibilidad de contrato CTR-004."""
        q = dict(query_json)
        filtros = dict(q.get("filtros", {}))
        
        # Eliminar codigos vacíos para evitar que el validador estricto lo marque como filtro no admitido
        if not filtros.get("codigos"):
            filtros.pop("codigos", None)
            
        # Si componente no es subsistema canónico, moverlo a texto de búsqueda
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

    return agente2_handler, len(chunks)


def ejecutar_flujo(pregunta: str, agente1: Agente1, agente2_func):
    """Ejecuta una consulta a través del flujo completo Agente 1 -> Agente 2 -> Agente 1."""
    print("\n" + "=" * 80)
    print(f"  PREGUNTA DEL TÉCNICO: \"{pregunta}\"")
    print("=" * 80)
    
    t0 = time.perf_counter()
    resultado = consultar_asistente(pregunta, agente1, agente2=agente2_func)
    duracion = time.perf_counter() - t0
    
    print(f"\n[TIEMPO TOTAL]: {duracion:.2f} s | [ESTADO]: {resultado.get('estado')}")
    print("\n--- RESPUESTA GENERADA AL TÉCNICO ---")
    print(resultado.get("texto", "").strip())
    
    fuentes = resultado.get("fuentes", [])
    if fuentes:
        print("\n--- FUENTES Y CITAS VERIFICADAS ---")
        for f in fuentes:
            print(f"  • Chunk ID: {f.get('chunk_id')} | Doc: {f.get('documento')} | Pág: {f.get('pagina')}")
    else:
        print("\n(No hay fuentes citadas o la respuesta fue bloqueada por falta de evidencias)")
    print("=" * 80 + "\n")
    return resultado


def main():
    parser = argparse.ArgumentParser(description="Prueba del flujo completo Agente 1 + Agente 2")
    parser.add_argument("--pregunta", type=str, help="Pregunta personalizada para consultar")
    parser.add_argument("--modelo", default="qwen2.5:3b", help="Modelo LLM de Ollama a usar (3b o 14b)")
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  TAREA 1: INTEGRACIÓN COMPLETA AGENTE 1 + AGENTE 2 (CTR-004)")
    print("=" * 80)
    print(f"  Modelo LLM: {args.modelo} | Ollama Local")
    
    agente2_func, total_chunks = construir_agente2_local()
    print(f"  Agente 2 conectado al dataset sintético ({total_chunks} fragmentos cargados).")
    
    agente1 = Agente1(modelo=args.modelo, timeout_s=45)
    print(f"  Agente 1 inicializado.")

    if args.pregunta:
        ejecutar_flujo(args.pregunta, agente1, agente2_func)
    else:
        # Prueba con dos casos: uno técnico y uno de aclaración
        print("\nEjecutando caso de prueba 1 (Especificación técnica)...")
        ejecutar_flujo("¿A qué temperatura inicial debe abrir el termostato electrónico CMP-08?", agente1, agente2_func)


if __name__ == "__main__":
    main()
