"""Sesión actual (usuario, id y token si existe). Se rellena al iniciar sesión."""
user: str | None = None
token: str | None = None
user_id: str = ""


def start(username: str, tok: str | None, uid: str = "") -> None:
    global user, token, user_id
    user, token, user_id = username, tok, uid


def clear() -> None:
    start(None, None, "")
