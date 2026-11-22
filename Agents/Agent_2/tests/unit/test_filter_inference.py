import json
from pathlib import Path

import pytest

from Agents.Agent_2.src.services.filter_inference import (
    build_filters,
    infer_codes,
    infer_component,
    infer_document_types,
    infer_filters,
    infer_version,
    load_catalogs,
    merge_filters,
)
from Agents.Agent_2.src.services.filters import filter_chunks, version_applies

DATA_FILE = (
    Path(__file__).resolve().parents[4]
    / "Agents"
    / "Agent_2"
    / "fixtures"
    / "bbdd_sintetica_chunks.json"
)


def read_dataset():
    return json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))["chunks"]


def test_infer_version_requires_a_single_explicit_version():
    assert infer_version("Revisa la V1.1 del sistema") == "V1.1"
    assert infer_version("según la versión 2.0") == "V2.0"
    assert infer_version("V2,0 cambia el sensor") == "V2.0"
    assert infer_version("v1.0") == "V1.0"

    # Ambigüedad: dos versiones en la misma consulta no se resuelven a una.
    assert infer_version("V1.0 y V2.0") is None
    assert infer_version("de V1.1 a V1.0") is None

    # Sin prefijo explícito no se adivina una versión.
    assert infer_version("el procedimiento 1.1") is None
    assert infer_version("sin versión") is None
    assert infer_version("") is None


def test_infer_component_uses_only_closed_categories():
    assert infer_component("la batería") == "bateria"
    assert infer_component("Baterías de alta tensión") == "bateria"
    assert infer_component("el motor") is None  # Alias genérico sin especificidad
    assert infer_component("los motores") is None
    assert infer_component("pierde refrigerante") == "refrigeracion"
    assert infer_component("calefacción") == "calefaccion"
    assert infer_component("la TCU") == "control_tcu"

    # Fuera del conjunto cerrado no se inventa un componente.
    assert infer_component("la bomba de agua") is None
    assert infer_component("qué dice el manual") is None

    # Ambiguo: dos componentes mencionados no se reducen a uno.
    assert infer_component("refrigeración de la batería") is None
    assert infer_component("el motor de la batería") is None

    # El componente no se deduce del componente de un código.
    assert infer_component("HTM-0142") is None
    assert infer_component("CMP-18") is None

    # «Seguridad» como tipo de documento no debe imponer un componente.
    assert infer_component("manual de seguridad") is None
    assert infer_component("sistema de seguridad") == "seguridad"


def test_inference_helpers_reject_non_text():
    for function in (
        infer_version,
        infer_component,
        infer_document_types,
        infer_codes,
    ):
        for invalid in (None, 7, ["batería"], 1.1):
            with pytest.raises(TypeError):
                function(invalid)


def test_infer_document_types_returns_every_mentioned_type():
    assert infer_document_types("manual de taller") == ["manual"]
    assert infer_document_types("manuales de taller") == ["manual"]
    assert set(infer_document_types("boletín y procedimiento")) == {
        "procedimiento",
        "boletin",
    }
    assert infer_document_types("códigos de avería") == ["codigo_averia"]
    assert infer_document_types("el DTC") == ["codigo_averia"]
    assert infer_document_types("casos de servicio") == ["casos_servicio"]
    assert infer_document_types("diagnósticos") is None  # Término genérico: no imponer documento

    assert infer_document_types("ficha técnica") is None
    assert infer_document_types("no sé qué documento") is None

    # «día» no debe confundirse con el código de documento DIA.
    assert infer_document_types("revisado cada día") is None


def test_infer_codes_canonicalizes_known_codes_and_preserves_exactness():
    assert infer_codes("htm-0142") == ["HTM-0142"]
    assert infer_codes("CMP-17") == ["CMP-17"]
    assert infer_codes("HTM240-DTC-001") == ["HTM240-DTC-001"]
    assert infer_codes("HTM-0142 y htm-0142") == ["HTM-0142"]

    # Los códigos se comparan como tokens completos.
    assert infer_codes("HTM-0142 y HTM-01420") == ["HTM-0142"]
    assert infer_codes("HTM-0142 y HTM-014") == ["HTM-0142", "HTM-014"]

    assert infer_codes("sin códigos") is None
    assert infer_codes("") is None


def test_infer_codes_uses_the_given_catalogs(tmp_path):
    (tmp_path / "codigos.json").write_text(
        json.dumps({"codigos": [{"codigo": "HTM-9999"}]}),
        encoding="utf-8",
    )
    (tmp_path / "componentes.json").write_text(
        json.dumps({"componentes": [{"id": "CMP-99"}]}),
        encoding="utf-8",
    )

    catalogs = load_catalogs(tmp_path)

    assert infer_codes("htm-9999 y cmp-99", catalogs) == [
        "HTM-9999",
        "CMP-99",
    ]
    # Un código que no está en el catálogo conserva su forma en mayúsculas.
    assert infer_codes("htm-1234", catalogs) == ["HTM-1234"]


def test_infer_filters_combines_all_signals():
    filters = infer_filters(
        "¿Cómo se revisa HTM-0142 en la V2.0 del manual de taller de la batería?"
    )

    assert filters == {
        "version": "V2.0",
        "componente": "bateria",
        "tipo_documento": ["manual"],
        "codigos": ["HTM-0142"],
    }

    assert infer_filters("   ") == {}
    assert infer_filters("una consulta sin señales") == {}


def test_infer_filters_rejects_non_text():
    for value in (None, 7, ["batería"]):
        with pytest.raises(TypeError):
            infer_filters(value)


def test_merge_filters_explicit_version_and_component_win():
    merged = merge_filters(
        explicit={"version": "v1.1", "componente": "Batería"},
        inferred={
            "version": "V2.0",
            "componente": "motor",
            "tipo_documento": ["manual"],
            "codigos": ["HTM-0142"],
        },
    )

    assert merged["version"] == "V1.1"
    assert merged["componente"] == "bateria"
    assert merged["tipo_documento"] == ["manual"]
    assert merged["codigos"] == ["HTM-0142"]


def test_merge_filters_keeps_inferred_when_explicit_value_is_empty():
    inferred = {"version": "V2.0", "componente": "motor"}

    for explicit in (
        {},
        {"version": None, "componente": None},
        {"version": "", "componente": "   "},
    ):
        merged = merge_filters(explicit, inferred)
        assert merged["version"] == "V2.0"
        assert merged["componente"] == "motor"


def test_merge_filters_expands_document_types_and_codes():
    merged = merge_filters(
        explicit={
            "tipo_documento": ["manual", "Manual de taller"],
            "codigos": ["HTM-0142", "CMP-17"],
        },
        inferred={
            "tipo_documento": ["boletin", "manual"],
            "codigos": ["HTM-0142", "HTM-0202"],
        },
    )

    assert merged["tipo_documento"] == ["manual", "boletin"]
    assert merged["codigos"] == ["HTM-0142", "CMP-17", "HTM-0202"]


def test_merge_filters_only_takes_incluir_obsoletos_from_explicit():
    assert "incluir_obsoletos" not in merge_filters({}, {"version": "V1.0"})
    assert merge_filters({"incluir_obsoletos": False}, {})[
        "incluir_obsoletos"
    ] is False
    assert merge_filters({"incluir_obsoletos": True}, {})[
        "incluir_obsoletos"
    ] is True


def test_merge_filters_rejects_invalid_inputs():
    for invalid in ("filtros", 7, [1]):
        with pytest.raises(TypeError):
            merge_filters(invalid, {})
        with pytest.raises(TypeError):
            merge_filters({}, invalid)

    with pytest.raises(TypeError):
        merge_filters({"version": 1.1}, {})
    with pytest.raises(TypeError):
        merge_filters({"componente": 3}, {})
    with pytest.raises(TypeError):
        merge_filters({"tipo_documento": 5}, {})
    with pytest.raises(TypeError):
        merge_filters({"codigos": 5}, {})
    with pytest.raises(TypeError):
        merge_filters({"incluir_obsoletos": "no"}, {})


def test_build_filters_combines_inference_with_explicit_filters():
    filters = build_filters("HTM-0142 en la V2.0 de la batería")

    assert filters["version"] == "V2.0"
    assert filters["componente"] == "bateria"
    assert filters["codigos"] == ["HTM-0142"]

    overridden = build_filters("HTM-0142 en la V2.0", {"componente": "motor"})
    assert overridden["componente"] == "motor"


def test_inferred_filters_select_the_expected_chunks_in_the_real_dataset():
    chunks = read_dataset()

    filters = build_filters("HTM-0142 en V2.0")
    results = filter_chunks(chunks, filters)
    result_ids = [chunk["chunk_id"] for chunk in results]

    assert results
    assert all(version_applies(chunk, "V2.0") for chunk in results)
    assert all(
        "HTM-0142" in chunk["ids_referenciados"] for chunk in results
    )
    assert "HTM240-DTC-001@1.0_p1_htm0142_v20" in result_ids
    assert "HTM240-DTC-001@1.0_p1_htm0142" not in result_ids
    assert "HTM240-BOL-003@1.0_p1_significado_HTM0142_v20" in result_ids

    battery = filter_chunks(
        chunks,
        build_filters("batería", {"version": "V1.1"}),
    )

    assert battery
    assert all(chunk["componente"] == "bateria" for chunk in battery)
    assert all(version_applies(chunk, "V1.1") for chunk in battery)
    assert "HTM240-DTC-001@1.0_p1_htm0142" in [
        chunk["chunk_id"] for chunk in battery
    ]


def test_explicit_hard_filters_are_never_relaxed_by_the_query():
    chunks = read_dataset()

    # La consulta menciona batería y V2.0, pero el filtro explícito manda.
    filters = build_filters(
        "batería en V2.0",
        {"version": "V1.0", "componente": "motor"},
    )

    assert filters["version"] == "V1.0"
    assert filters["componente"] == "motor"

    results = filter_chunks(chunks, filters)
    assert results
    assert all(chunk["componente"] == "motor" for chunk in results)
    assert all(version_applies(chunk, "V1.0") for chunk in results)
