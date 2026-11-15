"""Búsqueda vectorial de ARSOFT-CTR-002 ed. 1.1 (POST /conocimiento/vectorial).

El módulo no crea la aplicación ni la conexión: se monta en la API con una línea, pasándole
cómo abrir la conexión y, si procede, la dependencia de acceso (token de servicio):

    from app.vectorial import crear_router
    app.include_router(crear_router(connect, service_access))   # los de links.py
"""

from .router import crear_router

__all__ = ["crear_router"]
