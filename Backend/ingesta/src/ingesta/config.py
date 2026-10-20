"""Constantes y reglas del corpus ThermoDrive HTM-240.

Fuentes: ARSOFT-CTR-002 ed. 0.4 (docx de Dirección), ARSOFT-MEM-003 y el diseño
«Ingesta de la documentación» (ARSOFT-DIS, 2026-10-16). Los valores marcados como
PROVISIONAL dependen de puntos abiertos del contrato.
"""

import os

MODELO_EMBEDDINGS = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
DIMENSIONES = 1024

# CTR-002 §5.2: Backend inyecta "passage: " antes de vectorizar cada chunk.
# El diseño de ingesta y TEC-001 dicen que bge-m3 no usa prefijos; lo que importa es
# que coincida con lo que hace Agentes en consulta. Se puede cambiar sin tocar código.
PREFIJO_PASSAGE = os.getenv("EMBEDDING_PREFIX", "passage: ")

# Tamaño máximo del texto de un chunk, medido con el tokenizador de bge-m3.
# El límite del reranker es 512; se deja margen para el prefijo y los tokens especiales.
MAX_TOKENS = int(os.getenv("MAX_TOKENS_CHUNK", "500"))

VERSIONES_VEHICULO = ["V1.0", "V1.1", "V2.0"]

# CTR-002 §5.3 define DTC, MNT, CAT y BOL. El resto es PROVISIONAL (punto abierto del contrato).
TIPO_DOCUMENTO = {
    "DTC": "codigo_averia",
    "MNT": "mantenimiento",
    "CAT": "catalogo",
    "BOL": "boletin",
    "MAN": "manual",
    "OPE": "operacion",
    "PRC": "procedimiento",
    "DIA": "diagnostico",
    "ADV": "testigos",
    "SEG": "seguridad",
    "HIS": "caso_servicio",
    "ESQ": "esquema",
    "DIC": "diccionario",
}

# El compilado duplica los documentos individuales y mezcla obsoleto con vigente: no se indexa.
COMPILADOS = {"HTM240_Documentacion_Completa_Alumnos"}

# Documentos sustituidos (MEM-003 §2): doc_id obsoleto -> doc_id que lo sustituye.
SUSTITUCIONES = {
    "HTM240-MNT-001@1.0": "HTM240-MNT-001@1.1",
    "HTM240-PRC-003@1.0": "HTM240-PRC-003@2.0",
}

# Versiones de vehículo para las que un documento sustituido sigue vigente (propuesta vigente_para).
VIGENTE_PARA = {
    "HTM240-PRC-003@1.0": ["V1.0"],
}

# Versiones afectadas por cada boletín (MEM-003 §3; el texto de los boletines es ambiguo para parsearlo).
VERSIONES_BOLETIN = {
    "HTM240-BOL-001": ["V1.0"],
    "HTM240-BOL-002": ["V1.1", "V2.0"],
    "HTM240-BOL-003": ["V1.0", "V1.1", "V2.0"],
    "HTM240-BOL-004": ["V1.0", "V1.1"],
    "HTM240-BOL-005": ["V2.0"],
    "HTM240-BOL-006": ["V1.0", "V1.1", "V2.0"],
    "HTM240-BOL-007": ["V2.0"],
}

# Qué fragmentos modifica cada boletín (MEM-003 §3). Una regla aplica a los chunks del
# documento indicado (doc_id o código) que cumplan todas las condiciones opcionales:
#   seccion: el nombre de la sección empieza por este texto
#   contiene: el identificador aparece en ids_referenciados o en la sección
REGLAS_BOLETINES = [
    {"boletin": "BOL-001", "documento": "HTM240-MNT-001@1.1", "seccion": "1."},
    {"boletin": "BOL-002", "documento": "HTM240-PRC-003"},
    {"boletin": "BOL-003", "documento": "HTM240-DTC-001", "seccion": "HTM-0142"},
    {"boletin": "BOL-003", "documento": "HTM240-DIA-001", "seccion": "4.3"},
    {"boletin": "BOL-003", "documento": "HTM240-MAN-001", "seccion": "9."},
    {"boletin": "BOL-003", "documento": "HTM240-HIS-001", "contiene": "HTM-0142"},
    {"boletin": "BOL-004", "documento": "HTM240-CAT-001", "seccion": "CMP-25"},
    {"boletin": "BOL-004", "documento": "HTM240-DTC-001", "seccion": "HTM-0501"},
    {"boletin": "BOL-005", "documento": "HTM240-CAT-001", "seccion": "CMP-15"},
    {"boletin": "BOL-006", "documento": "HTM240-MNT-001@1.0"},
    {"boletin": "BOL-007", "documento": "HTM240-DIA-001", "seccion": "4.6"},
]

# Secciones de un procedimiento PRC que no se separan de los pasos (Riesgos, EPI, condiciones previas).
SECCIONES_PRC_PREVIAS = [
    "Objetivo", "Aplicabilidad", "Perfil autorizado", "Riesgos",
    "Equipos de protección individual", "Herramientas necesarias", "Condiciones previas",
]
SECCIONES_PRC_SEGURIDAD = ["Riesgos", "Equipos de protección individual", "Condiciones previas"]
SECCION_PRC_PASOS = "Pasos"
