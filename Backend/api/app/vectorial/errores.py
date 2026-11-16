"""Errores del contrato CTR-002 (§4) con cuerpo plano: {"codigo": ..., "mensaje": ..., ...}."""

from fastapi.responses import JSONResponse


class ErrorContrato(Exception):
    def __init__(self, estado: int, codigo: str, mensaje: str, **extra):
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.extra = extra

    def respuesta(self) -> JSONResponse:
        return JSONResponse(status_code=self.estado,
                            content={"codigo": self.codigo, "mensaje": self.mensaje, **self.extra})


def indice_no_disponible(motivo: str) -> ErrorContrato:
    return ErrorContrato(503, "indice_no_disponible", motivo)


def peticion_invalida(errores_pydantic: list) -> ErrorContrato:
    # No se devuelve «input»: en una petición vectorial serían 1024 floats.
    errores = [{"campo": ".".join(str(p) for p in e["loc"]), "motivo": e["msg"]} for e in errores_pydantic]
    return ErrorContrato(400, "peticion_invalida", "La petición no cumple el contrato CTR-002.", errores=errores)
