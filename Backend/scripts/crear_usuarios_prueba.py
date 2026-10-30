"""Crea las tablas (si no existen) y los usuarios de prueba.

Uso (desde la raíz del repo):
    DATABASE_URL=postgresql+psycopg://arsoft:arsoft@localhost:5432/arsoft python Backend/scripts/crear_usuarios_prueba.py

Es idempotente: si un usuario ya existe, no lo toca.
Las contraseñas son SOLO para pruebas; no usar en producción.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Usuario  # noqa: E402
from app.security import hash_password  # noqa: E402

USUARIOS_PRUEBA = [
    {"username": "admin", "nombre": "Administrador de pruebas", "rol": "admin", "password": "admin123"},
    {"username": "usuario1", "nombre": "Usuario de pruebas 1", "rol": "usuario", "password": "usuario123"},
    {"username": "usuario2", "nombre": "Usuario de pruebas 2", "rol": "usuario", "password": "usuario123"},
    {"username": "inactivo", "nombre": "Usuario desactivado", "rol": "usuario", "password": "usuario123", "activo": False},
]


def crear_usuarios_prueba(session) -> list[str]:
    creados = []
    for u in USUARIOS_PRUEBA:
        if session.scalar(select(Usuario).where(Usuario.username == u["username"])):
            continue
        session.add(Usuario(
            username=u["username"],
            nombre=u["nombre"],
            rol=u["rol"],
            activo=u.get("activo", True),
            password_hash=hash_password(u["password"]),
        ))
        creados.append(u["username"])
    session.commit()
    return creados


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        creados = crear_usuarios_prueba(s)
    print("Usuarios creados:", ", ".join(creados) if creados else "ninguno (ya existían)")
