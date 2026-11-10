
"""
Pruebas del cargador reutilizable del reranker del Agente 2.

Incluyen reutilización, configuración, recuperación de errores
y comportamiento ante llamadas concurrentes.
"""

import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor

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


def instalar_modelo_simulado(monkeypatch, clase_modelo):
    """Sustituye FlagEmbedding por un módulo simulado."""
    modulo = types.ModuleType("FlagEmbedding")
    modulo.FlagReranker = clase_modelo
    monkeypatch.setitem(sys.modules, "FlagEmbedding", modulo)


def test_get_reranker_utiliza_modelo_configurado(monkeypatch):
    """Comprueba que se utiliza el modelo configurado."""
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
    """Dos llamadas sucesivas reutilizan el modelo."""
    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append((model_name, use_fp16))

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    primero = reranker_loader.get_reranker()
    segundo = reranker_loader.get_reranker()

    assert primero is segundo
    assert isinstance(primero, RerankerModel)
    assert cargas == [(config.RERANKER_MODEL, False)]


def test_load_reranker_no_carga_hasta_primera_llamada(monkeypatch):
    """El modelo se inicializa únicamente cuando se solicita."""
    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append(model_name)

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    assert cargas == []

    reranker_loader.get_reranker()

    assert len(cargas) == 1


def test_load_reranker_propaga_error(monkeypatch):
    """Un error de carga se propaga al llamante."""

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            raise RuntimeError("Error simulado de carga")

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    with pytest.raises(RuntimeError, match="Error simulado de carga"):
        reranker_loader.get_reranker()


def test_load_reranker_permite_reintentar_tras_error(monkeypatch):
    """Un fallo temporal no queda almacenado en caché."""
    intentos = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            intentos.append(model_name)

            if len(intentos) == 1:
                raise RuntimeError("Fallo temporal")

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    with pytest.raises(RuntimeError, match="Fallo temporal"):
        reranker_loader.get_reranker()

    modelo = reranker_loader.get_reranker()

    assert isinstance(modelo, RerankerModel)
    assert len(intentos) == 2


def test_load_reranker_reutiliza_instancia_en_multiples_llamadas(monkeypatch):
    """Diez llamadas sucesivas reutilizan una única instancia."""
    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append(model_name)

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    instancias = [
        reranker_loader.get_reranker()
        for _ in range(10)
    ]

    assert all(modelo is instancias[0] for modelo in instancias)
    assert len(cargas) == 1


def test_load_reranker_carga_nuevo_modelo_si_cambia_configuracion(monkeypatch):
    """La caché distingue modelos con nombres diferentes."""
    cargas = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            cargas.append(model_name)

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    monkeypatch.setattr(config, "RERANKER_MODEL", "modelo-A")
    modelo_a = reranker_loader.get_reranker()

    monkeypatch.setattr(config, "RERANKER_MODEL", "modelo-B")
    modelo_b = reranker_loader.get_reranker()

    assert modelo_a is not modelo_b
    assert cargas == ["modelo-A", "modelo-B"]


def test_load_reranker_funciona_despues_de_recuperar_error(monkeypatch):
    """El modelo recuperado permite realizar predicciones."""
    intentos = []

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            intentos.append(model_name)

            if len(intentos) == 1:
                raise RuntimeError("Fallo temporal")

        def compute_score(self, pairs, normalize=False):
            return [0.95] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    with pytest.raises(RuntimeError, match="Fallo temporal"):
        reranker_loader.get_reranker()

    modelo = reranker_loader.get_reranker()

    puntuaciones = modelo.predict([
        ["problema con bomba", "La bomba auxiliar suministra presión."]
    ])

    assert puntuaciones == [0.95]
    assert len(intentos) == 2


def test_load_reranker_una_sola_carga_con_llamadas_concurrentes(monkeypatch):
    """
    Varias solicitudes simultáneas deben compartir una única
    inicialización del modelo.
    """
    numero_cargas = 0
    bloqueo_contador = threading.Lock()
    barrera_inicio = threading.Barrier(5)

    class FakeFlagReranker:
        def __init__(self, model_name, use_fp16):
            nonlocal numero_cargas

            with bloqueo_contador:
                numero_cargas += 1

            # Simula una carga suficientemente lenta para
            # que coincidan varias solicitudes.
            time.sleep(0.15)

        def compute_score(self, pairs, normalize=False):
            return [0.9] * len(pairs)

    instalar_modelo_simulado(monkeypatch, FakeFlagReranker)

    def obtener_modelo():
        barrera_inicio.wait(timeout=5)
        return reranker_loader.get_reranker()

    with ThreadPoolExecutor(max_workers=5) as ejecutor:
        modelos = list(ejecutor.map(
            lambda _: obtener_modelo(),
            range(5),
        ))

    assert numero_cargas == 1
    assert all(modelo is modelos[0] for modelo in modelos)
