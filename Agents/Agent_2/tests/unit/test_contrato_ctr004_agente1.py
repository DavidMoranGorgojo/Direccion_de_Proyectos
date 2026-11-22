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

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_DIR = REPO_ROOT / "Agents" / "Agent_2" / "tests" / "fixtures"

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
