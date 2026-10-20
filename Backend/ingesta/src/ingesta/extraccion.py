"""Extracción y limpieza del texto de un PDF del corpus.

Produce una lista de elementos en orden de lectura: título, cabecera, encabezados de
sección, párrafos y filas de tabla, cada uno con su página. Se eliminan la cabecera
repetida, el aviso de documentación sintética y los números de página; se unen las
palabras partidas por guion sin romper los códigos (HTM240-BOL-002, CMP-18), y las
tablas se reconstruyen fila a fila («Columna: valor | Columna: valor»).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pymupdf as fitz

TAM_TITULO = 13.5
TAM_ENCABEZADO = 11.5
SEPARACION_COLUMNAS = 25  # puntos mínimos entre el inicio de dos columnas de una tabla
TOLERANCIA_Y = 2.5

RE_INICIO_PARRAFO = re.compile(r"^(?:[•–\-]\s|\d+\.\s|[a-z]\)\s)")
RE_CABECERA = re.compile(r"^(Documento|Código|Fecha de entrada|Total de|Estado:)")
RE_INICIO_CELDA = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9¿“\"]")


@dataclass
class Elemento:
    tipo: str  # titulo | cabecera | encabezado | parrafo | fila
    texto: str
    pagina: int


@dataclass
class _Linea:
    texto: str
    x0: float
    y0: float
    x1: float
    tamano: float
    negrita: bool


def unir(previo: str, siguiente: str, compuestos: set) -> str:
    """Une dos trozos de línea: quita el guion de fin de línea salvo en códigos y compuestos."""
    if not previo:
        return siguiente
    if previo.endswith("-") and not previo.endswith(" -"):
        palabra_previa = re.search(r"[\wáéíóúñÁÉÍÓÚÑ]+-$", previo)
        palabra_siguiente = re.match(r"[\wáéíóúñÁÉÍÓÚÑ]+", siguiente)
        if siguiente[:1].islower() and palabra_previa and palabra_siguiente:
            compuesto = (palabra_previa.group(0)[:-1] + palabra_siguiente.group(0)).lower()
            if compuesto in compuestos:
                return previo + siguiente
            return previo[:-1] + siguiente
        return previo + siguiente
    return previo + " " + siguiente


def _compuestos(doc: fitz.Document) -> set:
    """Palabras compuestas con guion que aparecen enteras en el documento (aceite-refrigerante)."""
    texto = " ".join(pagina.get_text("text") for pagina in doc)
    return {c.lower().replace("-", "") for c in re.findall(r"[a-záéíóúñ]+-[a-záéíóúñ]+", texto)}


def _bloques(pagina: fitz.Page) -> List[List[_Linea]]:
    """Bloques de la página sin cabecera repetida, aviso de documentación sintética ni número de página."""
    alto = pagina.rect.height
    bloques = []
    for bloque in pagina.get_text("dict")["blocks"]:
        lineas = []
        for l in bloque.get("lines", []):
            texto = "".join(s["text"] for s in l["spans"]).strip()
            if not texto:
                continue
            span = l["spans"][0]
            linea = _Linea(texto, l["bbox"][0], l["bbox"][1], l["bbox"][2], span["size"], bool(span["flags"] & 16))
            if linea.tamano < 9.5 and texto.startswith("ThermoDrive HTM-240 — Documentaci"):
                continue
            if texto.isdigit() and linea.y0 > 0.9 * alto:
                continue
            lineas.append(linea)
        if not lineas:
            continue
        primera = lineas[0].texto.upper()
        if primera.startswith("DOCUMENTACI") and "SINT" in primera:
            continue
        bloques.append(lineas)
    return bloques


def _columnas_cabecera(lineas: List[_Linea]) -> Optional[List[float]]:
    """Si el bloque es la cabecera de una tabla (3 o más celdas alineadas en la misma altura), sus columnas."""
    y_primera = lineas[0].y0
    alineadas = sorted(l.x0 for l in lineas if abs(l.y0 - y_primera) <= TOLERANCIA_Y)
    columnas = []
    for x in alineadas:
        if not columnas or x - columnas[-1] > SEPARACION_COLUMNAS:
            columnas.append(x)
    return columnas if len(columnas) >= 3 else None


def _columna(x0: float, columnas: List[float]) -> int:
    candidatas = [i for i, x in enumerate(columnas) if x <= x0 + 5]
    return candidatas[-1] if candidatas else 0


def _filas_tabla(lineas: List[_Linea], columnas: List[float], compuestos: set) -> List[List[str]]:
    """Agrupa las líneas de una tabla en filas: una fila empieza a la altura en la que casi todas
    las columnas arrancan una celda (texto en mayúscula, cifra o código)."""
    bandas: List[List[_Linea]] = []
    for linea in sorted(lineas, key=lambda l: (l.y0, l.x0)):
        if bandas and abs(linea.y0 - bandas[-1][0].y0) <= TOLERANCIA_Y:
            bandas[-1].append(linea)
        else:
            bandas.append([linea])
    minimo = max(2, len(columnas) - 1)
    filas: List[List[str]] = []
    for banda in bandas:
        inicios = sum(1 for l in banda if RE_INICIO_CELDA.match(l.texto))
        if not filas or inicios >= minimo:
            filas.append([""] * len(columnas))
        for linea in sorted(banda, key=lambda l: l.x0):
            i = _columna(linea.x0, columnas)
            filas[-1][i] = unir(filas[-1][i], linea.texto, compuestos)
    return filas


def extraer(ruta: Path) -> List[Elemento]:
    doc = fitz.open(ruta)
    compuestos = _compuestos(doc)
    elementos: List[Elemento] = []

    for num_pagina, pagina in enumerate(doc, start=1):
        bloques = _bloques(pagina)
        i = 0
        while i < len(bloques):
            lineas = bloques[i]
            primera = lineas[0]

            columnas = None if primera.negrita else _columnas_cabecera(lineas)
            if columnas:
                # Tabla: la cabecera da los nombres; siguen las líneas hasta un encabezado o un párrafo a todo el ancho
                nombres = _filas_tabla(lineas, columnas, compuestos)[0]
                cuerpo: List[_Linea] = []
                i += 1
                while i < len(bloques):
                    siguiente = bloques[i]
                    if siguiente[0].negrita or any(l.x1 > columnas[1] + 40 and _columna(l.x0, columnas) == 0
                                                  and len(l.texto) > 60 for l in siguiente):
                        break
                    cuerpo.extend(siguiente)
                    i += 1
                for valores in _filas_tabla(cuerpo, columnas, compuestos) if cuerpo else []:
                    fila = " | ".join(f"{n}: {v}" if n else v for n, v in zip(nombres, valores) if v)
                    elementos.append(Elemento("fila", fila, num_pagina))
                if not cuerpo:
                    elementos.append(Elemento("parrafo", " | ".join(n for n in nombres if n), num_pagina))
                continue
            i += 1

            if primera.negrita and primera.tamano >= TAM_ENCABEZADO:
                texto = ""
                for l in lineas:
                    texto = unir(texto, l.texto, compuestos)
                tipo = "titulo" if primera.tamano >= TAM_TITULO else "encabezado"
                elementos.append(Elemento(tipo, texto, num_pagina))
                continue

            tipo = "cabecera" if primera.negrita and RE_CABECERA.match(primera.texto) else "parrafo"
            parrafos: List[str] = []
            for l in lineas:
                if not parrafos or (RE_INICIO_PARRAFO.match(l.texto) and not parrafos[-1].endswith("-")):
                    parrafos.append(l.texto)
                else:
                    parrafos[-1] = unir(parrafos[-1], l.texto, compuestos)

            # Continuación de un párrafo que viene del bloque o la página anterior
            previo = elementos[-1] if elementos else None
            if previo is not None and previo.tipo == tipo and parrafos[0][:1].islower():
                previo.texto = unir(previo.texto, parrafos.pop(0), compuestos)
            for p in parrafos:
                elementos.append(Elemento(tipo, p, num_pagina))
    return elementos
