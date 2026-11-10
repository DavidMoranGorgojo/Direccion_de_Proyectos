"""Pruebas de la ingesta sobre el corpus real (tabla 7 del diseño de ingesta).

Necesitan los PDF de ARSOFT, que no se versionan: INGESTA_CORPUS=/ruta/a/ThermoDrive_HTM240_Alumnos_PDF
"""

import os
from pathlib import Path

import pytest

from ingesta import config
from ingesta.__main__ import _chunks
from ingesta.inventario import inventariar, leer_documento
from ingesta.troceado import Troceador
from ingesta.validacion import validar

CORPUS = os.getenv("INGESTA_CORPUS")
pytestmark = pytest.mark.skipif(not CORPUS or not Path(CORPUS).is_dir(), reason="INGESTA_CORPUS no definido")


@pytest.fixture(scope="module")
def contar_tokens():
    from ingesta.embeddings import Embebedor
    return Embebedor().contar_tokens


def _ingestar(contar_tokens):
    pdfs, excluidos = inventariar(Path(CORPUS))
    troceador = Troceador(contar_tokens)
    documentos, chunks = [], []
    for ruta in pdfs:
        doc = leer_documento(ruta)
        documentos.append(doc)
        chunks.extend(_chunks(doc, troceador.trocear(doc)))
    return documentos, chunks, excluidos


@pytest.fixture(scope="module")
def resultado(contar_tokens):
    return _ingestar(contar_tokens)


def test_compilado_excluido(resultado):
    documentos, chunks, excluidos = resultado
    assert [e["archivo"] for e in excluidos] == ["HTM240_Documentacion_Completa_Alumnos.pdf"]
    assert len(documentos) == 32


def test_sustituidos_marcados(resultado):
    documentos, _, _ = resultado
    obsoletos = {d.doc_id: d.sustituido_por for d in documentos if d.obsoleto}
    assert obsoletos == {"HTM240-MNT-001@1.0": "HTM240-MNT-001@1.1", "HTM240-PRC-003@1.0": "HTM240-PRC-003@2.0"}
    prc_v1 = next(d for d in documentos if d.doc_id == "HTM240-PRC-003@1.0")
    assert prc_v1.vigente_para == ["V1.0"]


def test_metadatos_completos_y_tamano_maximo(resultado, contar_tokens):
    _, chunks, _ = resultado
    validos, rechazados, errores = validar(chunks, contar_tokens)
    assert rechazados == [] and errores == []
    assert max(contar_tokens(c["texto"]) for c in chunks) <= config.MAX_TOKENS


def test_procedimientos_no_separan_seguridad_de_los_pasos(resultado):
    _, chunks, _ = resultado
    pasos = [c for c in chunks if c["tipo_documento"] == "procedimiento" and c["seccion"] == "Pasos"]
    assert pasos
    for c in pasos:
        assert "\nRiesgos\n" in c["texto"] and "\nCondiciones previas\n" in c["texto"], c["chunk_id"]


def test_codigo_htm_0142(resultado):
    _, chunks, _ = resultado
    chunk = next(c for c in chunks if c["seccion"].startswith("HTM-0142 — "))
    assert "HTM-0142" in chunk["ids_referenciados"]
    assert chunk["afectado_por"] == ["BOL-003"]


def test_tablas_fila_a_fila(resultado):
    _, chunks, _ = resultado
    plan = next(c for c in chunks if c["doc_id"] == "HTM240-MNT-001@1.1" and c["seccion"].startswith("1."))
    assert ("Intervalo (ficticio): Cada 60.000 km o 48 meses | Elemento: Refrigerante (los tres circuitos)"
            in plan["texto"])


def test_reejecucion_estable(resultado, contar_tokens):
    _, chunks, _ = resultado
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids == [c["chunk_id"] for c in _ingestar(contar_tokens)[1]]
