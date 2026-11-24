#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
ARSOFT — Reto IA Automoción | Sistema ThermoDrive HTM-240
Simulador de Backend para Pruebas Locales de Agentes (CTR-003 y CTR-006)
=============================================================================
Responsable: Marco Barranco (Agente 1)

Servidor HTTP de pruebas autónomo y sin dependencias externas (utiliza http.server).
Emula:
  - POST /registros: Almacenamiento de auditoría contractual con idempotencia (CTR-003).
  - GET /registros: Consulta de registros almacenados.
  - POST /chats: Creación de sesiones de chat (CTR-006).
  - POST /chats/{id}/mensajes: Registro de mensajes en la sesión.
  - GET /chats/{id}: Consulta de historial de la conversación.
  - Inyección de fallos: HTTP 503 (servidor caído), HTTP 400 (datos erróneos),
    y latencia configurable para validar resiliencia y timeouts.
=============================================================================
"""

import json
import time
import logging
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional

logger = logging.getLogger("SimuladorBackend")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [SimuladorBackend]: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class EstadoSimulador:
    """Almacén en memoria compartida para el simulador de Backend."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.registros: Dict[str, Dict[str, Any]] = {}
        self.chats: Dict[Any, Dict[str, Any]] = {}
        self.next_chat_id = 1
        self.next_msg_id = 1
        self.simular_503 = False
        self.simular_400 = False
        self.latencia_s = 0.0


ESTADO_GLOBAL = EstadoSimulador()


class ManejadorSimuladorBackend(BaseHTTPRequestHandler):
    """Manejador HTTP para las peticiones entrantes de Agente 1."""

    def _responder_json(self, status_code: int, datos: Any):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        try:
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _leer_cuerpo_json(self) -> Optional[Dict[str, Any]]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw_data = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw_data)
        except Exception as e:
            logger.warning(f"Error al parsear JSON del cliente: {e}")
        return None

    def log_message(self, format, *args):
        # Suprimir logs automáticos por defecto de BaseHTTPRequestHandler
        pass

    def do_POST(self):
        cuerpo = self._leer_cuerpo_json()

        # Inyección de latencia simulada
        if ESTADO_GLOBAL.latencia_s > 0:
            time.sleep(ESTADO_GLOBAL.latencia_s)

        # Inyección de fallo 503 (servidor saturado o caído)
        if ESTADO_GLOBAL.simular_503:
            logger.warning("Simulador devolviendo HTTP 503 forzado.")
            return self._responder_json(503, {"error": "Servicio temporalmente no disponible (simulado)"})

        # Inyección de fallo 400 (bad request)
        if ESTADO_GLOBAL.simular_400:
            logger.warning("Simulador devolviendo HTTP 400 forzado.")
            return self._responder_json(400, {"error": "Petición con campos inválidos o ausentes (simulado)"})

        parsed = urlparse(self.path)
        ruta = parsed.path

        # ---------------------------------------------------------------------
        # CTR-005: POST /auth/login
        # ---------------------------------------------------------------------
        if ruta == "/auth/login":
            if not cuerpo or not isinstance(cuerpo, dict):
                return self._responder_json(422, {
                    "estado": "no_autenticado",
                    "codigo_error": "datos_incompletos",
                    "mensaje": "Faltan datos o el formato es incorrecto."
                })
            usuario = cuerpo.get("usuario")
            contrasena = cuerpo.get("contrasena")
            if not usuario or not contrasena:
                return self._responder_json(422, {
                    "estado": "no_autenticado",
                    "codigo_error": "datos_incompletos",
                    "mensaje": "Faltan datos o el formato es incorrecto."
                })
            if (usuario == "admin" and contrasena == "admin123") or (usuario == "usuario1" and contrasena == "usuario123") or contrasena == "valida":
                token = f"simulated-jwt-token-{usuario}"
                return self._responder_json(200, {
                    "estado": "autenticado",
                    "mensaje": "Inicio de sesión correcto.",
                    "usuario": {
                        "id": 1 if usuario == "admin" else 2,
                        "nombre_usuario": usuario,
                        "nombre": usuario.capitalize(),
                        "rol": "admin" if usuario == "admin" else "usuario"
                    },
                    "token": token,
                    "token_type": "bearer",
                    "expires_in": 28800
                })
            return self._responder_json(401, {
                "estado": "no_autenticado",
                "codigo_error": "credenciales_invalidas",
                "mensaje": "Usuario o contraseña incorrectos."
            })

        # ---------------------------------------------------------------------
        # CTR-003: POST /registros
        # ---------------------------------------------------------------------
        if ruta == "/registros":
            if not cuerpo or not isinstance(cuerpo, dict):
                return self._responder_json(400, {"error": "Cuerpo JSON requerido"})

            trace_id = cuerpo.get("trace_id")
            if not trace_id:
                return self._responder_json(400, {"error": "El campo trace_id es obligatorio según CTR-003"})

            # Idempotencia: Si ya existe el trace_id, HTTP 200 sin duplicar
            if trace_id in ESTADO_GLOBAL.registros:
                logger.info(f"CTR-003: Registro ya existente detectado (idempotente trace_id: {trace_id}) -> HTTP 200")
                return self._responder_json(200, {
                    "mensaje": "Registro ya recibido previamente (idempotente)",
                    "trace_id": trace_id
                })

            nuevo_id = len(ESTADO_GLOBAL.registros) + 1
            registro_guardado = {
                "id": nuevo_id,
                "recibido_en": time.time(),
                **cuerpo
            }
            ESTADO_GLOBAL.registros[trace_id] = registro_guardado
            logger.info(f"CTR-003: Consulta registrada con éxito (id: {nuevo_id}, trace_id: {trace_id})")
            return self._responder_json(201, {
                "id": nuevo_id,
                "trace_id": trace_id,
                "mensaje": "Registro guardado correctamente"
            })

        # ---------------------------------------------------------------------
        # CTR-006: POST /chats
        # ---------------------------------------------------------------------
        if ruta == "/chats":
            titulo = (cuerpo or {}).get("titulo", "Nueva consulta técnica")
            chat_id = ESTADO_GLOBAL.next_chat_id
            ESTADO_GLOBAL.next_chat_id += 1
            ESTADO_GLOBAL.chats[chat_id] = {
                "id": chat_id,
                "titulo": titulo,
                "creado_en": time.time(),
                "mensajes": []
            }
            logger.info(f"CTR-006: Chat creado (id: {chat_id}, titulo: '{titulo}')")
            return self._responder_json(201, {"id": chat_id, "titulo": titulo})

        # ---------------------------------------------------------------------
        # CTR-006: POST /chats/{id}/mensajes
        # ---------------------------------------------------------------------
        partes = ruta.strip("/").split("/")
        if len(partes) == 3 and partes[0] == "chats" and partes[2] == "mensajes":
            try:
                chat_id = int(partes[1])
            except ValueError:
                return self._responder_json(400, {"error": "ID de chat debe ser numérico"})

            if chat_id not in ESTADO_GLOBAL.chats:
                return self._responder_json(404, {"error": f"Chat {chat_id} no encontrado"})

            if not cuerpo or not isinstance(cuerpo, dict):
                return self._responder_json(400, {"error": "Cuerpo del mensaje requerido"})

            msg_id = ESTADO_GLOBAL.next_msg_id
            ESTADO_GLOBAL.next_msg_id += 1
            mensaje_guardado = {
                "id": msg_id,
                "chat_id": chat_id,
                "timestamp": time.time(),
                "rol": cuerpo.get("rol", "usuario"),
                "contenido": cuerpo.get("contenido", ""),
                "fuentes": cuerpo.get("fuentes", []),
                "trace_id": cuerpo.get("trace_id")
            }
            ESTADO_GLOBAL.chats[chat_id]["mensajes"].append(mensaje_guardado)
            logger.info(f"CTR-006: Mensaje añadido a chat {chat_id} (id: {msg_id}, rol: {mensaje_guardado['rol']})")
            return self._responder_json(201, mensaje_guardado)

        return self._responder_json(404, {"error": f"Ruta POST no encontrada: {ruta}"})

    def do_GET(self):
        parsed = urlparse(self.path)
        ruta = parsed.path
        qs = parse_qs(parsed.query)

        # ---------------------------------------------------------------------
        # CTR-003: GET /registros y GET /consultas (mias y todas)
        # ---------------------------------------------------------------------
        if ruta == "/registros":
            return self._responder_json(200, list(ESTADO_GLOBAL.registros.values()))

        if ruta == "/consultas/mias":
            lista = list(ESTADO_GLOBAL.registros.values())
            limit = int(qs.get("limit", [50])[0])
            offset = int(qs.get("offset", [0])[0])
            return self._responder_json(200, {"consultas": lista[offset:offset+limit]})

        if ruta == "/consultas":
            lista = list(ESTADO_GLOBAL.registros.values())
            estado = qs.get("estado", [None])[0]
            if estado:
                lista = [r for r in lista if r.get("estado") == estado or r.get("estado_respuesta") == estado]
            limit = int(qs.get("limit", [100])[0])
            offset = int(qs.get("offset", [0])[0])
            return self._responder_json(200, {"consultas": lista[offset:offset+limit]})

        # ---------------------------------------------------------------------
        # CTR-006 / CTR-007: GET /chats/{id}
        # ---------------------------------------------------------------------
        partes = ruta.strip("/").split("/")
        if len(partes) == 2 and partes[0] == "chats":
            raw_id = partes[1]
            chat_id = int(raw_id) if raw_id.isdigit() else raw_id

            if chat_id not in ESTADO_GLOBAL.chats and raw_id not in ESTADO_GLOBAL.chats:
                return self._responder_json(404, {"error": f"Chat {raw_id} no encontrado", "codigo_error": "conversacion_no_encontrada"})

            chat = ESTADO_GLOBAL.chats.get(chat_id) or ESTADO_GLOBAL.chats.get(raw_id)
            mensajes = chat["mensajes"]
            limit = qs.get("limit")
            if limit:
                try:
                    lim_n = int(limit[0])
                    mensajes = mensajes[-lim_n:]
                except ValueError:
                    pass

            return self._responder_json(200, {
                "id": chat["id"],
                "conversacion_id": str(chat["id"]),
                "titulo": chat["titulo"],
                "mensajes": mensajes
            })

        return self._responder_json(404, {"error": f"Ruta GET no encontrada: {ruta}"})


class ServidorSimuladorBackend:
    """Controlador para iniciar y detener el servidor en un hilo secundario durante pruebas."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8099):
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        ESTADO_GLOBAL.reset()
        self.server = HTTPServer((self.host, self.port), ManejadorSimuladorBackend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Simulador de Backend escuchando en http://{self.host}:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            self.thread = None
        logger.info("Simulador de Backend detenido.")
