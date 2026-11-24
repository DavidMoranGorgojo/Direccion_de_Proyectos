"""Contrato de obsolescencia entre A2-06 y el Agente 1.

El Agente 2 calcula la vigencia con ``services.vigencia.document_state`` y el
Agente 1 decide con ``agente1.core.es_obsoleta``. Ambos deben coincidir: un
documento obsoleto o sustituido sigue vigente para las versiones de
``vigente_para``. El simulador del Agente 1 debe aplicar la misma regla.
"""

import pytest

from Agents.agente1 import core
from Agents.Agent_2.src.services.vigencia import document_state
from Agents.Agent_2.src.testing import agent1_simulator

CHUNKS = {
    "vigente": {"versiones": ["V1.0", "V2.0"], "obsoleto": False, "sustituido_por": None},
    "sustituido_con_vigente_para": {
        "versiones": ["V1.0"], "obsoleto": True,
        "sustituido_por": "DOC@2.0", "vigente_para": ["V1.0"],
    },
    "sustituido_sin_vigente_para": {
        "versiones": ["V1.0"], "obsoleto": False, "sustituido_por": "DOC@2.0",
    },
    "obsoleto_con_vigente_para": {
        "versiones": ["V1.0"], "obsoleto": True,
        "sustituido_por": None, "vigente_para": ["V1.0"],
    },
}
VERSIONES = [None, "V1.0"]


def como_evidencia(chunk, version):
    """Evidencia CTR-004 tal y como la emite el Agente 2 para ``version``."""
    metadata = {"version": chunk["versiones"][0].lstrip("V"), **chunk}
    return {
        "chunk_id": "c_1",
        "texto": "Texto de prueba.",
        "metadata": metadata,
        "estado_documento": document_state(chunk, version),
    }


@pytest.mark.parametrize("nombre", CHUNKS)
@pytest.mark.parametrize("version", VERSIONES)
def test_agente1_y_a2_06_coinciden(nombre, version):
    chunk = CHUNKS[nombre]
    esperado = document_state(chunk, version) != "vigente"
    evidencia = como_evidencia(chunk, version)

    assert core.es_obsoleta(evidencia, version) is esperado
    assert agent1_simulator.es_obsoleta(evidencia, version) is esperado


def test_sustituido_vigente_para_la_version_pedida_no_lleva_aviso():
    evidencia = como_evidencia(CHUNKS["sustituido_con_vigente_para"], "V1.0")

    assert core.es_obsoleta(evidencia, "V1.0") is False
    # Sin versión solicitada se mantiene obsoleto.
    assert core.es_obsoleta(evidencia) is True


def test_simulador_agente1_usa_la_version_para_decidir_fuentes():
    evidencia = como_evidencia(CHUNKS["sustituido_con_vigente_para"], "V1.0")
    evidencia["metadata"]["versiones"] = ["V1.0"]
    respuesta = {"estado": "suficiente", "evidencias": [evidencia]}

    final = agent1_simulator.resolver_evidencias(respuesta, version="V1.0")

    assert final["estado"] == "respuesta"
    assert final["fuentes"][0]["obsoleto"] is False
