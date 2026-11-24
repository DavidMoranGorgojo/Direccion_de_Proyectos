#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — RAG Completo con Inferencia en Clúster Legio
=============================================================================
Ejecuta el pipeline RAG completo del Asistente Técnico ThermoDrive HTM-240
combinando:
  1. Búsqueda y filtrado local en PC (BM25 + Hard Filters sobre ~98 fragmentos).
  2. Extracción de intención y Query JSON CTR-004 vía Clúster Legio (rol 'rapido').
  3. Redacción técnica y citas extractivas obligatorias vía Clúster Legio (rol 'potente').
  4. Verificador de citas y seguridad extractiva A1-07 (máximo 1 reintento).

Precauciones operativas del clúster Legio:
  - El nodo 'legio2' es de acceso con cuota estricta (4 GiB RAM, 1 CPU por usuario).
    No ejecutar procesos de cálculo pesados directamente en 'legio2'.
  - Las GPUs del clúster son compartidas: no lanzar miles de peticiones automáticas.
  - El túnel SSH se abre desde el PC local hacia el clúster.

Requisitos previos:
  - Túnel SSH activo en otra terminal:
    ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97
    (Activar la VPN de la ULE si se conecta desde fuera del campus).
  - Clave en ~/.config/llm-gvis/api_key o variable LLM_KEY.

Uso:
  python scripts/probar_rag_cluster.py
  python scripts/probar_rag_cluster.py --pregunta "¿Cuál es el par de apriete de los tornillos de culata V1.1?"
=============================================================================
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Configuración del entorno de prueba local para catálogos del Agente 2
os.environ["ARSOFT_ENV"] = "test"
os.environ["ARSOFT_ALLOW_SYNTHETIC_CATALOGS"] = "1"
os.environ["LLM_PROVIDER"] = "cluster"

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from Agents.agente1.core import Agente1, consultar_asistente
from Agents.agente1.cliente_cluster import (
    ClienteClusterLegio,
    TunelClusterError,
    AutenticacionClusterError,
    verificar_puerto_abierto,
)
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
    """Inicializa la búsqueda local en el PC sin requerir PostgreSQL ni pgvector remoto."""
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

    return agente2_handler, len(chunks)


def ejecutar_consulta_rag(pregunta: str, agente1: Agente1, agente2_func):
    print("\n" + "=" * 78)
    print(f"  CONSULTA DEL TÉCNICO: \"{pregunta}\"")
    print("=" * 78)

    t0 = time.perf_counter()
    try:
        resultado = consultar_asistente(pregunta, agente1, agente2=agente2_func)
    except TunelClusterError as err:
        print(f"\n[ERROR DE CONEXIÓN CON CLÚSTER]:\n{err}")
        return None
    duracion = time.perf_counter() - t0

    print(f"\n[TIEMPO TOTAL]: {duracion:.2f} s | [ESTADO]: {resultado.get('estado')}")
    print("\n--- RESPUESTA GENERADA AL TÉCNICO ---")
    print(resultado.get("texto", "").strip())

    fuentes = resultado.get("fuentes", [])
    if fuentes:
        print("\n--- FUENTES Y CITAS VERIFICADAS ---")
        for f in fuentes:
            print(f"  • Chunk: {f.get('chunk_id')} | Doc: {f.get('documento')} | Pág: {f.get('pagina')}")
    else:
        print("\n(No se citaron fuentes o la consulta no requirió evidencias)")
    print("=" * 78 + "\n")
    return resultado


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="RAG Automotriz con Clúster Legio")
    parser.add_argument("--pregunta", type=str, help="Pregunta personalizada")
    parser.add_argument("--url", default="http://localhost:4000/v1", help="URL base del túnel LLM")
    args = parser.parse_args()

    print("\n" + "=" * 78)
    print("  ASISTENTE TÉCNICO AUTOMOTRIZ THERMODRIVE HTM-240")
    print("  Búsqueda Local (BM25 + Hard Filters) + LLM Clúster Legio (http://localhost:4000/v1)")
    print("=" * 78)

    # 1. Comprobar socket túnel
    if not verificar_puerto_abierto(host="127.0.0.1", puerto=4000, timeout_s=1.0):
        print("\n[AVISO CRÍTICO] El puerto 4000 no responde en localhost.")
        print("Para conectar con el clúster, abre otra terminal y ejecuta:")
        print("  ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97")
        print("(Asegúrate de tener activa la VPN de la ULE si estás fuera del campus).\n")
        sys.exit(1)

    # 2. Inicializar cliente clúster
    cliente_llm = ClienteClusterLegio(base_url=args.url, timeout_s=45.0)
    if not cliente_llm.tiene_credenciales():
        print("\n[ERROR] No se encontró la API Key en LLM_KEY ni en ~/.config/llm-gvis/api_key.")
        sys.exit(2)

    # 3. Inicializar agentes
    agente2_func, total_chunks = construir_agente2_local()
    print(f"  [OK] Agente 2 local cargado ({total_chunks} fragmentos indexados en memoria).")

    agente1 = Agente1(cliente_cluster=cliente_llm, timeout_s=45.0)
    print(f"  [OK] Agente 1 conectado al clúster [rol rápido: {cliente_llm.modelo_rapido}, rol potente: {cliente_llm.modelo_potente}].")

    pregunta = args.pregunta or "¿A qué temperatura inicial debe abrir el termostato electrónico CMP-08?"
    ejecutar_consulta_rag(pregunta, agente1, agente2_func)


if __name__ == "__main__":
    main()
