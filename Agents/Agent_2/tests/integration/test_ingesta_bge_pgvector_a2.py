"""Integración real: ingesta BGE-M3 → pgvector → Backend → Agente 2.

Comprueba la integración de ingesta, búsqueda y entrega de evidencias:

1. La ingesta trocea los PDF, calcula embeddings ``passage:`` con BGE-M3 y
   carga una versión nueva del índice en PostgreSQL + pgvector.
2. La API real del Backend se sirve con uvicorn (HTTP de verdad, con Bearer).
3. El ``BackendAPIClient`` del Agente 2 consulta la ficha, la búsqueda
   vectorial (con ``query:`` de BGE-M3), la léxica y el detalle con vecinos.
4. El pipeline del Agente 2 devuelve evidencias CTR-004 que el Agente 1 acepta.

Este último paso usa un modo explícito sin reranker. No sustituye la prueba
posterior de ambos modelos y del flujo completo desde Frontend.

Es opcional: se salta si falta cualquiera de estas piezas.

* ``ARSOFT_TEST_DATABASE_URL``: PostgreSQL **de pruebas** con pgvector. La
  prueba crea el esquema si no existe y activa su propia versión del índice
  (``test-a2-…``), así que no debe apuntar a la base de datos real.
* ``ARSOFT_TEST_MANUALES``: carpeta con los PDF de ThermoDrive HTM-240.
* Dependencias de inferencia: ``Backend/ingesta/requirements.txt`` y
  ``Agents/Agent_2/requirements.txt`` (descarga ``BAAI/bge-m3`` la primera vez).

Ejemplo (Linux/macOS)::

    # PostgreSQL de pruebas con pgvector, iniciado como instancia de Apptainer.
    # Debe ser una base aislada de la base de desarrollo.
    export ARSOFT_TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/thermodrive_test
    export ARSOFT_TEST_MANUALES=/ruta/ThermoDrive_HTM240_Alumnos_PDF
    PYTHONPATH=".:shared:Backend/api:Backend/ingesta/src" \\
        python -m pytest Agents/Agent_2/tests/integration -q -rs
"""

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

RAIZ = Path(__file__).resolve().parents[4]
DB = os.getenv("ARSOFT_TEST_DATABASE_URL")
MANUALES = os.getenv("ARSOFT_TEST_MANUALES")
TOKEN = "arsoft-integracion"
MODELO = "BAAI/bge-m3"

pytestmark = [
    pytest.mark.skipif(not DB, reason="define ARSOFT_TEST_DATABASE_URL (PostgreSQL de pruebas con pgvector)"),
    pytest.mark.skipif(
        not MANUALES or not Path(MANUALES).is_dir(),
        reason="define ARSOFT_TEST_MANUALES (carpeta con los PDF de ThermoDrive)",
    ),
]


@pytest.fixture(scope="module")
def indice(tmp_path_factory):
    """Ejecuta la ingesta real con embeddings y la carga en pgvector."""

    for modulo in ("fitz", "transformers", "sentence_transformers", "psycopg"):
        pytest.importorskip(modulo)

    ruta_ingesta = str(RAIZ / "Backend" / "ingesta" / "src")
    if ruta_ingesta not in sys.path:
        sys.path.insert(0, ruta_ingesta)
    from ingesta.__main__ import main as ingesta

    version = f"test-a2-{uuid.uuid4().hex[:8]}"
    salida = tmp_path_factory.mktemp("ingesta")
    codigo = ingesta([
        "--entrada", MANUALES, "--salida", str(salida), "--cargar", "--crear-esquema",
        "--database-url", DB, "--indice-version", version,
    ])
    assert codigo == 0, "La ingesta real terminó con error"

    with (salida / "chunks.jsonl").open(encoding="utf-8") as f:
        chunks = [json.loads(linea) for linea in f if linea.strip()]
    assert chunks, "La ingesta no generó fragmentos"
    assert all(len(c["embedding"]) == 1024 for c in chunks)
    return {"version": version, "chunks": chunks}


@pytest.fixture(scope="module")
def backend(indice):
    """API real del Backend por HTTP, apuntando a la base de pruebas."""

    from Test.test_Backend.test_api_contracts import serve

    from Agents.Agent_2.src.clients.backend import BackendAPIClient

    with patch.dict(os.environ, {"DATABASE_URL": DB, "ARSOFT_SERVICE_TOKEN": TOKEN}):
        from Backend.api.app.main import app

        with serve(app) as url:
            yield BackendAPIClient(url, MODELO, token=TOKEN, timeout=30, connect_timeout=3)


@pytest.fixture(scope="module")
def bge():
    pytest.importorskip("FlagEmbedding")
    from Agents.Agent_2.src.clients.bge_m3 import load_bge_m3_client

    return load_bge_m3_client(MODELO, use_fp16=False)


def _muestra(chunks, n=3):
    """Un fragmento de cada uno de los primeros documentos, para variar."""
    vistos, muestra = set(), []
    for chunk in chunks:
        if chunk["documento"] not in vistos and len(chunk["texto"]) > 80:
            vistos.add(chunk["documento"])
            muestra.append(chunk)
        if len(muestra) == n:
            break
    return muestra


def test_ficha_del_indice_coincide_con_la_ingesta(indice, backend):
    info = backend.get_info()

    assert info["version"] == indice["version"]
    assert info["modelo_embeddings"] == MODELO


def test_busqueda_vectorial_recupera_el_fragmento_por_su_texto(indice, backend, bge):
    for chunk in _muestra(indice["chunks"]):
        vector = bge.encode_query(chunk["texto"])
        respuesta = backend.search_vector(vector, k=5)

        assert respuesta["indice"]["version"] == indice["version"]
        ids = [r["chunk_id"] for r in respuesta["resultados"]]
        assert chunk["chunk_id"] in ids, f"{chunk['chunk_id']} no está en el top 5: {ids}"


def test_busqueda_lexica_y_detalle_con_vecinos(indice, backend):
    chunk = _muestra(indice["chunks"], 1)[0]

    lexica = backend.search_lexical_candidates(chunk["documento"], k=10)
    assert lexica.resultados, "BM25 no devuelve nada para el código del documento"

    detalle = backend.get_chunk(chunk["chunk_id"], vecinos=1)
    assert detalle["chunk"]["chunk_id"] == chunk["chunk_id"]
    assert detalle["indice"]["version"] == indice["version"]


def test_pipeline_a2_entrega_evidencias_que_acepta_el_agente1(indice, backend, bge):
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

    core = pytest.importorskip("Agents.agente1.core")
    chunk = _muestra(indice["chunks"], 1)[0]

    # Sin reranker real (otra dependencia pesada): umbral 0 sobre RRF.
    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=bge, threshold=0.0)
    respuesta = pipeline.procesar_consulta({"texto_preprocesado": chunk["texto"][:300]})

    assert respuesta["estado"] in {"suficiente", "solo_obsoleto", "ambiguo"}, respuesta.get("mensaje_error")
    for evidencia in respuesta["evidencias"]:
        assert evidencia["metadata"]["documento"]
        assert evidencia["metadata"]["version"] == evidencia["metadata"]["version_documento"]

    normalizada = core.normalizar_respuesta_agente2(respuesta)
    assert normalizada["estado"] == respuesta["estado"]
    assert normalizada.get("codigo_error") in (None, "")
