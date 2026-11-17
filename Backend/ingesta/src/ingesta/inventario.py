"""Inventario y clasificación de los PDF del corpus (paso 5.1 del diseño de ingesta)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from . import config
from .extraccion import Elemento, extraer

RE_CODIGO = re.compile(r"HTM240-([A-Z]{3})-\d{3}")
RE_VERSION = re.compile(r"Versi[oó]n(?: del procedimiento)?:\s*(\d+\.\d+)")
RE_FECHA = re.compile(r"Fecha(?: de entrada en vigor)?:\s*(\d{4}-\d{2}-\d{2})")
RE_VERSION_VEHICULO = re.compile(r"V\d\.\d")


@dataclass
class Documento:
    ruta: Path
    codigo: str
    tipo: str
    titulo: str
    version_documento: str
    fecha_revision: Optional[str]
    obsoleto: bool
    sustituido_por: Optional[str]
    versiones_vehiculo: List[str]
    vigente_para: List[str]
    elementos: List[Elemento]
    avisos: List[str] = field(default_factory=list)

    @property
    def doc_id(self) -> str:
        return f"{self.codigo}@{self.version_documento}"

    @property
    def tipo_documento(self) -> str:
        return config.TIPO_DOCUMENTO[self.tipo]

    def fila(self) -> dict:
        """Fila de la tabla conocimiento.documento."""
        return {
            "doc_id": self.doc_id,
            "codigo": self.codigo,
            "tipo_documento": self.tipo_documento,
            "titulo": self.titulo,
            "version_documento": self.version_documento,
            "fecha_revision": self.fecha_revision,
            "obsoleto": self.obsoleto,
            "sustituido_por": self.sustituido_por,
            "versiones_vehiculo": self.versiones_vehiculo,
            "vigente_para": self.vigente_para,
        }


def inventariar(entrada: Path) -> Tuple[List[Path], List[dict]]:
    """Lista los PDF a ingestar y los excluidos con su motivo."""
    pdfs, excluidos = [], []
    for ruta in sorted(entrada.rglob("*.pdf")):
        if ruta.stem in config.COMPILADOS:
            excluidos.append({"archivo": ruta.name, "motivo": "Compilado: duplica los documentos individuales y mezcla obsoleto con vigente."})
        elif not RE_CODIGO.search(ruta.name):
            excluidos.append({"archivo": ruta.name, "motivo": "El nombre no contiene un código de documento HTM240-XXX-NNN."})
        elif RE_CODIGO.search(ruta.name).group(1) not in config.TIPO_DOCUMENTO:
            excluidos.append({"archivo": ruta.name, "motivo": "Tipo de documento desconocido."})
        else:
            pdfs.append(ruta)
    return pdfs, excluidos


def _secciones_texto(elementos: List[Elemento], nombre: str) -> str:
    """Texto de la sección con ese encabezado exacto (para leer la aplicabilidad de un PRC)."""
    dentro, partes = False, []
    for e in elementos:
        if e.tipo == "encabezado":
            dentro = e.texto == nombre
        elif dentro:
            partes.append(e.texto)
    return " ".join(partes)


def _versiones_vehiculo(tipo: str, codigo: str, doc_id: str, cabecera: str, elementos: List[Elemento]) -> List[str]:
    if tipo == "BOL":
        return config.VERSIONES_BOLETIN.get(codigo, config.VERSIONES_VEHICULO)
    if doc_id in config.VIGENTE_PARA:
        return config.VIGENTE_PARA[doc_id]
    match = re.search(r"Aplicable a:([^(|]*)", cabecera)
    texto = match.group(1) if match else ""
    if not texto and tipo == "PRC":
        # Solo la primera frase: «V1.1 y V2.0. Para V1.0 consultar la versión previa...»
        texto = re.split(r"\.\s", _secciones_texto(elementos, "Aplicabilidad"), maxsplit=1)[0]
    if "Todas" in texto:
        return list(config.VERSIONES_VEHICULO)
    versiones = [v for v in config.VERSIONES_VEHICULO if v in RE_VERSION_VEHICULO.findall(texto)]
    return versiones or list(config.VERSIONES_VEHICULO)


def leer_documento(ruta: Path) -> Documento:
    elementos = extraer(ruta)
    if not elementos:
        raise ValueError("El PDF no contiene texto extraíble.")
    codigo = RE_CODIGO.search(ruta.name).group(0)
    tipo = codigo.split("-")[1]
    avisos = []

    titulo_completo = next((e.texto for e in elementos if e.tipo == "titulo"), codigo)
    titulo = titulo_completo.split(f"{codigo} — ", 1)[-1]
    cabecera = " | ".join(e.texto for e in elementos if e.tipo == "cabecera")

    obsoleto = "SUSTITUIDO" in ruta.name.upper() or titulo_completo.startswith("DOCUMENTO SUSTITUIDO")
    match_version = RE_VERSION.search(cabecera)
    if match_version:
        version = match_version.group(1)
    else:
        version = "1.0"
        avisos.append("Sin versión en la cabecera: se asigna 1.0 por defecto.")
    match_fecha = RE_FECHA.search(cabecera)
    fecha = match_fecha.group(1) if match_fecha else None
    if fecha is None:
        avisos.append("Sin fecha en la cabecera: fecha_revision queda a null.")

    doc_id = f"{codigo}@{version}"
    sustituido_por = config.SUSTITUCIONES.get(doc_id) if obsoleto else None
    if obsoleto and sustituido_por is None:
        avisos.append("Documento sustituido sin entrada en config.SUSTITUCIONES.")
    if not obsoleto and doc_id in config.SUSTITUCIONES:
        avisos.append("Figura como sustituido en config.SUSTITUCIONES pero el PDF no está marcado como tal.")

    return Documento(
        ruta=ruta,
        codigo=codigo,
        tipo=tipo,
        titulo=titulo,
        version_documento=version,
        fecha_revision=fecha,
        obsoleto=obsoleto,
        sustituido_por=sustituido_por,
        versiones_vehiculo=_versiones_vehiculo(tipo, codigo, doc_id, cabecera, elementos),
        vigente_para=config.VIGENTE_PARA.get(doc_id, []),
        elementos=elementos,
        avisos=avisos,
    )
