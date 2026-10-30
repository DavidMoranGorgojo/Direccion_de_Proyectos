"""API de ARSOFT (FastAPI).

Módulos incluidos:
  - auth      · login (CTR-005)
  - chats     · historial de chats (CTR-006)
  - consultas · registro de consultas (CTR-003)
Aquí se añadirán los routers de búsqueda (CTR-002) y /health.
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.routers import auth, chats, consultas

app = FastAPI(title="ARSOFT API")


@app.exception_handler(RequestValidationError)
async def validacion(request: Request, exc: RequestValidationError):
    # CTR-005 pide un 422 con el formato de error de login
    if request.url.path == "/auth/login":
        return JSONResponse(
            status_code=422,
            content={"estado": "no_autenticado", "mensaje": "Faltan datos o el formato es incorrecto.",
                     "codigo_error": "datos_incompletos"},
        )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(consultas.router)
