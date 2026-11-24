#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Sistema ThermoDrive HTM-240
Módulo Cliente de Backend para Agentes (CTR-003 y CTR-006 / CTR-007)
Paquete de Trabajo: A1-08 (Registro, feedback, exportación e historial)
=============================================================================
Responsable: Marco Barranco (Agente 1)

Cumplimiento estricto de especificación contractual:
  1. Registro de Consultas (CTR-003):
     - Envía el registro de cada turno mediante POST /registros (ruta única fijada en CTR-003).
     - Estados HTTP soportados:
       * 201: Registro guardado correctamente.
       * 200: Registro ya recibido previamente (idempotencia por trace_id).
       * 400 / 422: Datos inválidos. Se registran en el log de error local y NO
         se guardan en la cola offline para evitar reintentos infinitos.
       * 503 / 5xx / Sin respuesta / Timeout: Backend no disponible. Se activa
         la contingencia local guardando en JSONL para sincronización diferida.
  2. Historial de Sesiones (CTR-006 / CTR-007):
     - Operaciones: POST /chats, POST /chats/{id}/mensajes, GET /chats/{id}.
     - Si el Backend no responde al crear un chat, se notifica el error formalmente
       sin inventar IDs locales ficticios con time.time().
=============================================================================
"""

import os
import sys
import json
import uuid
import time
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

logger = logging.getLogger("ClienteBackendAgentes")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ClienteBackendAgentes:
    """Cliente HTTP de comunicación entre Agente 1 y Backend.

    Implementa CTR-003 (POST /registros) y CTR-006 (Historial de chats)
    con resiliencia local en archivo JSONL cuando el servidor no está disponible.
    """

    # Ruta oficial fijada en el contrato CTR-003
    RUTA_REGISTROS = "/registros"
    RUTA_CHATS = "/chats"

    _fallos_por_host: Dict[str, float] = {}
    _cooldown_fallo_s: float = 3.0

    def _esta_disponible(self) -> bool:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        clave = f"{host}:{port}"
        ahora = time.monotonic()
        fallos = getattr(self, '_fallos_por_host', {})
        ultimo_fallo = fallos.get(clave, 0.0) if isinstance(fallos, dict) else 0.0
        cooldown = self._cooldown_fallo_s if isinstance(getattr(self, '_cooldown_fallo_s', None), (int, float)) else 3.0
        if isinstance(ultimo_fallo, (int, float)) and ahora - ultimo_fallo < cooldown:
            return False
        if host in ("localhost", "127.0.0.1"):
            import socket
            try:
                with socket.create_connection((host, port), timeout=0.05):
                    return True
            except Exception:
                if isinstance(fallos, dict):
                    fallos[clave] = time.monotonic()
                return False
        return True

    def __init__(
        self,
        base_url: Optional[str] = None,
        ruta_offline: Optional[str] = None,
        timeout: float = 2.0,
        token_auth: Optional[str] = None
    ):
        """Inicializa el cliente de Backend."""
        self.base_url = (base_url or os.environ.get("BACKEND_URL", "http://localhost:8000")).rstrip("/")
        self.ruta_offline = Path(ruta_offline or os.environ.get("AGENTE1_OFFLINE_LOG", "auditoria_offline.jsonl"))
        self.timeout = float(timeout)
        self.token_auth = token_auth or os.environ.get("ARSOFT_SERVICE_TOKEN") or os.environ.get("BACKEND_TOKEN")

    def login(self, usuario: str, contrasena: str) -> Dict[str, Any]:
        """Autentica contra el endpoint CTR-005 (POST /auth/login) y almacena el JWT en self.token_auth."""
        ruta = "/auth/login"
        status_code, respuesta = self._post_http(ruta, {"usuario": usuario, "contrasena": contrasena})
        if status_code == 200 and "token" in respuesta:
            self.token_auth = respuesta["token"]
            logger.info(f"Autenticación exitosa en Backend para usuario '{usuario}'")
            return respuesta
        logger.warning(f"Fallo en login de Backend (HTTP {status_code}): {respuesta}")
        raise PermissionError(f"Error en login (HTTP {status_code}): {respuesta.get('mensaje', respuesta)}")

    def _headers(self) -> Dict[str, str]:
        """Encabezados HTTP estándar con autenticación Bearer opcional."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token_auth:
            headers["Authorization"] = f"Bearer {self.token_auth}"
        return headers

    def _post_http(self, ruta: str, datos: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Realiza una petición HTTP POST usando requests o urllib como fallback."""
        url = f"{self.base_url}{ruta}"
        if not self._esta_disponible():
            raise ConnectionError(f"Backend no alcanzable en {url}")
        payload_bytes = json.dumps(datos, ensure_ascii=False).encode("utf-8")

        if HAS_REQUESTS:
            try:
                res = requests.post(url, json=datos, headers=self._headers(), timeout=self.timeout)
                parsed = urlparse(self.base_url)
                ClienteBackendAgentes._fallos_por_host.pop(f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 80}", None)
                try:
                    cuerpo = res.json()
                except Exception:
                    cuerpo = {"raw": res.text}
                return res.status_code, cuerpo
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                parsed = urlparse(self.base_url)
                ClienteBackendAgentes._fallos_por_host[f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 80}"] = time.monotonic()
                raise ConnectionError(f"Backend no alcanzable en {url}: {e}")
        else:
            req = urllib.request.Request(url, data=payload_bytes, headers=self._headers(), method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    status_code = response.getcode()
                    cuerpo = json.loads(response.read().decode("utf-8"))
                    return status_code, cuerpo
            except urllib.error.HTTPError as e:
                status_code = e.code
                try:
                    cuerpo = json.loads(e.read().decode("utf-8"))
                except Exception:
                    cuerpo = {"error": str(e)}
                return status_code, cuerpo
            except urllib.error.URLError as e:
                ClienteBackendAgentes._ultimo_fallo_conexion = time.monotonic()
                raise ConnectionError(f"Backend no alcanzable en {url}: {e}")

    def _get_http(self, ruta: str, params: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        """Realiza una petición HTTP GET con soporte para parámetros de consulta."""
        query_str = ""
        if params:
            query_parts = [f"{k}={v}" for k, v in params.items() if v is not None]
            if query_parts:
                query_str = "?" + "&".join(query_parts)
        url = f"{self.base_url}{ruta}{query_str}"
        if not self._esta_disponible():
            raise ConnectionError(f"Backend no alcanzable en {url}")

        if HAS_REQUESTS:
            try:
                res = requests.get(url, headers=self._headers(), timeout=self.timeout)
                parsed = urlparse(self.base_url)
                ClienteBackendAgentes._fallos_por_host.pop(f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 80}", None)
                try:
                    cuerpo = res.json()
                except Exception:
                    cuerpo = {"raw": res.text}
                return res.status_code, cuerpo
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                parsed = urlparse(self.base_url)
                ClienteBackendAgentes._fallos_por_host[f"{parsed.hostname or '127.0.0.1'}:{parsed.port or 80}"] = time.monotonic()
                raise ConnectionError(f"Backend no alcanzable en {url}: {e}")
        else:
            req = urllib.request.Request(url, headers=self._headers(), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    status_code = response.getcode()
                    cuerpo = json.loads(response.read().decode("utf-8"))
                    return status_code, cuerpo
            except urllib.error.HTTPError as e:
                status_code = e.code
                try:
                    cuerpo = json.loads(e.read().decode("utf-8"))
                except Exception:
                    cuerpo = {"error": str(e)}
                return status_code, cuerpo
            except urllib.error.URLError as e:
                raise ConnectionError(f"Backend no alcanzable en {url}: {e}")

    # =========================================================================
    # 1. CTR-003: REGISTRO DE CONSULTAS Y RESILIENCIA OFFLINE
    # =========================================================================

    def formatear_registro_ctr003(
        self,
        trace_id: str,
        conversacion_id: str,
        pregunta_original: str,
        pregunta_limpia: str,
        entidades: Dict[str, Any],
        clasificacion: str,
        query: Optional[Dict[str, Any]],
        estado_agente2: Optional[str],
        chunks_usados: List[str],
        scores: List[float],
        estado_respuesta: str,
        respuesta: str,
        citas_verificadas: bool,
        latencia_ms: int,
        modelo: str = "qwen2.5:14b",
        version_prompt: str = "v1.2",
        marca_tiempo: Optional[str] = None
    ) -> Dict[str, Any]:
        """Construye el payload JSON con todos los metadatos exigidos por CTR-003."""
        if not marca_tiempo:
            marca_tiempo = datetime.now(timezone.utc).isoformat()

        return {
            "trace_id": str(trace_id),
            "conversacion_id": str(conversacion_id),
            "marca_tiempo": str(marca_tiempo),
            "pregunta_original": str(pregunta_original),
            "pregunta_limpia": str(pregunta_limpia),
            "entidades": entidades or {},
            "clasificacion": str(clasificacion),
            "query": query or {},
            "estado_agente2": estado_agente2,
            "chunks_usados": chunks_usados or [],
            "scores": [float(s) for s in scores or []],
            "estado_respuesta": str(estado_respuesta),
            "respuesta": str(respuesta),
            "citas_verificadas": bool(citas_verificadas),
            "latencia_ms": int(latencia_ms),
            "modelo": str(modelo),
            "version_prompt": str(version_prompt),
            "feedback": {"util": None, "comentario": None}
        }

    def registrar_turno(self, registro: Dict[str, Any]) -> Dict[str, Any]:
        """Envía el registro a Backend vía POST /registros (CTR-003).

        Comportamiento ante respuestas:
          - HTTP 201: Registrado exitosamente online.
          - HTTP 200: Ya existía en Backend (idempotencia).
          - HTTP 400 / 422: Datos inválidos. Se anota en log de error y NO se guarda en offline.
          - HTTP 500 / 503 o ConnectionError / Timeout: Backend caído. Se guarda en JSONL offline.
        """
        trace_id = registro.get("trace_id", "desconocido")

        try:
            status_code, respuesta = self._post_http(self.RUTA_REGISTROS, registro)

            if status_code in (200, 201):
                logger.info(
                    f"Turno registrado exitosamente en Backend vía {self.RUTA_REGISTROS} "
                    f"(HTTP {status_code}, trace_id: {trace_id})"
                )
                return {"enviado": True, "offline": False, "status_code": status_code, "respuesta": respuesta}

            if 400 <= status_code < 500:
                logger.error(
                    f"Backend rechazó registro {trace_id} por datos inválidos (HTTP {status_code}): {respuesta}. "
                    f"NO se guarda en cola offline para evitar bucles infinitos."
                )
                return {"enviado": False, "offline": False, "status_code": status_code, "error": respuesta}

            # Códigos 5xx (500, 502, 503, 504): error de servidor
            logger.warning(f"Backend devolvió error de servidor HTTP {status_code} al registrar turno {trace_id}. Guardando offline.")
            self._guardar_registro_offline(registro)
            return {"enviado": False, "offline": True, "status_code": status_code, "error": f"HTTP {status_code}"}

        except ConnectionError as e:
            logger.warning(f"Backend no disponible ({e}). Activando contingencia offline para trace_id: {trace_id}")
            self._guardar_registro_offline(registro)
            return {"enviado": False, "offline": True, "error": str(e)}

    def _guardar_registro_offline(self, registro: Dict[str, Any]) -> None:
        """Guarda un registro en el archivo JSONL de contingencia local."""
        try:
            self.ruta_offline.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ruta_offline, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            logger.info(f"Registro de auditoría guardado en contingencia local: {self.ruta_offline} (trace_id: {registro.get('trace_id')})")
        except Exception as e:
            logger.error(f"Error crítico al guardar registro en contingencia local: {e}")

    def sincronizar_pendientes(self) -> Dict[str, int]:
        """Reenvía los registros pendientes acumulados en el archivo offline a POST /registros."""
        if not self.ruta_offline.exists():
            return {"procesados": 0, "enviados": 0, "descartados": 0, "pendientes": 0}

        registros_pendientes = []
        try:
            with open(self.ruta_offline, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea:
                        try:
                            registros_pendientes.append(json.loads(linea))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Error al leer archivo offline {self.ruta_offline}: {e}")
            return {"procesados": 0, "enviados": 0, "descartados": 0, "pendientes": 0}

        if not registros_pendientes:
            return {"procesados": 0, "enviados": 0, "descartados": 0, "pendientes": 0}

        logger.info(f"Intentando sincronizar {len(registros_pendientes)} registros pendientes acumulados vía {self.RUTA_REGISTROS}...")
        enviados = 0
        descartados = 0
        aun_pendientes = []

        for reg in registros_pendientes:
            try:
                status_code, _ = self._post_http(self.RUTA_REGISTROS, reg)
                if status_code in (200, 201):
                    enviados += 1
                elif 400 <= status_code < 500:
                    # Descartar registros con datos erróneos para que no taponen la cola
                    logger.warning(f"Descartando registro inválido {reg.get('trace_id')} durante sincronización (HTTP {status_code}).")
                    descartados += 1
                else:
                    aun_pendientes.append(reg)
            except ConnectionError:
                aun_pendientes.append(reg)

        # Reescribir el archivo offline solo con los que no se hayan podido enviar
        try:
            if aun_pendientes:
                with open(self.ruta_offline, "w", encoding="utf-8") as f:
                    for reg in aun_pendientes:
                        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            else:
                self.ruta_offline.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Error al actualizar archivo offline tras sincronización: {e}")

        logger.info(f"Sincronización finalizada: {enviados} enviados, {descartados} descartados por inválidos, {len(aun_pendientes)} pendientes.")
        return {
            "procesados": len(registros_pendientes),
            "enviados": enviados,
            "descartados": descartados,
            "pendientes": len(aun_pendientes)
        }

    def obtener_consultas_mias(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """CTR-003: Recupera el registro de consultas del usuario autenticado vía GET /consultas/mias."""
        ruta = "/consultas/mias"
        params = {"limit": limit, "offset": offset}
        try:
            status_code, respuesta = self._get_http(ruta, params=params)
            if status_code == 200 and isinstance(respuesta, dict):
                return respuesta.get("consultas", [])
            logger.warning(f"Error al obtener consultas propias (HTTP {status_code}): {respuesta}")
            return []
        except ConnectionError as e:
            logger.warning(f"Backend no alcanzable para obtener consultas propias: {e}")
            return []

    def obtener_todas_consultas(
        self,
        usuario_id: Optional[int] = None,
        tipo: Optional[str] = None,
        estado: Optional[str] = None,
        desde: Optional[str] = None,
        hasta: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """CTR-003: Consulta el registro completo de consultas (solo admin) vía GET /consultas."""
        ruta = "/consultas"
        params = {
            "usuario_id": usuario_id,
            "tipo": tipo,
            "estado": estado,
            "desde": desde,
            "hasta": hasta,
            "limit": limit,
            "offset": offset
        }
        try:
            status_code, respuesta = self._get_http(ruta, params=params)
            if status_code == 200 and isinstance(respuesta, dict):
                return respuesta.get("consultas", [])
            logger.warning(f"Error al obtener registro global de consultas (HTTP {status_code}): {respuesta}")
            return []
        except ConnectionError as e:
            logger.warning(f"Backend no alcanzable para obtener registro global: {e}")
            return []

    # =========================================================================
    # 2. CTR-006 / CTR-007: HISTORIAL DE CHATS Y MENSAJES
    # =========================================================================

    def crear_chat(self, titulo: Optional[str] = None) -> Dict[str, Any]:
        """Crea un nuevo hilo de chat en Backend vía POST /chats.

        Si el Backend falla o está caído, NO se inventa un ID falso con time.time():
        se lanza un ConnectionError o RuntimeError para informar limpiamente del fallo.
        """
        payload = {"titulo": titulo or "Nueva consulta técnica"}
        try:
            status_code, respuesta = self._post_http(self.RUTA_CHATS, payload)
            if status_code in (200, 201):
                chat_id = respuesta.get("id") or respuesta.get("chat_id")
                logger.info(f"Chat creado con éxito en Backend (ID: {chat_id})")
                return {"id": chat_id, "titulo": payload["titulo"], "online": True}
            raise RuntimeError(f"Backend rechazó la creación de chat (HTTP {status_code}): {respuesta}")
        except ConnectionError as e:
            logger.error(f"No se pudo crear chat en Backend: el servicio no está disponible ({e})")
            raise ConnectionError(f"Backend no disponible para crear chat: {e}")

    def guardar_mensaje(
        self,
        chat_id: Any,
        rol: str,
        contenido: str,
        fuentes: Optional[List[Dict[str, Any]]] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Añade un mensaje al historial de un chat vía POST /chats/{chat_id}/mensajes."""
        payload = {
            "rol": rol,
            "contenido": contenido,
            "fuentes": fuentes or [],
            "trace_id": trace_id
        }
        ruta = f"{self.RUTA_CHATS}/{chat_id}/mensajes"
        try:
            status_code, respuesta = self._post_http(ruta, payload)
            if status_code in (200, 201):
                return {"guardado": True, "respuesta": respuesta}
            logger.warning(f"Error al guardar mensaje en chat {chat_id} (HTTP {status_code}): {respuesta}")
            return {"guardado": False, "status_code": status_code, "error": respuesta}
        except ConnectionError as e:
            logger.warning(f"No se pudo guardar mensaje en chat {chat_id} (Backend caído): {e}")
            return {"guardado": False, "error": str(e)}

    def obtener_historial(self, chat_id: Any, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Recupera los mensajes de un chat vía GET /chats/{chat_id} con límite opcional."""
        ruta = f"{self.RUTA_CHATS}/{chat_id}"
        params = {"limit": limit} if limit else None
        try:
            status_code, respuesta = self._get_http(ruta, params=params)
            if status_code == 200:
                mensajes = respuesta.get("mensajes") if isinstance(respuesta, dict) else (
                    respuesta if isinstance(respuesta, list) else []
                )
                logger.info(f"Historial recuperado para chat {chat_id}: {len(mensajes)} mensajes")
                return mensajes
            if status_code == 404:
                logger.info(f"Chat {chat_id} no encontrado en Backend (HTTP 404).")
                return []
            logger.warning(f"Error al recuperar historial de chat {chat_id} (HTTP {status_code}): {respuesta}")
            return []
        except ConnectionError as e:
            logger.warning(f"No se pudo consultar historial de chat {chat_id} (Backend caído): {e}")
            return []
