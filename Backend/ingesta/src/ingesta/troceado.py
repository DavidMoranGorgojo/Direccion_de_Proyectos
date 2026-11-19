"""Troceado estructural (paso 5.5 del diseño de ingesta).

Reglas por tipo:
- BOL y documentos sustituidos: documento completo en un fragmento.
- PRC: procedimiento completo si cabe; si no, preparación, pasos (cada grupo repite título,
  riesgos, EPI y condiciones previas) y cierre. Nunca se separan los avisos de los pasos.
- DTC: un código de avería por fragmento. CAT: una ficha CMP. HIS: un caso. DIA: una rama.
- Resto: una sección por fragmento.
Si una unidad supera MAX_TOKENS se parte por párrafos o filas, repitiendo su encabezado.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, List, Tuple

from . import config
from .inventario import Documento

# Unidades que en el PDF son párrafos y no encabezados
RE_SUBUNIDAD = {"DTC": re.compile(r"^HTM-\d{4} — ")}


@dataclass
class Seccion:
    titulo: str
    pagina: int
    lineas: List[Tuple[str, int]] = field(default_factory=list)  # (texto, página)

    def texto(self) -> str:
        return "\n".join([self.titulo] + [t for t, _ in self.lineas])


@dataclass
class Fragmento:
    seccion: str
    pagina: int
    orden_en_seccion: int
    texto: str


def _secciones(doc: Documento) -> Tuple[Seccion, List[Seccion]]:
    """Separa el encabezado del documento (título, cabecera e introducción) de sus secciones."""
    intro = Seccion(doc.titulo, 1)
    secciones: List[Seccion] = []
    subunidad = RE_SUBUNIDAD.get(doc.tipo)
    for e in doc.elementos:
        if e.tipo == "encabezado" or (subunidad and e.tipo == "parrafo" and subunidad.match(e.texto)):
            secciones.append(Seccion(e.texto, e.pagina))
        elif e.tipo == "titulo":
            intro.lineas.append((e.texto, e.pagina))
        elif secciones:
            secciones[-1].lineas.append((e.texto, e.pagina))
        else:
            intro.lineas.append((e.texto, e.pagina))
    # Encabezados sin cuerpo (por ejemplo «Subsistema: ...» en DTC) no forman fragmento
    return intro, [s for s in secciones if s.lineas]


class Troceador:
    def __init__(self, contar_tokens: Callable[[str], int], max_tokens: int = config.MAX_TOKENS):
        self.contar = contar_tokens
        self.max = max_tokens

    def _cabe(self, texto: str) -> bool:
        return self.contar(texto) <= self.max

    def _partir_linea(self, linea: str, cabecera: str) -> List[str]:
        """Parte una línea demasiado larga por frases y, si hace falta, por palabras."""
        trozos, actual = [], ""
        piezas = re.split(r"(?<=[.;])\s+", linea)
        if len(piezas) == 1:
            piezas = linea.split(" ")
        for pieza in piezas:
            candidato = f"{actual} {pieza}".strip()
            if actual and not self._cabe(f"{cabecera}\n{candidato}"):
                trozos.append(actual)
                actual = pieza
            else:
                actual = candidato
        return trozos + [actual] if actual else trozos

    def _agrupar(self, cabecera: str, lineas: List[Tuple[str, int]], pagina_cabecera: int) -> List[Tuple[str, int]]:
        """Agrupa líneas en textos que no superan el máximo, cada uno precedido de la cabecera."""
        grupos: List[Tuple[str, int]] = []
        actual: List[str] = []
        pagina = None
        for texto, pag in lineas:
            piezas = [texto] if self._cabe(f"{cabecera}\n{texto}") else self._partir_linea(texto, cabecera)
            for pieza in piezas:
                if actual and not self._cabe("\n".join([cabecera] + actual + [pieza])):
                    grupos.append(("\n".join([cabecera] + actual), pagina))
                    actual, pagina = [], None
                actual.append(pieza)
                pagina = pagina or pag
        if actual:
            grupos.append(("\n".join([cabecera] + actual), pagina))
        return grupos or [(cabecera, pagina_cabecera)]

    def _seccion(self, seccion: Seccion, nombre: str = None) -> List[Fragmento]:
        nombre = nombre or seccion.titulo
        if self._cabe(seccion.texto()):
            pagina = seccion.lineas[0][1] if seccion.lineas else seccion.pagina
            return [Fragmento(nombre, min(seccion.pagina, pagina), 1, seccion.texto())]
        grupos = self._agrupar(seccion.titulo, seccion.lineas, seccion.pagina)
        return [Fragmento(nombre, pag, i, texto) for i, (texto, pag) in enumerate(grupos, start=1)]

    def _documento_completo(self, intro: Seccion, secciones: List[Seccion], nombre: str) -> List[Fragmento]:
        todo = Seccion(intro.lineas[0][0] if intro.lineas else intro.titulo, 1,
                       intro.lineas[1:] + [l for s in secciones for l in [(s.titulo, s.pagina)] + s.lineas])
        return self._seccion(todo, nombre)

    def _procedimiento(self, intro: Seccion, secciones: List[Seccion]) -> List[Fragmento]:
        todo = self._documento_completo(intro, secciones, "Procedimiento completo")
        if len(todo) == 1:
            return todo
        titulo = intro.lineas[0][0] if intro.lineas else intro.titulo
        por_nombre = {s.titulo: s for s in secciones}
        previas = [s for s in secciones if s.titulo in config.SECCIONES_PRC_PREVIAS]
        pasos = por_nombre.get(config.SECCION_PRC_PASOS)
        cierre = [s for s in secciones if s not in previas and s is not pasos]

        def lineas(grupo: List[Seccion]) -> List[Tuple[str, int]]:
            return [l for s in grupo for l in [(s.titulo, s.pagina)] + s.lineas]

        def nombre(grupo: List[Seccion]) -> str:
            return grupo[0].titulo if len(grupo) == 1 else f"{grupo[0].titulo} a {grupo[-1].titulo}"

        fragmentos: List[Fragmento] = []
        if previas:
            fragmentos += self._seccion(Seccion(titulo, previas[0].pagina, intro.lineas[1:] + lineas(previas)), nombre(previas))
        if pasos:
            seguridad = [s for s in previas if s.titulo in config.SECCIONES_PRC_SEGURIDAD]
            contexto = "\n".join([titulo] + [t for t, _ in lineas(seguridad)] + [pasos.titulo])
            grupos = self._agrupar(contexto, pasos.lineas, pasos.pagina)
            fragmentos += [Fragmento(pasos.titulo, pag, i, texto) for i, (texto, pag) in enumerate(grupos, start=1)]
        if cierre:
            fragmentos += self._seccion(Seccion(titulo, cierre[0].pagina, lineas(cierre)), nombre(cierre))
        return fragmentos

    def trocear(self, doc: Documento) -> List[Fragmento]:
        intro, secciones = _secciones(doc)
        if doc.tipo == "BOL" or doc.obsoleto:
            return self._documento_completo(intro, secciones, "Documento completo")
        if doc.tipo == "PRC":
            return self._procedimiento(intro, secciones)
        fragmentos: List[Fragmento] = []
        if intro.lineas:
            fragmentos += self._seccion(Seccion(intro.lineas[0][0], 1, intro.lineas[1:]), doc.titulo)
        for seccion in secciones:
            fragmentos += self._seccion(seccion)
        return fragmentos
