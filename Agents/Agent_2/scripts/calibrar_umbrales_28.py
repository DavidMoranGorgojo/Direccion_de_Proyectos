"""Calibración A2-08 del umbral del reranker con las 20 de control y las 8 trampa.

Ejecuta el pipeline del Agente 2 sobre cada pregunta con umbral 0.0, guarda el
ranking completo del reranker y evalúa la rejilla de umbrales con
``calibration.evaluate_thresholds`` (Recall@k, MRR y abstención) a nivel de
documento.

Uso (desde la raíz del repositorio):

    # Máquina con modelos y Backend real (resultado válido para fijar umbral)
    python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend real --reranker real

    # Sin modelos: Backend simulado y reranker por solapamiento de palabras
    # (solo valida el flujo; los números no sirven para fijar el umbral)
    python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend simulado --reranker solapamiento
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_ROOT = REPO_ROOT / "Agents" / "Agent_2"
DATASET = AGENT_ROOT / "fixtures" / "bbdd_sintetica_chunks.json"
SALIDA_POR_DEFECTO = AGENT_ROOT / "docs" / "resultados"

sys.path.insert(0, str(REPO_ROOT))


class RerankerSolapamiento:
    """Sustituto sin modelo: fracción de palabras de la consulta en el pasaje."""

    nombre = "solapamiento"

    @staticmethod
    def _palabras(texto):
        return set(re.findall(r"\w+", texto.lower()))

    def predict(self, pairs):
        return [
            len(self._palabras(q) & self._palabras(p)) / max(1, len(self._palabras(q)))
            for q, p in pairs
        ]


class _EmbedderSimulado:
    """Embedding determinista del Backend simulado (mismo espacio que su índice)."""

    def __init__(self, simulador):
        self._simulador = simulador

    def encode_query(self, texto):
        return self.encode(texto)

    def encode(self, texto, use_prefix=True):
        prefijado = texto if texto.startswith("query: ") else f"query: {texto}"
        return self._simulador.embed_query(prefijado)


def _documentos_dataset():
    chunks = json.loads(DATASET.read_text(encoding="utf-8-sig"))["chunks"]
    return chunks, {chunk["documento"] for chunk in chunks}


def crear_pipeline(backend, reranker):
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

    if reranker == "real":
        from Agents.Agent_2.src.clients.reranker_loader import get_reranker

        modelo_reranker = get_reranker()
    else:
        modelo_reranker = RerankerSolapamiento()

    kwargs = {"reranker_model": modelo_reranker, "threshold": 0.0,
              "require_reranker": True, "trace_retrieval": True}

    if backend == "simulado":
        from Agents.Agent_2.src.clients.backend import BackendAPIClient
        from Agents.Agent_2.src.testing.backend_simulator import (
            BackendSimulator,
            SimulatedSession,
        )

        chunks, _ = _documentos_dataset()
        simulador = BackendSimulator(chunks, catalogo_dir=DATASET.parent / "catalogos")
        kwargs["backend_client"] = BackendAPIClient(
            "http://backend.simulado",
            simulador.modelo_embeddings,
            session=SimulatedSession(simulador),
            timeout=5,
        )
        kwargs["embedding_client"] = _EmbedderSimulado(simulador)

    return Agent2Pipeline(**kwargs)


def obtener_ranking_con(pipeline, trazas):
    def obtener_ranking(pregunta):
        salida = pipeline.procesar_consulta({"texto_preprocesado": pregunta["pregunta"]})
        metricas = salida.get("metricas", {})
        ranking = (metricas.get("rankings") or {}).get("reranker", [])
        trazas[pregunta["id"]] = {
            "estado_a2": salida.get("estado"),
            "codigo_error": salida.get("codigo_error"),
            "documentos_entregados": list(dict.fromkeys(
                (e.get("metadata") or {}).get("documento") for e in salida.get("evidencias", [])
            )),
        }
        return ranking

    return obtener_ranking


def recomendar_umbral(resultados):
    """Umbral con mejor equilibrio entre abstenerse en trampas y no en controles.

    Puntuación = media de la tasa de abstención correcta (trampas) y de
    1 - tasa de abstención falsa (control). Desempata Recall@3 y, después, el
    umbral más bajo. Es una propuesta para A2-05; el umbral final lo fija el
    equipo con el reranker real.
    """

    def clave(item):
        abst = item["abstencion"]
        ok = abst["tasa_abstencion_correcta"]
        falsa = abst["tasa_abstencion_falsa"]
        partes = [v for v in (ok, None if falsa is None else 1 - falsa) if v is not None]
        equilibrio = sum(partes) / len(partes) if partes else 0.0
        recall3 = item["ranking"]["recall_at_k"].get("3") or 0.0
        return (equilibrio, recall3, -item["threshold"])

    mejor = max(resultados, key=clave)
    return {"threshold": mejor["threshold"], "equilibrio": clave(mejor)[0]}


def tabla_markdown(resultados):
    filas = [
        "| Umbral | Recall@1 | Recall@3 | Recall@5 | MRR | Abst. correcta (trampa) | Abst. falsa (control) | Docs/consulta |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def f(v):
        return "-" if v is None else f"{v:.3f}"

    for item in resultados:
        r = item["ranking"]
        a = item["abstencion"]
        filas.append(
            f"| {item['threshold']:.2f} | {f(r['recall_at_k'].get('1'))} | {f(r['recall_at_k'].get('3'))} "
            f"| {f(r['recall_at_k'].get('5'))} | {f(r['mrr'])} "
            f"| {a['abstenciones_correctas']}/{a['consultas_sin_relevantes']} "
            f"| {a['abstenciones_falsas']}/{a['consultas_con_relevantes']} "
            f"| {item['average_retained_per_query']:.2f} |"
        )
    return "\n".join(filas)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=("simulado", "real"), default="simulado")
    parser.add_argument("--reranker", choices=("real", "solapamiento"), default="real")
    parser.add_argument("--preguntas", type=Path, default=None, help="Batería JSON (por defecto, la oficial de 28)")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO, help="Carpeta de resultados")
    args = parser.parse_args(argv)

    if args.backend == "simulado":
        os.environ.setdefault("ARSOFT_ENV", "test")

    from Agents.Agent_2.src.evaluation.calibration import (
        dump_calibration_result,
        evaluate_thresholds,
        format_calibration_table,
    )
    from Agents.Agent_2.src.evaluation.dataset_calibracion import (
        PREGUNTAS_POR_DEFECTO,
        cargar_preguntas,
        construir_consultas,
    )

    preguntas = cargar_preguntas(args.preguntas or PREGUNTAS_POR_DEFECTO)
    _, documentos = _documentos_dataset()
    pipeline = crear_pipeline(args.backend, args.reranker)

    trazas = {}
    datos = construir_consultas(preguntas, obtener_ranking_con(pipeline, trazas), documentos)
    errores = {pid: t for pid, t in trazas.items() if t["estado_a2"] == "error"}
    if errores:
        print(f"AVISO: {len(errores)} preguntas terminaron en error: {errores}", file=sys.stderr)

    resultado = evaluate_thresholds(datos["consultas"])
    recomendacion = recomendar_umbral(resultado["results"])

    informe = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": args.backend,
        "reranker": args.reranker,
        "valido_para_fijar_umbral": args.reranker == "real",
        "granularidad": "documento",
        "preguntas_evaluadas": len(datos["consultas"]),
        "excluidas": datos["excluidas"],
        "umbral_recomendado": recomendacion,
        "trazas": trazas,
        "rankings": datos["rankings"],
        **resultado,
    }

    nombre = f"calibracion_28_{args.backend}_{args.reranker}"
    dump_calibration_result(informe, args.salida / f"{nombre}.json")
    (args.salida / f"{nombre}.md").write_text(tabla_markdown(resultado["results"]) + "\n", encoding="utf-8")

    print(format_calibration_table(resultado))
    print(f"\nExcluidas (documento ausente del índice): {[e['id'] for e in datos['excluidas']]}")
    print(f"Umbral recomendado: {recomendacion['threshold']:.2f} (equilibrio {recomendacion['equilibrio']:.3f})")
    if args.reranker != "real":
        print("AVISO: reranker sustituto; los números validan el flujo, no fijan el umbral.")
    print(f"Resultados en {args.salida / nombre}.json y .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
