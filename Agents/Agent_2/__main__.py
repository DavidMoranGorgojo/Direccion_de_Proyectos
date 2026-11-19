"""Ejecutar A2 real por CTR-004: python -m Agents.Agent_2 --query consulta.json."""

import argparse
import json
import sys
from pathlib import Path

from .src.services.pipeline import recuperar_evidencias
from .src.services.runtime import check_readiness


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--query", help="JSON CTR-004; '-' para stdin")
    modes.add_argument("--health", action="store_true", help="Verifica Backend y ambos modelos reales")
    modes.add_argument("--health-backend", action="store_true", help="Comprobación parcial sin cargar pesos")
    parser.add_argument("--timeout-s", type=float, help="Presupuesto entre etapas; no cancela inferencia en curso")
    args = parser.parse_args(argv)
    if args.health or args.health_backend:
        result = check_readiness(load_models=args.health)
        ok = result["status"] in {"ok", "partial"}
    else:
        try:
            raw = sys.stdin.read() if args.query == "-" else Path(args.query).read_text(encoding="utf-8-sig")
            query = json.loads(raw)
            result = recuperar_evidencias(query, timeout_s=args.timeout_s)
        except (ValueError, OSError):
            result = {"estado": "error", "evidencias": [],
                      "codigo_error": "entrada_invalida", "mensaje_error": "Consulta JSON o presupuesto inválidos."}
        ok = result["estado"] != "error"
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
