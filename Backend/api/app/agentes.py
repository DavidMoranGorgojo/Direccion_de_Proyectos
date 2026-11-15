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
# Forma de respuesta según el ejemplo orientativo de la Plantilla A (contratos de interfaz),
# a falta del contrato CTR firmado:
#   {"estado": "respuesta" | "sin_evidencia" | "aclaracion",
#    "texto": "...", "fuentes": [...], "trace_id": "...", "simulada": true}
#
# Fuentes: según ARSOFT-MEM-003 §6, cada fragmento lleva obligatoriamente
# documento, seccion, pagina y estado; se añaden id_fragmento y version_documento
# de la estructura de metadatos de pgvector.
# Aclaración: según ARSOFT-MEM-003 §4, si la respuesta depende de la versión del
# vehículo (V1.0, V1.1, V2.0) y el usuario no la indica, el estado es "aclaracion".

_FUERA_DE_AMBITO = ("receta", "futbol", "fútbol", "chiste", "política", "politica", "horóscopo", "horoscopo")

# Temas cuya respuesta cambia según la versión (ARSOFT-MEM-003 §4)
_DEPENDE_DE_VERSION = ("htm-0142", "bomba auxiliar", "cmp-02", "corriente", "ptc", "calentador",
                       "cmp-15", "sensor de temperatura de batería", "sensor de temperatura de bateria",
                       "sensor de presión", "sensor de presion")
_VERSION = re.compile(r"\bv\s?(1\.0|1\.1|2\.0)\b|\bversi[oó]n\s+(1\.0|1\.1|2\.0)\b", re.IGNORECASE)


def _fuente(id_fragmento, documento, version, seccion, pagina, extracto):
    return {"id_fragmento": id_fragmento, "documento": documento, "version_documento": version,
            "seccion": seccion, "pagina": pagina, "estado": "vigente", "extracto": extracto}


# Respuestas de ejemplo con datos reales del corpus ThermoDrive HTM-240
_CASOS = [
    (("refrigerante",),
     "El refrigerante se sustituye cada 60.000 km o 48 meses, lo que antes ocurra (MNT-001 v1.1, "
     "corregido por el boletín BOL-006).",
     [_fuente("HTM240-MNT-001_p2_refrigerante", "HTM240-MNT-001", "1.1", "Plan de mantenimiento", 2,
              "Sustitución de refrigerante: 60.000 km o 48 meses."),
      _fuente("HTM240-BOL-006_p1_correccion", "HTM240-BOL-006", "1.0", "Corrección", 1,
              "Corrige la errata del intervalo de refrigerante a 60.000 km o 48 meses.")]),
    (("htm-0142",),
     "En V2.0, el código HTM-0142 indica un fallo del sensor combinado CMP-18 (BOL-003). "
     "En V1.0 y V1.1 significa que el precalentamiento de batería no completó su objetivo.",
     [_fuente("HTM240-DTC-001_p3_htm0142", "HTM240-DTC-001", "1.0", "Códigos TCU", 3,
              "HTM-0142: precalentamiento de batería no completado."),
      _fuente("HTM240-BOL-003_p1_cambio", "HTM240-BOL-003", "1.0", "Cambio de significado", 1,
              "En V2.0, HTM-0142 pasa a indicar fallo del sensor combinado CMP-18.")]),
    (("bomba auxiliar", "cmp-02", "corriente"),
     "La corriente nominal de la bomba auxiliar CMP-02 es de 3-6 A a 12 V en V1.1 y V2.0 (BOL-002). "
     "En V1.0 sin actualizar se mantiene en 3-5 A.",
     [_fuente("HTM240-PRC-003_p1_pasos", "HTM240-PRC-003", "2.0", "Pasos de verificación", 1,
              "Corriente nominal CMP-02: 3-6 A a 12 V."),
      _fuente("HTM240-BOL-002_p1_corriente", "HTM240-BOL-002", "1.0", "Modificación", 1,
              "Actualiza la corriente nominal de la bomba CMP-02 a 3-6 A a 12 V.")]),
]

_FUENTES_GENERICAS = [
    _fuente("HTM240-SIM-001_p1", "HTM240-SIM-001", "1.0", "Fragmento simulado", 1,
            "Fragmento de ejemplo devuelto por la pasarela en modo simulado."),
]


def texto_de_consulta(datos: dict) -> str:
    """Texto de la pregunta en el cuerpo de Frontend (acepta los nombres de campo previstos)."""
    for campo in ("pregunta", "consulta", "mensaje", "texto"):
        valor = datos.get(campo)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def _version_indicada(datos: dict, texto: str) -> bool:
    version = datos.get("version_vehiculo")
    if isinstance(version, str) and version.strip():
        return True
    return bool(_VERSION.search(texto))


def respuesta_simulada(datos: dict, trace_id: str) -> dict:
    texto = texto_de_consulta(datos)
    minus = texto.lower()
    base = {"trace_id": trace_id, "simulada": True}

    if any(p in minus for p in _FUERA_DE_AMBITO):
        return {**base, "estado": "sin_evidencia", "fuentes": [],
                "texto": "No he encontrado información sobre esto en la documentación. Solo puedo resolver dudas técnicas sobre el sistema ThermoDrive HTM-240 "
                             "y su documentación."}

    if len(re.findall(r"\w+", texto)) < 3:
        return {**base, "estado": "aclaracion", "fuentes": [],
                "texto": "¿Puedes darme más detalles? Por ejemplo, el código de avería o el componente."}

    if any(p in minus for p in _DEPENDE_DE_VERSION) and not _version_indicada(datos, texto):
        return {**base, "estado": "aclaracion", "fuentes": [],
                "texto": "La respuesta depende de la versión del sistema. ¿Tu vehículo es V1.0, V1.1 o V2.0?"}

    for claves, respuesta, fuentes in _CASOS:
        if any(c in minus for c in claves):
            return {**base, "estado": "respuesta", "texto": respuesta,
                    "fuentes": [dict(f) for f in fuentes]}

    return {**base, "estado": "respuesta", "fuentes": [dict(f) for f in _FUENTES_GENERICAS],
            "texto": f"[Respuesta simulada] Esta sería la respuesta de Agentes a: «{texto}»."}
