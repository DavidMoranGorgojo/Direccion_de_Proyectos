
from Agents.Agent_2.src.services.filters import filter_chunks


def test_version_and_component_filters_are_strict():
    chunks = [
        {
            "chunk_id": "bateria-v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "bateria-v2",
            "versiones": ["V1.0", "V1.1", "V2.0"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "motor-v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "motor",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "procedimiento-sustituido",
            "versiones": ["V2.0"],
            "vigente_para": ["V1.0"],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": "PRC-004",
        },
    ]

    results = filter_chunks(
        chunks,
        {"version": "V1.1", "componente": "bateria"},
    )

    assert [c["chunk_id"] for c in results] == [
        "bateria-v11",
        "bateria-v2",
    ]

    no_match = filter_chunks(
        chunks,
        {"version": "V2.0", "componente": "motor"},
    )

    assert no_match == []

    # Un documento sustituido puede seguir aplicando a V1.0.
    legacy = filter_chunks(
        chunks,
        {"version": "V1.0"},
    )

    assert "procedimiento-sustituido" in [
        c["chunk_id"] for c in legacy
    ]
