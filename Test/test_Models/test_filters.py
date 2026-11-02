from Agents.Agent_2.src.services.filters import filter_chunks


def test_version_and_component_filters_are_strict():
    chunks = [
        {
            "chunk_id": "bateria-v11",
            "versiones": ["V1.1"],
            "vigente_para": ["V1.1"],
            "componente": "bateria",
            "tipo_documento": "manual",
        },
        {
            "chunk_id": "bateria-v2",
            "versiones": ["V1.0", "V1.1", "V2.0"],
            "vigente_para": ["V2.0"],
            "componente": "bateria",
            "tipo_documento": "manual",
        },
        {
            "chunk_id": "motor-v11",
            "versiones": ["V1.1"],
            "vigente_para": ["V1.1"],
            "componente": "motor",
            "tipo_documento": "manual",
        },
        {
            "chunk_id": "obsoleto-v1",
            "versiones": ["V1.0", "V1.1", "V2.0"],
            "vigente_para": ["V1.0"],
            "componente": "bateria",
            "tipo_documento": "manual",
        },
    ]

    results = filter_chunks(
        chunks,
        {"version": "V1.1", "componente": "bateria"},
    )
    assert [chunk["chunk_id"] for chunk in results] == ["bateria-v11"]

    no_match = filter_chunks(
        chunks,
        {"version": "V2.0", "componente": "motor"},
    )
    assert no_match == []

def test_optional_document_type_filter_does_not_broaden():
    chunks = [
        {
            "chunk_id": "manual",
            "vigente_para": ["V1.0"],
            "componente": "motor",
            "tipo_documento": "manual",
        },
        {
            "chunk_id": "dtc",
            "vigente_para": ["V1.0"],
            "componente": "motor",
            "tipo_documento": "codigo_averia",
        },
    ]

    manuals = filter_chunks(chunks, {"tipo_documento": "manual"})
    assert [chunk["chunk_id"] for chunk in manuals] == ["manual"]

    assert filter_chunks(chunks, {}) == chunks
    assert filter_chunks(chunks, {"tipo_documento": "mantenimiento"}) == []