"""Límite de consultas por usuario para POST /consulta (429 demasiadas_consultas).
También limita POST /valoracion (ámbito aparte, ARSOFT_VALORACIONES_POR_MINUTO, 60 por defecto).

Ventana deslizante en memoria: como mucho ARSOFT_CONSULTAS_POR_MINUTO consultas (20 por defecto) en
60 segundos por usuario. Protege a Agentes, que atiende cada consulta con el LLM. Con varias réplicas
del backend habría que llevarlo a la base.
"""

import os
import threading
import time
from collections import deque

VENTANA_S = 60
POR_DEFECTO = 20
POR_DEFECTO_VALORACIONES = 60
VARIABLES = {"consulta": ("ARSOFT_CONSULTAS_POR_MINUTO", POR_DEFECTO),
             "valoracion": ("ARSOFT_VALORACIONES_POR_MINUTO", POR_DEFECTO_VALORACIONES)}
_consultas: dict[tuple, deque] = {}
_candado = threading.Lock()


def maximo(ambito: str = "consulta") -> int:
    variable, por_defecto = VARIABLES[ambito]
    try:
        valor = int(os.getenv(variable, ""))
    except ValueError:
        return por_defecto
    return valor if valor > 0 else por_defecto


def admitir(usuario_id: int, ambito: str = "consulta") -> int:
    """Anota la consulta si cabe y devuelve 0; si no cabe, devuelve los segundos que faltan."""
    ahora = time.monotonic()
    with _candado:
        for uid in [u for u, q in _consultas.items() if not q or q[-1] < ahora - VENTANA_S]:
            del _consultas[uid]  # usuarios sin consultas recientes: no ocupan memoria
        recientes = _consultas.setdefault((ambito, usuario_id), deque())
        while recientes and recientes[0] < ahora - VENTANA_S:
            recientes.popleft()
        if len(recientes) >= maximo(ambito):
            return max(1, int(recientes[0] + VENTANA_S - ahora) + 1)
        recientes.append(ahora)
        return 0


def reiniciar() -> None:
    with _candado:
        _consultas.clear()
