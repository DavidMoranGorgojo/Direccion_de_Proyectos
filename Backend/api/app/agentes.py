"""Cliente de la pasarela hacia Agentes.

La consulta de Frontend (CTR-001) se reenvía a Agentes TAL CUAL: los mismos bytes
que llegan. Backend solo añade cabeceras (trace y usuario), nunca toca el cuerpo.
La respuesta de Agentes también se devuelve a Frontend sin cambios.

Modos (variable AGENTES_MODO, ver config.py):
  - "real":     POST {AGENTES_URL}{AGENTES_RUTA} con el cuerpo original.
  - "simulado": respuesta de prueba con la forma del contrato, mientras Agentes no esté listo.
"""
import json
import re
import uuid
from dataclasses import dataclass

import httpx

from app import config

# Para los tests: se puede sustituir por un httpx.MockTransport.
_transport: httpx.BaseTransport | None = None


class AgentesNoDisponible(Exception):
    """No se pudo conectar con Agentes."""


class AgentesTiempoAgotado(Exception):
    """Agentes no respondió a tiempo."""


class AgentesRespuestaInvalida(Exception):
    """Agentes respondió con un error HTTP o con algo que no es JSON."""

    def __init__(self, mensaje: str, status: int | None = None):
        super().__init__(mensaje)
        self.status = status


@dataclass
class RespuestaAgentes:
    datos: dict
    simulada: bool


def nuevo_trace_id() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def modo() -> str:
    return config.AGENTES_MODO


def reenviar(cuerpo: bytes, *, trace_id: str, usuario_id: int) -> RespuestaAgentes:
    """Reenvía `cuerpo` (bytes originales de Frontend) a Agentes y devuelve su JSON."""
    if modo() == "simulado":
        return RespuestaAgentes(datos=respuesta_simulada(json.loads(cuerpo), trace_id), simulada=True)
    return RespuestaAgentes(datos=_reenviar_real(cuerpo, trace_id=trace_id, usuario_id=usuario_id), simulada=False)


def _reenviar_real(cuerpo: bytes, *, trace_id: str, usuario_id: int) -> dict:
    if not config.AGENTES_URL:
        raise AgentesNoDisponible("AGENTES_URL no está configurada")
    cabeceras = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Trace-Id": trace_id,
        "X-Usuario-Id": str(usuario_id),
    }
    try:
        with httpx.Client(timeout=config.AGENTES_TIMEOUT_S, transport=_transport) as cliente:
            r = cliente.post(f"{config.AGENTES_URL}{config.AGENTES_RUTA}", content=cuerpo, headers=cabeceras)
    except httpx.TimeoutException as e:
        raise AgentesTiempoAgotado(str(e)) from e
    except httpx.HTTPError as e:
        raise AgentesNoDisponible(str(e)) from e

    if r.status_code >= 400:
        raise AgentesRespuestaInvalida(f"Agentes respondió {r.status_code}", status=r.status_code)
    try:
        datos = r.json()
    except ValueError as e:
        raise AgentesRespuestaInvalida("La respuesta de Agentes no es JSON", status=r.status_code) from e
    if not isinstance(datos, dict):
        raise AgentesRespuestaInvalida("La respuesta de Agentes no es un objeto JSON", status=r.status_code)
    return datos


# ---------------------------------------------------------------- modo simulado
# Forma de respuesta PROVISIONAL (revisar con el contrato definitivo de Agentes):
#   {"estado": "respondida" | "aclaracion" | "rechazo",
#    "trace_id": "...", "respuesta": "...",
#    "fuentes": [{"fragmento_id", "documento", "pagina", "componente", "extracto"}],
#    "simulada": true}
# "aclaracion" y "rechazo" corresponden a los estados del Agente 1 (agente1_core.py).

_FUERA_DE_AMBITO = ("receta", "futbol", "fútbol", "chiste", "política", "politica", "horóscopo", "horoscopo")

_FUENTES_EJEMPLO = [
    {
        "fragmento_id": "sim-0001",
        "documento": "Manual de taller (simulado)",
        "pagina": 42,
        "componente": "motor",
        "extracto": "Fragmento de ejemplo devuelto por la pasarela en modo simulado.",
    },
    {
        "fragmento_id": "sim-0002",
        "documento": "Ficha técnica (simulada)",
        "pagina": 7,
        "componente": "motor",
        "extracto": "Segundo fragmento de ejemplo para probar la lista de fuentes.",
    },
]


def texto_de_consulta(datos: dict) -> str:
    """Texto de la pregunta en el cuerpo de Frontend (acepta los nombres de campo previstos)."""
    for campo in ("pregunta", "consulta", "mensaje", "texto"):
        valor = datos.get(campo)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def respuesta_simulada(datos: dict, trace_id: str) -> dict:
    texto = texto_de_consulta(datos)
    minus = texto.lower()
    base = {"trace_id": trace_id, "simulada": True}

    if any(p in minus for p in _FUERA_DE_AMBITO):
        return {**base, "estado": "rechazo", "fuentes": [],
                "respuesta": "Lo siento, solo puedo resolver dudas técnicas sobre automoción y sus manuales."}

    if len(re.findall(r"\w+", texto)) < 3:
        return {**base, "estado": "aclaracion", "fuentes": [],
                "respuesta": "¿Puedes darme más detalles? Por ejemplo, el modelo del vehículo y el componente."}

    return {**base, "estado": "respondida", "fuentes": [dict(f) for f in _FUENTES_EJEMPLO],
            "respuesta": f"[Respuesta simulada] Esta sería la respuesta de Agentes a: «{texto}»."}
