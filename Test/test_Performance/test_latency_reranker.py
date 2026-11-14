
"""
Benchmark de latencia del reranker real del Agente 2.

Mide:
- Tiempo de obtención del modelo mediante el cargador oficial.
- Latencia de reranking con diferentes cantidades de candidatos.
- Media, mediana, percentil 95 y máximo.

Utiliza fragmentos sintéticos de longitud representativa
y el mismo cargador de modelos que utiliza el Agente 2.

No incluye el resto del pipeline RAG.

Para ejecutarlo:
    RUN_REAL_RERANKER_TEST=1
"""

import math
import os
import statistics
import time

import pytest

from Agents.Agent_2.src.clients.reranker_loader import get_reranker
from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.services.reranker import rerank_results


CANTIDADES_CANDIDATOS = (1, 5, 10, 20)
NUM_MEDICIONES = 2
NUM_CALENTAMIENTOS = 1

CONSULTA = (
    "¿Qué comprobaciones de mantenimiento deben realizarse "
    "cuando la bomba auxiliar del sistema hidráulico pierde "
    "presión durante el funcionamiento?"
)

FRAGMENTOS_BASE = (
    (
        "El procedimiento de mantenimiento de la bomba auxiliar "
        "establece que, ante una pérdida de presión, el técnico "
        "debe comprobar primero el nivel del fluido hidráulico "
        "y verificar que no existen fugas visibles en las "
        "conexiones, juntas y conductos. A continuación, debe "
        "inspeccionar el estado del filtro de aspiración, "
        "comprobar la temperatura de funcionamiento y registrar "
        "la presión medida en los puntos de control indicados "
        "por el fabricante. Si la presión continúa fuera del "
        "intervalo permitido, se recomienda detener el equipo "
        "y revisar las válvulas de regulación antes de volver "
        "a poner el sistema en servicio."
    ),
    (
        "Durante la inspección preventiva del circuito hidráulico "
        "se debe verificar que la bomba mantiene un caudal "
        "estable y que los sensores de presión transmiten "
        "lecturas coherentes con los instrumentos de referencia. "
        "El personal de mantenimiento debe revisar las posibles "
        "obstrucciones en los conductos, comprobar el estado "
        "de las juntas de estanqueidad y documentar cualquier "
        "vibración o ruido anómalo. Las operaciones de ajuste "
        "deben realizarse siguiendo el procedimiento autorizado "
        "y dejando constancia de las mediciones efectuadas "
        "antes y después de la intervención."
    ),
    (
        "La planificación anual de vacaciones del personal "
        "se elabora a partir de las solicitudes presentadas "
        "por cada departamento y de las necesidades de cobertura "
        "del servicio. El calendario provisional se comunica "
        "a los responsables de área para que revisen posibles "
        "coincidencias y propongan ajustes. Una vez aprobada "
        "la distribución de los periodos de descanso, "
        "la información se incorpora al sistema de gestión "
        "de recursos humanos y se publica conforme a los "
        "plazos establecidos por la organización."
    ),
    (
        "El inventario de materiales de oficina incluye "
        "los consumibles utilizados por los distintos equipos "
        "de trabajo. Cada responsable debe registrar las "
        "necesidades de reposición, comprobar las existencias "
        "disponibles y comunicar las incidencias detectadas "
        "durante la recepción de suministros. El procedimiento "
        "de compras contempla la validación de pedidos, "
        "la comprobación de albaranes y el archivo de "
        "la documentación administrativa correspondiente."
    ),
)


def calcular_percentil_95(tiempos):
    """
    Calcula el percentil 95 mediante el método
    de rango más cercano.
    """

    if not tiempos:
        raise ValueError(
            "No se puede calcular el percentil 95 "
            "de una lista vacía"
        )

    tiempos_ordenados = sorted(tiempos)

    indice = math.ceil(
        0.95 * len(tiempos_ordenados)
    ) - 1

    return tiempos_ordenados[indice]


def generar_candidatos(cantidad):
    """
    Genera candidatos sintéticos con textos documentales
    más largos y puntuaciones RRF válidas.

    Alterna fragmentos relevantes y no relevantes
    para simular una recuperación híbrida.
    """

    if type(cantidad) is not int or cantidad <= 0:
        raise ValueError(
            "La cantidad de candidatos debe ser "
            "un entero mayor que cero"
        )

    candidatos = []

    for indice in range(cantidad):
        texto_base = FRAGMENTOS_BASE[
            indice % len(FRAGMENTOS_BASE)
        ]

        candidatos.append(
            {
                "chunk_id": f"benchmark_{indice}",
                "texto": texto_base,
                "rrf_score": 1 / (config.RRF_K + indice + 1),
                "documento": f"documento_{indice % 4}",
                "pagina": indice + 1,
            }
        )

    return candidatos


@pytest.mark.skipif(
    os.getenv("RUN_REAL_RERANKER_TEST") != "1",
    reason="Benchmark del modelo real desactivado por defecto",
)
def test_latency_reranker_real():
    """
    Mide la latencia del reranker real utilizando
    el cargador oficial del Agente 2.

    El modelo se obtiene una vez y se reutiliza
    durante todas las mediciones.
    """

    if max(CANTIDADES_CANDIDATOS) > config.RERANK_TOP_K:
        pytest.skip(
            "El límite RERANK_TOP_K es inferior "
            "al mayor tamaño del benchmark"
        )

    inicio_carga = time.perf_counter()

    modelo = get_reranker()

    tiempo_obtencion_ms = (
        time.perf_counter() - inicio_carga
    ) * 1000

    print("\n--- Benchmark reranker real (A2-09) ---")
    print(f"Modelo: {config.RERANKER_MODEL}")
    print(
        "Tiempo de obtención del modelo: "
        f"{tiempo_obtencion_ms:.2f} ms"
    )
    print(
        "Nota: este tiempo incluye la carga inicial "
        "solo si el modelo no estaba previamente en caché."
    )
    print(f"Límite de candidatos: {config.RERANK_TOP_K}")
    print(f"Mediciones por tamaño: {NUM_MEDICIONES}")
    print(
        f"Calentamientos por tamaño: {NUM_CALENTAMIENTOS}"
    )

    for cantidad in CANTIDADES_CANDIDATOS:
        resultados = generar_candidatos(cantidad)

        longitudes = [
            len(resultado["texto"].split())
            for resultado in resultados
        ]

        print(f"\nCandidatos: {cantidad}")
        print(
            "Longitud media de fragmento: "
            f"{statistics.mean(longitudes):.0f} palabras"
        )

        # Calentamientos fuera de las mediciones.
        for _ in range(NUM_CALENTAMIENTOS):
            rerank_results(
                CONSULTA,
                resultados,
                modelo,
            )

        tiempos = []

        for _ in range(NUM_MEDICIONES):
            inicio = time.perf_counter()

            resultados_ordenados = rerank_results(
                CONSULTA,
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

        print(f"Media: {media:.2f} ms")
        print(f"Mediana: {mediana:.2f} ms")
        print(f"P95: {p95:.2f} ms")
        print(f"Máximo: {maximo:.2f} ms")
