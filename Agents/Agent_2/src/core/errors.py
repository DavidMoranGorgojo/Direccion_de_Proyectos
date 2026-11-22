"""Códigos de error estándar de la recuperación (CTR-002 / CTR-004).

El Agente 1 solo acepta estos códigos. Cualquier fallo que no encaje en uno de
ellos se comunica como ``servicio_no_disponible`` y nunca como una lista vacía.
"""

CODIGOS_ERROR = frozenset(
    {
        "entrada_invalida",
        "modelo_no_disponible",
        "modelo_incompatible",
        "indice_no_disponible",
        "tiempo_agotado",
        "error_verificacion",
        "servicio_no_disponible",
    }
)

CODIGO_ERROR_POR_DEFECTO = "servicio_no_disponible"


class BackendRequestError(RuntimeError):
    """Fallo del Backend que debe convertirse en estado ``error``.

    ``mensaje`` se propaga tal cual al Agente 1 como ``mensaje_error``; nunca
    se convierte en una respuesta vacía porque eso significaría «sin
    evidencia».
    """

    def __init__(
        self,
        codigo_error=CODIGO_ERROR_POR_DEFECTO,
        mensaje="Fallo del Backend.",
    ):
        if codigo_error not in CODIGOS_ERROR:
            raise ValueError(
                f"Código de error no estándar: {codigo_error!r}"
            )

        super().__init__(mensaje)
        self.codigo_error = codigo_error
        self.mensaje = mensaje
