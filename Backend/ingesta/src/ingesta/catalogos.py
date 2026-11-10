"""Catálogos versionados para Agentes (CTR-002 §5.4): códigos, términos, vehículos y componentes.

Se generan desde DTC-001, DIC-001 y CAT-001. La tabla de vehículos procede de ARSOFT-MEM-003 §4.
"""

import re
from typing import Dict, List

from .inventario import Documento
from .metadatos import RE_CMP, ids_referenciados

VEHICULOS = [
    {"version": "V1.0", "software_tcu": "v1.0", "calentador_ptc": "3 kW", "sensor_presion_bateria": "dedicado"},
    {"version": "V1.1", "software_tcu": "v1.1", "calentador_ptc": "3 kW", "sensor_presion_bateria": "dedicado"},
    {"version": "V2.0", "software_tcu": "v2.0", "calentador_ptc": "5 kW", "sensor_presion_bateria": "integrado en CMP-18"},
]

RE_CAMPO = re.compile(r"^•\s*([^:]+):\s*(.*)$")


def _campos(lineas: List[str]) -> Dict[str, str]:
    campos = {}
    for linea in lineas:
        match = RE_CAMPO.match(linea)
        if match:
            campos[match.group(1).strip()] = match.group(2).strip()
    return campos


def codigos(dtc: Documento) -> List[dict]:
    resultado, subsistema, actual = [], None, None
    for e in dtc.elementos:
        if e.tipo == "encabezado" and e.texto.startswith("Subsistema:"):
            subsistema = e.texto.split(":", 1)[1].strip()
        elif e.tipo == "parrafo" and re.match(r"^HTM-\d{4} — ", e.texto):
            codigo, descripcion = e.texto.split(" — ", 1)
            actual = {"codigo": codigo, "descripcion": descripcion, "subsistema": subsistema, "lineas": []}
            resultado.append(actual)
        elif actual is not None and e.tipo == "parrafo":
            actual["lineas"].append(e.texto)
    for c in resultado:
        campos = _campos(c.pop("lineas"))
        detalle = campos.get("Descripción", "")
        cmp = RE_CMP.findall(detalle)
        c.update({
            "detalle": detalle,
            "severidad": campos.get("Severidad"),
            "componente": cmp[0] if cmp else None,
            "testigos": re.findall(r"TES-\d{2}", campos.get("Testigos asociados", "")),
            "procedimiento": campos.get("Procedimiento recomendado"),
        })
    return resultado


def componentes(cat: Documento) -> List[dict]:
    resultado, actual = [], None
    for e in cat.elementos:
        if e.tipo == "encabezado" and re.match(r"^CMP-\d{2} — ", e.texto):
            codigo, nombre = e.texto.split(" — ", 1)
            actual = {"codigo": codigo, "nombre": nombre, "lineas": []}
            resultado.append(actual)
        elif actual is not None and e.tipo == "parrafo":
            actual["lineas"].append(e.texto)
    for c in resultado:
        campos = _campos(c.pop("lineas"))
        c["circuito"] = campos.get("Circuito / ubicación funcional")
    return resultado


def terminos(dic: Documento) -> List[dict]:
    resultado = []
    for e in dic.elementos:
        match = RE_CAMPO.match(e.texto) if e.tipo == "parrafo" else None
        if match:
            definicion = match.group(2).strip()
            resultado.append({
                "termino": match.group(1).strip(),
                "definicion": definicion,
                "referencias": ids_referenciados(definicion, dic.codigo),
            })
    return resultado


def generar(documentos: List[Documento], version: str) -> Dict[str, dict]:
    por_codigo = {d.codigo: d for d in documentos if not d.obsoleto}
    contenido = {"vehiculos": VEHICULOS}
    if "HTM240-DTC-001" in por_codigo:
        contenido["codigos"] = codigos(por_codigo["HTM240-DTC-001"])
    if "HTM240-DIC-001" in por_codigo:
        contenido["terminos"] = terminos(por_codigo["HTM240-DIC-001"])
    if "HTM240-CAT-001" in por_codigo:
        contenido["componentes"] = componentes(por_codigo["HTM240-CAT-001"])
    return {nombre: {"nombre": nombre, "version": version, "contenido": datos} for nombre, datos in contenido.items()}
