import pytest

from Agents.Agent_2.src.evaluation.metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_precision_at_k_cuenta_relevantes_en_top_k():
    ranking = ["a", "b", "c", "d"]
    relevantes = ["b", "d"]

    assert precision_at_k(ranking, relevantes, 3) == pytest.approx(1 / 3)
    assert precision_at_k(ranking, relevantes, 4) == pytest.approx(0.5)


def test_precision_at_k_usa_k_como_denominador():
    ranking = ["a", "b"]
    relevantes = ["a"]

    assert precision_at_k(ranking, relevantes, 4) == pytest.approx(0.25)


def test_precision_at_k_sin_relevantes_recuperados():
    assert precision_at_k(["a", "b"], ["c"], 2) == pytest.approx(0.0)


def test_recall_at_k_cuenta_relevantes_recuperados():
    ranking = ["a", "b", "c", "d"]
    relevantes = ["b", "d", "e"]

    assert recall_at_k(ranking, relevantes, 2) == pytest.approx(1 / 3)
    assert recall_at_k(ranking, relevantes, 4) == pytest.approx(2 / 3)


def test_recall_at_k_recupera_todos_los_relevantes():
    ranking = ["a", "b", "c"]
    relevantes = ["a", "c"]

    assert recall_at_k(ranking, relevantes, 3) == pytest.approx(1.0)


def test_recall_at_k_sin_relevantes_recuperados():
    assert recall_at_k(["a", "b"], ["c"], 2) == pytest.approx(0.0)


def test_reciprocal_rank_usa_la_posicion_del_primer_relevante():
    assert reciprocal_rank(["a", "b", "c"], ["b"]) == pytest.approx(0.5)
    assert reciprocal_rank(["a", "b", "c"], ["c"]) == pytest.approx(1 / 3)


def test_reciprocal_rank_primera_posicion():
    assert reciprocal_rank(["a", "b"], ["a"]) == pytest.approx(1.0)


def test_reciprocal_rank_sin_relevantes_en_el_ranking():
    assert reciprocal_rank(["a", "b"], ["c"]) == pytest.approx(0.0)


def test_mrr_promedia_varias_consultas():
    rankings = [["a", "b"], ["x", "y"], ["m", "n"]]
    relevantes = [["b"], ["x"], ["z"]]

    assert mean_reciprocal_rank(rankings, relevantes) == pytest.approx(
        (0.5 + 1.0 + 0.0) / 3
    )


def test_mrr_con_una_sola_consulta():
    assert mean_reciprocal_rank([["a", "b"]], [["b"]]) == pytest.approx(0.5)


def test_ranking_vacio_produce_cero_si_hay_relevantes():
    assert precision_at_k([], ["a"], 3) == pytest.approx(0.0)
    assert recall_at_k([], ["a"], 3) == pytest.approx(0.0)
    assert reciprocal_rank([], ["a"]) == pytest.approx(0.0)
    assert mean_reciprocal_rank([[]], [["a"]]) == pytest.approx(0.0)


def test_consulta_sin_documentos_relevantes_es_error():
    with pytest.raises(ValueError, match="sin documentos relevantes"):
        precision_at_k(["a"], [], 1)

    with pytest.raises(ValueError, match="sin documentos relevantes"):
        recall_at_k(["a"], [], 1)

    with pytest.raises(ValueError, match="sin documentos relevantes"):
        reciprocal_rank(["a"], [])

    with pytest.raises(ValueError, match="sin documentos relevantes"):
        mean_reciprocal_rank([["a"]], [[]])


@pytest.mark.parametrize("k", [0, -1, 1.5, "2", True, None])
def test_k_invalido_es_error(k):
    with pytest.raises(ValueError, match="entero mayor que cero"):
        precision_at_k(["a"], ["a"], k)

    with pytest.raises(ValueError, match="entero mayor que cero"):
        recall_at_k(["a"], ["a"], k)


@pytest.mark.parametrize(
    "ranking",
    [
        "abc",
        {"a", "b"},
        [""],
        ["a", 1],
        ["a", "a"],
        None,
    ],
)
def test_ranking_invalido_es_error(ranking):
    with pytest.raises(ValueError):
        precision_at_k(ranking, ["a"], 1)


@pytest.mark.parametrize(
    "relevantes",
    [
        ["a", "a"],
        [""],
        ["a", 1],
        "abc",
        {"a": True},
        None,
    ],
)
def test_relevantes_invalidos_es_error(relevantes):
    with pytest.raises(ValueError):
        recall_at_k(["a"], relevantes, 1)


def test_mrr_sin_consultas_es_error():
    with pytest.raises(ValueError, match="al menos una consulta"):
        mean_reciprocal_rank([], [])


def test_mrr_con_listas_de_distinta_longitud_es_error():
    with pytest.raises(ValueError, match="un conjunto"):
        mean_reciprocal_rank([["a"]], [])


def test_mrr_con_rankings_invalidos_es_error():
    with pytest.raises(ValueError, match="lista o tupla de rankings"):
        mean_reciprocal_rank("abc", [])


def test_mrr_con_relevantes_invalidos_es_error():
    with pytest.raises(ValueError, match="lista o tupla de colecciones"):
        mean_reciprocal_rank([["a"]], "abc")


def test_metricas_no_modifican_las_entradas():
    ranking = ["b", "a"]
    relevantes = ["a"]

    precision_at_k(ranking, relevantes, 2)
    recall_at_k(ranking, relevantes, 2)
    reciprocal_rank(ranking, relevantes)

    assert ranking == ["b", "a"]
    assert relevantes == ["a"]


def test_acepta_tuplas_como_entrada():
    assert precision_at_k(("a", "b"), ("a",), 2) == pytest.approx(0.5)
    assert recall_at_k(("a", "b"), ("a",), 2) == pytest.approx(1.0)
