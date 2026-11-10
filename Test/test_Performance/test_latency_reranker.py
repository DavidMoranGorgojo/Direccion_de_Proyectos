
"""
Benchmark de latencia del reranker real del Agente 2.

Mide:
- Tiempo de carga inicial del modelo.
- Latencia de reranking con diferentes cantidades de candidatos.
- Media, mediana, percentil 95 y máximo.

No incluye el resto del pipeline RAG.
"""

import math
import os
import statistics
import time

import pytest

from Agents.Agent_2.src.clients.reranker_model import RerankerModel
from Agents.Agent_2.src.services.reranker import rerank_results


MODELO_RERANKER = "BAAI/bge-reranker-v2-m3"
CANTIDADES_CANDIDATOS = (1, 5, 10, 20)
NUM_MEDICIONES = 20
NUM_CALENTAMIENTOS = 2


def calcular_percentil_95(tiempos):
    """
    Calcula el percentil 95 mediante el método de rango más cercano.
    """
    tiempos_ordenados = sorted(tiempos)
    indice = math.ceil(0.95 * len(tiempos_ordenados)) - 1
    return tiempos_ordenados[indice]


def generar_candidatos(cantidad):
    """Genera candidatos sintéticos para medir la inferencia."""
    return [
        {
            "chunk_id": f"C{i}",
            "texto": (
                "La bomba auxiliar suministra presión al sistema."
                if i % 2 == 0
                else "El calendario de vacaciones se publica en enero."
            ),
        }
        for i in range(cantidad)
    ]


@pytest.mark.skipif(
    os.getenv("RUN_REAL_RERANKER_TEST") != "1",
    reason="Benchmark del modelo real desactivado por defecto",
)
def test_latency_reranker_real():
    """
    Compara la latencia del reranker real para diferentes
    cantidades de candidatos.

    El modelo se carga una vez y se reutiliza durante
    todas las mediciones.
    """
    from FlagEmbedding import FlagReranker

    consulta = "¿Cómo funciona la bomba auxiliar?"

    inicio_carga = time.perf_counter()

    modelo_real = FlagReranker(
        MODELO_RERANKER,
        use_fp16=False,
    )

    modelo = RerankerModel(model=modelo_real)

    tiempo_carga_ms = (
        time.perf_counter() - inicio_carga
    ) * 1000

    print("\n--- Benchmark reranker real (A2-09) ---")
    print(f"Modelo: {MODELO_RERANKER}")
    print(f"Tiempo de carga: {tiempo_carga_ms:.2f} ms")
    print(f"Mediciones por tamaño: {NUM_MEDICIONES}")
    print(f"Calentamientos por tamaño: {NUM_CALENTAMIENTOS}")

    for cantidad in CANTIDADES_CANDIDATOS:
        resultados = generar_candidatos(cantidad)

        for _ in range(NUM_CALENTAMIENTOS):
            rerank_results(
                consulta,
                resultados,
                modelo,
            )

        tiempos = []

        for _ in range(NUM_MEDICIONES):
            inicio = time.perf_counter()

            resultados_ordenados = rerank_results(
                consulta,
                resultados,
                modelo,
            )

            duracion_ms = (
                time.perf_counter() - inicio
            ) * 1000

            tiempos.append(duracion_ms)

            assert len(resultados_ordenados) == cantidad

        assert len(tiempos) == NUM_MEDICIONES
        assert all(
            math.isfinite(tiempo) and tiempo > 0
            for tiempo in tiempos
        )

        media = statistics.mean(tiempos)
        mediana = statistics.median(tiempos)
        p95 = calcular_percentil_95(tiempos)
        maximo = max(tiempos)

        print(f"\nCandidatos: {cantidad}")
        print(f"Media: {media:.2f} ms")
        print(f"Mediana: {mediana:.2f} ms")
        print(f"P95: {p95:.2f} ms")
        print(f"Máximo: {maximo:.2f} ms")
