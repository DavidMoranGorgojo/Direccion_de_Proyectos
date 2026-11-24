"""Datos de calibración A2-08 a partir de la batería de 20 de control y 8 trampa.

La batería oficial (``fixtures/preguntas_control_trampa.json``) indica para
cada pregunta el *documento* esperado, no los fragmentos. Por eso la
calibración se hace a nivel de documento: el ranking del reranker se reduce a
documentos (cada uno con la mejor puntuación de sus fragmentos) y el único
relevante es el documento esperado. Las preguntas trampa no tienen relevantes,
que es lo que activa las métricas de abstención de ``calibration.py``.

El módulo no ejecuta el pipeline: recibe una función que devuelve el ranking
de cada pregunta, así se puede probar sin modelos ni Backend.
"""

from __future__ import annotations

import json
from pathlib import Path

from .calibration import CalibrationError

PREGUNTAS_POR_DEFECTO = (
    Path(__file__).resolve().parents[2] / "fixtures" / "preguntas_control_trampa.json"
)

TIPOS_VALIDOS = ("control", "trampa")


def cargar_preguntas(path=PREGUNTAS_POR_DEFECTO):
    """Lee y valida la batería de preguntas."""

    with Path(path).open(encoding="utf-8") as fichero:
        datos = json.load(fichero)

    preguntas = datos.get("preguntas") if isinstance(datos, dict) else datos
    if not isinstance(preguntas, list) or not preguntas:
        raise CalibrationError("La batería de preguntas está vacía")

    vistos = set()
    for pregunta in preguntas:
        if not isinstance(pregunta, dict):
            raise CalibrationError(f"Cada pregunta debe ser un diccionario: {pregunta!r}")
        pid = pregunta.get("id")
        if not isinstance(pid, str) or not pid or pid in vistos:
            raise CalibrationError(f"Identificador de pregunta no válido: {pid!r}")
        vistos.add(pid)
        if pregunta.get("tipo") not in TIPOS_VALIDOS:
            raise CalibrationError(f"Tipo no válido en {pid}: {pregunta.get('tipo')!r}")
        if not isinstance(pregunta.get("pregunta"), str) or not pregunta["pregunta"].strip():
            raise CalibrationError(f"La pregunta {pid} no tiene texto")
        esperado = pregunta.get("doc_esperado")
        if pregunta["tipo"] == "trampa" and esperado is not None:
            raise CalibrationError(f"La trampa {pid} no puede tener doc_esperado")
        if pregunta["tipo"] == "control" and not esperado:
            raise CalibrationError(f"La pregunta de control {pid} necesita doc_esperado")

    return preguntas


def ranking_por_documento(ranking):
    """Reduce un ranking de fragmentos a documentos.

    Cada documento conserva la mejor puntuación de sus fragmentos y la posición
    del primero que aparece. Devuelve el formato de ``calibration.py``, con el
    identificador del documento en ``chunk_id``.
    """

    mejores = {}
    for entrada in ranking:
        documento = entrada.get("documento") or entrada["chunk_id"].split("@", 1)[0]
        score = entrada["rerank_score"]
        if documento not in mejores or score > mejores[documento]:
            mejores[documento] = score

    return sorted(
        ({"chunk_id": doc, "rerank_score": score} for doc, score in mejores.items()),
        key=lambda item: item["rerank_score"],
        reverse=True,
    )


def construir_consultas(preguntas, obtener_ranking, documentos_disponibles=None):
    """Construye los datos de entrada de ``evaluate_thresholds``.

    Args:
        preguntas: batería validada por ``cargar_preguntas``.
        obtener_ranking: función ``pregunta -> lista de {chunk_id, documento,
            rerank_score}`` (el ranking del reranker sin umbral).
        documentos_disponibles: documentos presentes en el índice. Las
            preguntas de control cuyo documento esperado no está se separan en
            ``excluidas``: ningún umbral puede acertarlas.

    Returns:
        ``{"consultas": [...], "excluidas": [...], "rankings": {...}}``.
    """

    consultas = []
    excluidas = []
    rankings = {}

    for pregunta in preguntas:
        pid = pregunta["id"]
        esperado = pregunta.get("doc_esperado")

        if (
            esperado
            and documentos_disponibles is not None
            and esperado not in documentos_disponibles
        ):
            excluidas.append({"id": pid, "doc_esperado": esperado,
                              "motivo": "documento esperado ausente del índice"})
            continue

        ranking = ranking_por_documento(obtener_ranking(pregunta))
        rankings[pid] = ranking
        consultas.append(
            {
                "query_id": pid,
                "ranking": ranking,
                "relevant_chunk_ids": [esperado] if esperado else [],
            }
        )

    return {"consultas": consultas, "excluidas": excluidas, "rankings": rankings}


__all__ = [
    "PREGUNTAS_POR_DEFECTO",
    "cargar_preguntas",
    "construir_consultas",
    "ranking_por_documento",
]
