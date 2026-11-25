#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — Prueba de Ejecución Local de Agente 2 (Dataset Sintético)
=============================================================================
Script para validar en local que el pipeline del Agente 2 (recuperador híbrido)
funciona correctamente contra el dataset sintético (98 fragmentos) sin necesidad
de levantar PostgreSQL ni el backend real.

Ejemplos de uso:
  python3 scripts/probar_agente2_local.py
  python3 scripts/probar_agente2_local.py --pregunta "¿Qué componente es el CMP-04 y qué hace?"
  python3 scripts/probar_agente2_local.py --bateria
=============================================================================
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path

# Configuración obligatoria para pruebas locales con dataset y catálogos sintéticos
os.environ["ARSOFT_ENV"] = "test"
os.environ["ARSOFT_ALLOW_SYNTHETIC_CATALOGS"] = "1"

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.Agent_2.src.clients.backend import load_chunks, BackendAPIClient
from Agents.Agent_2.src.testing.backend_simulator import BackendSimulator, SimulatedSession
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

FIXTURES_DATASET = ROOT_DIR / "Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json"


class LocalSimEmbedder:
    """Vectorizador ligero por proyección de hash para pruebas locales sin descargar BGE-M3."""
    def __init__(self, simulator):
        self._sim = simulator

    def encode(self, text, use_prefix=True):
        prefixed = f"query: {text}" if not text.startswith("query: ") else text
        return self._sim.embed_query(prefixed)


def inicializar_pipeline_agente2():
    """Carga los 98 fragmentos del dataset sintético e inicializa el pipeline."""
    if not FIXTURES_DATASET.exists():
        raise FileNotFoundError(f"No se encontró el dataset sintético en: {FIXTURES_DATASET}")

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
        reranker_model=None,  # En prueba local ligera sin GPU se usa RRF puro
        threshold=0.0,
    )
    
    return pipeline, len(chunks)


def consultar_agente2(pipeline, texto_busqueda: str, version: str = None, top_k: int = 5):
    """Ejecuta una consulta al pipeline respetando el contrato CTR-004."""
    query = {
        "trace_id": f"t-local-{int(time.time()*1000)%100000}",
        "intencion": "diagnostico",
        "texto_busqueda": texto_busqueda,
        "terminos_clave": texto_busqueda.split()[:5],
        "filtros": {
            "version": version,
            "componente": None,
            "tipo_documento": None
        },
        "opciones": {
            "top_k": top_k,
            "incluir_obsoletos": False,
            "umbral_similitud": 0.4
        }
    }
    
    t0 = time.perf_counter()
    resultado = pipeline.procesar_consulta(query)
    latencia_ms = (time.perf_counter() - t0) * 1000
    
    return resultado, latencia_ms


def imprimir_resultado(pregunta: str, resultado: dict, latencia_ms: float):
    print("=" * 80)
    print(f"  CONSULTA: \"{pregunta}\"")
    print(f"  Latencia: {latencia_ms:.2f} ms | Estado CTR-004: [{resultado.get('estado')}]")
    print("-" * 80)
    
    evidencias = resultado.get("evidencias", [])
    if not evidencias:
        print("  ⚠️  Sin evidencias recuperadas (o consulta fuera de ámbito).")
        if resultado.get("mensaje_error"):
            print(f"  Mensaje: {resultado['mensaje_error']}")
        print("=" * 80 + "\n")
        return

    print(f"  Se han recuperado {len(evidencias)} evidencias trazables:")
    for i, ev in enumerate(evidencias, 1):
        cid = ev.get("chunk_id", "DESCONOCIDO")
        meta = ev.get("metadata", {})
        doc = meta.get("documento", "N/A")
        vers = meta.get("versiones", [])
        score = ev.get("score_final", 0.0)
        texto = ev.get("texto", "").replace("\n", " ").strip()
        if len(texto) > 130:
            texto = texto[:130] + "..."
            
        print(f"  [{i}] ID: {cid}")
        print(f"      Doc: {doc} | Versiones: {vers} | Score RRF: {score:.4f}")
        print(f"      Texto: \"{texto}\"")
    print("=" * 80 + "\n")


def ejecutar_bateria_pruebas(pipeline):
    """Batería representativa para verificar que el Agente 2 encuentra información técnica."""
    casos = [
        ("¿Qué componente es el CMP-04 y qué permite hacer a la TCU?", None),
        ("¿A qué temperatura inicial debe abrir el termostato electrónico CMP-08?", None),
        ("Caudal y corriente de la bomba auxiliar A CMP-02 en versión V1.1", "V1.1"),
        ("¿Qué código DTC se asocia a contaminación cruzada de aceite en refrigerante?", None),
        ("¿Cuál es la presión recomendada para el inflado de los neumáticos?", None) # Trampa (fuera de ámbito)
    ]
    
    print("\n" + "=" * 80)
    print("  EJECUTANDO BATERÍA DE 5 CONSULTAS TÉCNICAS CONTRA EL AGENTE 2")
    print("=" * 80 + "\n")
    
    for pregunta, ver in casos:
        res, lat = consultar_agente2(pipeline, pregunta, version=ver)
        imprimir_resultado(pregunta, res, lat)


def main():
    parser = argparse.ArgumentParser(description="Prueba local de ejecución del Agente 2")
    parser.add_argument("--pregunta", type=str, help="Pregunta personalizada para consultar")
    parser.add_argument("--version", type=str, default=None, help="Versión del vehículo (ej: V1.1)")
    parser.add_argument("--bateria", action="store_true", help="Ejecutar batería de 5 preguntas de control")
    args = parser.parse_args()

    print("\nInicializando Agente 2 (pipeline híbrido) con el dataset sintético...")
    try:
        pipeline, total_chunks = inicializar_pipeline_agente2()
        print(f"✅ Agente 2 inicializado correctamente con {total_chunks} fragmentos vigentes en memoria.\n")
    except Exception as e:
        print(f"❌ Error al inicializar el Agente 2: {e}")
        sys.exit(1)

    if args.bateria:
        ejecutar_bateria_pruebas(pipeline)
    elif args.pregunta:
        res, lat = consultar_agente2(pipeline, args.pregunta, version=args.version)
        imprimir_resultado(args.pregunta, res, lat)
    else:
        # Por defecto si no se pasa nada, ejecuta una consulta demostrativa y luego invita a probar
        print("💡 Ejecutando consulta de prueba por defecto...\n")
        pregunta_demo = "¿Qué componente es el CMP-04 y qué función tiene?"
        res, lat = consultar_agente2(pipeline, pregunta_demo)
        imprimir_resultado(pregunta_demo, res, lat)
        print("Para probar con tus propias preguntas, ejecuta:")
        print('  python3 scripts/probar_agente2_local.py --pregunta "¿A qué temperatura abre el termostato CMP-08?"')
        print('  python3 scripts/probar_agente2_local.py --bateria\n')


if __name__ == "__main__":
    main()
