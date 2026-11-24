#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT Reto Automoción — Conector Clúster Legio (GVIS - Universidad de León)
=============================================================================
Cliente de inferencia LLM para el Agente 1 a través del túnel SSH con Legio.

Condiciones y limitaciones técnicas:
  1. Base URL estándar OpenAI: http://localhost:4000/v1 (endpoint /chat/completions).
  2. Autenticación: API Key leída desde la variable LLM_KEY o desde el archivo
     ~/.config/llm-gvis/api_key (Windows: %USERPROFILE%\\.config\\llm-gvis\\api_key).
     NUNCA se hardcodea, no se expone en logs ni se incluye en cadenas __repr__.
  3. Roles de modelo obligatorios (abstracción agnóstica de modelo):
     - 'rapido': normalización técnica, extracción de intención y filtros CTR-004.
     - 'potente': razonamiento, redacción técnica con citas obligatorias [chunk_id]
                  y apoyo a la verificación extractiva.
     - 'texto': PROHIBIDO (no soporta herramientas ni razonamiento).
     - Nombres concretos de modelo (ej. 'qwen2.5:14b', 'qwen3.6-27b', 'gpt-oss-20b'):
       PROHIBIDOS (el clúster exige abstracción por roles dinámicos).
  4. Parámetros estrictos:
     - temperature=0.0
     - max_tokens=512 (evita truncado de JSON y respuestas)
     - stream=False
     - timeout configurable (30-60 s, por defecto 45 s)
  5. Manejo explícito de excepciones de red y clúster:
     - TunelClusterError: túnel SSH cerrado en localhost:4000.
     - AutenticacionClusterError: error HTTP 401/403.
     - TimeoutClusterError: tiempo límite excedido por saturación de GPU en el nodo.
  6. Precauciones de recursos del clúster Legio:
     - El nodo 'legio2' es de acceso con cuota estricta (4 GiB RAM y 1 CPU por usuario).
       Este conector NO ejecuta procesos pesados ni almacenamiento en el clúster.
     - Las GPUs son compartidas: no lanzar miles de peticiones automáticas sin control.
=============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Agente1.ClienteCluster")

# Intento de importar el SDK oficial de OpenAI
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Constantes de configuración por defecto
DEFAULT_BASE_URL = "http://localhost:4000/v1"
DEFAULT_TIMEOUT_S = 45.0
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_TOKENS = 512

# Roles contractuales admitidos
ROL_RAPIDO = "rapido"
ROL_POTENTE = "potente"
ROLES_VALIDOS = frozenset({ROL_RAPIDO, ROL_POTENTE})
ROLES_PROHIBIDOS = frozenset({"texto"})

# Nombres concretos prohibidos para forzar el uso de abstracción por roles
NOMBRES_CONCRETOS_PROHIBIDOS = frozenset({
    "qwen2.5:14b", "qwen2.5:3b", "qwen2.5:72b", "qwen3.6-27b", "gpt-oss-20b",
    "qwen2.5-14b", "qwen2.5-3b", "qwen2.5-72b", "llama3", "llama-3", "llama-3.1",
})


# =============================================================================
# EXCEPCIONES ESPECÍFICAS DEL CLÚSTER
# =============================================================================

class ClusterLLMError(Exception):
    """Excepción base para fallos relacionados con la conexión al clúster Legio."""
    pass


class TunelClusterError(ClusterLLMError):
    """El túnel SSH a localhost:4000 no está disponible o la conexión fue rechazada."""
    pass


class AutenticacionClusterError(ClusterLLMError):
    """Error de autenticación con el servicio LLM del clúster (HTTP 401 o 403)."""
    pass


class TimeoutClusterError(ClusterLLMError):
    """La llamada al clúster ha excedido el tiempo límite configurado."""
    pass


class ModeloNoValidoError(ClusterLLMError):
    """Se solicitó un rol o nombre de modelo no permitido (ej. 'texto' o nombres fijos)."""
    pass


# =============================================================================
# RESOLUCIÓN SEGURA DE API KEY
# =============================================================================

def resolver_api_key(ruta_archivo: Optional[Path | str] = None) -> Optional[str]:
    """
    Resuelve la API Key del clúster Legio de forma segura en tiempo de ejecución:
      1. Variable de entorno LLM_KEY.
      2. Archivo en ruta especificada o por defecto:
         - Windows: %USERPROFILE%\\.config\\llm-gvis\\api_key
         - Linux/macOS: ~/.config/llm-gvis/api_key

    NUNCA imprime ni registra en logs el contenido de la clave.
    Devuelve la clave sin espacios si se encuentra, o None si no existe.
    """
    # 1. Variable de entorno
    env_key = os.environ.get("LLM_KEY", "").strip()
    if env_key:
        return env_key

    # 2. Archivo de configuración
    if ruta_archivo is not None:
        candidatos = [Path(ruta_archivo)]
    else:
        candidatos = []
        try:
            candidatos.append(Path.home() / ".config" / "llm-gvis" / "api_key")
        except (RuntimeError, OSError):
            pass

        # En Windows verificar también USERPROFILE directamente por si diverge o Path.home() falla
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            candidatos.append(Path(userprofile) / ".config" / "llm-gvis" / "api_key")

    for path in candidatos:
        try:
            if path.is_file():
                with open(path, "r", encoding="utf-8") as f:
                    contenido = f.read().strip()
                    if contenido:
                        return contenido
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("No se pudo leer la clave desde %s (%s).", path, type(exc).__name__)

    return None


def verificar_puerto_abierto(host: str = "127.0.0.1", puerto: int = 4000, timeout_s: float = 1.0) -> bool:
    """Comprueba de forma rápida si el socket local del túnel SSH está escuchando."""
    try:
        with socket.create_connection((host, puerto), timeout=timeout_s):
            return True
    except (OSError, socket.error):
        return False


# =============================================================================
# CLIENTE LLM CLÚSTER LEGIO
# =============================================================================

class ClienteClusterLegio:
    """
    Cliente modular y resiliente para el servicio de LLMs del clúster Legio (GVIS).
    
    Compatible con la API de chat/completions de OpenAI, configurable para operar
    mediante el SDK oficial de OpenAI o mediante transporte HTTP nativo (urllib).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_s: Optional[float] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        modelo_rapido: Optional[str] = None,
        modelo_potente: Optional[str] = None,
    ):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # Timeout bounded entre 5 y 120 segundos
        t_raw = timeout_s if timeout_s is not None else os.environ.get("LLM_TIMEOUT_S")
        self.timeout_s = float(t_raw) if t_raw is not None else DEFAULT_TIMEOUT_S
        if self.timeout_s <= 0:
            raise ValueError("timeout_s debe ser un número positivo")

        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)

        # Mapeo de roles a nombres solicitados (por defecto 'rapido' y 'potente')
        self.modelo_rapido = (modelo_rapido or os.environ.get("LLM_ROL_RAPIDO") or ROL_RAPIDO).strip()
        self.modelo_potente = (modelo_potente or os.environ.get("LLM_ROL_POTENTE") or ROL_POTENTE).strip()

        # Resolución segura de clave privada
        self._api_key = api_key or resolver_api_key()

        # Instanciación del cliente SDK si está disponible
        self._sdk_client: Optional[OpenAI] = None
        if OpenAI and self._api_key:
            try:
                self._sdk_client = OpenAI(
                    base_url=self.base_url,
                    api_key=self._api_key,
                    timeout=self.timeout_s,
                    max_retries=0,  # Los reintentos se controlan explícitamente en el pipeline
                )
            except Exception as exc:
                logger.debug("No se pudo inicializar OpenAI SDK: %s", exc)
                self._sdk_client = None

    def __repr__(self) -> str:
        # NUNCA revelar la API key en representaciones en consola o logs
        tiene_key = bool(self._api_key)
        return (
            f"<ClienteClusterLegio base_url='{self.base_url}' "
            f"key_configurada={tiene_key} timeout={self.timeout_s}s "
            f"rapido='{self.modelo_rapido}' potente='{self.modelo_potente}'>"
        )

    def tiene_credenciales(self) -> bool:
        """Indica si el cliente dispone de API Key configurada."""
        return bool(self._api_key)

    def resolver_nombre_modelo(self, rol: str) -> str:
        """
        Valida el rol solicitado y devuelve el identificador de modelo configurado.
        
        Roles válidos:
          - 'rapido': para tareas ligeras (extracción de intención, preprocesamiento).
          - 'potente': para redacción técnica, citas y verificación extractiva.
        """
        rol_limpio = (rol or "").strip().lower()

        if rol_limpio in ROLES_PROHIBIDOS:
            raise ModeloNoValidoError(
                f"El rol '{rol_limpio}' no está permitido en el agente (no soporta herramientas "
                "ni capacidades de razonamiento técnico). Utiliza 'rapido' o 'potente'."
            )

        if rol_limpio in NOMBRES_CONCRETOS_PROHIBIDOS:
            raise ModeloNoValidoError(
                f"No se permite el uso de nombres concretos de modelo ('{rol_limpio}') en el clúster Legio. "
                "El clúster exige abstracción por roles: utiliza 'rapido' o 'potente'."
            )

        if rol_limpio == ROL_RAPIDO:
            return self.modelo_rapido
        elif rol_limpio == ROL_POTENTE:
            return self.modelo_potente
        elif rol_limpio in (self.modelo_rapido.lower(), self.modelo_potente.lower()):
            return self.modelo_rapido if rol_limpio == self.modelo_rapido.lower() else self.modelo_potente
        else:
            raise ModeloNoValidoError(
                f"Rol '{rol_limpio}' no reconocido. Los únicos roles admitidos para el clúster son 'rapido' y 'potente'."
            )

    def consultar(
        self,
        mensajes: List[Dict[str, str]],
        rol: str = ROL_RAPIDO,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> Optional[str]:
        """
        Envía una petición al endpoint de chat completions del clúster Legio.
        
        Args:
            mensajes: Lista de turnos [{"role": "system"|"user"|"assistant", "content": "..."}]
            rol: 'rapido' o 'potente'
            temperature: opcional (default 0.0)
            max_tokens: opcional (default 512)
            timeout_s: tiempo límite para esta petición concreta

        Returns:
            Texto devuelto por el modelo, o None si hubo error controlado.
        """
        if not self._api_key:
            raise AutenticacionClusterError(
                "No se encontró la API Key del clúster Legio. "
                "Configura la variable de entorno LLM_KEY o crea el archivo "
                "~/.config/llm-gvis/api_key con tu token."
            )

        modelo_efectivo = self.resolver_nombre_modelo(rol)
        temp_efectiva = self.temperature if temperature is None else float(temperature)
        tokens_efectivos = self.max_tokens if max_tokens is None else int(max_tokens)
        timeout_efectivo = self.timeout_s if timeout_s is None else float(timeout_s)

        t_inicio = time.monotonic()

        # Intento 1: SDK de OpenAI si está operativo
        if self._sdk_client:
            try:
                logger.debug("Invocando clúster Legio vía OpenAI SDK [rol: %s, modelo: %s]", rol, modelo_efectivo)
                resp = self._sdk_client.chat.completions.create(
                    model=modelo_efectivo,
                    messages=mensajes,
                    temperature=temp_efectiva,
                    max_tokens=tokens_efectivos,
                    stream=False,
                    timeout=timeout_efectivo,
                )
                contenido = resp.choices[0].message.content
                if isinstance(contenido, str) and contenido.strip():
                    duracion_ms = (time.monotonic() - t_inicio) * 1000
                    logger.info("Respuesta clúster [rol: %s, latencia: %.1f ms]", rol, duracion_ms)
                    return contenido.strip()
            except Exception as exc:
                self._gestionar_excepcion_red(exc, host_puerto="localhost:4000")

        # Intento 2: Fallback directo HTTP nativo (urllib)
        return self._consultar_http_nativo(
            mensajes=mensajes,
            modelo=modelo_efectivo,
            temperature=temp_efectiva,
            max_tokens=tokens_efectivos,
            timeout_s=timeout_efectivo,
            rol=rol,
            t_inicio=t_inicio,
        )

    def _consultar_http_nativo(
        self,
        mensajes: List[Dict[str, str]],
        modelo: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        rol: str,
        t_inicio: float,
    ) -> Optional[str]:
        """Transporte HTTP nativo usando urllib.request con autenticación Bearer."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": modelo,
            "messages": mensajes,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ARSOFT-Agente1-LegioClient/1.0",
        }

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw_body = resp.read().decode("utf-8")
                datos = json.loads(raw_body)
                choices = datos.get("choices", [])
                if choices and "message" in choices[0]:
                    texto = choices[0]["message"].get("content", "")
                    duracion_ms = (time.monotonic() - t_inicio) * 1000
                    logger.info("Respuesta clúster HTTP nativo [rol: %s, latencia: %.1f ms]", rol, duracion_ms)
                    return texto.strip() if isinstance(texto, str) else None
        except urllib.error.HTTPError as http_err:
            if http_err.code in (401, 403):
                raise AutenticacionClusterError(
                    f"Fallo de autenticación con el clúster Legio (HTTP {http_err.code}). "
                    "Verifica la clave en LLM_KEY o en ~/.config/llm-gvis/api_key."
                ) from http_err
            elif http_err.code == 404:
                raise ClusterLLMError(
                    f"Endpoint no encontrado (HTTP 404 en {url}). "
                    "Verifica que el servicio esté escuchando en /v1/chat/completions."
                ) from http_err
            else:
                logger.error("HTTP error del clúster Legio (código %s).", http_err.code)
                return None
        except (urllib.error.URLError, ConnectionRefusedError, socket.timeout, TimeoutError) as net_err:
            self._gestionar_excepcion_red(net_err, host_puerto="localhost:4000")

        return None

    def _gestionar_excepcion_red(self, exc: Exception, host_puerto: str = "localhost:4000"):
        """Traduce errores crudos de socket o biblioteca a excepciones legibles del sistema."""
        msg = str(exc)
        # Conexión rechazada (túnel cerrado)
        if isinstance(exc, (ConnectionRefusedError, urllib.error.URLError)) and (
            "10061" in msg or "refused" in msg.lower() or "connection closed" in msg.lower()
        ):
            raise TunelClusterError(
                f"No se pudo conectar a {self.base_url}. El túnel SSH a Legio no está activo en {host_puerto}.\n"
                "Para activarlo, ejecuta en una terminal:\n"
                "  ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97\n"
                "(Asegúrate de tener activa la VPN de la ULE si estás fuera del campus universitario)."
            ) from exc

        # Timeout de red
        if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in msg.lower():
            raise TimeoutClusterError(
                f"La llamada al clúster excedió el tiempo límite ({self.timeout_s} s). "
                "Las GPUs pueden estar bajo alta demanda o procesando un contexto largo."
            ) from exc

        # Error 401 / 403
        if "401" in msg or "403" in msg or "authentication" in msg.lower() or "unauthorized" in msg.lower():
            raise AutenticacionClusterError(
                "Fallo de autenticación con el clúster Legio (401/403). "
                "Comprueba la validez de tu API key."
            ) from exc

        logger.warning("Fallo durante la comunicación con el clúster Legio (%s).", type(exc).__name__)

    def comprobar_estado(self) -> Dict[str, Any]:
        """
        Ejecuta un diagnóstico completo y seguro del conector sin exponer credenciales:
          1. Detección de API Key.
          2. Detección del puerto local 4000 (túnel SSH).
          3. Prueba de llamada mínima con rol 'rapido'.
        """
        resultado: Dict[str, Any] = {
            "api_key_detectada": bool(self._api_key),
            "tunel_ssh_activo": False,
            "endpoint": self.base_url,
            "rol_rapido": self.modelo_rapido,
            "rol_potente": self.modelo_potente,
            "latencia_ms": None,
            "estado": "desconocido",
            "mensaje": "",
        }

        if not self._api_key:
            resultado["estado"] = "sin_credenciales"
            resultado["mensaje"] = (
                "No se detectó API Key. Configura la variable de entorno LLM_KEY o "
                "guarda tu clave en %USERPROFILE%\\.config\\llm-gvis\\api_key."
            )
            return resultado

        # Extraer host y puerto de la URL
        match = re.search(r"://([^:/]+):?(\d+)?", self.base_url)
        host = match.group(1) if match else "127.0.0.1"
        puerto = int(match.group(2)) if match and match.group(2) else 4000

        if host in ("localhost", "127.0.0.1"):
            tunel_ok = verificar_puerto_abierto(host="127.0.0.1", puerto=puerto, timeout_s=1.5)
            resultado["tunel_ssh_activo"] = tunel_ok
            if not tunel_ok:
                resultado["estado"] = "tunel_inactivo"
                resultado["mensaje"] = (
                    f"El túnel SSH en {host}:{puerto} está inactivo. "
                    "Ejecuta en otra terminal: ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97"
                )
                return resultado
        else:
            resultado["tunel_ssh_activo"] = True

        # Prueba de llamada mínima al rol rápido
        t0 = time.monotonic()
        try:
            mensajes_test = [
                {"role": "user", "content": "Di únicamente 'OK' para verificar la conexión."}
            ]
            resp = self.consultar(mensajes_test, rol=ROL_RAPIDO, max_tokens=10, timeout_s=15.0)
            latencia = (time.monotonic() - t0) * 1000
            resultado["latencia_ms"] = round(latencia, 1)

            if resp:
                resultado["estado"] = "operativo"
                resultado["mensaje"] = f"Conexión exitosa con el clúster Legio ({resultado['latencia_ms']} ms)."
            else:
                resultado["estado"] = "sin_respuesta"
                resultado["mensaje"] = "El endpoint respondió pero no devolvió contenido."
        except TunelClusterError as err:
            resultado["estado"] = "tunel_inactivo"
            resultado["mensaje"] = str(err)
        except AutenticacionClusterError as err:
            resultado["estado"] = "error_autenticacion"
            resultado["mensaje"] = str(err)
        except Exception as err:
            resultado["estado"] = "error"
            resultado["mensaje"] = f"Error al contactar con el clúster: {type(err).__name__}"

        return resultado
