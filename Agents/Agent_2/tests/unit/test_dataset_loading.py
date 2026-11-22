import json
from pathlib import Path
from collections import Counter
from datetime import date
import pytest
from Agents.Agent_2.src.clients.backend import load_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_FILE = (
    PROJECT_ROOT
    / "Agents"
    / "Agent_2"
    / "fixtures"
    / "bbdd_sintetica_chunks.json"
)
REQUIRED_CHUNK_FIELDS = {
    "chunk_id",
    "texto",
    "documento",
    "seccion",
    "pagina",
    "versiones",
    "componente",
    "tipo_documento",
    "obsoleto",
    "sustituido_por",
    "vigente_para",
    "fecha_revision",
    "orden_en_seccion",
    "version_documento",
    "afectado_por",
    "ids_referenciados",
}


def read_dataset():
    return json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))

def test_dataset_json_loads_and_chunk_count_matches():
    with DATA_FILE.open(encoding="utf-8-sig") as file:
        dataset = json.load(file)

    assert dataset["version_bbdd"] == "1.0-sintetica-completa"
    assert dataset["total_chunks"] == 98
    assert len(dataset["chunks"]) == dataset["total_chunks"]

def test_chunk_ids_are_nonempty_and_unique():
    chunks = read_dataset()["chunks"]
    chunk_ids = [chunk.get("chunk_id") for chunk in chunks]
    counts = Counter(chunk_ids)
    duplicates = {chunk_id: count for chunk_id, count in counts.items() if count > 1}

    if duplicates:
        duplicate_id = next(iter(duplicates))
        matches = [
            chunk for chunk in chunks
            if chunk.get("chunk_id") == duplicate_id
        ]

        for number, chunk in enumerate(matches, start=1):
            print(f"\n--- Fragmento {number} ---")
            for field in (
                "documento", "seccion", "pagina", "versiones",
                "componente", "tipo_documento", "obsoleto", "version_documento",
            ):
                print(f"{field}: {chunk.get(field)}")
            print(f"texto: {chunk.get('texto', '')[:300]}")

        print(f"\n¿Las dos filas son idénticas?: {matches[0] == matches[1]}")

    assert all(isinstance(chunk_id, str) and chunk_id.strip() for chunk_id in chunk_ids)
    assert not duplicates, f"IDs duplicados: {duplicates}"

def test_each_chunk_has_required_metadata():
    chunks = read_dataset()["chunks"]
    missing = [
        (chunk.get("chunk_id", f"índice {index}"), sorted(REQUIRED_CHUNK_FIELDS - chunk.keys()))
        for index, chunk in enumerate(chunks)
        if REQUIRED_CHUNK_FIELDS - chunk.keys()
    ]

    assert not missing, (
        f"{len(missing)} fragmentos tienen metadatos ausentes. "
        f"Primeros casos: {missing[:3]}"
    )

def test_chunk_metadata_types_are_valid():
    for chunk in read_dataset()["chunks"]:
        chunk_id = chunk.get("chunk_id", "<sin id>")

        for field in ("texto", "documento", "seccion", "componente", "tipo_documento"):
            assert isinstance(chunk.get(field), str) and chunk[field].strip(), (
                f"{chunk_id}: {field} debe ser texto no vacío"
            )

        assert type(chunk.get("pagina")) is int and chunk["pagina"] > 0, (
            f"{chunk_id}: pagina debe ser un entero mayor que cero"
        )
        assert isinstance(chunk.get("versiones"), list) and chunk["versiones"], (
            f"{chunk_id}: versiones debe ser una lista no vacía"
        )
        assert all(isinstance(version, str) and version.strip() for version in chunk["versiones"]), (
            f"{chunk_id}: cada versión debe ser texto no vacío"
        )
        assert type(chunk.get("obsoleto")) is bool, (
            f"{chunk_id}: obsoleto debe ser booleano"
        )
        assert isinstance(chunk.get("afectado_por"), list), (
            f"{chunk_id}: afectado_por debe ser una lista"
        )
        assert isinstance(chunk.get("ids_referenciados"), list), (
            f"{chunk_id}: ids_referenciados debe ser una lista"
        )

def test_chunk_metadata_values_are_valid():
    for chunk in read_dataset()["chunks"]:
        chunk_id = chunk.get("chunk_id", "<sin id>")

        assert type(chunk.get("orden_en_seccion")) is int
        assert chunk["orden_en_seccion"] > 0, (
            f"{chunk_id}: orden_en_seccion debe ser mayor que cero"
        )

        try:
            date.fromisoformat(chunk.get("fecha_revision", ""))
        except (TypeError, ValueError):
            raise AssertionError(
                f"{chunk_id}: fecha_revision debe tener formato YYYY-MM-DD"
            )

        for field in ("afectado_por", "ids_referenciados"):
            assert all(
                isinstance(value, str) and value.strip()
                for value in chunk[field]
            ), f"{chunk_id}: {field} debe contener solo textos no vacíos"

        sustituido_por = chunk.get("sustituido_por")
        assert sustituido_por is None or (
            isinstance(sustituido_por, str) and sustituido_por.strip()
        ), f"{chunk_id}: sustituido_por debe ser texto o null"

def make_valid_chunk(chunk_id):
    return {
        "chunk_id": chunk_id,
        "texto": "Evidencia de prueba",
        "documento": "DOC-001",
        "seccion": "1",
        "pagina": 1,
        "versiones": ["V1.0"],
        "componente": "motor",
        "tipo_documento": "manual",
        "obsoleto": False,
        "sustituido_por": None,
        "vigente_para": ["V1.0"],
        "fecha_revision": "2025-09-18",
        "orden_en_seccion": 1,
        "version_documento": "1.0",
        "afectado_por": [],
        "ids_referenciados": [],
    }


def test_loader_discards_incomplete_chunk_and_warns(tmp_path):
    valid_chunk = make_valid_chunk("chunk-valido")
    incomplete_chunk = make_valid_chunk("chunk-incompleto")
    del incomplete_chunk["pagina"]

    dataset = {
        "version_bbdd": "test",
        "total_chunks": 2,
        "chunks": [valid_chunk, incomplete_chunk],
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="chunk-incompleto"):
        loaded_chunks = load_chunks(dataset_path)

    assert [chunk["chunk_id"] for chunk in loaded_chunks] == ["chunk-valido"]

def test_loader_rejects_wrong_total_chunks(tmp_path):
    dataset = {
        "version_bbdd": "test",
        "total_chunks": 2,
        "chunks": [make_valid_chunk("chunk-1")],
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="total_chunks"):
        load_chunks(dataset_path)

def test_loader_discards_chunk_with_invalid_page_and_warns(tmp_path):
    valid_chunk = make_valid_chunk("chunk-valido")
    invalid_chunk = make_valid_chunk("chunk-pagina-texto")
    invalid_chunk["pagina"] = "1"

    dataset = {
        "version_bbdd": "test",
        "total_chunks": 2,
        "chunks": [valid_chunk, invalid_chunk],
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="chunk-pagina-texto"):
        loaded_chunks = load_chunks(dataset_path)

    assert [chunk["chunk_id"] for chunk in loaded_chunks] == ["chunk-valido"]

@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("chunk_id", ""),
        ("texto", ""),
        ("documento", ""),
        ("seccion", ""),
        ("versiones", "V1.0"),
        ("componente", ""),
        ("tipo_documento", ""),
        ("obsoleto", "false"),
        ("sustituido_por", 7),
        ("vigente_para", "V1.0"),
        ("fecha_revision", "2025/09/18"),
        ("orden_en_seccion", 0),
        ("version_documento", ""),
        ("afectado_por", None),
        ("ids_referenciados", [7]),
    ],
)
def test_loader_discards_chunk_with_invalid_metadata(tmp_path, field, invalid_value):
    valid_chunk = make_valid_chunk("chunk-valido")
    invalid_chunk = make_valid_chunk("chunk-invalido")
    invalid_chunk[field] = invalid_value

    dataset = {
        "version_bbdd": "test",
        "total_chunks": 2,
        "chunks": [valid_chunk, invalid_chunk],
    }
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="se omite"):
        loaded_chunks = load_chunks(dataset_path)

    assert [chunk["chunk_id"] for chunk in loaded_chunks] == ["chunk-valido"]
