"""Tests de login, historial y registro de consultas. Usan SQLite en memoria (no hace falta Postgres)."""
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RAIZ / "Backend" / "api"))
sys.path.insert(0, str(_RAIZ / "Backend" / "scripts"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.db import Base, get_db
from app.main import app
from crear_usuarios_prueba import crear_usuarios_prueba


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with TestSession() as s:
        crear_usuarios_prueba(s)

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _token(client, username, password):
    r = client.post("/auth/login", json={"usuario": username, "contrasena": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(autouse=True)
def _limpiar_intentos():
    from app.routers.auth import _fallos
    _fallos.clear()
    yield
    _fallos.clear()


@pytest.fixture()
def h_user1(client):
    return _token(client, "usuario1", "usuario123")


@pytest.fixture()
def h_user2(client):
    return _token(client, "usuario2", "usuario123")


@pytest.fixture()
def h_admin(client):
    return _token(client, "admin", "admin123")
