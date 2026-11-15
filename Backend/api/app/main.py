"""API del Backend (FastAPI). Arranque: uvicorn app.main:app --port 8000 (desde Backend/api)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db, errores
from .routers import conocimiento


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.abrir_pool()
    yield
    db.cerrar_pool()


app = FastAPI(title="Backend ARSOFT", lifespan=lifespan)
errores.registrar(app)
app.include_router(conocimiento.router)
