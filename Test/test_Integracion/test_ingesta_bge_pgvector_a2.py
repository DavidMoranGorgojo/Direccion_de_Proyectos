"""Integración real: ingesta BGE-M3 → pgvector → Backend → Agente 2.

Responde a la revisión de la PR #32 («la ingesta real con BGE-M3 y pgvector no
se ejecutó»). Recorre la cadena completa sin dobles:

1. La ingesta trocea los PDF, calcula embeddings ``passage:`` con BGE-M3 y
   carga una versión nueva del índice en PostgreSQL + pgvector.
2. La API real del Backend se sirve con uvicorn (HTTP de verdad, con Bearer).
3. El ``BackendAPIClient`` del Agente 2 consulta la ficha, la búsqueda
   vectorial (con ``query:`` de BGE-M3), la léxica y el detalle con vecinos.
4. El pipeline del Agente 2 devuelve evidencias CTR-004 que el Agente 1 acepta.

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
        python -m pytest Test/test_Integracion -q -rs
"""

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

RAIZ = Path(__file__).resolve().parents[2]
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


# --- Validación del cliente CTR-002 contra el Backend real ---------------------


def _aplica(chunk, version):
    """Regla de vigencia de CTR-002 (la misma que aplica el Backend)."""
    if version in (chunk["vigente_para"] or []):
        return True
    return not chunk["obsoleto"] and version in (chunk["versiones"] or [])


def _mas_frecuente(chunks, campo):
    from collections import Counter

    valores = Counter(c[campo] for c in chunks if c.get(campo))
    return valores.most_common(1)[0][0]


@pytest.mark.parametrize("token", ["", "token-incorrecto"])
def test_bearer_de_servicio_obligatorio(indice, backend, token):
    from Agents.Agent_2.src.clients.backend import BackendAPIClient, BackendRequestError

    sin_permiso = BackendAPIClient(backend.base_url, MODELO, token=token, timeout=30, connect_timeout=3)
    with pytest.raises(BackendRequestError) as error:
        sin_permiso.search_vector([0.0] * 1024, k=1)
    assert "401" in str(error.value)
    with pytest.raises(BackendRequestError):
        sin_permiso.search_lexical_candidates("HTM-0142", k=1)
    # El token nunca aparece en los errores ni en la representación del cliente.
    assert TOKEN not in str(error.value) and TOKEN not in repr(backend)


def test_timeout_de_conexion_falla_rapido_sin_recortar_lectura(indice, backend):
    import socket
    import time

    from Agents.Agent_2.src.clients.backend import BackendAPIClient, BackendRequestError

    with socket.socket() as libre:
        libre.bind(("127.0.0.1", 0))
        puerto = libre.getsockname()[1]
    caido = BackendAPIClient(f"http://127.0.0.1:{puerto}", MODELO, token=TOKEN, timeout=30, connect_timeout=1)
    inicio = time.monotonic()
    with pytest.raises(BackendRequestError) as error:
        caido.search_vector([0.0] * 1024, k=1)
    assert error.value.codigo_error == "servicio_no_disponible"
    assert time.monotonic() - inicio < 10

    impaciente = BackendAPIClient(backend.base_url, MODELO, token=TOKEN, timeout=0.0005, connect_timeout=3)
    with pytest.raises(BackendRequestError) as error:
        impaciente.search_vector([0.0] * 1024, k=50)
    assert error.value.codigo_error == "tiempo_agotado"


def test_prefijo_passage_de_la_ingesta_coincide_con_el_agente2(indice, bge):
    """Mismo modelo y mismo ``passage:``: el vector del Agente 2 reproduce el del índice."""
    import numpy as np

    chunk = _muestra(indice["chunks"], 1)[0]
    propio = np.asarray(bge.encode_passages([chunk["texto"]])[0], dtype=float)
    indexado = np.asarray(chunk["embedding"], dtype=float)
    coseno = propio @ indexado / (np.linalg.norm(propio) * np.linalg.norm(indexado))
    assert coseno > 0.99, f"coseno {coseno:.4f}: el prefijo o el modelo no coinciden con la ingesta"


def test_prefijo_query_mejora_o_iguala_la_recuperacion(indice, backend, bge):
    from Agents.Agent_2.src.clients.bge_m3 import QUERY_PREFIX

    chunk = _muestra(indice["chunks"], 1)[0]
    pregunta = chunk["texto"][:200]
    vector = bge.encode_query(pregunta)
    # encode_query no duplica el prefijo si ya viene puesto.
    import numpy as np

    assert np.allclose(vector, bge.encode_query(QUERY_PREFIX + pregunta), atol=1e-5)
    ids = [r["chunk_id"] for r in backend.search_vector(vector, k=5)["resultados"]]
    assert chunk["chunk_id"] in ids


@pytest.mark.parametrize("campo", ["version", "componente", "tipo_documento"])
def test_filtros_se_aplican_en_vectorial_y_lexica(indice, backend, bge, campo):
    chunks = indice["chunks"]
    valor = "V1.0" if campo == "version" else _mas_frecuente(chunks, campo)
    filtros = {campo: valor}
    vector = bge.encode_query("procedimiento de verificación del circuito")

    vectorial = backend.search_vector(vector, filtros=filtros, k=20)["resultados"]
    lexica = backend.search_lexical_candidates("circuito", filtros=filtros, k=20).resultados
    assert vectorial, f"sin resultados vectoriales con {filtros}"

    por_id = {c["chunk_id"]: c for c in chunks}
    ids = [r["chunk_id"] for r in vectorial] + [r.chunk_id for r in lexica]
    for chunk_id in ids:
        chunk = por_id[chunk_id]
        if campo == "version":
            assert _aplica(chunk, valor), f"{chunk_id} no aplica a {valor}"
        else:
            assert chunk[campo] == valor, f"{chunk_id}: {campo}={chunk[campo]!r} con filtro {valor!r}"


def test_version_sustituida_solo_aplica_donde_sigue_vigente(indice, backend, bge):
    sustituidos = [c for c in indice["chunks"] if c["obsoleto"]]
    if not sustituidos:
        # Hoy la ingesta excluye los PDF sustituidos («no se indexa»), así que
        # vigente_para (PRC-003 v1.0 → V1.0) no llega a pgvector. Punto abierto
        # con Backend; la prueba se activa sola si se empiezan a indexar.
        pytest.skip("la ingesta no indexa documentos sustituidos")
    chunk = sustituidos[0]
    vector = bge.encode_query(chunk["texto"][:300])
    for version in ("V1.0", "V1.1", "V2.0"):
        ids = [r["chunk_id"] for r in backend.search_vector(vector, filtros={"version": version}, k=30)["resultados"]]
        assert (chunk["chunk_id"] in ids) == (version in chunk["vigente_para"]), (version, chunk["vigente_para"])


def test_filtro_inexistente_es_entrada_invalida(indice, backend):
    from Agents.Agent_2.src.clients.backend import BackendRequestError

    with pytest.raises(BackendRequestError) as error:
        backend.search_vector([0.0] * 1024, filtros={"version": "V9.9"}, k=1)
    assert error.value.codigo_error == "entrada_invalida"


def test_relajacion_solo_quita_tipo_documento(indice, backend, bge):
    """CTR-002 §4: sin resultados por el tipo documental se reintenta sin él."""
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

    chunks = indice["chunks"]
    pares = {(c["componente"], c["tipo_documento"]) for c in chunks if c["componente"]}
    componentes = sorted({c for c, _ in pares})
    tipos = sorted({t for _, t in pares})
    vacio = next(((c, t) for c in componentes for t in tipos if (c, t) not in pares), None)
    if vacio is None:
        pytest.skip("todas las combinaciones componente/tipo tienen fragmentos")
    componente, tipo = vacio

    pipeline = Agent2Pipeline(backend_client=backend, embedding_client=bge, threshold=0.0)
    respuesta = pipeline.procesar_consulta({
        "texto_preprocesado": "¿cómo se revisa este componente?",
        "filtros": {"componente": componente, "tipo_documento": tipo},
    })

    assert respuesta["estado"] != "error", respuesta.get("mensaje_error")
    assert respuesta["metricas"].get("tipo_documento_ampliado") is True
    por_id = {c["chunk_id"]: c for c in chunks}
    # Versión y componente nunca se relajan (los vecinos también los cumplen).
    for evidencia in respuesta["evidencias"]:
        assert por_id[evidencia["chunk_id"]]["componente"] == componente
