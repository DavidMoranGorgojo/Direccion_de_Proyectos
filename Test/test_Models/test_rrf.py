
import pytest

from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.services.fusion import rrf
from Agents.Agent_2.src.services.reranker import rerank_results


def test_rrf_fusion():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "C"},
        {"chunk_id": "B"},
    ]

    bm25_results = [
        {"chunk_id": "B"},
        {"chunk_id": "A"},
        {"chunk_id": "D"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 4
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"
    assert resultado[2]["chunk_id"] == "C"
    assert resultado[3]["chunk_id"] == "D"
    assert "rrf_score" in resultado[0]


def test_rrf_vectorial_vacio():
    vector_results = []

    bm25_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 2
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"


def test_rrf_lexico_vacio():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    bm25_results = []

    resultado = rrf(vector_results, bm25_results)

    assert len(resultado) == 2
    assert resultado[0]["chunk_id"] == "A"
    assert resultado[1]["chunk_id"] == "B"


def test_rrf_ambos_vacios():
    resultado = rrf([], [])

    assert resultado == []


def test_rrf_chunk_en_ambos_rankings():
    vector_results = [
        {"chunk_id": "A"},
        {"chunk_id": "B"},
    ]

    bm25_results = [
        {"chunk_id": "A"},
        {"chunk_id": "C"},
    ]

    resultado = rrf(vector_results, bm25_results)

    assert resultado[0]["chunk_id"] == "A"

    score_esperado = (1 / 61) + (1 / 61)
    assert resultado[0]["rrf_score"] == score_esperado


def test_rrf_conserva_metadatos():
    vector_results = [
        {
            "chunk_id": "A",
            "texto": "Comprobar el sensor de presión",
            "documento": "manual_taller",
            "pagina": 15,
        }
    ]

    resultado = rrf(vector_results, [])

    assert resultado[0]["chunk_id"] == "A"
    assert resultado[0]["texto"] == "Comprobar el sensor de presión"
    assert resultado[0]["documento"] == "manual_taller"
    assert resultado[0]["pagina"] == 15
    assert "rrf_score" in resultado[0]


def test_rrf_k_personalizable():
    vector_results = [
        {"chunk_id": "A"},
    ]

    resultado = rrf(vector_results, [], k=10)

    assert resultado[0]["rrf_score"] == 1 / 11


def test_rrf_no_modifica_resultados_originales():
    vector_results = [
        {"chunk_id": "A", "score": 0.90},
    ]

    bm25_results = [
        {"chunk_id": "A", "score": 8.5},
    ]

    rrf(vector_results, bm25_results)

    assert "rrf_score" not in vector_results[0]
    assert "rrf_score" not in bm25_results[0]


def test_rrf_rechaza_resultado_sin_chunk_id():
    resultados_invalidos = [
        {"texto": "Fragmento sin identificador"}
    ]

    with pytest.raises(ValueError, match="chunk_id"):
        rrf(resultados_invalidos, [])


def test_rrf_utiliza_k_de_configuracion(monkeypatch):
    """
    Comprueba que RRF utiliza config.RRF_K
    cuando no se indica k explícitamente.
    """

    monkeypatch.setattr(config, "RRF_K", 80)

    resultados = [
        {"chunk_id": "A"},
    ]

    fusionados = rrf(resultados, [])

    assert fusionados[0]["rrf_score"] == 1 / 81


def test_rrf_k_explicito_tiene_prioridad(monkeypatch):
    """
    Comprueba que un valor explícito de k
    tiene prioridad sobre la configuración.
    """

    monkeypatch.setattr(config, "RRF_K", 80)

    resultados = [
        {"chunk_id": "A"},
    ]

    fusionados = rrf(resultados, [], k=10)

    assert fusionados[0]["rrf_score"] == 1 / 11


@pytest.mark.parametrize(
    "k_invalido",
    [0, -1, "abc", True, 1.5],
)
def test_rrf_rechaza_k_invalido(k_invalido):
    """
    Comprueba que RRF rechaza valores de k
    que no sean enteros positivos.
    """

    resultados = [
        {"chunk_id": "A"},
    ]

    with pytest.raises(ValueError, match="k"):
        rrf(resultados, [], k=k_invalido)


# ----------------------------------------------------------
# Pruebas de integración con el adaptador vectorial y BM25
# ----------------------------------------------------------


def test_rrf_c46_conserva_puntuaciones_y_metadatos():
    """
    Reproduce el problema comunicado por Álvaro:
    un chunk presente en ambos rankings no debe perder
    su score vectorial ni sus metadatos.
    """

    vector_results = [
        {
            "chunk_id": "c46",
            "texto": "Procedimiento de mantenimiento del sensor",
            "score_vectorial": 0.92,
            "documento": "manual_sensor",
            "pagina": 12,
            "versiones": ["v2"],
        }
    ]

    bm25_results = [
        {
            "chunk_id": "c46",
            "texto": "Procedimiento de mantenimiento del sensor",
            "score": 8.5,
            "seccion": "Mantenimiento",
        }
    ]

    resultado = rrf(vector_results, bm25_results)
    chunk = resultado[0]

    assert len(resultado) == 1
    assert chunk["chunk_id"] == "c46"
    assert chunk["texto"] == "Procedimiento de mantenimiento del sensor"
    assert chunk["score_vectorial"] == 0.92
    assert chunk["score_bm25"] == 8.5
    assert chunk["rrf_score"] == pytest.approx(2 / 61)
    assert chunk["documento"] == "manual_sensor"
    assert chunk["pagina"] == 12
    assert chunk["versiones"] == ["v2"]
    assert chunk["seccion"] == "Mantenimiento"
    assert "score" not in chunk


def test_rrf_conserva_score_bm25_explicito():
    """
    Acepta resultados BM25 que ya contienen
    el nombre normalizado score_bm25.
    """

    resultado = rrf(
        [],
        [
            {
                "chunk_id": "c46",
                "texto": "Mantenimiento del sensor",
                "score_bm25": 7.3,
            }
        ],
    )

    assert resultado[0]["score_bm25"] == 7.3
    assert resultado[0]["rrf_score"] == pytest.approx(1 / 61)


def test_rrf_conserva_texto_de_bm25_si_falta_en_vectorial():
    """
    Si el candidato vectorial no incluye texto,
    RRF debe recuperarlo del resultado BM25.
    """

    vector_results = [
        {
            "chunk_id": "c46",
            "score_vectorial": 0.91,
        }
    ]

    bm25_results = [
        {
            "chunk_id": "c46",
            "texto": "Instrucciones de calibración",
            "score": 6.2,
        }
    ]

    resultado = rrf(vector_results, bm25_results)

    assert resultado[0]["texto"] == "Instrucciones de calibración"
    assert resultado[0]["score_vectorial"] == 0.91
    assert resultado[0]["score_bm25"] == 6.2


def test_rrf_no_modifica_entradas_al_fusionar_metadatos():
    """
    La fusión no debe añadir puntuaciones ni metadatos
    a los diccionarios de entrada.
    """

    vector_results = [
        {
            "chunk_id": "c46",
            "texto": "Texto original",
            "score": 0.88,
        }
    ]

    bm25_results = [
        {
            "chunk_id": "c46",
            "texto": "Texto original",
            "score": 9.1,
            "pagina": 4,
        }
    ]

    resultado = rrf(vector_results, bm25_results)

    assert resultado[0]["score_vectorial"] == 0.88
    assert resultado[0]["score_bm25"] == 9.1
    assert resultado[0]["pagina"] == 4

    assert vector_results == [
        {
            "chunk_id": "c46",
            "texto": "Texto original",
            "score": 0.88,
        }
    ]

    assert bm25_results == [
        {
            "chunk_id": "c46",
            "texto": "Texto original",
            "score": 9.1,
            "pagina": 4,
        }
    ]


def test_rrf_reranker_conserva_todas_las_puntuaciones():
    """
    Comprueba que la salida de RRF puede pasar
    al reranker sin perder puntuaciones anteriores.
    """

    class ModeloSimulado:
        def predict(self, pairs):
            assert pairs == [
                ["¿Cómo mantener el sensor?", "Mantenimiento del sensor"]
            ]
            return [0.95]

    vector_results = [
        {
            "chunk_id": "c46",
            "texto": "Mantenimiento del sensor",
            "score_vectorial": 0.91,
            "documento": "manual_sensor",
        }
    ]

    bm25_results = [
        {
            "chunk_id": "c46",
            "texto": "Mantenimiento del sensor",
            "score": 8.5,
        }
    ]

    fusionados = rrf(vector_results, bm25_results)

    resultado = rerank_results(
        "¿Cómo mantener el sensor?",
        fusionados,
        ModeloSimulado(),
    )

    assert len(resultado) == 1
    assert resultado[0]["score_vectorial"] == 0.91
    assert resultado[0]["score_bm25"] == 8.5
    assert resultado[0]["rrf_score"] == pytest.approx(2 / 61)
    assert resultado[0]["rerank_score"] == 0.95
    assert resultado[0]["documento"] == "manual_sensor"
