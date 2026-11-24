"""Entorno común de las pruebas del Agente 2.

Las pruebas usan los catálogos sintéticos de ``Agents/Agent_2/fixtures``; en
producción el Agente 2 exige los catálogos reales del Backend. Cada prueba
puede sobrescribir ``ARSOFT_ENV`` con ``monkeypatch`` si necesita otro modo.

Se fija al cargar el módulo y no con un fixture ``autouse`` de ``monkeypatch``
para no alterar el orden de desmontaje de los fixtures de cada fichero.
"""

import os

os.environ.setdefault("ARSOFT_ENV", "test")

import pytest

_CONTRATO = {"test_contrato_ctr004_agente1.py", "test_calibracion_28.py"}


def pytest_collection_modifyitems(config, items):
    """Marca las pruebas de esta carpeta para poder filtrarlas con ``-m``.

    - ``agente2``: todas las de ``Test/test_Models``.
    - ``contrato``: contrato CTR-004 con el Agente 1 y calibración A2-08.
    - ``modelo_real``: las que solo corren con ``RUN_REAL_RERANKER_TEST=1``.
    """

    carpeta = __file__.rsplit("conftest.py", 1)[0]
    for item in items:
        if not str(item.fspath).startswith(carpeta):
            continue
        item.add_marker(pytest.mark.agente2)
        if item.fspath.basename in _CONTRATO:
            item.add_marker(pytest.mark.contrato)
        for marca in item.iter_markers("skipif"):
            if "RUN_REAL_RERANKER_TEST" in str(marca.args) or "modelo real" in marca.kwargs.get("reason", ""):
                item.add_marker(pytest.mark.modelo_real)
