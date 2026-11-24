import pytest

from Agents.Agent_2.src.core.config import (
    Agent2Settings,
    DATASET_PATH,
)


def test_default_settings_match_bge_m3_and_backend_contract():
    settings = Agent2Settings.from_env(env={})

    assert settings.backend_base_url == "http://localhost:8000"
    assert settings.embeddings_model == "BAAI/bge-m3"
    assert settings.embedding_dimension == 1024
    assert settings.search_top_k == 30
    assert settings.request_timeout == 5.0
    assert settings.use_query_prefix is True
    assert settings.dataset_path == DATASET_PATH
    assert settings.dataset_path.name == "bbdd_sintetica_chunks.json"
    assert settings.dataset_path.is_file()


def test_environment_overrides_are_applied():
    settings = Agent2Settings.from_env(env={
        "AGENT2_BACKEND_BASE_URL": "http://backend.test:9000/",
        "AGENT2_EMBEDDINGS_MODEL": "custom/model",
        "AGENT2_EMBEDDING_DIMENSION": "512",
        "AGENT2_SEARCH_TOP_K": "10",
        "AGENT2_REQUEST_TIMEOUT": "2.5",
        "AGENT2_USE_QUERY_PREFIX": "false",
    })

    assert settings.backend_base_url == "http://backend.test:9000"
    assert settings.embeddings_model == "custom/model"
    assert settings.embedding_dimension == 512
    assert settings.search_top_k == 10
    assert settings.request_timeout == 2.5
    assert settings.use_query_prefix is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AGENT2_BACKEND_BASE_URL", "   "),
        ("AGENT2_EMBEDDING_DIMENSION", "0"),
        ("AGENT2_EMBEDDING_DIMENSION", "no-es-un-numero"),
        ("AGENT2_SEARCH_TOP_K", "-1"),
        ("AGENT2_REQUEST_TIMEOUT", "0"),
        ("AGENT2_REQUEST_TIMEOUT", "inf"),
        ("AGENT2_USE_QUERY_PREFIX", "quizas"),
    ],
)
def test_invalid_environment_values_are_rejected(name, value):
    with pytest.raises(ValueError):
        Agent2Settings.from_env(env={name: value})
