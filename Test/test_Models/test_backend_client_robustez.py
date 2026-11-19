"""Timeouts, secreto del token y uso síncrono del cliente CTR-002.

Mejoras recomendadas en la revisión de la PR #32:

* Timeouts separados de conexión y lectura.
* El token de servicio no aparece en mensajes de error, logs ni ``repr``.
* ``requests`` es síncrono: el servicio no debe llamarlo desde el bucle
  asíncrono, así que sus endpoints son funciones normales que FastAPI ejecuta
  en su pool de hilos.
"""

import inspect

import pytest
import requests

from Agents.Agent_2.src.clients.backend import BackendAPIClient
from Agents.Agent_2.src.core import config
from Agents.Agent_2.src.core.config import Agent2Settings
from Agents.Agent_2.src.core.errors import BackendRequestError

TOKEN = "token-secreto-de-servicio-123"


class SesionQueFalla:
    """Sesión cuyo error de red incluye la cabecera, como peor caso."""

    def __init__(self, error_cls=requests.RequestException):
        self.error_cls = error_cls
        self.llamadas = []

    def _fallar(self, url, **kwargs):
        self.llamadas.append(kwargs)
        cabeceras = kwargs.get("headers") or {}
        raise self.error_cls(f"fallo hacia {url} con {cabeceras}")

    def post(self, url, **kwargs):
        self._fallar(url, **kwargs)

    def get(self, url, **kwargs):
        self._fallar(url, **kwargs)


def cliente(sesion, **kwargs):
    return BackendAPIClient(
        "http://backend.test", "BAAI/bge-m3", session=sesion, token=TOKEN, **kwargs
    )


# --- Timeouts ---------------------------------------------------------------


def test_timeout_unico_se_conserva_si_no_hay_conexion():
    assert cliente(SesionQueFalla(), timeout=2).timeout == 2


def test_timeouts_de_conexion_y_lectura_separados():
    sesion = SesionQueFalla()
    backend = cliente(sesion, timeout=8, connect_timeout=1.5)

    with pytest.raises(BackendRequestError):
        backend.search_vector([0.1] * config.EMBEDDING_DIMENSION)

    assert backend.timeout == (1.5, 8)
    assert sesion.llamadas[0]["timeout"] == (1.5, 8)


def test_connect_timeout_configurable_por_entorno():
    settings = Agent2Settings.from_env(
        {"AGENT2_CONNECT_TIMEOUT": "2.5", "AGENT2_REQUEST_TIMEOUT": "9"}
    )
    assert settings.connect_timeout == 2.5
    assert settings.request_timeout == 9.0
    assert Agent2Settings.from_env({}).connect_timeout == config.DEFAULT_CONNECT_TIMEOUT


@pytest.mark.parametrize("valor", ["0", "-1", "nan", "abc"])
def test_connect_timeout_invalido_se_rechaza(valor):
    with pytest.raises(ValueError, match="AGENT2_CONNECT_TIMEOUT"):
        Agent2Settings.from_env({"AGENT2_CONNECT_TIMEOUT": valor})


def test_pipeline_y_runtime_usan_timeouts_separados(monkeypatch):
    from Agents.Agent_2.src.services import runtime
    from Agents.Agent_2.src.services.pipeline import Agent2Pipeline

    esperado = (config.CONNECT_TIMEOUT, config.REQUEST_TIMEOUT)
    assert Agent2Pipeline().backend_client.timeout == esperado

    creados = []

    class ClienteCapturado(BackendAPIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            creados.append(self)

        def get_info(self):
            raise BackendRequestError("indice_no_disponible", "sin índice")

    monkeypatch.setattr(runtime, "BackendAPIClient", ClienteCapturado)
    runtime.check_readiness(load_models=False)
    assert creados[0].timeout == esperado


# --- Token ------------------------------------------------------------------


LLAMADAS = {
    "search_vector": lambda b: b.search_vector([0.1] * config.EMBEDDING_DIMENSION),
    "search_lexical": lambda b: b.search_lexical("par de apriete"),
    "get_chunk": lambda b: b.get_chunk("c1"),
    "get_catalogo": lambda b: b.get_catalogo("codigos"),
    "get_info": lambda b: b.get_info(),
}


@pytest.mark.parametrize("error_cls", [requests.RequestException, requests.ConnectionError, requests.Timeout])
@pytest.mark.parametrize("nombre", LLAMADAS)
def test_el_token_no_aparece_en_errores(nombre, error_cls):
    sesion = SesionQueFalla(error_cls)

    with pytest.raises(BackendRequestError) as info:
        LLAMADAS[nombre](cliente(sesion))

    # La petición sí lleva el Bearer...
    assert sesion.llamadas[0]["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    # ...pero el mensaje que llega al Agente 1 y a los logs no.
    assert TOKEN not in str(info.value)
    assert TOKEN not in getattr(info.value, "mensaje", "")


def test_repr_del_cliente_oculta_el_token():
    texto = repr(cliente(SesionQueFalla()))

    assert TOKEN not in texto
    assert "token='***'" in texto or "token=***" in texto


# --- Uso síncrono desde el servicio -----------------------------------------


def test_endpoints_del_servicio_no_bloquean_el_bucle_asincrono():
    service = pytest.importorskip("Agents.service")

    # Funciones normales: FastAPI las ejecuta en su pool de hilos, así que
    # las llamadas síncronas del Agente 2 (requests, modelos) no bloquean el
    # bucle de eventos. Convertirlas en ``async def`` lo rompería.
    for endpoint in (service.query, service.health):
        assert not inspect.iscoroutinefunction(endpoint), endpoint.__name__
