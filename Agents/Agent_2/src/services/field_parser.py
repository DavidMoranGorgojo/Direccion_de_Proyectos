"""Validación común de campos CTR-002.

La usan el parser vectorial (A2-02) y el empaquetado de evidencias (A2-07), y
la puede reutilizar el parser léxico (A2-03). Cada módulo crea un
``FieldParser`` con sus propias clases de error, de modo que los mensajes y las
excepciones de cada etapa siguen siendo los suyos.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Optional

from ..models.ctr_002 import ChunkMetadata

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class FieldParser:
    """Lee y valida campos de un diccionario ya decodificado.

    ``contract_error`` se lanza cuando falta un campo obligatorio y
    ``validation_error`` cuando el campo existe pero su tipo o valor no es
    válido. ``path`` es la ruta que aparece en el mensaje de error.
    """

    def __init__(self, contract_error: type, validation_error: type):
        self.contract_error = contract_error
        self.validation_error = validation_error

    def required(self, data: dict, field: str, path: str) -> Any:
        if field not in data:
            raise self.contract_error(f"Falta el campo obligatorio '{path}'")

        return data[field]

    def string(
        self,
        data: dict,
        field: str,
        path: str,
        *,
        non_empty: bool = False,
    ) -> str:
        value = self.required(data, field, path)

        if not isinstance(value, str):
            raise self.validation_error(f"El campo '{path}' debe ser un string")

        if non_empty and not value.strip():
            raise self.validation_error(
                f"El campo '{path}' debe ser un string no vacío"
            )

        return value

    def optional_string(self, data: dict, field: str, path: str) -> Optional[str]:
        value = self.required(data, field, path)

        if value is None:
            return None

        if not isinstance(value, str):
            raise self.validation_error(
                f"El campo '{path}' debe ser un string o null"
            )

        return value

    def integer(
        self,
        data: dict,
        field: str,
        path: str,
        *,
        positive: bool = False,
    ) -> int:
        value = self.required(data, field, path)

        if isinstance(value, bool) or not isinstance(value, int):
            raise self.validation_error(f"El campo '{path}' debe ser un entero")

        if positive and value < 1:
            raise self.validation_error(
                f"El campo '{path}' debe ser un entero mayor que cero"
            )

        return value

    def boolean(self, data: dict, field: str, path: str) -> bool:
        value = self.required(data, field, path)

        if not isinstance(value, bool):
            raise self.validation_error(f"El campo '{path}' debe ser un booleano")

        return value

    def string_list(self, data: dict, field: str, path: str) -> list[str]:
        value = self.required(data, field, path)

        if not isinstance(value, list):
            raise self.validation_error(f"El campo '{path}' debe ser una lista")

        for posicion, item in enumerate(value):
            if not isinstance(item, str):
                raise self.validation_error(
                    f"El campo '{path}[{posicion}]' debe ser un string"
                )

        return list(value)

    def finite_number(
        self,
        data: dict,
        field: str,
        path: str,
        *,
        unit_interval: bool = False,
    ) -> float:
        """Número finito; con ``unit_interval`` además debe estar en [0, 1]."""

        value = self.required(data, field, path)
        mensaje = f"El campo '{path}' debe ser un número finito"
        if unit_interval:
            mensaje += " entre 0 y 1"

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self.validation_error(mensaje)

        try:
            finito = math.isfinite(value)
        except OverflowError:
            finito = False

        if not finito or (unit_interval and not 0 <= value <= 1):
            raise self.validation_error(mensaje)

        return float(value)

    def optional_date(self, data: dict, field: str, path: str) -> Optional[str]:
        """Fecha ``YYYY-MM-DD`` válida o ``null``; la clave es obligatoria."""

        value = self.required(data, field, path)

        if value is None:
            return None

        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise self.validation_error(
                f"El campo '{path}' debe tener formato YYYY-MM-DD o ser null"
            )

        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise self.validation_error(
                f"El campo '{path}' debe ser una fecha válida"
            ) from error

        return value

    def chunk_metadata(
        self,
        data: dict,
        base: str,
        *,
        citable: bool = False,
    ) -> ChunkMetadata:
        """Lee los metadatos CTR-002 de un chunk con estructura plana.

        Con ``citable`` exige origen citable: ``documento`` y ``seccion`` no
        vacíos y ``pagina`` mayor que cero (CTR-004 §5).
        """

        return ChunkMetadata(
            documento=self.string(
                data, "documento", f"{base}.documento", non_empty=citable
            ),
            seccion=self.string(
                data, "seccion", f"{base}.seccion", non_empty=citable
            ),
            pagina=self.integer(
                data, "pagina", f"{base}.pagina", positive=citable
            ),
            versiones=self.string_list(data, "versiones", f"{base}.versiones"),
            componente=self.string(data, "componente", f"{base}.componente"),
            tipo_documento=self.string(
                data, "tipo_documento", f"{base}.tipo_documento"
            ),
            obsoleto=self.boolean(data, "obsoleto", f"{base}.obsoleto"),
            sustituido_por=self.optional_string(
                data, "sustituido_por", f"{base}.sustituido_por"
            ),
            vigente_para=self.string_list(
                data, "vigente_para", f"{base}.vigente_para"
            ),
            fecha_revision=self.optional_date(
                data, "fecha_revision", f"{base}.fecha_revision"
            ),
            orden_en_seccion=self.integer(
                data, "orden_en_seccion", f"{base}.orden_en_seccion"
            ),
            version_documento=self.string(
                data, "version_documento", f"{base}.version_documento"
            ),
            afectado_por=self.string_list(
                data, "afectado_por", f"{base}.afectado_por"
            ),
            ids_referenciados=self.string_list(
                data, "ids_referenciados", f"{base}.ids_referenciados"
            ),
        )


__all__ = ["FieldParser"]
