"""Entorno común de las pruebas del Agente 2.

Las pruebas usan los catálogos sintéticos de ``Agents/Agent_2/fixtures``; en
producción el Agente 2 exige los catálogos reales del Backend. Cada prueba
puede sobrescribir ``ARSOFT_ENV`` con ``monkeypatch`` si necesita otro modo.

Se fija al cargar el módulo y no con un fixture ``autouse`` de ``monkeypatch``
para no alterar el orden de desmontaje de los fixtures de cada fichero.
"""

import os

os.environ.setdefault("ARSOFT_ENV", "test")
