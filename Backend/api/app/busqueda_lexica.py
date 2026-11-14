"""Búsqueda léxica BM25 de CTR-002 (``POST /conocimiento/lexica``).

BM25 (Okapi) en memoria sobre los chunks del índice activo: el corpus es pequeño
(cientos de chunks), así que no hace falta un índice de texto en PostgreSQL y se
obtiene un BM25 real. El contrato pide:

* los filtros se aplican como WHERE duro antes de puntuar;
* el tokenizador conserva los códigos de avería y las referencias (HTM-0142, CMP-18)
  como un único término, y normaliza mayúsculas y acentos;
* el score es el valor crudo de BM25 (sin RRF) y el texto devuelto va sin modificar.

Este módulo no depende de FastAPI ni de la base de datos, para poder probarlo solo.
"""

import math
import re
import threading
import unicodedata
from collections import Counter

from .busqueda import COLUMNAS, filtro_invalido

TOKENIZADOR = "bm25-v1: minusculas, sin acentos, identificadores con guion como un unico termino"
K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_SEPARADOR = re.compile(r"[-_.]")


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos (la ñ se conserva como n; no afecta a la recuperación)."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    """Un término por palabra; los identificadores con dígitos (HTM-0142, V1.1) no se parten."""
    terminos: list[str] = []
    for token in _TOKEN.findall(normalizar(texto)):
        if any(c.isdigit() for c in token):
            terminos.append(token)
        else:
            terminos.extend(_SEPARADOR.split(token))
    return terminos


def aplicable(fila: dict, version: str) -> bool:
    """Vigencia por versión: ``vigente_para`` decide la aplicabilidad.

    Un documento vigente aplica a las versiones del vehículo que cubre; un documento
    sustituido solo aplica donde ``vigente_para`` lo mantiene (p. ej. V1.0). Así no
    depende de que la ingesta rellene ``vigente_para`` en los documentos vigentes.
    """
    if version in (fila["vigente_para"] or []):
        return True
    return not fila["obsoleto"] and version in (fila["versiones"] or [])


def cumple(fila: dict, filtros: dict) -> bool:
    if filtros.get("version") is not None and not aplicable(fila, filtros["version"]):
        return False
    if filtros.get("componente") is not None and fila["componente"] != filtros["componente"]:
        return False
    if filtros.get("tipo_documento") is not None and fila["tipo_documento"] != filtros["tipo_documento"]:
        return False
    return True


class IndiceLexico:
    """Estadísticas BM25 de todo el índice; el filtro solo restringe qué chunks se puntúan."""

    def __init__(self, filas: list[dict]):
        self.filas = filas
        frecuencias: list[Counter] = []
        self.longitudes: list[int] = []
        self.postings: dict[str, list[int]] = {}
        for posicion, fila in enumerate(filas):
            tf = Counter(tokenizar(fila["texto"]))
            frecuencias.append(tf)
            self.longitudes.append(sum(tf.values()))
            for termino in tf:
                self.postings.setdefault(termino, []).append(posicion)
        self.frecuencias = frecuencias
        total = len(filas)
        self.longitud_media = (sum(self.longitudes) / total) if total else 0.0
        # IDF de Lucene/BM25+: siempre positivo, también para términos en más de la mitad del corpus.
        self.idf = {t: math.log(1 + (total - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}
        self.valores = {
            "version": {v for f in filas for v in (f["versiones"] or []) + (f["vigente_para"] or [])},
            "componente": {f["componente"] for f in filas},
            "tipo_documento": {f["tipo_documento"] for f in filas},
        }

    def validar(self, filtros: dict) -> None:
        """HTTP 400 con el campo y los valores válidos si un filtro apunta a un valor que no existe."""
        for campo, valor in filtros.items():
            if valor is not None and valor not in self.valores[campo]:
                raise filtro_invalido(campo, valor, self.valores[campo])

    def buscar(self, texto: str, filtros: dict, k: int) -> list[tuple[dict, float]]:
        """Los k mejores chunks por BM25 entre los que cumplen los filtros; sin coincidencias, lista vacía."""
        consulta = Counter(tokenizar(texto))
        puntuaciones: dict[int, float] = {}
        for termino, veces in consulta.items():
            idf = self.idf.get(termino)
            if idf is None:
                continue
            for posicion in self.postings[termino]:
                if posicion not in puntuaciones and not cumple(self.filas[posicion], filtros):
                    continue
                tf = self.frecuencias[posicion][termino]
                norma = K1 * (1 - B + B * self.longitudes[posicion] / self.longitud_media)
                puntuaciones[posicion] = puntuaciones.get(posicion, 0.0) + veces * idf * tf * (K1 + 1) / (tf + norma)
        orden = sorted(puntuaciones, key=lambda p: (-puntuaciones[p], self.filas[p]["chunk_id"]))
        return [(self.filas[p], puntuaciones[p]) for p in orden[:k]]


_cache: dict = {"clave": None, "indice": None}
_bloqueo = threading.Lock()


def indice_lexico(conn, indice: dict) -> IndiceLexico:
    """Índice BM25 del índice activo; se reconstruye solo cuando cambia la versión o el nº de chunks."""
    clave = (indice["version"], indice["n_chunks"])
    with _bloqueo:
        if _cache["clave"] != clave:
            filas = conn.execute(
                f"SELECT {COLUMNAS} FROM conocimiento.chunk c WHERE c.indice_version=%s ORDER BY c.chunk_id",
                (indice["version"],),
            ).fetchall()
            _cache["indice"], _cache["clave"] = IndiceLexico(filas), clave
        return _cache["indice"]
