"""Crea los usuarios de prueba en aplicacion.usuario (CTR-005). Es idempotente: no toca los que ya existen.

Solo para desarrollo y pruebas. Con el despliegue de Apptainer levantado:
    apptainer exec instance://arsoft-api python -m app.usuarios_prueba
Fuera del contenedor (desde Backend/api, con DATABASE_URL y el PYTHONPATH de shared/):
    python -m app.usuarios_prueba
"""

from .links import connect
from .sesiones import hash_password

USUARIOS_PRUEBA = [
    {"nombre_usuario": "admin", "nombre": "Administrador de pruebas", "rol": "admin", "password": "admin123"},
    {"nombre_usuario": "usuario1", "nombre": "Usuario de pruebas 1", "rol": "usuario", "password": "usuario123"},
    {"nombre_usuario": "usuario2", "nombre": "Usuario de pruebas 2", "rol": "usuario", "password": "usuario123"},
    {"nombre_usuario": "inactivo", "nombre": "Usuario desactivado", "rol": "usuario", "password": "usuario123",
     "activo": False},
]


def crear_usuarios_prueba(conn) -> list[str]:
    creados = []
    for u in USUARIOS_PRUEBA:
        fila = conn.execute("""
            INSERT INTO aplicacion.usuario (nombre_usuario, nombre, password_hash, rol, activo)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (nombre_usuario) DO NOTHING RETURNING nombre_usuario
        """, (u["nombre_usuario"], u["nombre"], hash_password(u["password"]), u["rol"],
              u.get("activo", True))).fetchone()
        if fila:
            creados.append(fila["nombre_usuario"])
    return creados


if __name__ == "__main__":
    with connect() as conexion:
        nuevos = crear_usuarios_prueba(conexion)
    print("Creados: " + (", ".join(nuevos) if nuevos else "ninguno (ya existían)"))
