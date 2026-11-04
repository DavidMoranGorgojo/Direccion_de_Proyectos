"""
AGENTE 1 (Conversacional y Preprocesamiento) — Reto IA Automoción
==================================================================
Versión corregida según revisión de código (PR).
Correcciones bloqueantes (1-7) y mejoras de robustez:
  1. Regex REF: exige dígitos para no romper palabras como 'refrigerante' o 'referencia'.
  2. Regex DTC: insensible a falsos positivos como 'Clase C 2019' y normaliza 'p0301' a 'P0301'.
  3. Regex versión: no rompe modelos ni cilindradas tipo 'Golf V 1.9 TDI'.
  4. Saludos: 'buenas tardes' y 'buenos días/dias' se limpian completamente (alternativas largas primero).
  5. max_tokens=512 y captura de JSON truncado/malformado como error (no aclaración).
  6. Simulador Agente 2 tolerante a valores null en filtros y query_busqueda.
  7. Validación estricta del esquema Query JSON (Pydantic / esquema formal CTR-004).
"""

import os
import re
import json
import time
import uuid
import logging
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

# ============================================================================
# CONFIGURACIÓN Y LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Agente1")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
MODELO_LLM = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ============================================================================
# 1. ESQUEMA FORMAL DEL QUERY JSON (CTR-004)
# ============================================================================
INTENCIONES_VALIDAS = {
    "diagnostico", "procedimiento", "especificacion", "normativa", "mantenimiento", "otro"
}
TIPOS_DOC_VALIDOS = {
    "manual", "ficha_tecnica", "procedimiento", "normativa", "otro", None
}

MAPA_SINONIMOS_INTENCION = {
    "fallo": "diagnostico", "averia": "diagnostico", "analizar_fallo": "diagnostico",
    "codigo_error": "diagnostico", "sintoma": "diagnostico", "dtc": "diagnostico",
    "montaje": "procedimiento", "manual_montaje": "procedimiento", "desmontaje": "procedimiento",
    "instalacion": "procedimiento", "sustitucion": "procedimiento", "cambio": "procedimiento",
    "reparacion": "procedimiento", "paso_a_paso": "procedimiento", "proceso": "procedimiento",
    "par": "especificacion", "par_apriete": "especificacion", "tolerancia": "especificacion",
    "presion": "especificacion", "capacidad": "especificacion", "medidas": "especificacion",
    "revision": "mantenimiento", "intervalo": "mantenimiento", "servicio": "mantenimiento",
    "norma": "normativa", "seguridad": "normativa"
}

def normalizar_intencion(v: Any) -> str:
    """Mapea de forma robusta intenciones sinónimas al conjunto estricto de CTR-004."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("intencion debe ser una cadena no vacía")
    v_clean = v.strip().lower()
    if v_clean in INTENCIONES_VALIDAS:
        return v_clean
    if v_clean in MAPA_SINONIMOS_INTENCION:
        return MAPA_SINONIMOS_INTENCION[v_clean]
    for k, target in MAPA_SINONIMOS_INTENCION.items():
        if k in v_clean:
            return target
    raise ValueError(f"Intención '{v}' inválida. Debe ser una de {INTENCIONES_VALIDAS}.")

def normalizar_tipo_documento(v: Any) -> Optional[str]:
    """Mapea tipos de documento variantes al conjunto permitido en CTR-004."""
    if not v:
        return None
    v_clean = str(v).strip().lower()
    if v_clean in TIPOS_DOC_VALIDOS:
        return v_clean
    if "manual" in v_clean or "guia" in v_clean:
        return "manual"
    if "ficha" in v_clean or "dato" in v_clean:
        return "ficha_tecnica"
    if "paso" in v_clean or "proced" in v_clean:
        return "procedimiento"
    if "norma" in v_clean or "ley" in v_clean:
        return "normativa"
    return "otro"

try:
    from pydantic import BaseModel, Field, field_validator

    class FiltrosQuerySchema(BaseModel):
        version: Optional[str] = Field(default=None)
        componente: Optional[str] = Field(default=None)
        tipo_documento: Optional[str] = Field(default=None)
        codigos: List[str] = Field(default_factory=list)

        @field_validator("tipo_documento", mode="before")
        @classmethod
        def validar_tipo_doc(cls, v):
            return normalizar_tipo_documento(v)

    class OpcionesQuerySchema(BaseModel):
        top_k: int = Field(default=3)
        incluir_obsoletos: bool = Field(default=True)

    class QueryJSONSchema(BaseModel):
        trace_id: str = Field(default_factory=lambda: f"t-{uuid.uuid4().hex[:6]}")
        conversacion_id: str = Field(default="c-0001")
        texto_busqueda: str = Field(...)
        pregunta_original: str = Field(...)
        intencion: str = Field(...)
        filtros: FiltrosQuerySchema = Field(default_factory=FiltrosQuerySchema)
        opciones: OpcionesQuerySchema = Field(default_factory=OpcionesQuerySchema)

        @field_validator("texto_busqueda")
        @classmethod
        def validar_query(cls, v):
            if not isinstance(v, str) or not v.strip():
                raise ValueError("El campo 'texto_busqueda' no puede estar vacío.")
            return v.strip()

        @field_validator("intencion", mode="before")
        @classmethod
        def validar_intencion(cls, v):
            return normalizar_intencion(v)

    HAS_PYDANTIC = True

except ImportError:
    HAS_PYDANTIC = False


def validar_esquema_query_json(datos: Any) -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Valida exhaustivamente la estructura y campos del Query JSON según CTR-004.
    Funciona con Pydantic si está instalado o con validador de respaldo equivalente.
    """
    if not isinstance(datos, dict):
        return False, "La respuesta no es un diccionario JSON.", None

    # Una única normalización antes del validador opcional: mismo contrato sin SDK.
    try:
        texto = datos.get("texto_busqueda", datos.get("query_busqueda"))
        if not isinstance(texto, str) or not texto.strip():
            raise ValueError("texto_busqueda debe ser una cadena no vacía")
        pregunta = datos.get("pregunta_original", texto)
        trace = datos.get("trace_id", f"t-{uuid.uuid4().hex[:6]}")
        conv = datos.get("conversacion_id", "c-0001")
        for nombre, valor in (("pregunta_original", pregunta), ("trace_id", trace),
                              ("conversacion_id", conv)):
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"{nombre} debe ser una cadena no vacía")
        filtros = datos.get("filtros", {})
        opciones = datos.get("opciones", {})
        if not isinstance(filtros, dict) or not isinstance(opciones, dict):
            raise ValueError("filtros y opciones deben ser objetos")
        for nombre in ("version", "componente", "tipo_documento"):
            if filtros.get(nombre) is not None and not isinstance(filtros[nombre], str):
                raise ValueError(f"{nombre} debe ser cadena o null")
        codigos = filtros.get("codigos", [])
        if not isinstance(codigos, list) or any(not isinstance(c, str) or not c.strip() for c in codigos):
            raise ValueError("codigos debe ser una lista de cadenas no vacías")
        top_k = opciones.get("top_k", 3)
        obsoletos = opciones.get("incluir_obsoletos", True)
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k debe ser entero positivo")
        if type(obsoletos) is not bool:
            raise ValueError("incluir_obsoletos debe ser booleano")
        limpio = {
            "trace_id": trace, "conversacion_id": conv,
            "texto_busqueda": texto.strip(), "pregunta_original": pregunta.strip(),
            "intencion": normalizar_intencion(datos.get("intencion")),
            "filtros": {"version": filtros.get("version"),
                        "componente": filtros.get("componente"),
                        "tipo_documento": normalizar_tipo_documento(filtros.get("tipo_documento")),
                        "codigos": list(dict.fromkeys(codigos))},
            "opciones": {"top_k": top_k, "incluir_obsoletos": obsoletos}
        }
        if HAS_PYDANTIC:
            limpio = QueryJSONSchema(**limpio).model_dump()
        return True, None, limpio
    except (ValueError, TypeError) as exc:
        return False, f"Query JSON inválido: {exc}", None



# ============================================================================
# 2. MÓDULO DE PREPROCESAMIENTO Y NORMALIZACIÓN (A1-01 y A1-10)
# ============================================================================
class PreprocesadorAutomocion:
    """
    Limpia ruido, normaliza identificadores técnicos con regex robustas
    y enriquece síntomas sin sustituciones destructivas.
    """

    # Enriquecimiento de síntomas sin sesgar ni perder las palabras originales
    DICCIONARIO_SINTOMAS = {
        "tirones": "fallo de encendido / discontinuidad de par",
        "clac clac": "holgura mecánica / ruido de articulación",
        "humo blanco": "consumo de líquido refrigerante",
        "humo negro": "defecto de inyección diésel / exceso de combustible",
        "pedal esponjoso": "presencia de aire en circuito hidráulico de frenos",
        "no arranca": "fallo en circuito de arranque / inmovilizador activo",
        "testigo motor": "código DTC almacenado en ECU / aviso MIL",
        "calentamiento": "temperatura de refrigerante fuera de rango",
    }

    # BLOQUEANTE 4: Alternativas largas primero y aceptación de días/dias
    PATRON_SALUDO_INICIO = re.compile(
        r'^(?:buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|saludos|buenas|hola|hey)(?!\w)[,\s!.]*',
        re.IGNORECASE
    )
    PATRON_CORTESIA_INICIO = re.compile(
        r'^(?:por\s+favor|podr[ií]as\s+decirme|quisiera\s+saber|necesito\s+saber)[,\s]*',
        re.IGNORECASE
    )
    PATRON_CORTESIA_INTERNA = re.compile(
        r'\b(?:muchas\s+gracias|gracias|por\s+favor)\b',
        re.IGNORECASE
    )

    # BLOQUEANTE 1: Exige que el identificador REF contenga al menos un dígito
    # Evita corromper 'refrigerante', 'referencia', 'refuerzo', etc.
    RE_REF = re.compile(r'\bREF[-\s]?(?=[A-Za-z0-9]*\d)([A-Za-z0-9]+)\b', re.IGNORECASE)

    # Códigos HTM
    RE_HTM = re.compile(r'\bHTM[-\s]?(\d{4})\b', re.IGNORECASE)

    # BLOQUEANTE 2: Códigos DTC estándar (P, C, B, U seguidos de 4 dígitos exactos sin espacio)
    # No afecta a 'Clase C 2019' ni a 'Serie B 2015', y normaliza 'p0301' a 'P0301'
    RE_DTC = re.compile(r'\b([pcbuPCBU]\d{4})\b')

    # BLOQUEANTE 3: Solo normaliza versiones cuando van precedidas explícitamente de versión/version/ver.
    # No modifica 'Golf V 1.9 TDI' ni motores 'V6'/'V8'
    RE_VERSION = re.compile(r'\b(?:versión|version|ver\.)\s*([vV]?\d+(?:\.\d+)*)\b', re.IGNORECASE)

    # Patrón para extracción determinista de códigos
    PATRON_EXTRACCION_CODIGOS = re.compile(
        r'\b(?:HTM-\d{4}|REF-[A-Za-z0-9]*\d[A-Za-z0-9]*|[PCBU]\d{4})\b'
    )
    PATRON_EXTRACCION_VERSIONES = re.compile(r'\bV\d+(?:\.\d+)*\b')

    @classmethod
    def procesar(cls, texto_usuario: str) -> Dict[str, Any]:
        """
        Ejecuta el pipeline de preprocesamiento sobre el texto.
        """
        if not isinstance(texto_usuario, str):
            raise ValueError('La consulta debe ser texto')
        texto = texto_usuario.strip()

        # 1. Limpieza de saludos iniciales y cortesía (BLOQUEANTE 4)
        texto = cls.PATRON_SALUDO_INICIO.sub('', texto).strip()
        texto = cls.PATRON_CORTESIA_INICIO.sub('', texto).strip()
        texto = cls.PATRON_CORTESIA_INTERNA.sub('', texto).strip()

        # 2. Normalización de REF con lookahead de dígitos (BLOQUEANTE 1)
        texto = cls.RE_REF.sub(lambda m: f"REF-{m.group(1).upper()}", texto)

        # 3. Normalización de HTM
        texto = cls.RE_HTM.sub(r'HTM-\1', texto)

        # 4. Normalización de DTCs pasando a mayúsculas sin tocar años (BLOQUEANTE 2)
        texto = cls.RE_DTC.sub(lambda m: m.group(1).upper(), texto)

        versiones_explicitas = ["V" + m.group(1).lstrip("vV") for m in cls.RE_VERSION.finditer(texto)]

        # 5. Normalización de versión solo con prefijo explícito (BLOQUEANTE 3)
        texto = cls.RE_VERSION.sub(lambda m: 'V' + m.group(1).lstrip('vV'), texto)

        # 6. Mapeo no destructivo de síntomas
        for coloquial, formal in cls.DICCIONARIO_SINTOMAS.items():
            if re.search(r'\b' + re.escape(coloquial) + r'\b', texto, re.IGNORECASE):
                texto = re.sub(
                    r'\b' + re.escape(coloquial) + r'\b',
                    f"{coloquial} ({formal})",
                    texto,
                    flags=re.IGNORECASE
                )

        texto = re.sub(r'\s+', ' ', texto).strip()

        # 7. Extracción de códigos sin duplicados y con orden determinista
        codigos_raw = cls.PATRON_EXTRACCION_CODIGOS.findall(texto)
        codigos_detectados = list(dict.fromkeys(c.upper() for c in codigos_raw))

        versiones_raw = cls.PATRON_EXTRACCION_VERSIONES.findall(texto)
        versiones_detectadas = list(dict.fromkeys(v.upper() for v in versiones_raw
                                                  if v.upper() not in {"V6", "V8"} or v.upper() in versiones_explicitas))

        return {
            "texto_procesado": texto if texto else texto_usuario.strip(),
            "codigos_detectados": codigos_detectados,
            "versiones_detectadas": versiones_detectadas
        }


# ============================================================================
# 3. PROMPT DEL SISTEMA CON FEW-SHOTS (CTR-004)
# ============================================================================
SYSTEM_PROMPT_AGENTE1 = """
Eres el Agente 1 (Orquestador) de un sistema RAG de automoción.
Tu objetivo es analizar la consulta del usuario y clasificarla:

1. INVÁLIDA: Si la consulta no es de automoción (temas generales, saludos vacíos, finanzas).
   -> Responde exactamente la palabra: INVALIDA
2. INCOMPLETA: Si faltan datos clave (pregunta por un par de apriete, presión o avería sin especificar vehículo o pieza).
   -> Responde con una pregunta breve de aclaración técnica en texto plano.
3. VÁLIDA: Si contiene vehículo/componente y el detalle técnico buscado.
   -> Responde ÚNICAMENTE con un JSON conforme al contrato CTR-004.
   IMPORTANTE: El campo "intencion" DEBE ser una de estas palabras exactas:
     - "procedimiento" (para montaje, desmontaje, cambio, reparación o pasos técnicos)
     - "especificacion" (para pares de apriete, tolerancias, presiones, capacidades)
     - "diagnostico" (para averías, síntomas de fallo o códigos DTC/HTM)
     - "mantenimiento" (para intervalos de servicio, revisiones, aceite)
     - "normativa" (para normativas o directivas técnicas)
     - "otro" (cualquier otro aspecto)

EJEMPLO 1 (Especificación / Par de apriete):
Usuario: "Par de apriete de los tornillos de culata del Golf 7 1.6 TDI V1.1"
Respuesta:
{
  "texto_busqueda": "par apriete tornillos culata Golf 7 1.6 TDI",
  "intencion": "especificacion",
  "filtros": {
    "version": "V1.1",
    "componente": "culata",
    "tipo_documento": "ficha_tecnica",
    "codigos": []
  }
}

EJEMPLO 2 (Diagnóstico / Avería / Códigos de error):
Usuario: "Tengo un Golf 7 con motor 1.6 TDI, da tirones y marca el fallo P0301 con HTM-0142"
Respuesta:
{
  "texto_busqueda": "Golf 7 1.6 TDI tirones fallo encendido P0301 HTM-0142",
  "intencion": "diagnostico",
  "filtros": {
    "version": null,
    "componente": "encendido / inyección",
    "tipo_documento": "manual",
    "codigos": ["P0301", "HTM-0142"]
  }
}

EJEMPLO 3 (Consulta incompleta):
Usuario: "Cuál es el par de apriete de la culata?"
Respuesta:
¿De qué vehículo y motorización necesitas el par de apriete de la culata?
"""


# ============================================================================
# 4. AGENTE 1: CLIENTE LLM Y ORQUESTACIÓN (A1-02, A1-03, A1-04)
# ============================================================================
class Agente1:
    def __init__(self, base_url: str = OLLAMA_URL, modelo: str = MODELO_LLM, max_turnos: int = 6, conversacion_id: str = "c-0001"):
        self.modelo = modelo
        self.base_url = base_url
        self.max_turnos = max_turnos
        self.conversacion_id = conversacion_id
        self.cliente = OpenAI(base_url=base_url, api_key="ollama") if OpenAI else None
        self.historial: List[Dict[str, str]] = []

    def reset(self):
        """Limpia el historial de la conversación para evitar mezclar sesiones."""
        self.historial.clear()
        logger.info("Historial de conversación reiniciado.")

    def _consultar_llm(self, mensajes: List[Dict[str, str]]) -> Optional[str]:
        """
        Realiza la inferencia contra Ollama en localhost con max_tokens=512 (BLOQUEANTE 5).
        Soporta el SDK oficial de OpenAI o fallback nativo con urllib (sin dependencias pip).
        """
        # Intento 1: SDK de OpenAI si está instalado
        if self.cliente:
            try:
                respuesta = self.cliente.chat.completions.create(
                    model=self.modelo,
                    messages=mensajes,
                    temperature=0.0,
                    max_tokens=512,  # BLOQUEANTE 5: aumentado para evitar truncar JSONs
                    timeout=45
                )
                return respuesta.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"Fallo en cliente OpenAI ({e}). Intentando fallback nativo HTTP...")

        # Intento 2: Fallback nativo usando urllib (sin dependencias pip)
        # Probamos primero /v1/chat/completions (OpenAI-compatible) y luego /api/chat
        endpoints = [
            (f"{self.base_url.rstrip('/')}/chat/completions", "v1"),
            (f"{self.base_url.replace('/v1', '').rstrip('/')}/api/chat", "api")
        ]

        for url, modo in endpoints:
            try:
                if modo == "v1":
                    payload = {
                        "model": self.modelo,
                        "messages": mensajes,
                        "temperature": 0.0,
                        "max_tokens": 512,
                        "stream": False
                    }
                else:
                    payload = {
                        "model": self.modelo,
                        "messages": mensajes,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "num_predict": 512
                        }
                    }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=50) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if modo == "v1":
                        choices = data.get("choices") or []
                        if choices:
                            return choices[0].get("message", {}).get("content", "").strip()
                    else:
                        return data.get("message", {}).get("content", "").strip()

            except urllib.error.HTTPError as e:
                cuerpo = ""
                try:
                    cuerpo = e.read().decode("utf-8")
                except Exception:
                    pass
                logger.warning(f"Intento en {url} falló con HTTP {e.code}: {cuerpo if cuerpo else e.reason}")
                continue
            except Exception as e:
                logger.warning(f"Error de conexión en {url}: {e}")
                continue

        logger.error(f"No se pudo conectar con Ollama en ninguno de los endpoints ({self.base_url}).")
        return None

    def procesar_consulta(self, entrada_usuario: str) -> Dict[str, Any]:
        """
        Flujo de procesamiento:
          1. Preprocesamiento determinista (limpieza, normalización y extracción de códigos).
          2. Consulta al LLM.
          3. Tratamiento de respuestas y validación estricta de JSON CTR-004.
        """
        if not isinstance(entrada_usuario, str) or not entrada_usuario.strip():
            return {"estado": "error", "mensaje": "La consulta debe ser texto no vacío."}
        # Paso 1: Preprocesamiento de texto
        datos_prep = PreprocesadorAutomocion.procesar(entrada_usuario)
        texto_limpio = datos_prep["texto_procesado"]
        codigos_detectados = datos_prep["codigos_detectados"]

        # Paso 2: Preparar contexto para el LLM
        mensajes = [
            {"role": "system", "content": SYSTEM_PROMPT_AGENTE1}
        ] + self.historial + [
            {"role": "user", "content": texto_limpio}
        ]

        # Paso 3: Invocación al LLM
        salida_llm = self._consultar_llm(mensajes)
        if not salida_llm:
            return {
                "estado": "error",
                "mensaje": "No se pudo conectar con Ollama. Verifica que 'ollama serve' esté activo."
            }

        salida_strip = salida_llm.strip()

        # Paso 4: Evaluar respuesta

        # A) Detección de rechazo (Inválida)
        if salida_strip.upper().startswith("INVALIDA"):
            return {
                "estado": "rechazo",
                "mensaje": "Lo siento, solo puedo resolver dudas técnicas sobre automoción y sus manuales."
            }

        # B) Detección de intento de JSON (BLOQUEANTE 5)
        parece_json = salida_strip.startswith("{") or '"texto_busqueda"' in salida_strip or '"intencion"' in salida_strip or '"query_busqueda"' in salida_strip

        if parece_json:
            match_json = re.search(r'\{.*\}', salida_strip, re.DOTALL)
            if not match_json:
                logger.warning("Salida del modelo parece JSON pero no tiene delimitadores válidos (truncado).")
                return {
                    "estado": "error",
                    "mensaje": "Respuesta truncada o JSON malformado recibido del modelo LLM."
                }

            try:
                query_dict = json.loads(match_json.group(0))
            except json.JSONDecodeError as err:
                logger.warning(f"Error al decodificar JSON del modelo: {err}")
                return {
                    "estado": "error",
                    "mensaje": "Respuesta truncada o JSON malformado recibido del modelo LLM."
                }

            # Compatibilidad si el LLM usó query_busqueda
            if "query_busqueda" in query_dict and "texto_busqueda" not in query_dict:
                query_dict["texto_busqueda"] = query_dict["query_busqueda"]

            # Inyectar campos de infraestructura de CTR-004 de forma determinista
            query_dict["trace_id"] = f"t-{uuid.uuid4().hex[:6]}"
            query_dict["conversacion_id"] = self.conversacion_id
            query_dict["pregunta_original"] = texto_limpio

            # Inyectar filtros estructurados
            filtros = query_dict.get("filtros", {})
            if not isinstance(filtros, dict):
                return {"estado": "error", "mensaje": "El campo filtros no cumple CTR-004."}

            # Incorporar códigos detectados por regex deterministamente
            codigos_existentes = filtros.get("codigos", [])
            if not isinstance(codigos_existentes, list) or any(not isinstance(c, str) for c in codigos_existentes):
                return {"estado": "error", "mensaje": "El campo codigos no cumple CTR-004."}
            filtros["codigos"] = list(dict.fromkeys(codigos_existentes + codigos_detectados))
            versiones = datos_prep["versiones_detectadas"]
            if len(versiones) == 1:
                filtros["version"] = versiones[0]
            elif len(versiones) > 1:
                return {"estado": "aclaracion", "mensaje": "¿Qué versión necesitas consultar?"}
            query_dict["filtros"] = filtros

            if "opciones" not in query_dict:
                query_dict["opciones"] = {"top_k": 3, "incluir_obsoletos": True}

            # Validar esquema contractual CTR-004
            es_valido, error_val, query_validado = validar_esquema_query_json(query_dict)
            if not es_valido:
                logger.warning(f"Fallo de validación de contrato CTR-004: {error_val}")
                return {
                    "estado": "error",
                    "mensaje": f"El Query JSON generado no cumple el contrato CTR-004: {error_val}"
                }

            # Actualizar historial limitado (ventana deslizante)
            self._guardar_turno(texto_limpio, json.dumps(query_validado, ensure_ascii=False))

            return {
                "estado": "valida",
                "query_json": query_validado,
                "entidades_detectadas": datos_prep
            }

        # C) Aclaración en texto plano (Incompleta)
        self._guardar_turno(texto_limpio, salida_llm)
        return {
            "estado": "aclaracion",
            "mensaje": salida_llm
        }

    def _guardar_turno(self, entrada: str, salida: str):
        self.historial.append({"role": "user", "content": entrada})
        self.historial.append({"role": "assistant", "content": salida})
        if len(self.historial) > self.max_turnos * 2:
            self.historial = self.historial[-self.max_turnos * 2:]


# ============================================================================
# 5. SIMULADOR DEL AGENTE 2 (Mock CJ-01) — 5 CASOS DE PRUEBA
# ============================================================================
class RespuestaSimuladorAgente2(dict):
    """
    Representa el contrato Evidencias JSON devuelto por el Agente 2 (CTR-004).
    Hereda de dict para soportar res["estado"], res["evidencias"], res["mensaje_error"],
    y mantiene compatibilidad con listas: for ev in res, len(res), res[0].
    """
    def __init__(self, estado: str, evidencias: list, campo_ambiguo: Optional[str] = None, mensaje_error: Optional[str] = None):
        super().__init__(
            estado=estado,
            evidencias=evidencias,
            campo_ambiguo=campo_ambiguo,
            mensaje_error=mensaje_error
        )

    def __iter__(self):
        return iter(self["evidencias"])

    def __len__(self):
        return len(self["evidencias"])

    def __getitem__(self, item):
        if isinstance(item, int):
            return self["evidencias"][item]
        return super().__getitem__(item)

    def __eq__(self, other):
        if isinstance(other, list):
            return self["evidencias"] == other
        return super().__eq__(other)


def _simular_agente_2(query_json: Dict[str, Any]) -> RespuestaSimuladorAgente2:
    """
    Simulador del Agente 2 (Mock CJ-01) implementando los 5 casos de prueba
    requeridos por el plan de trabajo:
      1. Resultados buenos (vigente / suficiente)
      2. Lista vacía (sin evidencia)
      3. Varias versiones (ambigüedad para forzar aclaración)
      4. Documentos obsoletos (vigente vs obsoleto, o solo obsoleto)
      5. Error técnico (nunca devuelto como lista vacía)
    """
    filtros = (query_json.get("filtros") or {}) if isinstance(query_json, dict) else {}
    query = (query_json.get("texto_busqueda") or query_json.get("query_busqueda") or "").lower() if isinstance(query_json, dict) else ""
    componente = str(filtros.get("componente") or "").lower()
    version_filtro = filtros.get("version")
    codigos = [str(c).lower() for c in (filtros.get("codigos") or [])]

    # ------------------------------------------------------------------------
    # CASO 5: ERROR TÉCNICO
    # Si la consulta simula un fallo de índice o backend caído
    # ------------------------------------------------------------------------
    if "error_simulado" in query or "simular_error" in query or "timeout" in query:
        logger.error("[Mock Agente 2] Simulación de error en motor vectorial BGE-M3.")
        return RespuestaSimuladorAgente2(
            estado="error",
            evidencias=[],
            mensaje_error="Error 503: Motor de búsqueda vectorial BGE-M3 no disponible (timeout > 5s)."
        )

    # ------------------------------------------------------------------------
    # CASO 3: VARIAS VERSIONES (Ambigüedad detectada)
    # Si busca componente/procedimiento con diferencias entre versiones y no indicó versión
    # ------------------------------------------------------------------------
    if ("circuito primario" in query or "presion" in query or "varias_versiones" in query) and not version_filtro:
        return RespuestaSimuladorAgente2(
            estado="ambiguo",
            campo_ambiguo="version",
            evidencias=[
                {
                    "chunk_id": "HTM240-MAN-001@1.0_p14_1",
                    "texto": "Para el sistema ThermoDrive HTM-240 versión V1.0, la presión nominal del circuito primario es de 120 bar.",
                    "metadata": {
                        "documento": "HTM240-MAN-001",
                        "seccion": "Circuito_Primario",
                        "pagina": 14,
                        "version": "V1.0",
                        "componente": "circuito primario",
                        "obsoleto": False
                    },
                    "score": 0.89,
                    "estado_documento": "vigente"
                },
                {
                    "chunk_id": "HTM240-MAN-001@1.1_p18_1",
                    "texto": "Para la versión V1.1 y posteriores de ThermoDrive HTM-240, la presión de trabajo se calibró a 150 bar por mejora de estanqueidad.",
                    "metadata": {
                        "documento": "HTM240-MAN-001",
                        "seccion": "Circuito_Primario",
                        "pagina": 18,
                        "version": "V1.1",
                        "componente": "circuito primario",
                        "obsoleto": False
                    },
                    "score": 0.88,
                    "estado_documento": "vigente"
                }
            ]
        )

    # ------------------------------------------------------------------------
    # CASO 4: DOCUMENTOS OBSOLETOS VS VIGENTES
    # Si busca procedimientos con historial de revisiones (aceite, refrigerante, htm-0142)
    # ------------------------------------------------------------------------
    if "refrigerante" in query or "aceite" in query or "obsoleto" in query or "htm-0142" in query or any("htm-0142" in c for c in codigos):
        # Subcaso 4b: Solo obsoleto
        if "solo_obsoleto" in query or "descatalogado" in query:
            return RespuestaSimuladorAgente2(
                estado="solo_obsoleto",
                evidencias=[
                    {
                        "chunk_id": "HTM240-OBS-001@1.0_p3_1",
                        "texto": "[DOCUMENTO OBSOLETO] Filtro referencia OBS-240 descatalogado. No instalar en unidades posteriores a 2021.",
                        "metadata": {
                            "documento": "HTM240-OBS-001",
                            "seccion": "Filtros_Antiguos",
                            "pagina": 3,
                            "version": "V1.0",
                            "componente": "filtro",
                            "obsoleto": True
                        },
                        "score": 0.79,
                        "estado_documento": "obsoleto"
                    }
                ]
            )

        # Subcaso 4a: Obsoleto + Vigente (el Agente 1 debe descartar el obsoleto)
        return RespuestaSimuladorAgente2(
            estado="suficiente",
            evidencias=[
                {
                    "chunk_id": "HTM240-MAN-001@1.0_p10_1",
                    "texto": "[DOCUMENTO SUSTITUIDO] Procedimiento antiguo: cambio de fluido refrigerante cada 30.000 km utilizando refrigerante G12.",
                    "metadata": {
                        "documento": "HTM240-MAN-001",
                        "seccion": "Refrigeracion",
                        "pagina": 10,
                        "version": "V1.0",
                        "componente": "refrigerante",
                        "obsoleto": True,
                        "sustituido_por": "HTM240-BOL-002@1.1_p5_1"
                    },
                    "score": 0.81,
                    "estado_documento": "obsoleto"
                },
                {
                    "chunk_id": "HTM240-BOL-002@1.1_p5_1",
                    "texto": "Procedimiento vigente (actualización HTM-0142): el intervalo de sustitución es de 60.000 km empleando fluido orgánico G13 de larga duración.",
                    "metadata": {
                        "documento": "HTM240-BOL-002",
                        "seccion": "Refrigeracion",
                        "pagina": 5,
                        "version": "V1.1",
                        "componente": "refrigerante",
                        "obsoleto": False
                    },
                    "score": 0.94,
                    "estado_documento": "vigente"
                }
            ]
        )

    # ------------------------------------------------------------------------
    # CASO 1: RESULTADOS BUENOS (Vigentes y Suficientes)
    # Culata / Par de apriete o Códigos DTC (P0301)
    # ------------------------------------------------------------------------
    if "culata" in query or "culata" in componente:
        return RespuestaSimuladorAgente2(
            estado="suficiente",
            evidencias=[
                {
                    "chunk_id": "chunk_01",
                    "texto": "El par de apriete de los tornillos de culata se realiza en 3 fases: Fase 1 a 40 Nm, Fase 2 a 90° y Fase 3 a 90° adicionales.",
                    "metadata": {
                        "documento": "HTM240-MAN-001",
                        "seccion": "Culata",
                        "pagina": 42,
                        "version": "V1.1",
                        "componente": "culata",
                        "obsoleto": False
                    },
                    "score": 0.96,
                    "estado_documento": "vigente"
                }
            ]
        )

    if "p0301" in query or any("p0301" in c for c in codigos):
        return RespuestaSimuladorAgente2(
            estado="suficiente",
            evidencias=[
                {
                    "chunk_id": "HTM240-DTC-001@1.0_p15_1",
                    "texto": "El código DTC P0301 indica fallo de combustión detectado en el cilindro 1. Comprobar bujía, bobina de encendido e inyector.",
                    "metadata": {
                        "documento": "HTM240-DTC-001",
                        "seccion": "Ignicion",
                        "pagina": 15,
                        "version": "V1.0",
                        "componente": "encendido",
                        "obsoleto": False
                    },
                    "score": 0.93,
                    "estado_documento": "vigente"
                }
            ]
        )

    # ------------------------------------------------------------------------
    # CASO 2: LISTA VACÍA (Sin evidencia)
    # Para cualquier consulta que no tenga documentación en el sistema
    # ------------------------------------------------------------------------
    return RespuestaSimuladorAgente2(
        estado="sin_evidencia",
        evidencias=[],
        mensaje_error=None
    )


def es_obsoleta(evidencia: Dict[str, Any]) -> bool:
    meta = evidencia.get("metadata", {})
    return (evidencia.get("estado_documento") in {"obsoleto", "sustituido"}
            or meta.get("obsoleto") is True or bool(meta.get("sustituido_por")))


def simulador_agente_2(query_json: Dict[str, Any]) -> RespuestaSimuladorAgente2:
    """Mock local sustituible; sus datos son ficticios, no un corpus documental."""
    if not isinstance(query_json, dict):
        return RespuestaSimuladorAgente2("error", [], mensaje_error="Query JSON inválido")
    filtros = query_json.get("filtros", {})
    opciones = query_json.get("opciones", {})
    filtros = {} if filtros is None else filtros  # compatibilidad histórica CJ-01
    opciones = {} if opciones is None else opciones
    texto = query_json.get("texto_busqueda") or query_json.get("query_busqueda") or ""
    if (not isinstance(filtros, dict) or not isinstance(opciones, dict)
            or not isinstance(texto, str) or not isinstance(filtros.get("codigos", []), list)):
        return RespuestaSimuladorAgente2("error", [], mensaje_error="Query JSON inválido")
    top_k = opciones.get("top_k", 3)
    if type(top_k) is not int or top_k < 1 or type(opciones.get("incluir_obsoletos", True)) is not bool:
        return RespuestaSimuladorAgente2("error", [], mensaje_error="Opciones inválidas")
    # Recuperar las variantes antes de aplicar el filtro explícito de versión.
    sin_version = {**query_json, "filtros": {**filtros, "version": None}}
    respuesta = _simular_agente_2(sin_version)
    if respuesta["estado"] == "error":
        return respuesta
    evidencias = respuesta["evidencias"]
    version = filtros.get("version")
    if version:
        evidencias = [e for e in evidencias if e.get("metadata", {}).get("version") == version]
    if not opciones.get("incluir_obsoletos", True):
        evidencias = [e for e in evidencias if not es_obsoleta(e)]
    estado = respuesta["estado"]
    if not evidencias:
        estado = "sin_evidencia"
    elif version or estado != "ambiguo":
        estado = "solo_obsoleto" if all(es_obsoleta(e) for e in evidencias) else "suficiente"
    # No truncar variantes antes de pedir aclaración.
    return RespuestaSimuladorAgente2(estado, evidencias if estado == "ambiguo" else evidencias[:top_k],
                                    "version" if estado == "ambiguo" else None)


# ============================================================================
# 5b. REDACTOR TÉCNICO CON CITAS Y VERIFICADOR CON REINTENTO (A1-06 y A1-07)
# ============================================================================
PROMPT_REDACTOR_TECNICO = """
Eres el Redactor Técnico de automoción del Agente 1 (Reto ARSOFT).
Tu tarea es redactar la respuesta final al técnico usando ÚNICAMENTE los fragmentos de evidencias proporcionados.

ESTRUCTURA OBLIGATORIA:
- **Causas y Diagnóstico**: (si aplica a avería o síntoma)
- **Criticidad y Seguridad**: (precauciones de taller)
- **Procedimiento técnico**: (valores exactos, pares de apriete, tolerancias)
- **Fuentes consultadas**: (documento, página y chunk_id)

REGLAS ESTRICTAS DE CERO ALUCINACIÓN:
1. Cada afirmación técnica debe llevar entre corchetes el identificador exacto de la evidencia que la respalda (ej. [chunk_01] o [HTM240-MAN-001@1.1_p42_1]).
2. Queda PROHIBIDO inventar valores, pares o pasos que no figuren en los textos.
3. Si un dato no figura en las evidencias, escribe textualmente: "no indicado en la documentación".
4. Cita ÚNICAMENTE identificadores que existan en la lista de evidencias.
"""

def extraer_citas(texto: str) -> List[str]:
    """Identificadores entre corchetes, individuales o separados por comas."""
    return list(dict.fromkeys(
        parte.strip() for bloque in re.findall(r'\[([^\]]+)\]', texto)
        for parte in bloque.split(',')
        if re.fullmatch(r'[A-Za-z0-9_@.\-]+', parte.strip())
    ))


def verificar_citas(texto_respuesta: str, evidencias_validas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    A1-07: Comprueba que cada cita [chunk_id] en la respuesta exista realmente
    en las evidencias entregadas por el Agente 2. Detecta citas alucinadas.
    """
    citas_candidatas = extraer_citas(texto_respuesta)
    chunks_permitidos = {ev.get("chunk_id") for ev in evidencias_validas if ev.get("chunk_id")}
    citas_validas = [c for c in citas_candidatas if c in chunks_permitidos]
    citas_falsas = [c for c in citas_candidatas if c not in chunks_permitidos]

    es_valido = len(citas_falsas) == 0 and len(citas_validas) > 0

    return {
        "valido": es_valido,
        "citas_detectadas": list(dict.fromkeys(citas_candidatas)),
        "citas_validas": list(dict.fromkeys(citas_validas)),
        "citas_falsas": list(dict.fromkeys(citas_falsas))
    }


def redactar_respuesta_con_verificacion(
    pregunta: str,
    evidencias: List[Dict[str, Any]],
    agente: Agente1,
    aviso_obsoleto: Optional[str] = None
) -> Dict[str, Any]:
    """
    A1-06 & A1-07: Redacta la respuesta final citando chunks obligatorios,
    valida las citas y reintenta 1 vez si detecta citas alucinadas.
    Si vuelve a fallar, aborta con error de verificación seguro.
    """
    if not evidencias:
        return {
            "estado": "sin_evidencia",
            "texto": "No indicado en la documentación disponible.",
            "fuentes": [],
            "verificacion": {"valido": True, "citas_validas": [], "citas_falsas": []},
            "reintentos": 0
        }

    bloques = []
    for i, ev in enumerate(evidencias, 1):
        cid = ev.get("chunk_id", f"chunk_{i:02d}")
        txt = ev.get("texto", "")
        meta = ev.get("metadata", {})
        doc = meta.get("documento", "Manual")
        pag = meta.get("pagina", "-")
        bloques.append(f"EVIDENCIA [{cid}] (Doc: {doc}, Pág: {pag}):\n{txt}")

    contexto_evidencias = "\n\n".join(bloques)

    mensajes_base = [
        {"role": "system", "content": PROMPT_REDACTOR_TECNICO},
        {"role": "user", "content": f"CONSULTA DEL TÉCNICO: {pregunta}\n\nEVIDENCIAS DISPONIBLES:\n{contexto_evidencias}"}
    ]

    # INTENTO 1
    respuesta_1 = agente._consultar_llm(mensajes_base)
    if not respuesta_1:
        return {
            "estado": "error",
            "texto": "Error de comunicación con el modelo redactor.",
            "fuentes": [],
            "verificacion": {"valido": False, "citas_validas": [], "citas_falsas": []},
            "reintentos": 0
        }

    check_1 = verificar_citas(respuesta_1, evidencias)
    if check_1["valido"]:
        texto_final = f"{aviso_obsoleto}\n\n{respuesta_1}" if aviso_obsoleto else respuesta_1
        return {
            "estado": "respuesta",
            "texto": texto_final,
            "fuentes": check_1["citas_validas"],
            "verificacion": check_1,
            "reintentos": 0
        }

    # REINTENTO 1 (Regla de Juanmi: regenerar una vez con feedback del fallo)
    logger.warning(f"Verificación de citas falló en intento 1 (citas falsas: {check_1['citas_falsas']}). Regenerando con reintento...")
    chunks_validos_lista = [e.get("chunk_id") for e in evidencias]
    mensajes_reintento = mensajes_base + [
        {"role": "assistant", "content": respuesta_1},
        {
            "role": "user",
            "content": f"ALERTA: Has citado identificadores inexistentes: {check_1['citas_falsas']}. "
                       f"Regenera la respuesta citando ÚNICAMENTE los chunks válidos de la lista: {chunks_validos_lista}."
        }
    ]

    respuesta_2 = agente._consultar_llm(mensajes_reintento)
    if respuesta_2:
        check_2 = verificar_citas(respuesta_2, evidencias)
        if check_2["valido"]:
            texto_final = f"{aviso_obsoleto}\n\n{respuesta_2}" if aviso_obsoleto else respuesta_2
            return {
                "estado": "respuesta",
                "texto": texto_final,
                "fuentes": check_2["citas_validas"],
                "verificacion": check_2,
                "reintentos": 1
            }

    # Si volvió a fallar en el reintento: Error de verificación estricto
    logger.error("Verificación de citas falló tras reintento. Abortando respuesta por seguridad.")
    return {
        "estado": "error_verificacion",
        "texto": "Error de verificación: No se pudo respaldar la respuesta con evidencias comprobadas del manual técnico. Por política de seguridad, no se emite respuesta no verificada.",
        "fuentes": [],
        "verificacion": check_2 if respuesta_2 else check_1,
        "reintentos": 1
    }


def registrar_turno_auditoria(datos: Dict[str, Any]):
    """
    A1-08: Guarda auditoría por turno en archivo JSONL. Tolerante a fallos.
    """
    try:
        with open("agente1_registros.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(datos, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"No se pudo escribir registro de auditoría JSONL: {e}")


def evidencia_valida(ev: Any) -> bool:
    """Tipos necesarios para citar y serializar fuentes de CTR-001 sin coerciones."""
    if not isinstance(ev, dict) or not isinstance(ev.get("chunk_id"), str) or not ev["chunk_id"]:
        return False
    if not isinstance(ev.get("texto"), str) or not ev["texto"].strip():
        return False
    meta = ev.get("metadata")
    if not isinstance(meta, dict):
        return False
    for campo in ("documento", "seccion", "version"):
        if campo in meta and not isinstance(meta[campo], str):
            return False
    if "pagina" in meta and (type(meta["pagina"]) is not int or meta["pagina"] < 0):
        return False
    if "versiones" in meta and (not isinstance(meta["versiones"], list)
                               or any(not isinstance(v, str) for v in meta["versiones"])):
        return False
    if "obsoleto" in meta and type(meta["obsoleto"]) is not bool:
        return False
    if meta.get("sustituido_por") is not None and not isinstance(meta["sustituido_por"], str):
        return False
    estado = ev.get("estado_documento", "vigente")
    return isinstance(estado, str) and estado in {"vigente", "obsoleto", "sustituido"}


def resolver_evidencias(pregunta: str, respuesta_a2: dict, agente: Agente1) -> dict:
    """Decisión común a la consola y al adaptador CTR-001; no realiza transporte remoto."""
    if not isinstance(respuesta_a2, dict):
        return {"estado": "error", "texto": "Contrato de Agente 2 inválido.", "fuentes": []}
    estado = respuesta_a2.get("estado")
    evidencias = respuesta_a2.get("evidencias")
    if not isinstance(estado, str) or estado not in {"error", "sin_evidencia", "insuficiente", "ambiguo", "suficiente", "solo_obsoleto"} or not isinstance(evidencias, list):
        return {"estado": "error", "texto": "Contrato de Agente 2 inválido.", "fuentes": []}
    if estado == "error":
        mensaje = respuesta_a2.get("mensaje_error")
        return {"estado": "error", "texto": mensaje if isinstance(mensaje, str) and mensaje else "Error de recuperación.", "fuentes": []}
    if estado == "ambiguo":
        campo = respuesta_a2.get("campo_ambiguo") or "version"
        versiones = sorted({e.get("metadata", {}).get("version") for e in evidencias
                            if isinstance(e, dict) and isinstance(e.get("metadata"), dict)
                            and isinstance(e["metadata"].get("version"), str)})
        detalle = " (" + ", ".join(versiones) + ")" if versiones else ""
        return {"estado": "aclaracion", "texto": f"¿Qué {campo} necesitas consultar{detalle}?",
                "fuentes": [], "campo_aclaracion": campo}
    if estado in {"sin_evidencia", "insuficiente"} or not evidencias:
        return {"estado": "sin_evidencia", "texto": "No se ha encontrado información en la documentación disponible.", "fuentes": []}
    if any(not evidencia_valida(e) for e in evidencias):
        return {"estado": "error", "texto": "Evidencias de Agente 2 inválidas.", "fuentes": []}
    vigentes = [e for e in evidencias if not es_obsoleta(e)]
    seleccion = vigentes or evidencias
    aviso = None if vigentes else "AVISO: La documentación disponible es OBSOLETA / SUSTITUIDA."
    return redactar_respuesta_con_verificacion(pregunta, seleccion, agente, aviso)


def consultar_asistente(pregunta: str, agente: Agente1, agente2=simulador_agente_2) -> dict:
    """Entrada local CTR-001. Reutilizar un Agente1 por conversación; agente2 es un callable.

    El llamador conserva/selecciona la instancia por conversacion_id. No añade rutas
    al backend ni inicia servicios. El simulador es el valor por defecto para desarrollo.
    """
    resultado = agente.procesar_consulta(pregunta)
    trace = f"t-{uuid.uuid4().hex[:6]}"
    evidencias = []
    if resultado["estado"] != "valida":
        final = {"estado": {"rechazo": "fuera_de_ambito"}.get(resultado["estado"], resultado["estado"]),
                 "texto": resultado.get("mensaje", ""), "fuentes": []}
    else:
        query = resultado["query_json"]
        trace = query["trace_id"]
        try:
            respuesta = agente2(query)
        except Exception:
            logger.exception("Fallo en la llamada local a Agente 2")
            respuesta = {"estado": "error", "evidencias": [], "mensaje_error": "Error de comunicación con Agente 2."}
        final = resolver_evidencias(pregunta, respuesta, agente)
        if isinstance(respuesta, dict) and isinstance(respuesta.get("evidencias"), list):
            evidencias = respuesta["evidencias"]
    estado = final["estado"]
    codigo = ""
    if estado in {"error", "error_verificacion"}:
        codigo, estado = estado, "error"
    fuentes = []
    for ev in evidencias:
        if isinstance(ev, dict) and ev.get("chunk_id") in final["fuentes"]:
            meta = ev["metadata"]
            versiones = meta.get("versiones")
            if not isinstance(versiones, list):
                versiones = [meta["version"]] if meta.get("version") else []
            fuentes.append({"chunk_id": ev["chunk_id"], "documento": meta.get("documento", ""),
                            "seccion": meta.get("seccion", ""), "pagina": meta.get("pagina", 0),
                            "versiones": versiones, "obsoleto": es_obsoleta(ev)})
    return {"trace_id": trace, "estado": estado, "texto": final["texto"],
            "fuentes": fuentes, "codigo_error": codigo}


def ejecutar_paso_a_paso(pregunta: str, agente: Optional[Agente1] = None, agente2=simulador_agente_2) -> Dict[str, Any]:
    """
    Comando que ejecuta una pregunta de principio a fin mostrando lo que hace cada paso
    (Preprocesado -> LLM CTR-004 -> Mock Agente 2 -> Decisión -> Redacción -> Verificación -> Auditoría).
    """
    t0 = time.time()
    if agente is None:
        agente = Agente1()

    print("\n" + "=" * 70)
    print("  EJECUCIÓN PASO A PASO (Agente 1 -> Agente 2 -> Decisión -> Redacción)")
    print("=" * 70)

    # PASO 1: Preprocesamiento y extracción determinista
    print("\n[PASO 1: Preprocesamiento y Normalización (A1-01 / A1-10)]")
    datos_prep = PreprocesadorAutomocion.procesar(pregunta)
    print(f"  • Entrada original:      {pregunta}")
    print(f"  • Texto normalizado:     {datos_prep['texto_procesado']}")
    print(f"  • Códigos detectados:    {datos_prep['codigos_detectados']}")
    print(f"  • Versiones detectadas:  {datos_prep['versiones_detectadas']}")

    # PASO 2: Clasificación y Generación de Query JSON CTR-004
    print("\n[PASO 2: Clasificación y Query JSON CTR-004 (A1-03 / A1-04)]")
    resultado = agente.procesar_consulta(pregunta)
    print(f"  • Estado de consulta:    {resultado['estado'].upper()}")

    if resultado["estado"] != "valida":
        print(f"  • Mensaje de salida:     {resultado.get('mensaje')}")
        print("=" * 70)
        registrar_turno_auditoria({
            "trace_id": "sin_query",
            "pregunta": pregunta,
            "estado": resultado["estado"],
            "mensaje": resultado.get("mensaje"),
            "latencia_ms": int((time.time() - t0) * 1000)
        })
        return resultado

    query_json = resultado["query_json"]
    trace_id = query_json.get("trace_id", "t-000000")
    print("  • Query JSON generado para Agente 2:")
    print(json.dumps(query_json, ensure_ascii=False, indent=4))

    # PASO 3: Invocación al Simulador del Agente 2
    print("\n[PASO 3: Invocación al Simulador del Agente 2 (Mock CJ-01)]")
    try:
        respuesta_a2 = agente2(query_json)
    except Exception:
        logger.exception("Fallo en la llamada local a Agente 2")
        respuesta_a2 = {"estado": "error", "evidencias": [], "mensaje_error": "Error de comunicación con Agente 2."}
    if not isinstance(respuesta_a2, dict):
        respuesta_a2 = {"estado": "error", "evidencias": [], "mensaje_error": "Contrato de Agente 2 inválido."}
    estado_a2 = respuesta_a2.get("estado", "error")
    evidencias = respuesta_a2.get("evidencias", [])
    print(f"  • Estado devuelto por Agente 2:  {estado_a2.upper()}")
    print(f"  • Cantidad de evidencias:        {len(evidencias)}")
    if respuesta_a2.get("mensaje_error"):
        print(f"  • Mensaje de error:              {respuesta_a2['mensaje_error']}")

    for i, ev in enumerate(evidencias, 1):
        print(f"    [{i}] ({ev.get('estado_documento', 'vigente')}) {ev['chunk_id']} (score: {ev.get('score', 0.0)}): {ev['texto'][:85]}...")

    # PASO 4: Decisor del Agente 1 sobre lo devuelto
    print("\n[PASO 4: Decisión del Agente 1 ante la respuesta del Agente 2]")
    respuesta_final = resolver_evidencias(pregunta, respuesta_a2, agente)
    decision = respuesta_final["estado"]
    print(f"  • Acción del Agente 1: {decision}")
    print(respuesta_final["texto"])

    # PASO 6: Registro de auditoría local (A1-08)
    latencia_total_ms = int((time.time() - t0) * 1000)
    registrar_turno_auditoria({
        "trace_id": trace_id,
        "pregunta": pregunta,
        "query_json": query_json,
        "estado_agente2": estado_a2,
        "decision": decision,
        "respuesta_final": respuesta_final.get("texto"),
        "fuentes": respuesta_final.get("fuentes"),
        "latencia_ms": latencia_total_ms
    })
    print(f"\n[PASO 6: Auditoría JSONL (A1-08)] -> Turno registrado en 'agente1_registros.jsonl' (trace_id: {trace_id}, {latencia_total_ms} ms)")
    print("=" * 70)

    return {
        "resultado_agente1": resultado,
        "respuesta_agente2": respuesta_a2,
        "decision": decision,
        "respuesta_final": respuesta_final
    }



# ============================================================================
# 6. BUCLE PRINCIPAL DE CONSOLA Y COMANDO PASO A PASO
# ============================================================================
def ejecutar_bateria_5_casos(agente: Optional[Agente1] = None):
    """
    Ejecuta automáticamente una batería con los 5 casos de prueba de Juanmi:
      1. Resultados buenos
      2. Lista vacía (sin evidencia)
      3. Varias versiones (ambigüedad)
      4. Documento obsoleto
      5. Error técnico
    """
    if agente is None:
        agente = Agente1()

    casos = [
        ("CASO 1 - RESULTADOS BUENOS", "Par de apriete de los tornillos de culata del Golf 7"),
        ("CASO 2 - SIN EVIDENCIA", "Manual de montaje del alerón de titanio para el Golf 7"),
        ("CASO 3 - VARIAS VERSIONES", "Cuál es la presión nominal del circuito primario"),
        ("CASO 4 - DOCUMENTO OBSOLETO", "Procedimiento de cambio de fluido refrigerante HTM-0142"),
        ("CASO 5 - ERROR TÉCNICO", "Consulta con simular_error en el motor de búsqueda")
    ]

    print("\n" + "#" * 70)
    print("  EJECUTANDO BATERÍA DE LOS 5 CASOS DE PRUEBA (MOCK AGENTE 2 CJ-01)")
    print("#" * 70)

    for titulo, consulta in casos:
        print(f"\n>>> {titulo} <<<")
        agente.reset()
        ejecutar_paso_a_paso(consulta, agente)


def main():
    import sys

    # Si se pasa una pregunta por argumento de línea de comandos, ejecutar paso a paso y salir:
    # Ej: python3 agente1_core.py "par de apriete culata Golf 7"
    if len(sys.argv) > 1:
        param = " ".join(sys.argv[1:]).strip()
        if param == "--test-casos" or param == "test_casos":
            ejecutar_bateria_5_casos()
        else:
            ejecutar_paso_a_paso(param)
        return

    print("=" * 65)
    print("  AGENTE 1: CONVERSACIONAL Y PREPROCESAMIENTO (Core)")
    print(f"  Modelo: {MODELO_LLM} en {OLLAMA_URL}")
    print("  Comandos especiales:")
    print("    • 'test_casos'  -> Ejecuta los 5 casos de prueba del Agente 2")
    print("    • 'paso <texto>' -> Muestra la traza paso a paso de la pregunta")
    print("    • 'reset'       -> Reinicia la memoria de la conversación")
    print("    • 'salir'       -> Termina el programa")
    print("=" * 65)

    agente = Agente1()

    while True:
        try:
            pregunta = input("\nTú: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if pregunta.lower() in ["salir", "exit", "quit"]:
            print("Cerrando sesión de Agente 1.")
            break
        if pregunta.lower() == "reset":
            agente.reset()
            print("[Agente 1]: Conversación reiniciada.")
            continue
        if pregunta.lower() == "test_casos":
            ejecutar_bateria_5_casos(agente)
            continue
        if pregunta.lower().startswith("paso "):
            pregunta_paso = pregunta[5:].strip()
            ejecutar_paso_a_paso(pregunta_paso, agente)
            continue
        if not pregunta:
            continue

        resultado = agente.procesar_consulta(pregunta)

        if resultado["estado"] == "valida":
            query_json = resultado["query_json"]
            print("\n[CONSULTA VÁLIDA — Query JSON validado CTR-004]:")
            print(json.dumps(query_json, ensure_ascii=False, indent=2))

            print("\n[Consultando Simulador Agente 2 (CJ-01)...]")
            resp_a2 = simulador_agente_2(query_json)
            estado_a2 = resp_a2.get("estado")
            evidencias = resp_a2.get("evidencias", [])

            print(f"-> Estado Agente 2: {estado_a2.upper()}")
            if resp_a2.get("mensaje_error"):
                print(f"-> Error técnico reportado: {resp_a2['mensaje_error']}")

            if evidencias:
                print(f"-> Se recuperaron {len(evidencias)} evidencia(s) simulada(s):")
                for ev in evidencias:
                    estado_doc = f"[{ev.get('estado_documento', 'vigente').upper()}]"
                    print(f"   {estado_doc} [{ev['chunk_id']}] {ev['texto']} (Doc: {ev['metadata']['documento']}, pág. {ev['metadata']['pagina']})")
            elif estado_a2 == "sin_evidencia":
                print("-> El simulador no encontró datos para estos términos (sin evidencia).")

        elif resultado["estado"] == "aclaracion":
            print(f"\nAgente 1 (Aclaración): {resultado['mensaje']}")

        elif resultado["estado"] == "rechazo":
            print(f"\nAgente 1: {resultado['mensaje']}")

        else:
            print(f"\n[Error]: {resultado['mensaje']}")


if __name__ == "__main__":
    main()
