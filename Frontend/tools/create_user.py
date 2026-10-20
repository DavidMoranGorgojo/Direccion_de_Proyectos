"""Crea o actualiza un usuario del modo local simulado.

Uso:  python tools/create_user.py
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.auth import USERS_FILE, add_user  # noqa: E402

user = input("Usuario: ").strip()
pwd = getpass.getpass("Contraseña: ")
if not user or len(pwd) < 6:
    sys.exit("Usuario vacío o contraseña de menos de 6 caracteres.")
if pwd != getpass.getpass("Repite la contraseña: "):
    sys.exit("Las contraseñas no coinciden.")
add_user(user, pwd)
print(f"Usuario «{user.lower()}» guardado en {USERS_FILE}")
