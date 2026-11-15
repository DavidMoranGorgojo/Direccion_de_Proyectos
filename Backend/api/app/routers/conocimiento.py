"""POST /conocimiento/vectorial (ARSOFT-CTR-002 ed. 1.1, Agentes → Backend)."""

import psycopg
from fastapi import APIRouter, Depends

from ..busqueda import buscar_vectorial
from ..db import get_conn
from ..esquemas import PeticionVectorial, RespuestaBusqueda

router = APIRouter(prefix="/conocimiento", tags=["conocimiento"])


@router.post("/vectorial", response_model=RespuestaBusqueda)
def vectorial(peticion: PeticionVectorial, conn: psycopg.Connection = Depends(get_conn)):
    return buscar_vectorial(conn, peticion)
