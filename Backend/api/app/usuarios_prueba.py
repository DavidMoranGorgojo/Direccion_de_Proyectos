"""Crea los usuarios de prueba en aplicacion.usuario (CTR-005). Es idempotente: no toca los que ya existen.

NO EJECUTAR EN PRODUCCIÓN: las contraseñas son públicas (están en este archivo y en Backend/readme.md)
y el usuario «admin» puede leer todo el registro de consultas. Por eso el script exige --desarrollo.

Con el despliegue de Apptainer levantado:
    apptainer exec instance://arsoft-api python -m app.usuarios_prueba --desarrollo
Fuera del contenedor (desde Backend/api, con DATABASE_URL y el PYTHONPATH de shared/):
    python -m app.usuarios_prueba --desarrollo
"""

import sys

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
    if "--desarrollo" not in sys.argv[1:]:
        sys.exit("Usuarios de prueba con contraseñas públicas: solo para desarrollo, nunca en producción.\n"
                 "Si es un entorno de desarrollo, repite el comando con --desarrollo.")
    with connect() as conexion:
        nuevos = crear_usuarios_prueba(conexion)
    print("Creados: " + (", ".join(nuevos) if nuevos else "ninguno (ya existían)"))
