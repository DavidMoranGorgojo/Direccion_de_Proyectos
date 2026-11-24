"""Test de contrato entre el Agente 2 y el Agente 1 (CTR-004).

Pasa la salida real de ``build_evidence_response`` por el normalizador real del
Agente 1 (``core.normalizar_respuesta_agente2``) y por su decisión
(``core.resolver_evidencias``), una vez por cada estado.

Se salta si el código del Agente 1 (``Agents/agente1``) no está en la rama.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "Test" / "fixtures" / "agent2"

sys.path.insert(0, str(REPO_ROOT))

core = pytest.importorskip(
    "Agents.agente1.core",
    reason="El Agente 1 (Agents/agente1) no está en esta rama",
)

from Agents.Agent_2.src.services.evidence_builder import (  # noqa: E402
    build_evidence_response,
)

PREGUNTA = "¿Qué hago si aparece HTM-0142?"


def _candidatos():
    with (FIXTURES_DIR / "evidencias_candidatos.json").open(
        encoding="utf-8"
    ) as fixture:
        return json.load(fixture)


def _vigentes():
    """c45 y c46: documentos vigentes según A2-06."""

    candidatos = _candidatos()[:2]
    for candidato in candidatos:
        candidato["estado_documento"] = "vigente"
    return candidatos


def _sustituido():
    """c47: documento sustituido (obsoleto, con sustituido_por)."""

    candidato = copy.deepcopy(_candidatos()[2])
    candidato["estado_documento"] = "sustituido"
    return candidato


@pytest.fixture
def redaccion(monkeypatch):
    """Sustituye la redacción con LLM y guarda lo que recibe."""

    llamadas = []

    def falsa_redaccion(pregunta, evidencias, agente, aviso=None, *args, **kwargs):
        llamadas.append({"evidencias": evidencias, "aviso": aviso})
        return {
            "estado": "respuesta",
            "texto": "respuesta simulada",
            "fuentes": [evidencia["chunk_id"] for evidencia in evidencias],
        }

    monkeypatch.setattr(
        core, "redactar_respuesta_con_verificacion", falsa_redaccion
    )
    return llamadas


def _normalizar(mensaje):
    normalizada = core.normalizar_respuesta_agente2(mensaje)

    # Un mensaje bien formado nunca termina en error de contrato.
    if mensaje["estado"] != "error":
        assert normalizada["codigo_error"] != "error_verificacion"
        assert normalizada["mensaje_error"] != "Contrato de Agente 2 inválido."

    return normalizada


def test_suficiente(redaccion):
    mensaje = build_evidence_response("suficiente", _vigentes())

    normalizada = _normalizar(mensaje)
    assert normalizada["estado"] == "suficiente"
    assert [e["chunk_id"] for e in normalizada["evidencias"]] == ["c45", "c46"]

    final = core.resolver_evidencias(PREGUNTA, mensaje, None, version="V1.1")

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is None
    # c46 solo aplica a V1.0: el Agente 1 lo descarta al filtrar por V1.1.
    assert [e["chunk_id"] for e in redaccion[0]["evidencias"]] == ["c45"]


def test_solo_obsoleto(redaccion):
    # c47 tiene vigente_para=["V2.0"]: para V2.0 seguiría vigente (A2-06).
    # Aquí se prueba el caso realmente obsoleto, sin vigencia residual.
    candidato = _sustituido()
    candidato["vigente_para"] = []
    mensaje = build_evidence_response("solo_obsoleto", [candidato])

    normalizada = _normalizar(mensaje)
    assert normalizada["estado"] == "solo_obsoleto"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None, version="V2.0")

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is not None


def test_ambiguo(redaccion):
    mensaje = build_evidence_response(
        "ambiguo", [_vigentes()[0], _sustituido()], campo_ambiguo="version"
    )

    normalizada = _normalizar(mensaje)
    assert normalizada["estado"] == "ambiguo"
    assert normalizada["campo_ambiguo"] == "version"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "aclaracion"
    assert final["campo_aclaracion"] == "version"
    assert redaccion == []


@pytest.mark.parametrize("estado", ["sin_evidencia", "insuficiente"])
def test_sin_evidencia(estado, redaccion):
    mensaje = build_evidence_response(estado)

    normalizada = _normalizar(mensaje)
    assert normalizada["estado"] == "sin_evidencia"
    assert normalizada["evidencias"] == []

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "sin_evidencia"
    assert final["fuentes"] == []
    assert redaccion == []


@pytest.mark.parametrize(
    "codigo", ["indice_no_disponible", "modelo_incompatible", "tiempo_agotado"]
)
def test_error_conserva_el_codigo(codigo, redaccion):
    mensaje = build_evidence_response(
        "error", codigo_error=codigo, mensaje_error="Fallo del Backend."
    )

    normalizada = _normalizar(mensaje)
    assert normalizada["estado"] == "error"
    assert normalizada["codigo_error"] == codigo

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "error"
    assert final["codigo_error"] == codigo
    assert final["fuentes"] == []
    assert redaccion == []


@pytest.mark.parametrize(
    "candidato,obsoleto_esperado",
    [
        (_vigentes()[0], False),
        (_sustituido(), True),
    ],
)
def test_obsoleto_de_las_fuentes_coincide_con_a2_06(candidato, obsoleto_esperado):
    mensaje = build_evidence_response("suficiente", [candidato])
    evidencia = _normalizar(mensaje)["evidencias"][0]

    assert core.es_obsoleta(evidencia) is obsoleto_esperado


def test_sustituido_aun_vigente_para_la_version_no_cuenta_como_obsoleto(redaccion):
    # Punto 3 de la revisión, ya resuelto: es_obsoleta sigue el criterio
    # vigente_para de A2-06 cuando se pide una de esas versiones.
    candidato = _sustituido()
    candidato["estado_documento"] = "vigente"

    mensaje = build_evidence_response("suficiente", [candidato])
    evidencia = _normalizar(mensaje)["evidencias"][0]

    assert core.es_obsoleta(evidencia, "V2.0") is False
    # Sin versión solicitada no hay excepción.
    assert core.es_obsoleta(evidencia) is True

    final = core.resolver_evidencias(PREGUNTA, mensaje, None, version="V2.0")

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is None


# ---------------------------------------------------------------------------
# Extremo a extremo: pipeline del Agente 2 -> Agente 1 real
# ---------------------------------------------------------------------------
#
# Los tests anteriores construyen el mensaje con ``build_evidence_response``.
# Estos ejecutan ``Agent2Pipeline.procesar_consulta`` sobre los 98 fragmentos
# del dataset sintético (Backend simulado) y pasan su salida tal cual al
# Agente 1. El embedding es constante y el reranker puntúa por solapamiento
# de palabras, así que el resultado es determinista y no necesita modelos.

import re  # noqa: E402

import requests  # noqa: E402

from Agents.Agent_2.src.clients.backend import BackendAPIClient  # noqa: E402
from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client  # noqa: E402
from Agents.Agent_2.src.services.pipeline import Agent2Pipeline  # noqa: E402
from Agents.Agent_2.src.testing.backend_simulator import (  # noqa: E402
    BackendSimulator,
    SimulatedSession,
)

DATASET = REPO_ROOT / "Agents" / "Agent_2" / "fixtures" / "bbdd_sintetica_chunks.json"
CATALOGOS = DATASET.parent / "catalogos"


class _EmbeddingConstante:
    def encode(self, texts, **kwargs):
        return {"dense_vecs": [[0.05] * 1024 for _ in texts]}


def _palabras(texto):
    return set(re.findall(r"\w+", texto.lower()))


class _RerankerSolapamiento:
    """Puntúa cada pasaje por la fracción de palabras de la consulta que contiene."""

    def predict(self, pairs):
        return [
            len(_palabras(consulta) & _palabras(pasaje)) / max(1, len(_palabras(consulta)))
            for consulta, pasaje in pairs
        ]


class _SesionCaida(requests.Session):
    def request(self, *args, **kwargs):
        raise requests.ConnectionError("Backend caído")


def _chunks_dataset():
    return json.loads(DATASET.read_text(encoding="utf-8-sig"))["chunks"]


def _pipeline(chunks=None, sesion=None):
    simulador = BackendSimulator(
        chunks if chunks is not None else _chunks_dataset(), catalogo_dir=CATALOGOS
    )
    cliente = BackendAPIClient(
        "http://backend.simulado",
        simulador.modelo_embeddings,
        session=sesion or SimulatedSession(simulador),
        timeout=2,
    )
    return Agent2Pipeline(
        backend_client=cliente,
        embedding_client=BgeM3Client(_EmbeddingConstante()),
        reranker_model=_RerankerSolapamiento(),
        require_reranker=True,
    )


def _consultar(texto, version=None, **kwargs):
    entrada = {"texto_preprocesado": texto}
    if version:
        entrada["filtros"] = {"version": version}
    salida = _pipeline(**kwargs).procesar_consulta(entrada)
    # Las métricas viajan aparte; el Agente 1 recibe solo el sobre CTR-004.
    salida.pop("metricas", None)
    return salida


def test_e2e_suficiente_responde_con_las_fuentes_del_agente2(redaccion):
    mensaje = _consultar("HTM-0142 bateria", "V1.1")
    assert mensaje["estado"] == "suficiente"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None, version="V1.1")

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is None
    usadas = {e["chunk_id"] for e in redaccion[0]["evidencias"]}
    assert "HTM240-DTC-001@1.0_p1_htm0142" in usadas
    assert usadas <= {e["chunk_id"] for e in mensaje["evidencias"]}


def test_e2e_ambiguo_por_version_pide_aclaracion(redaccion):
    # HTM-0142 cambia de significado en V2.0 (HTM240-BOL-003).
    mensaje = _consultar("codigo HTM-0142")
    assert mensaje["estado"] == "ambiguo"
    assert mensaje["campo_ambiguo"] == "version"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "aclaracion"
    assert final["campo_aclaracion"] == "version"
    assert redaccion == []


def test_e2e_pregunta_trampa_termina_sin_evidencia(redaccion):
    # TRAMP-01: el dataset no habla de neumáticos.
    mensaje = _consultar("presion neumaticos delanteros")
    assert mensaje["evidencias"] == []

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "sin_evidencia"
    assert final["fuentes"] == []
    assert redaccion == []


def test_e2e_solo_obsoleto_responde_con_aviso(redaccion):
    # Solo el plan de mantenimiento sustituido (80.000 km, vigente_para=[]).
    sustituidos = [c for c in _chunks_dataset() if "sustituido" in c["chunk_id"]]
    mensaje = _consultar("intervalo cambio refrigerante 80.000 km", chunks=sustituidos)
    assert mensaje["estado"] == "solo_obsoleto"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is not None
    assert [e["chunk_id"] for e in redaccion[0]["evidencias"]] == [
        "HTM240-MNT-001@1.0_p1_sustituido_refrigerante_80k"
    ]


def test_e2e_sustituido_vigente_para_la_version_pedida_no_lleva_aviso(redaccion):
    # PRC-003 v1.0 está sustituido pero sigue vigente para V1.0 (A2-06).
    sustituidos = [c for c in _chunks_dataset() if "sustituido" in c["chunk_id"]]
    mensaje = _consultar("corriente bomba auxiliar A", "V1.0", chunks=sustituidos)
    assert mensaje["estado"] == "suficiente"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None, version="V1.0")

    assert final["estado"] == "respuesta"
    assert redaccion[0]["aviso"] is None


def test_e2e_backend_caido_llega_como_error_con_codigo(redaccion):
    mensaje = _consultar("HTM-0142", sesion=_SesionCaida())
    assert mensaje["estado"] == "error"

    final = core.resolver_evidencias(PREGUNTA, mensaje, None)

    assert final["estado"] == "error"
    assert final["codigo_error"] == "servicio_no_disponible"
    assert final["fuentes"] == []
    assert redaccion == []
