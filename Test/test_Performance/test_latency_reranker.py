
import os
import statistics
import time

import pytest

from Agents.Agent_2.src.clients.reranker_model import RerankerModel
from Agents.Agent_2.src.services.reranker import rerank_results


@pytest.mark.skipif(
    os.getenv("RUN_REAL_RERANKER_TEST") != "1",
    reason="Benchmark del modelo real desactivado por defecto",
)
def test_latency_reranker_real():
    """
    Mide el tiempo de carga y la latencia de inferencia
    del reranker real BAAI/bge-reranker-v2-m3.

    La medición incluye nuestro adaptador y el servicio
    rerank_results(), pero no el resto del pipeline.
    """

    from FlagEmbedding import FlagReranker

    consulta = "¿Cómo funciona la bomba auxiliar?"

    resultados = [
        {
            "chunk_id": f"C{i}",
            "texto": (
                "La bomba auxiliar suministra presión al sistema."
                if i % 2 == 0
                else "El calendario de vacaciones se publica en enero."
            ),
        }
        for i in range(10)
    ]

    # Medir la inicialización del modelo.
    inicio_carga = time.perf_counter()

    modelo_real = FlagReranker(
        "BAAI/bge-reranker-v2-m3",
        use_fp16=False,
    )

    modelo = RerankerModel(model=modelo_real)

    tiempo_carga_ms = (
        time.perf_counter() - inicio_carga
    ) * 1000

    # Calentamiento: no incluir la primera inferencia
    # en las mediciones.
    rerank_results(consulta, resultados, modelo)

    tiempos = []
    resultados_ordenados = None

    # Pocas iteraciones porque el modelo puede ejecutarse
    # en CPU y cada inferencia puede ser costosa.
    for _ in range(10):
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

    assert len(resultados_ordenados) == 10
    assert len(tiempos) == 10
    assert all(tiempo > 0 for tiempo in tiempos)

    tiempos_ordenados = sorted(tiempos)

    media = statistics.mean(tiempos)
    mediana = statistics.median(tiempos)
    p95 = tiempos_ordenados[9]
    maximo = max(tiempos)

    print("\n--- Benchmark reranker real (A2-09) ---")
    print("Modelo: BAAI/bge-reranker-v2-m3")
    print("Candidatos por consulta: 10")
    print(f"Tiempo de carga: {tiempo_carga_ms:.2f} ms")
    print(f"Ejecuciones medidas: {len(tiempos)}")
    print(f"Media: {media:.2f} ms")
    print(f"Mediana: {mediana:.2f} ms")
    print(f"P95: {p95:.2f} ms")
    print(f"Máximo: {maximo:.2f} ms")
