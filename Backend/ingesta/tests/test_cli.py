"""Opciones de la línea de órdenes de la ingesta."""
from ingesta.__main__ import crear_parser

BASE = ["--entrada", "."]


def test_sustituidos_se_excluyen_por_defecto():
    assert crear_parser().parse_args(BASE).excluir_sustituidos is True


def test_excluir_sustituidos():
    assert crear_parser().parse_args(BASE + ["--excluir-sustituidos"]).excluir_sustituidos is True


def test_incluir_sustituidos_es_opcion_explicita():
    args = crear_parser().parse_args(BASE + ["--incluir-sustituidos"])
    assert args.excluir_sustituidos is False
