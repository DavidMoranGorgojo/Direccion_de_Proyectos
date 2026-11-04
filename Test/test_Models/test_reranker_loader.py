
import pytest

from Agents.Agent_2.src.clients import reranker_loader
from Agents.Agent_2.src.clients.reranker_model import RerankerModel
from Agents.Agent_2.src.core import config


@pytest.fixture(autouse=True)
def limpiar_cache():
    """
    Aísla los tests para que ninguno reutilice
    el modelo creado por otro test.
    """
    reranker_loader._load_reranker.cache_clear()

    yield

    reranker_loader._load_reranker.cache_clear()


def test_get_reranker_utiliza_modelo_configurado(monkeypatch):
    """
    Comprueba que el cargador utiliza el nombre
    de modelo definido en config.py.
    """
    nombres_recibidos = []

    def fake_loader(model_name):
        nombres_recibidos.append(model_name)
        return object()

    monkeypatch.setattr(
        reranker_loader,
        "_load_reranker",
        fake_loader,
    )
    monkeypatch.setattr(
        config,
        "RERANKER_MODEL",
        "modelo-de-prueba",
    )

    reranker_loader.get_reranker()

    assert nombres_recibidos == ["modelo-de-prueba"]


def test_load_reranker_reutiliza_instancia(monkeypatch):
    """
    Comprueba que el modelo se carga una sola vez
    y se reutiliza en llamadas posteriores.
    """
    import sys
    import types

    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append((model_name, use_fp16))

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    fake_module = types.ModuleType("FlagEmbedding")
    fake_module.FlagReranker = FakeFlagReranker

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        fake_module,
    )

    primero = reranker_loader.get_reranker()
    segundo = reranker_loader.get_reranker()

    assert primero is segundo
    assert isinstance(primero, RerankerModel)
    assert cargas == [(config.RERANKER_MODEL, False)]


def test_load_reranker_no_carga_hasta_primera_llamada(monkeypatch):
    """
    Comprueba que importar el módulo no obliga
    a inicializar el modelo real.
    """
    import sys
    import types

    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append(model_name)

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    fake_module = types.ModuleType("FlagEmbedding")
    fake_module.FlagReranker = FakeFlagReranker

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        fake_module,
    )

    assert cargas == []

    reranker_loader.get_reranker()

    assert len(cargas) == 1


def test_load_reranker_propaga_error(monkeypatch):
    """
    Un fallo durante la carga del modelo
    no debe convertirse en un resultado vacío.
    """
    import sys
    import types

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            raise RuntimeError("Error simulado de carga")

    fake_module = types.ModuleType("FlagEmbedding")
    fake_module.FlagReranker = FakeFlagReranker

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        fake_module,
    )

    with pytest.raises(RuntimeError, match="Error simulado de carga"):
        reranker_loader.get_reranker()


def test_load_reranker_permite_reintentar_tras_error(monkeypatch):
    """
    Un error de inicialización no debe quedar
    almacenado en la caché.
    """
    import sys
    import types

    intentos = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            intentos.append(model_name)

            if len(intentos) == 1:
                raise RuntimeError("Fallo temporal")

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    fake_module = types.ModuleType("FlagEmbedding")
    fake_module.FlagReranker = FakeFlagReranker

    monkeypatch.setitem(
        sys.modules,
        "FlagEmbedding",
        fake_module,
    )

    with pytest.raises(RuntimeError, match="Fallo temporal"):
        reranker_loader.get_reranker()

    modelo = reranker_loader.get_reranker()

    assert isinstance(modelo, RerankerModel)
    assert len(intentos) == 2
