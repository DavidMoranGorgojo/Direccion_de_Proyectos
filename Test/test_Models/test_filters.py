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


def test_versions_are_normalized_but_never_relaxed():
    chunks = [
        {
            "chunk_id": "v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "motor",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
    ]

    for requested in ("V1.1", "v1.1", "1.1", "  V1.1  "):
        results = filter_chunks(chunks, {"version": requested})
        assert [c["chunk_id"] for c in results] == ["v11"]

    # Una versión desconocida no se aproxima ni se ignora.
    for unknown in ("V1.2", "V9.9", "V1", "actual"):
        assert filter_chunks(chunks, {"version": unknown}) == []

    # Un valor vacío equivale a no restringir por versión.
    assert [c["chunk_id"] for c in filter_chunks(chunks, {"version": "  "})] == [
        "v11"
    ]


def test_component_aliases_are_normalized_and_unknown_components_excluded():
    chunks = [
        {
            "chunk_id": "bateria",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
    ]

    for requested in ("bateria", "Batería", "Batería de alta tensión"):
        results = filter_chunks(chunks, {"componente": requested})
        assert [c["chunk_id"] for c in results] == ["bateria"]

    # El componente es duro: ni se deduce ni se sustituye por otro.
    assert filter_chunks(chunks, {"componente": "motor"}) == []
    assert filter_chunks(chunks, {"componente": "general"}) == []


def test_substituted_chunk_uses_vigente_para_only_when_it_was_substituted():
    chunks = [
        {
            "chunk_id": "sustituido",
            "versiones": ["V2.0"],
            "vigente_para": ["V1.0"],
            "componente": "bateria",
            "tipo_documento": "procedimiento",
            "sustituido_por": "PRC-004",
        },
        {
            "chunk_id": "no-sustituido",
            "versiones": ["V2.0"],
            "vigente_para": ["V1.0"],
            "componente": "bateria",
            "tipo_documento": "procedimiento",
            "sustituido_por": None,
        },
    ]

    v1 = filter_chunks(chunks, {"version": "V1.0"})
    v11 = filter_chunks(chunks, {"version": "V1.1"})
    v2 = filter_chunks(chunks, {"version": "V2.0"})

    assert [c["chunk_id"] for c in v1] == ["sustituido"]
    assert v11 == []
    assert [c["chunk_id"] for c in v2] == ["sustituido", "no-sustituido"]


def test_document_type_accepts_one_or_several_canonical_values():
    chunks = [
        {
            "chunk_id": "manual",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "boletin",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "boletin",
            "sustituido_por": None,
        },
        {
            "chunk_id": "catalogo",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "catalogo",
            "sustituido_por": None,
        },
        {
            "chunk_id": "diagnostico",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "diagnostico",
            "sustituido_por": None,
        },
    ]

    single = filter_chunks(chunks, {"tipo_documento": "manual de taller"})
    assert [c["chunk_id"] for c in single] == ["manual"]

    several = filter_chunks(
        chunks,
        {"tipo_documento": ["manual de taller", "Boletines", "CAT", "arbol de diagnostico"]},
    )
    assert [c["chunk_id"] for c in several] == [
        "manual",
        "boletin",
        "catalogo",
        "diagnostico",
    ]

    # Un tipo desconocido filtra a vacío; no se interpreta como comodín.
    assert filter_chunks(chunks, {"tipo_documento": "ficha_tecnica"}) == []


def test_document_type_expansion_does_not_relax_hard_filters():
    chunks = [
        {
            "chunk_id": "manual-bateria-v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "boletin-bateria-v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "boletin",
            "sustituido_por": None,
        },
        {
            "chunk_id": "manual-bateria-v20",
            "versiones": ["V2.0"],
            "vigente_para": [],
            "componente": "bateria",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
        {
            "chunk_id": "manual-motor-v11",
            "versiones": ["V1.1"],
            "vigente_para": [],
            "componente": "motor",
            "tipo_documento": "manual",
            "sustituido_por": None,
        },
    ]

    results = filter_chunks(
        chunks,
        {
            "version": "V1.1",
            "componente": "bateria",
            "tipo_documento": ["manual", "boletin"],
        },
    )

    assert [c["chunk_id"] for c in results] == [
        "manual-bateria-v11",
        "boletin-bateria-v11",
    ]


def test_codes_match_exact_tokens_in_all_metadata_fields():
    chunks = [
        {"chunk_id": "por-ids", "ids_referenciados": ["HTM-0142"], "texto": "x"},
        {"chunk_id": "por-texto", "texto": "Se registra HTM-0142 en la TCU."},
        {"chunk_id": "por-seccion", "seccion": "HTM-0142"},
        {"chunk_id": "por-documento", "documento": "HTM-0142"},
        {"chunk_id": "htm0142_sin_guion"},
        {"chunk_id": "texto-sin-guion", "texto": "código htm0142"},
        {"chunk_id": "prefijo", "texto": "Se registra HTM-01420 en la TCU."},
        {"chunk_id": "parcial", "texto": "Se registra HTM-014 en la TCU."},
        {"chunk_id": "otro-codigo", "texto": "Revisar CMP-17."},
    ]

    expected = [
        "por-ids",
        "por-texto",
        "por-seccion",
        "por-documento",
        "htm0142_sin_guion",
        "texto-sin-guion",
    ]

    exact = filter_chunks(chunks, {"codigos": "htm-0142"})
    assert [c["chunk_id"] for c in exact] == expected

    several = filter_chunks(chunks, {"codigos": ["HTM-0142", "cmp17"]})
    assert [c["chunk_id"] for c in several] == expected + ["otro-codigo"]

    assert filter_chunks(chunks, {"codigos": "HTM-9999"}) == []


def test_obsolete_chunks_are_included_by_default_and_can_be_excluded():
    chunks = [
        {
            "chunk_id": "vigente",
            "versiones": ["V1.0"],
            "vigente_para": [],
            "componente": "refrigeracion",
            "tipo_documento": "mantenimiento",
            "obsoleto": False,
            "sustituido_por": None,
        },
        {
            "chunk_id": "obsoleto",
            "versiones": ["V1.0"],
            "vigente_para": [],
            "componente": "refrigeracion",
            "tipo_documento": "mantenimiento",
            "obsoleto": True,
            "sustituido_por": "MNT-002",
        },
    ]

    default = filter_chunks(chunks, {"componente": "refrigeracion"})
    assert [c["chunk_id"] for c in default] == ["vigente", "obsoleto"]

    explicit_include = filter_chunks(
        chunks,
        {"componente": "refrigeracion", "incluir_obsoletos": True},
    )
    assert [c["chunk_id"] for c in explicit_include] == ["vigente", "obsoleto"]

    excluded = filter_chunks(
        chunks,
        {"componente": "refrigeracion", "incluir_obsoletos": False},
    )
    assert [c["chunk_id"] for c in excluded] == ["vigente"]


def test_empty_filters_return_every_chunk():
    chunks = [{"chunk_id": "uno"}, {"chunk_id": "dos"}]

    assert filter_chunks(chunks) == chunks
    assert filter_chunks(chunks, {}) == chunks
    assert filter_chunks(chunks, {"version": None, "componente": None}) == chunks
    assert filter_chunks([], {"componente": "motor"}) == []


def test_invalid_filters_are_rejected():
    chunks = [{"chunk_id": "uno"}]

    for invalid_filter in ("version=V1.1", 7, [1]):
        try:
            filter_chunks(chunks, invalid_filter)
        except TypeError:
            pass
        else:
            raise AssertionError(f"se esperaba TypeError para {invalid_filter!r}")

    invalid_values = [
        ({"incluir_obsoletos": "false"}, TypeError),
        ({"incluir_obsoletos": 1}, TypeError),
        ({"version": 1.1}, TypeError),
        ({"componente": 3}, TypeError),
        ({"tipo_documento": 5}, TypeError),
        ({"tipo_documento": [5]}, TypeError),
        ({"tipo_documento": ""}, ValueError),
        ({"tipo_documento": []}, None),
        ({"codigos": 5}, TypeError),
        ({"codigos": ""}, ValueError),
        ({"codigos": [""]}, ValueError),
        ({"codigos": ["   "]}, ValueError),
    ]

    for filters, expected_error in invalid_values:
        if expected_error is None:
            assert filter_chunks(chunks, filters) == chunks
            continue

        try:
            filter_chunks(chunks, filters)
        except expected_error:
            pass
        else:
            raise AssertionError(
                f"se esperaba {expected_error.__name__} para {filters!r}"
            )
