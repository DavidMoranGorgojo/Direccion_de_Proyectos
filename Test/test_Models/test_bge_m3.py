import sys
import types

import pytest

from Agents.Agent_2.src.clients import bge_m3
from Agents.Agent_2.src.clients.bge_m3 import BgeM3Client


ENCODE_OPTIONS = {
    "return_dense": True,
    "return_sparse": False,
    "return_colbert_vecs": False,
}


class FakeEncoder:
    def __init__(self):
        self.received_texts = []
        self.options = []

    def encode(self, texts, **kwargs):
        self.received_texts.extend(texts)
        self.options.append(kwargs)
        return {
            "dense_vecs": [[1.0, 0.0] for _ in texts],
        }


def test_bge_client_adds_query_and_passage_prefixes():
    encoder = FakeEncoder()
    client = BgeM3Client(encoder)

    client.encode_query("HTM-0142")
    client.encode_passages(["Texto del manual", "Texto del boletín"])

    assert encoder.received_texts == [
        "query: HTM-0142",
        "passage: Texto del manual",
        "passage: Texto del boletín",
    ]


def test_bge_client_can_disable_prefix_for_benchmark():
    encoder = FakeEncoder()
    client = BgeM3Client(encoder, use_prefix=False)

    client.encode_query("HTM-0142")
    client.encode_passages(["Texto del manual"])

    assert encoder.received_texts == [
        "HTM-0142",
        "Texto del manual",
    ]


def test_bge_client_returns_dense_vectors():
    encoder = FakeEncoder()
    client = BgeM3Client(encoder)

    query_vector = client.encode_query("HTM-0142")
    passage_vectors = client.encode_passages(["Texto del manual"])

    assert query_vector == [1.0, 0.0]
    assert passage_vectors == [[1.0, 0.0]]
    assert encoder.options == [ENCODE_OPTIONS, ENCODE_OPTIONS]


def test_bge_client_does_not_duplicate_existing_prefixes():
    encoder = FakeEncoder()
    client = BgeM3Client(encoder)

    client.encode_query("query: HTM-0142")
    client.encode_passages(["passage: Texto del manual"])

    assert encoder.received_texts == [
        "query: HTM-0142",
        "passage: Texto del manual",
    ]


def test_load_bge_m3_client_imports_flag_embedding_lazily(monkeypatch):
    created = {}

    class FakeFlagModel:
        def __init__(self, model_name, **kwargs):
            created["model_name"] = model_name
            created["kwargs"] = kwargs

    fake_module = types.SimpleNamespace(BGEM3FlagModel=FakeFlagModel)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)

    client = bge_m3.load_bge_m3_client(
        "BAAI/bge-m3",
        device="cpu",
        use_fp16=False,
    )

    assert isinstance(client, BgeM3Client)
    assert isinstance(client.encoder, FakeFlagModel)
    assert created == {
        "model_name": "BAAI/bge-m3",
        "kwargs": {"use_fp16": False, "device": "cpu"},
    }


def test_load_bge_m3_client_reports_missing_flag_embedding(monkeypatch):
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)

    with pytest.raises(RuntimeError, match="FlagEmbedding"):
        bge_m3.load_bge_m3_client()