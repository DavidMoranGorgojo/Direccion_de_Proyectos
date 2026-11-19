"""Script de calibración de umbrales del reranker (A2-08).

Trabaja únicamente con puntuaciones ya calculadas. No carga el modelo
real ni llama a servicios externos.
"""

from __future__ import annotations

import argparse
import sys

from Agents.Agent_2.src.evaluation.calibration import (
    CalibrationError,
    dump_calibration_result,
    evaluate_thresholds,
    format_calibration_table,
    load_calibration_data,
    normalize_thresholds,
)


def parse_thresholds(raw_value):
    if raw_value is None:
        return None

    values = []
    for part in raw_value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError as error:
            raise CalibrationError(f"Umbral inválido: {part!r}") from error

    return normalize_thresholds(values)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Evalúa distintos umbrales del reranker."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Archivo JSON con consultas y puntuaciones.",
    )
    parser.add_argument(
        "--output",
        help="Archivo JSON donde guardar los resultados.",
    )
    parser.add_argument(
        "--thresholds",
        help="Lista de umbrales separados por comas.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        queries = load_calibration_data(args.input)
        result = evaluate_thresholds(queries, parse_thresholds(args.thresholds))
    except CalibrationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(format_calibration_table(result))

    if args.output:
        try:
            dump_calibration_result(result, args.output)
        except OSError as error:
            print(f"Error al guardar resultados: {error}", file=sys.stderr)
            return 1
        print(f"Resultados guardados en: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
