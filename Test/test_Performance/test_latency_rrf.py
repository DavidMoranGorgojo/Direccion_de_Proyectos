import statistics
import time

from Agents.Agent_2.src.services.fusion import rrf


def test_latency_rrf():
    """Mide la latencia del RRF con resultados sintéticos."""

    vectoriales = [
        {"chunk_id": f"chunk_{i}", "texto": f"Texto {i}"}
        for i in range(100)
    ]

    bm25 = [
        {"chunk_id": f"chunk_{i}", "texto": f"Texto {i}"}
        for i in range(50, 150)
    ]

    # Calentamiento
    for _ in range(100):
        rrf(vectoriales, bm25)

    # Mediciones
    tiempos = []

    for _ in range(1000):
        inicio = time.perf_counter()
        resultados = rrf(vectoriales, bm25)
        tiempos.append((time.perf_counter() - inicio) * 1000)

    assert len(resultados) == 150

    tiempos_ordenados = sorted(tiempos)

    media = statistics.mean(tiempos)
    mediana = statistics.median(tiempos)
    p95 = tiempos_ordenados[949]
    maximo = max(tiempos)

    print("\n--- Benchmark RRF (A2-09) ---")
    print(f"Ejecuciones: {len(tiempos)}")
    print(f"Media: {media:.4f} ms")
    print(f"Mediana: {mediana:.4f} ms")
    print(f"P95: {p95:.4f} ms")
    print(f"Máximo: {maximo:.4f} ms")