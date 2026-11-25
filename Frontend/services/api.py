"""Comunicación con el servicio (API JSON sobre HTTP, FastAPI en el Backend).

Contratos que implementa este módulo:

  CTR-001  Consulta al asistente. Cuerpo EXACTO (sin historial: la memoria de la conversación
           la lleva Agentes por conversacion_id):
               {"conversacion_id": "...", "pregunta": "texto tal y como se escribió"}
           Respuesta (siempre los mismos campos; los errores controlados de Agentes también son HTTP 200):
               {"trace_id", "estado", "texto", "fuentes": [{"chunk_id", "documento", "seccion",
                "pagina", "versiones", "obsoleto"}], "codigo_error"}
           El Backend expone POST /consulta y devuelve conversacion_id. Errores HTTP del propio Backend:
           401/403 sesión caducada, 404 conversación no encontrada, 422 entrada inválida, 429 demasiadas
           consultas; el resto (5xx, JSON no válido) se muestra como error genérico.
  CTR-006  Historial:  GET /chats?limit&offset (paginado); PATCH /chats/{id} {"titulo"}; DELETE /chats/{id}
           Cada usuario solo puede operar sobre sus propias conversaciones.
  CTR-001  Valoración: POST /valoracion {"trace_id", "util"} -> 200 {"trace_id", "util"}
           Errores: 401/403 sesión caducada, 404 respuesta no encontrada, 422 entrada inválida,
           429 demasiadas valoraciones, 500/503 error del servicio.
  CTR-005  Login: ver services/auth.py

Toda la configuración (URL, rutas, tiempo máximo y modo) se lee en config.py.
Sin ARSOFT_API_URL (o con ARSOFT_MODO=simulado) se usa un MODO SIMULADO solo para desarrollar
la interfaz. NO es el asistente real.
Fuera de entornos locales se exige HTTPS (ARSOFT_ALLOW_HTTP=1 lo desactiva, solo para pruebas).
"""
from __future__ import annotations
import json
import socket
import time
from copy import deepcopy
from datetime import datetime, timezone
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from PySide6.QtCore import QThread, Signal

from models.conversation import Conversation
from models.response import (Response, STATUS_CLARIFY, STATUS_NO_EVIDENCE, STATUS_OK,
                             STATUS_OUT_OF_SCOPE)
from models.source import Source
import config
from services import session

# Valores tomados de config.py (no definir aquí: config.py es el único sitio).
MODO = config.MODO
API_URL = config.API_URL
TIMEOUT_S = config.TIMEOUT_S
CONSULTA_PATH = config.CONSULTA_PATH          # CTR-001: Frontend -> Backend
LOGIN_PATH = config.LOGIN_PATH                # CTR-005
HISTORIAL_PATH = config.HISTORIAL_PATH        # CTR-006
VALORACION_PATH = config.VALORACION_PATH      # CTR-001: valoración de una respuesta
SESSION_EXPIRED = "Tu sesión ha caducado. Cierra sesión y vuelve a entrar."
TOO_MANY_REQUESTS = "Demasiadas consultas seguidas. Espera un momento antes de volver a intentarlo."
CONVERSATION_NOT_FOUND = "Esta conversación ya no está disponible. Empieza un chat nuevo."
INVALID_INPUT = "La consulta no se ha podido enviar: faltan datos o el formato es incorrecto."
MISSING_URL = "Modo real sin servidor configurado: define ARSOFT_API_URL en el archivo .env."
RATING_FAILED = "No se pudo enviar tu valoración. Inténtalo de nuevo."
RATING_TOO_MANY = "Demasiadas valoraciones seguidas. Espera un momento."
RATING_NOT_FOUND = "Esta respuesta ya no se puede valorar."
HISTORY_TOO_MANY = "Demasiadas peticiones. Espera un momento y reintenta."
HISTORY_SERVER_ERROR = "No se pudo cargar el historial. Inténtalo más tarde."


def is_mock() -> bool:
    if MODO == config.MODO_SIMULADO:
        return True
    if MODO == config.MODO_REAL:
        return False
    return not API_URL


# ------------------------------------------------------------------- HTTP común
class ConnectionFailed(Exception):
    """No se obtuvo respuesta HTTP (sin conexión, tiempo agotado o conexión no segura)."""

    def __init__(self, message: str = "", code: str = "servicio_no_disponible"):
        super().__init__(message)
        self.code = code


class ConfigError(ConnectionFailed):
    """La configuración impide conectar (falta la URL o no es segura). El mensaje se muestra."""


def _is_local(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def _insecure() -> bool:
    u = urlparse(API_URL)
    return u.scheme == "http" and not _is_local(u.hostname or "") and not config.ALLOW_HTTP


def auth_headers() -> dict:
    """Identificación del usuario. Si el Backend devolvió un token en el login se envía;
    si no, no se envía nada."""
    return {"Authorization": f"Bearer {session.token}"} if session.token else {}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
    """Devuelve (código HTTP, JSON o None). Solo lanza ConnectionFailed si no hay respuesta."""
    if is_mock():
        return _mock_call(method, path, body)
    if not API_URL:
        raise ConfigError(MISSING_URL)
    if _insecure():
        raise ConfigError("Conexión no segura: fuera de un entorno local se exige HTTPS.")
    headers = {"Accept": "application/json", **auth_headers()}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (socket.timeout, TimeoutError) as e:
        raise ConnectionFailed(str(e), "tiempo_agotado") from e
    except (urllib.error.URLError, OSError) as e:
        raise ConnectionFailed(str(e), "servicio_no_disponible") from e
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return status, parsed if isinstance(parsed, dict) else None


# ------------------------------------------------------------ consulta (CTR-001)
def send_message(conversation_id: str, pregunta: str) -> Response:
    try:
        status, data = call("POST", CONSULTA_PATH,
                            {"conversacion_id": conversation_id, "pregunta": pregunta})
    except ConfigError as e:                   # falta la URL o no es segura: el usuario debe saberlo
        return Response.error(str(e), "configuracion")
    except ConnectionFailed as e:
        return Response.error(codigo=e.code)
    if status in (401, 403):
        return Response.error(SESSION_EXPIRED, "sesion_caducada")
    if status == 429:
        return Response.error(TOO_MANY_REQUESTS, "demasiadas_consultas")
    if status == 404:                          # chat ajeno o borrado: el Backend no reenvía a Agentes
        return Response.error(CONVERSATION_NOT_FOUND, "conversacion_no_encontrada")
    if status == 422:
        return Response.error(INVALID_INPUT, "entrada_invalida")
    if status == 200 and data is not None:
        return Response.from_dict(data)
    return Response.error()                    # 5xx, JSON no válido…: mensaje genérico


class ChatWorker(QThread):
    """Ejecuta la consulta fuera del hilo de la interfaz (no la congela)."""
    finished_ok = Signal(object)  # Response

    def __init__(self, conversation_id: str, pregunta: str):
        super().__init__()
        self._args = (conversation_id, pregunta)

    def run(self) -> None:
        self.finished_ok.emit(send_message(*self._args))


# ------------------------------------------------------------ historial (CTR-006)
@dataclass
class HistoryResult:
    ok: bool
    conversations: list[Conversation] = field(default_factory=list)
    error: str = ""
    session_expired: bool = False


HISTORY_PAGE_SIZE = 200  # máximo de `limit` que acepta GET /chats (el Backend pagina de 50 en 50 por defecto)
HISTORY_MAX_PAGES = 50   # tope de seguridad: evita un bucle si el servidor devuelve `total` incoherente


def fetch_history() -> HistoryResult:
    """GET /chats paginado: pide páginas de HISTORY_PAGE_SIZE hasta cubrir `total` (CTR-006).

    `total` es el número de chats del usuario (no el de la página). Un servidor sin paginación
    ignora limit/offset y devuelve todo de una vez: entonces total == len(chats) y se para."""
    conversations: list[Conversation] = []
    offset = 0
    for _ in range(HISTORY_MAX_PAGES):
        try:
            status, data = call("GET", f"{HISTORIAL_PATH}?limit={HISTORY_PAGE_SIZE}&offset={offset}")
        except ConfigError as e:
            return HistoryResult(False, error=str(e))
        except ConnectionFailed:
            return HistoryResult(False, error="No se ha podido contactar con el servidor.")
        if status in (401, 403):
            return HistoryResult(False, error=SESSION_EXPIRED, session_expired=True)
        if status == 429:
            return HistoryResult(False, error=HISTORY_TOO_MANY)
        if status >= 500:
            return HistoryResult(False, error=HISTORY_SERVER_ERROR)
        if not (status == 200 and data is not None and isinstance(data.get("chats"), list)):
            break
        try:
            page = [Conversation.from_dict(c) for c in data["chats"]]
        except (KeyError, TypeError, ValueError):
            break
        conversations.extend(page)
        offset += len(page)
        total = data.get("total")
        if not page or not isinstance(total, int) or offset >= total:
            return HistoryResult(True, conversations)
    return HistoryResult(False, error="No se ha podido recuperar el historial.")


class HistoryWorker(QThread):
    done = Signal(object)  # HistoryResult

    def run(self) -> None:
        self.done.emit(fetch_history())


# ----------------------------------------------------------- valoración (CTR-001)
@dataclass
class RatingResult:
    ok: bool
    trace_id: str = ""
    util: bool = False
    error: str = ""
    session_expired: bool = False


@dataclass
class HistoryActionResult:
    ok: bool
    conversation: Conversation | None = None
    error: str = ""
    session_expired: bool = False


def send_rating(trace_id: str, util: bool) -> RatingResult:
    """POST /valoracion {"trace_id", "util"}. El Backend solo admite respuestas con estado "respuesta"
    del propio usuario; valorar de nuevo la misma respuesta cambia la valoración."""
    def fail(msg: str, expired: bool = False) -> RatingResult:
        return RatingResult(False, trace_id, util, msg, expired)

    try:
        status, data = call("POST", VALORACION_PATH, {"trace_id": trace_id, "util": util})
    except ConfigError as e:
        return fail(str(e))
    except ConnectionFailed:
        return fail(RATING_FAILED)
    if status in (401, 403):
        return fail(SESSION_EXPIRED, True)
    if status == 404:
        return fail(RATING_NOT_FOUND)
    if status == 429:
        return fail(RATING_TOO_MANY)
    if status == 200 and data is not None and isinstance(data.get("util"), bool):
        return RatingResult(True, trace_id, data["util"])
    return fail(RATING_FAILED)                 # 422, 5xx, JSON no válido…: mensaje genérico


class RatingWorker(QThread):
    """Envía la valoración fuera del hilo de la interfaz."""
    done = Signal(object)  # RatingResult

    def __init__(self, trace_id: str, util: bool):
        super().__init__()
        self._args = (trace_id, util)

    def run(self) -> None:
        self.done.emit(send_rating(*self._args))


def _history_item_path(conversation_id: str) -> str:
    return f"{HISTORIAL_PATH.rstrip('/')}/{quote(conversation_id, safe='')}"


def rename_chat(conversation_id: str, title: str) -> HistoryActionResult:
    title = title.strip()
    if not title or len(title) > 200:
        return HistoryActionResult(False, error="El título debe tener entre 1 y 200 caracteres.")
    try:
        status, data = call("PATCH", _history_item_path(conversation_id), {"titulo": title})
    except ConfigError as e:
        return HistoryActionResult(False, error=str(e))
    except ConnectionFailed:
        return HistoryActionResult(False, error="No se ha podido contactar con el servidor.")
    if status in (401, 403):
        return HistoryActionResult(False, error=SESSION_EXPIRED, session_expired=True)
    if status == 404:
        return HistoryActionResult(False, error=CONVERSATION_NOT_FOUND)
    if status == 200 and data is not None:
        try:
            return HistoryActionResult(True, conversation=Conversation.from_dict(data))
        except (KeyError, TypeError, ValueError):
            pass
    if status == 422:
        return HistoryActionResult(False, error="El título no es válido.")
    return HistoryActionResult(False, error="No se ha podido renombrar la conversación.")


def delete_chat(conversation_id: str) -> HistoryActionResult:
    try:
        status, _ = call("DELETE", _history_item_path(conversation_id))
    except ConfigError as e:
        return HistoryActionResult(False, error=str(e))
    except ConnectionFailed:
        return HistoryActionResult(False, error="No se ha podido contactar con el servidor.")
    if status in (401, 403):
        return HistoryActionResult(False, error=SESSION_EXPIRED, session_expired=True)
    if status == 404:
        return HistoryActionResult(False, error=CONVERSATION_NOT_FOUND)
    if status == 204:
        return HistoryActionResult(True)
    return HistoryActionResult(False, error="No se ha podido eliminar la conversación.")


class HistoryActionWorker(QThread):
    done = Signal(object)  # (action, conversation_id, HistoryActionResult)

    def __init__(self, action: str, conversation_id: str, title: str = ""):
        super().__init__()
        self._action = action
        self._conversation_id = conversation_id
        self._title = title

    def run(self) -> None:
        if self._action == "rename":
            result = rename_chat(self._conversation_id, self._title)
        else:
            result = delete_chat(self._conversation_id)
        self.done.emit((self._action, self._conversation_id, result))


# ---------------------------------------------------------------- modo simulado
_MOCK_EMPTY_HISTORY = config.MOCK_EMPTY_HISTORY
_MOCK_CHATS = [
    {
        "conversacion_id": "demo-chat-001",
        "titulo": "Temperatura del motor",
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-01-15T10:03:00Z",
        "mensajes": [
            {
                "message_id": "demo-msg-001",
                "trace_id": "t-demo-001",
                "role": "user",
                "contenido": "¿Qué hago si sube la temperatura?",
                "estado": "respuesta",
                "timestamp": "2026-01-15T10:00:00Z",
                "fuentes": [],
            },
            {
                "message_id": "demo-msg-002",
                "trace_id": "t-demo-001",
                "role": "assistant",
                "contenido": "Comprueba el nivel de refrigerante en frío y busca fugas visibles.",
                "estado": "respuesta",
                "timestamp": "2026-01-15T10:03:00Z",
                "fuentes": [
                    {
                        "chunk_id": "c45",
                        "documento": "Manual_ejemplo",
                        "seccion": "2.1",
                        "pagina": 128,
                        "versiones": ["V1.1", "V2.0"],
                        "obsoleto": False,
                    }
                ],
            },
        ],
    }
]


def _mock_call(method: str, path: str, body: dict | None) -> tuple[int, dict | None]:
    """Simula el servidor conservando los mismos cuerpos que el modo real."""
    if method == "POST" and path == LOGIN_PATH:
        if body and body.get("usuario") == "rate_limit":
            return 429, {"estado": "error", "mensaje": "Demasiados intentos."}
        if body and body.get("usuario") == "demo" and body.get("contrasena") == "demo1234":
            return 200, {
                "estado": "autenticado",
                "mensaje": "Inicio de sesión correcto.",
                "usuario": {"id": "demo", "nombre_usuario": "demo"},
                "token": "mock-token",
            }
        return 401, {
            "estado": "no_autenticado",
            "mensaje": "Usuario o contraseña incorrectos.",
            "codigo_error": "credenciales_invalidas",
        }
    if method == "POST" and path == VALORACION_PATH:
        if not body or not body.get("trace_id") or not isinstance(body.get("util"), bool):
            return 422, {"codigo_error": "entrada_invalida", "mensaje": "Valoración no válida."}
        return 200, {"trace_id": body["trace_id"], "util": body["util"]}
    if method == "GET" and path.split("?", 1)[0] == HISTORIAL_PATH:
        chats = [] if _MOCK_EMPTY_HISTORY else deepcopy(_MOCK_CHATS)
        return 200, {"chats": chats, "total": len(chats)}
    history_item_prefix = f"{HISTORIAL_PATH.rstrip('/')}/"
    if path.startswith(history_item_prefix) and method in ("PATCH", "DELETE"):
        conversation_id = unquote(path[len(history_item_prefix):])
        chat = next((c for c in _MOCK_CHATS if c["conversacion_id"] == conversation_id), None)
        if chat is None:
            return 404, {"codigo_error": "conversacion_no_encontrada"}
        if method == "PATCH":
            title = body.get("titulo", "") if body else ""
            if not isinstance(title, str) or not title.strip() or len(title) > 200:
                return 422, {"codigo_error": "entrada_invalida"}
            chat["titulo"] = title.strip()
            chat["updated_at"] = datetime.now(timezone.utc).isoformat()
            return 200, deepcopy(chat)
        _MOCK_CHATS.remove(chat)
        return 204, None
    if method == "POST" and path == CONSULTA_PATH and body:
        response = _mock_response(body.get("pregunta", ""))
        conversation_id = body.get("conversacion_id") or uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        chat = next((c for c in _MOCK_CHATS if c["conversacion_id"] == conversation_id), None)
        if chat is None:
            question = body.get("pregunta", "")
            chat = {
                "conversacion_id": conversation_id,
                "titulo": question.strip()[:40] + ("…" if len(question.strip()) > 40 else ""),
                "created_at": now,
                "updated_at": now,
                "mensajes": [],
            }
            _MOCK_CHATS.append(chat)
        chat["updated_at"] = now
        chat["mensajes"].extend([
            {
                "message_id": uuid4().hex,
                "trace_id": response.trace_id,
                "role": "user",
                "contenido": body.get("pregunta", ""),
                "estado": "",
                "codigo_error": "",
                "timestamp": now,
                "fuentes": [],
            },
            {
                "message_id": uuid4().hex,
                "trace_id": response.trace_id,
                "role": "assistant",
                "contenido": response.texto,
                "estado": response.estado,
                "codigo_error": response.codigo_error,
                "timestamp": now,
                "fuentes": [source.to_dict() for source in response.fuentes],
            },
        ])
        return 200, {
            "trace_id": response.trace_id,
            "conversacion_id": conversation_id,
            "estado": response.estado,
            "texto": response.texto,
            "fuentes": [source.to_dict() for source in response.fuentes],
            "codigo_error": response.codigo_error,
        }
    return 404, {"estado": "error", "mensaje": "Ruta no disponible en el simulador."}


def _mock_response(pregunta: str) -> Response:
    time.sleep(1.2)
    text = pregunta.lower()
    if any(marker in text for marker in ("servidor_caido", "backend_caido", "agentes_caido")):
        return Response.error(codigo="servicio_no_disponible")
    if any(marker in text for marker in ("error_simulado", "simular_error", "timeout")):
        return Response.error(
            "Error 503: Motor de búsqueda vectorial BGE-M3 no disponible (timeout > 5s).",
            "error",
        )
    if len(text.split()) <= 2:
        return Response("¿Qué testigo o código aparece exactamente y en qué versión del vehículo?",
                        STATUS_CLARIFY, trace_id="t-demo")
    if "refrigerante" in text or "temperatura" in text:
        return Response(
            "**Causas posibles:** pérdida de refrigerante, termostato o sensor.\n\n"
            "**Seguridad:** no abrir el circuito con el motor caliente.\n\n"
            "**Procedimiento:** comprobar nivel en frío y fugas visibles.\n\n"
            "*(Respuesta de ejemplo del modo simulado)*",
            STATUS_OK,
            [Source("Manual_ejemplo", "2.1", 128, ["V1.1", "V2.0"], False, "c45"),
             Source("Boletin_ejemplo_014", "Comprobaciones previas", 3, ["V1.0"], True, "c12")],
            trace_id="t-demo")
    if "tiempo" in text or "receta" in text:
        return Response("Solo puedo responder consultas sobre la documentación técnica del vehículo.",
                        STATUS_OUT_OF_SCOPE, trace_id="t-demo")
    return Response("No hay evidencia suficiente en la documentación para responder esto.",
                    STATUS_NO_EVIDENCE, trace_id="t-demo")
