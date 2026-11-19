"""Evalúa consultas etiquetadas de A2 sin entregar el ground truth al recuperador.

Entrada: {procedencia, tipo: real|sintetico, consultas: [{id, query,
relevant_chunk_ids}]}. No certifica calidad real sin corpus/modelos reales.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Agents.Agent_2.src.services.pipeline import recuperar_evidencias
from Agents.Agent_2.src.services.filters import filter_chunks
from Agents.Agent_2.src.evaluation.metrics import recall_at_k, reciprocal_rank


def evaluate(data, retrieve=recuperar_evidencias, k=10):
    if not isinstance(data, dict) or not data.get("procedencia") or data.get("tipo") not in {"real", "sintetico"}:
        raise ValueError("Se exige procedencia y tipo de corpus explícitos.")
    cases = data.get("consultas")
    if not isinstance(cases, list) or not cases or type(k) is not int or k < 1:
        raise ValueError("Se requieren consultas y k positivo.")
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("IDs de evaluación duplicados.")
    rows = []
    for case in cases:
        relevant = case["relevant_chunk_ids"]
        if not isinstance(relevant, list) or any(not isinstance(cid, str) or not cid for cid in relevant):
            raise ValueError("Etiquetas de relevancia inválidas.")
        response = retrieve(case["query"], trace_retrieval=True)
        evidences = response.get("evidencias", [])
        ranking = list(dict.fromkeys(e["chunk_id"] for e in evidences))
        metrics = response.get("metricas", {})
        sources = metrics.get("rankings", {})
        recalled = {name: recall_at_k(sources.get(name, []), relevant, k) if relevant else None
                    for name in ("vectorial", "lexica", "fusion")}
        flat = [{**e["metadata"], "chunk_id": e["chunk_id"], "texto": e["texto"]} for e in evidences]
        hard = {key: val for key, val in case["query"].get("filtros", {}).items()
                if key in {"version", "componente"}}
        error = response.get("estado") == "error"
        rows.append(dict(id=case["id"], estado=response.get("estado"), codigo_error=response.get("codigo_error"),
                         recall=recall_at_k(ranking, relevant, k) if relevant else None,
                         reciprocal_rank=reciprocal_rank(ranking, relevant) if relevant else None,
                         recall_recuperadores=recalled,
                         fusion_no_inferior=(recalled["fusion"] >= max(recalled["vectorial"], recalled["lexica"])) if relevant else None,
                         hard_filters_ok=len(filter_chunks(flat, hard)) == len(flat),
                         abstencion_correcta=(not error and not ranking) if not relevant else None,
                         metricas=metrics))
    labeled = [row for row in rows if row["recall"] is not None]
    negatives = [row for row in rows if row["abstencion_correcta"] is not None]
    return dict(procedencia=data["procedencia"], tipo=data["tipo"], k=k, casos=len(rows),
                errores=sum(row["estado"] == "error" for row in rows),
                recall_medio=sum(row["recall"] for row in labeled) / len(labeled) if labeled else None,
                mrr=sum(row["reciprocal_rank"] for row in labeled) / len(labeled) if labeled else None,
                abstencion=sum(row["abstencion_correcta"] for row in negatives) / len(negatives) if negatives else None,
                hard_filters_ok=all(row["hard_filters_ok"] for row in rows), detalle=rows,
                certifica_despliegue=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="Archivo nuevo fuera de documentación versionada")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args(argv)
    data = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    report = evaluate(data, k=args.k)
    with open(args.output, "x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"{report['casos']} consultas; {report['errores']} errores; corpus {report['tipo']}")
    return 1 if report["errores"] or not report["hard_filters_ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
