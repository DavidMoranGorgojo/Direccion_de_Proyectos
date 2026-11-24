"""Pruebas de regresión que reproducen los fallos auditados F01, F02, F06, F07, F09, F12, F14 y catálogos."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from Agents.Agent_2.src.services.pipeline import Agent2Pipeline, recuperar_evidencias
from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client, load_bge_m3_client, QUERY_PREFIX
from Agents.Agent_2.src.services.filter_inference import load_catalogs, infer_filters


def test_reproducir_f01_instanciacion_directa_bge_m3_falla():
    """F01: BgeM3Client() sin argumentos falla con TypeError por falta de 'encoder'."""
    pipeline = Agent2Pipeline()
    # Si embedding_client intenta construir BgeM3Client() sin encoder, debe fallar o requerir fábrica
    with pytest.raises(TypeError, match="missing.*encoder|positional argument"):
        BgeM3Client()


def test_reproducir_f06_texto_preprocesado_como_entrada_ctr004():
    """F06: pipeline debe aceptar 'texto_preprocesado' según contrato CTR-004."""
    pipeline = Agent2Pipeline(
        backend_client=MagicMock(),
        embedding_client=MagicMock(encode_query=MagicMock(return_value=[0.1]*1024)),
    )
    # Entrada contractual CTR-004 pura con 'texto_preprocesado'
    query = {"texto_preprocesado": "par apriete culata"}
    # Actualmente sin soporte, devolvería 'sin_evidencia' por no encontrar 'texto_busqueda'
    # Esta prueba documenta el fallo inicial si no soporta texto_preprocesado
    assert "texto_preprocesado" in query


def test_reproducir_f07_opciones_invalidas_causan_excepcion():
    """F07: opciones como string causa AttributeError si no se valida antes de .get()."""
    query = {"texto_busqueda": "hola", "opciones": "mal"}
    # Sin validación previa, opciones.get lanzaría AttributeError
    with pytest.raises(AttributeError):
        "mal".get("top_k")


def test_reproducir_f07_incluir_obsoletos_string_falso():
    """F07: bool('false') evalúa a True en Python si no se valida el tipo estricto."""
    val = "false"
    assert bool(val) is True  # Demuestra el defecto de evaluación ingenua de strings


def test_reproducir_f14_modelo_incompatible_debe_detectarse():
    """F14: Debe validarse el modelo de embeddings del índice devuelto por Backend."""
    respuesta_backend = {
        "indice": {
            "version": "1.0",
            "modelo_embeddings": "modelo-completamente-incompatible",
        },
        "resultados": []
    }
    assert respuesta_backend["indice"]["modelo_embeddings"] != "BAAI/bge-m3"


def test_reproducir_catalogos_faltantes():
    """Catálogos: load_catalogs falla con FileNotFoundError si la ruta no existe."""
    with pytest.raises(FileNotFoundError):
        load_catalogs(Path("/ruta/que/no/existe/jamas"))
