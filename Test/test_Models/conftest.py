"""Entorno común de las pruebas del Agente 2.

Las pruebas usan los catálogos sintéticos de ``Agents/Agent_2/fixtures``; en
producción el Agente 2 exige los catálogos reales del Backend. Cada prueba
puede sobrescribir ``ARSOFT_ENV`` con ``monkeypatch`` si necesita otro modo.

Se fija al cargar el módulo y no con un fixture ``autouse`` de ``monkeypatch``
para no alterar el orden de desmontaje de los fixtures de cada fichero.
"""

import os

os.environ.setdefault("ARSOFT_ENV", "test")

from pathlib import Path

import pytest

_CONTRATO = {"test_contrato_ctr004_agente1.py", "test_calibracion_28.py"}


def pytest_collection_modifyitems(config, items):
    """Marca las pruebas de esta carpeta para poder filtrarlas con ``-m``.

    - ``agente2``: todas las de ``Test/test_Models``.
    - ``contrato``: contrato CTR-004 con el Agente 1 y calibración A2-08.
    - ``modelo_real``: las que solo corren con ``RUN_REAL_RERANKER_TEST=1``.
    """

    carpeta = Path(__file__).resolve().parent
    for item in items:
        ruta = Path(str(item.fspath)).resolve()
        if carpeta not in ruta.parents:
            continue
        item.add_marker(pytest.mark.agente2)
        if ruta.name in _CONTRATO:
            item.add_marker(pytest.mark.contrato)
        # skipif recibe la condición ya evaluada; se reconoce por su motivo.
        if any("modelo real" in m.kwargs.get("reason", "") for m in item.iter_markers("skipif")):
            item.add_marker(pytest.mark.modelo_real)
