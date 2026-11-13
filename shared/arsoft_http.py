"""Validación común de llamadas HTTP internas de ARSOFT."""

import hmac
import os

GENERIC_ERROR = "El asistente no está disponible, inténtalo de nuevo."
MAX_QUESTION_LENGTH = 2000
SERVICE_TOKEN_ENV = "ARSOFT_SERVICE_TOKEN"


def service_token_configured() -> bool:
    return bool(os.getenv(SERVICE_TOKEN_ENV, "").strip())


def service_headers() -> dict[str, str]:
    token = os.getenv(SERVICE_TOKEN_ENV, "")
    return {"Authorization": f"Bearer {token}"} if token.strip() else {}


def valid_service_token(authorization: str) -> bool:
    token = os.getenv(SERVICE_TOKEN_ENV, "")
    expected = f"Bearer {token}".encode("utf-8")
    supplied = authorization.encode("utf-8")
    return bool(token.strip() and hmac.compare_digest(supplied, expected))


def invalid_question(question: object) -> bool:
    return not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_LENGTH
