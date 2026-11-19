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
import math
import unicodedata
from contextlib import contextmanager
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
    PATRON_EXTRACCION_VERSIONES = re.compile(r'\bV\d+(?:\.\d+)*\b', re.IGNORECASE)

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
    def __init__(self, base_url: str = OLLAMA_URL, modelo: str = MODELO_LLM, max_turnos: int = 6, conversacion_id: str = "c-0001", timeout_s: Optional[float] = None):
        self.modelo = modelo
        self.base_url = base_url
        self.max_turnos = max_turnos
        self.conversacion_id = conversacion_id
        self.timeout_s = float(timeout_s if timeout_s is not None else os.environ.get("OLLAMA_TIMEOUT_S", "10"))
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("OLLAMA_TIMEOUT_S debe ser un número positivo y finito")
        self.cliente = OpenAI(base_url=base_url, api_key="ollama", timeout=self.timeout_s,
                              max_retries=0) if OpenAI else None
        self.historial: List[Dict[str, str]] = []
        self.aclaraciones_consecutivas = 0
        self.consulta_pendiente = False
        self._query_pendiente = None
        self._deadline_llm = None

    def reset(self):
        """Limpia el historial de la conversación para evitar mezclar sesiones."""
        self.finalizar_consulta()
        logger.info("Historial de conversación reiniciado.")

    def finalizar_consulta(self):
        """Solo memoria temporal; cada instancia sigue perteneciendo a una conversación."""
        self.historial.clear()
        self.aclaraciones_consecutivas = 0
        self.consulta_pendiente = False
        self._query_pendiente = None

    def pedir_aclaracion(self, entrada: str, mensaje: str) -> dict:
        """Dos repreguntas como máximo; después se abstiene y termina la consulta."""
        if self.aclaraciones_consecutivas >= 2:
            self.finalizar_consulta()
            return {"estado": "sin_evidencia", "mensaje":
                    "No puedo resolver la consulta tras dos aclaraciones. Inicia una nueva consulta con los datos técnicos necesarios."}
        self.aclaraciones_consecutivas += 1
        self.consulta_pendiente = True
        if self.historial and self.historial[-1]["role"] == "assistant":
            self.historial[-1]["content"] = mensaje
        else:
            self._guardar_turno(entrada, mensaje)
        return {"estado": "aclaracion", "mensaje": mensaje}

    @contextmanager
    def presupuesto_llm(self):
        """Presupuesto compartido por clasificación, fallbacks y redacción/reintento.

        OLLAMA_TIMEOUT_S (10 s por defecto) limita los timeouts de E/S al tiempo
        restante. No cancela el trabajo de inferencia que ya esté en el servidor.
        """
        propio = self._deadline_llm is None
        if propio:
            self._deadline_llm = time.monotonic() + self.timeout_s
        try:
            yield
        finally:
            if propio:
                self._deadline_llm = None

    def _consultar_llm(self, mensajes: List[Dict[str, str]]) -> Optional[str]:
        """
        Realiza la inferencia contra Ollama en localhost con max_tokens=512 (BLOQUEANTE 5).
        Soporta el SDK oficial de OpenAI o fallback nativo con urllib (sin dependencias pip).
        """
        deadline = self._deadline_llm or (time.monotonic() + self.timeout_s)
        # El SDK no hace reintentos internos; todos los intentos comparten presupuesto.
        restante = deadline - time.monotonic()
        if restante <= 0:
            return None
        # Intento 1: SDK de OpenAI si está instalado
        if self.cliente:
            try:
                respuesta = self.cliente.chat.completions.create(
                    model=self.modelo,
                    messages=mensajes,
                    temperature=0.0,
                    max_tokens=512,  # BLOQUEANTE 5: aumentado para evitar truncar JSONs
                    timeout=restante
                )
                texto = respuesta.choices[0].message.content
                if time.monotonic() < deadline and isinstance(texto, str) and texto.strip():
                    return texto.strip()
            except Exception as e:
                logger.warning("Fallo en cliente OpenAI (%s); se intenta fallback con el tiempo restante.", type(e).__name__)

        # Intento 2: Fallback nativo usando urllib (sin dependencias pip)
        # Probamos primero /v1/chat/completions (OpenAI-compatible) y luego /api/chat
        endpoints = [
            (f"{self.base_url.rstrip('/')}/chat/completions", "v1"),
            (f"{self.base_url.replace('/v1', '').rstrip('/')}/api/chat", "api")
        ]

        for url, modo in endpoints:
            restante = deadline - time.monotonic()
            if restante <= 0:
                break
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
                with urllib.request.urlopen(req, timeout=restante) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if time.monotonic() >= deadline:
                        return None
                    if modo == "v1":
                        texto = data["choices"][0]["message"]["content"]
                    else:
                        texto = data["message"]["content"]
                    if isinstance(texto, str) and texto.strip():
                        return texto.strip()

            except urllib.error.HTTPError as e:
                logger.warning("Endpoint LLM respondió HTTP %s.", e.code)
                continue
            except Exception as e:
                logger.warning("Fallo de conexión al modelo (%s).", type(e).__name__)
                continue

        logger.error("No se obtuvo respuesta del modelo dentro del presupuesto disponible.")
        return None

    def procesar_consulta(self, entrada_usuario: str, *, nueva_consulta: bool = False) -> Dict[str, Any]:
        """Conserva contexto solo mientras hay aclaración pendiente.

        El llamador puede indicar nueva_consulta=True para separar una pregunta
        independiente de una respuesta a una aclaración; también se reconocen
        los marcadores explícitos «otra duda»/«nueva consulta».
        """
        nueva = isinstance(entrada_usuario, str) and re.match(
            r"^(?:gracias[,!.]?\s*)?(?:ahora\s+)?(?:otra duda|otra consulta|nueva consulta|cambiando de tema)\b",
            entrada_usuario.strip(), re.IGNORECASE)
        if nueva_consulta or nueva or not self.consulta_pendiente:
            self.finalizar_consulta()
        with self.presupuesto_llm():
            resultado = self._procesar_consulta(entrada_usuario)
        if resultado["estado"] == "aclaracion":
            return self.pedir_aclaracion(entrada_usuario, resultado["mensaje"])
        if resultado["estado"] != "valida":
            self.finalizar_consulta()
        return resultado

    def _procesar_consulta(self, entrada_usuario: str) -> Dict[str, Any]:
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

        if self._query_pendiente and len(datos_prep["versiones_detectadas"]) == 1 and re.fullmatch(r"(?:es\s+)?(?:la\s+)?V\d+(?:\.\d+)*[.!]?", texto_limpio, re.IGNORECASE):
            query = json.loads(json.dumps(self._query_pendiente))
            query["filtros"]["version"] = datos_prep["versiones_detectadas"][0]
            query["trace_id"] = f"t-{uuid.uuid4().hex[:6]}"
            query["pregunta_original"] = entrada_usuario
            self._guardar_turno(texto_limpio, json.dumps(query, ensure_ascii=False))
            return {"estado": "valida", "query_json": query, "entidades_detectadas": datos_prep}

        # Paso 2: Preparar contexto para el LLM
        mensajes = [
            {"role": "system", "content": SYSTEM_PROMPT_AGENTE1}
        ] + self.historial + [
            {"role": "user", "content": texto_limpio}
        ]

        # Paso 3: Invocación al LLM
        salida_llm = self._consultar_llm(mensajes)
        if not isinstance(salida_llm, str) or not salida_llm.strip():
            return {
                "estado": "error",
                "codigo_error": "modelo_no_disponible",
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
                self._guardar_turno(texto_limpio, "¿Qué versión necesitas consultar?")
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
    def __init__(self, estado: str, evidencias: list, campo_ambiguo: Optional[str] = None,
                 mensaje_error: Optional[str] = None, codigo_error: Optional[str] = None):
        super().__init__(
            estado=estado,
            evidencias=evidencias,
            campo_ambiguo=campo_ambiguo,
            mensaje_error=mensaje_error,
            codigo_error=codigo_error
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


def _version_norm(version: Any) -> Optional[str]:
    if not isinstance(version, str) or not version.strip():
        return None
    return version.strip().upper().lstrip("V")


def es_obsoleta(evidencia: Dict[str, Any], version: Optional[str] = None) -> bool:
    """Criterio A2-06: un documento obsoleto o sustituido sigue vigente para
    las versiones de ``vigente_para``; sin versión solicitada no hay excepción."""
    meta = evidencia.get("metadata") or {}
    pedida = _version_norm(version)
    if pedida is not None and pedida in {_version_norm(v) for v in meta.get("vigente_para") or []}:
        return False
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
        evidencias = [e for e in evidencias if not es_obsoleta(e, version)]
    estado = respuesta["estado"]
    if not evidencias:
        estado = "sin_evidencia"
    elif version or estado != "ambiguo":
        estado = "solo_obsoleto" if all(es_obsoleta(e, version) for e in evidencias) else "suficiente"
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
5. Para permitir una comprobación determinista, copia oraciones completas de los
   fragmentos sin cambiar valores, negaciones, condiciones ni versiones. Cada
   oración debe terminar en su cita. Omite introducciones, paráfrasis y conclusiones
   que no puedan verificarse literalmente. Los encabezados anteriores son opcionales.
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


def verificar_respaldo_extractivo(texto: str, evidencias: list) -> bool:
    """Regla conservadora, no verificación semántica: cada afirmación debe ser
    una oración literal de una de las evidencias que cita. Una paráfrasis no
    comprobable se rechaza; se permiten únicamente los encabezados del prompt.
    """
    def normalizar(fragmento):
        fragmento = fragmento.replace("[DOCUMENTO SUSTITUIDO]", "")
        sin_tildes = unicodedata.normalize("NFKD", fragmento.casefold())
        sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c)).replace("−", "-")
        return " ".join(re.findall(r"[+-]?\d+(?:[.,]\d+)*|[^\W_]+|[°%≤≥<>±=/×*^+\-]", sin_tildes))

    encabezados = {normalizar(h) for h in ("Causas y Diagnóstico", "Criticidad y Seguridad",
                                         "Procedimiento técnico", "Fuentes consultadas")}
    texto = "\n".join(linea for linea in texto.splitlines() if normalizar(linea.strip("*#: ")) not in encabezados)
    por_id = {e["chunk_id"]: {normalizar(oracion) for oracion in re.split(
        r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])|\n+", e["texto"])} for e in evidencias}
    posicion = 0
    afirmaciones = 0
    for cita in re.finditer(r"\[([^\]]+)\]", texto):
        afirmacion = normalizar(texto[posicion:cita.start()])
        ids = [c.strip() for c in cita.group(1).split(",")]
        if any(cid not in por_id for cid in ids):
            return False
        if afirmacion:
            if not all(afirmacion in por_id[cid] for cid in ids):
                return False
            afirmaciones += 1
        posicion = cita.end()
    return afirmaciones > 0 and not normalizar(texto[posicion:])


def redactar_respuesta_con_verificacion(pregunta: str, evidencias: list, agente: Agente1,
                                        aviso_obsoleto: Optional[str] = None) -> dict:
    if not isinstance(evidencias, list) or any(not evidencia_valida(e) for e in evidencias):
        return {"estado": "error", "texto": "Evidencias de Agente 2 inválidas.", "fuentes": []}
    try:
        with agente.presupuesto_llm():
            return _redactar_respuesta_con_verificacion(pregunta, evidencias, agente, aviso_obsoleto)
    except Exception as exc:
        logger.error("Fallo del modelo redactor (%s).", type(exc).__name__)
        return {"estado": "error", "texto": "Error de comunicación con el modelo redactor.", "fuentes": []}


def _redactar_respuesta_con_verificacion(
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
    check_1["respaldo_extractivo"] = verificar_respaldo_extractivo(respuesta_1, evidencias)
    check_1["valido"] = check_1["valido"] and check_1["respaldo_extractivo"]
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
                       f"Regenera copiando oraciones completas de las evidencias, sin cambios ni afirmaciones adicionales, "
                       f"y citando ÚNICAMENTE los chunks válidos: {chunks_validos_lista}."
        }
    ]

    respuesta_2 = agente._consultar_llm(mensajes_reintento)
    if respuesta_2:
        check_2 = verificar_citas(respuesta_2, evidencias)
        check_2["respaldo_extractivo"] = verificar_respaldo_extractivo(respuesta_2, evidencias)
        check_2["valido"] = check_2["valido"] and check_2["respaldo_extractivo"]
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
        ruta = os.getenv("ARSOFT_AUDIT_PATH", "agente1_registros.jsonl")
        directorio = os.path.dirname(ruta)
        if directorio:
            os.makedirs(directorio, mode=0o700, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as f:
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


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Extrae un valor float sin lanzar TypeError ni ValueError ante None o valores inválidos."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return default


def normalizar_respuesta_agente2(respuesta: Any) -> RespuestaSimuladorAgente2:
    """
    Adaptador universal y normalizador para respuestas de recuperación (CTR-004).

    Garantiza compatibilidad robusta entre:
      - Especificación oficial CTR-004 (evidencias, metadata, scores.rerank, estado).
      - Implementación de Agente 2 de Víctor (PR #18: rerank_score, rrf_score).
      - Variante de pruebas de OpenCode (resultados, metadatos, score_final, sin estado).

    Cumple estrictamente con las validaciones de contrato:
      1. Mapeo prioritario de 'rerank_score' y 'rrf_score' (PR #18) para evitar score = 0.0.
      2. Prioridad de valores saneados: un documento "" no sobreescribe "DOC_DESCONOCIDO".
      3. Extracción segura con _safe_float: ningún valor None lanza TypeError.
      4. Rechazo estricto de tipos no serializables o metadatos inválidos según evidencia_valida.
      5. Preservación de códigos de error según PR #23 (Apptainer).
    """
    error = RespuestaSimuladorAgente2(
        estado="error",
        evidencias=[],
        campo_ambiguo=None,
        mensaje_error="Contrato de Agente 2 inválido.",
        codigo_error="error_verificacion"
    )

    if not isinstance(respuesta, dict):
        return error

    try:
        json.dumps(respuesta, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return error

    # 1. Resolver lista de fragmentos (evidencias o resultados)
    raw_evidencias = respuesta.get("evidencias")
    if raw_evidencias is None and "resultados" in respuesta:
        raw_evidencias = respuesta.get("resultados")

    # 2. Resolver estado contractual
    estado = respuesta.get("estado")
    if estado is None and "resultados" in respuesta:
        if isinstance(raw_evidencias, list):
            estado = "suficiente" if raw_evidencias else "sin_evidencia"
        else:
            return error

    if estado == "insuficiente":
        estado = "sin_evidencia"

    if (not isinstance(estado, str) or estado not in
            {"error", "sin_evidencia", "ambiguo", "suficiente", "solo_obsoleto"}
            or not isinstance(raw_evidencias, list)):
        return error

    if estado in {"suficiente", "solo_obsoleto"} and not raw_evidencias:
        return error
    if estado == "sin_evidencia" and raw_evidencias:
        return error

    campo = respuesta.get("campo_ambiguo")
    mensaje = respuesta.get("mensaje_error")
    if (campo is not None and (not isinstance(campo, str) or not campo.strip())) or (mensaje is not None and not isinstance(mensaje, str)):
        return error

    # 3. Normalizar y validar cada fragmento
    chunks_normalizados = []
    por_id = {}

    for c in raw_evidencias:
        if not isinstance(c, dict):
            return error

        chunk_id = c.get("chunk_id")
        texto = c.get("texto")
        if not isinstance(chunk_id, str) or not chunk_id.strip() or not isinstance(texto, str) or not texto.strip():
            return error

        # Compatibilidad de metadatos (inglés / español)
        meta_in = c.get("metadata") if "metadata" in c else c.get("metadatos")
        if not isinstance(meta_in, dict):
            return error

        # Validación estricta de tipos según evidencia_valida
        for campo_str in ("documento", "seccion", "version"):
            if campo_str in meta_in and not isinstance(meta_in[campo_str], str):
                return error
        if "pagina" in meta_in and (type(meta_in["pagina"]) is not int or meta_in["pagina"] < 0):
            return error
        if "versiones" in meta_in and (not isinstance(meta_in["versiones"], list)
                                      or any(not isinstance(v, str) for v in meta_in["versiones"])):
            return error
        if "obsoleto" in meta_in and type(meta_in["obsoleto"]) is not bool:
            return error
        if meta_in.get("sustituido_por") is not None and not isinstance(meta_in["sustituido_por"], str):
            return error

        estado_doc = c.get("estado_documento", "vigente")
        if not isinstance(estado_doc, str) or estado_doc not in {"vigente", "obsoleto", "sustituido"}:
            return error

        # Extracción segura de puntuaciones (PR #18 de Víctor: rerank_score, rrf_score)
        scores_dict = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        rerank_cand = None
        for cand in [
            c.get("rerank_score"),
            scores_dict.get("rerank"),
            scores_dict.get("rerank_score"),
            c.get("score_final"),
            c.get("score")
        ]:
            if cand is not None:
                rerank_cand = _safe_float(cand)
                break

        rrf_cand = None
        for cand in [
            c.get("rrf_score"),
            scores_dict.get("rrf"),
            scores_dict.get("rrf_score")
        ]:
            if cand is not None:
                rrf_cand = _safe_float(cand)
                break

        final_score = rerank_cand if rerank_cand is not None else (rrf_cand if rrf_cand is not None else 0.0)
        final_rrf = rrf_cand if rrf_cand is not None else final_score

        # Metadatos: saneamiento y no sobreescritura de valores calculados
        meta_dict = dict(meta_in)
        doc_raw = meta_dict.get("documento") or c.get("documento")
        documento = str(doc_raw).strip() if (doc_raw is not None and str(doc_raw).strip()) else "DOC_DESCONOCIDO"

        meta_homogeneo = {
            **meta_dict,
            "documento": documento,
        }
        if "pagina" not in meta_homogeneo and "pagina" in c:
            try:
                p = int(c["pagina"])
                if p >= 0:
                    meta_homogeneo["pagina"] = p
            except (ValueError, TypeError):
                pass

        chunk_norm = {
            **c,
            "chunk_id": chunk_id,
            "texto": texto,
            "metadata": meta_homogeneo,
            "metadatos": meta_homogeneo,
            "score": final_score,
            "score_final": final_score,
            "rerank_score": final_score,
            "rrf_score": final_rrf,
            "scores": {"rerank": final_score, "rrf": final_rrf},
            "estado_documento": estado_doc
        }

        if chunk_id in por_id and chunk_norm != por_id[chunk_id]:
            return error
        por_id[chunk_id] = chunk_norm
        chunks_normalizados.append(chunk_norm)

    # Comprobación de tipos finales con evidencia_valida
    if any(not evidencia_valida(e) for e in chunks_normalizados):
        return error

    codigo_error = respuesta.get("codigo_error")
    if codigo_error not in {"entrada_invalida", "filtro_invalido", "modelo_no_disponible", "modelo_incompatible",
                            "indice_no_disponible", "tiempo_agotado", "error_verificacion",
                            "servicio_no_disponible"}:
        codigo_error = None
    if estado == "error" and not codigo_error:
        codigo_error = "error_verificacion"

    return RespuestaSimuladorAgente2(
        estado=estado,
        evidencias=chunks_normalizados,
        campo_ambiguo=campo,
        mensaje_error=mensaje,
        codigo_error=codigo_error
    )


def resolver_evidencias(pregunta: str, respuesta_a2: dict, agente: Agente1, *, version: Optional[str] = None) -> dict:
    """Decisión común a la consola y al adaptador CTR-001; no realiza transporte remoto."""
    respuesta_a2 = normalizar_respuesta_agente2(respuesta_a2)
    estado = respuesta_a2["estado"]
    evidencias = respuesta_a2["evidencias"]
    if estado == "error":
        mensaje = respuesta_a2.get("mensaje_error")
        codigo = respuesta_a2.get("codigo_error") or "indice_no_disponible"
        return {"estado": "error", "texto": mensaje if isinstance(mensaje, str) and mensaje else "Error de recuperación.",
                "fuentes": [], "codigo_error": codigo}
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
    if version:
        compatibles = [e for e in evidencias if version in e["metadata"].get("versiones", [])
                       or e["metadata"].get("version") == version]
        if not compatibles:
            return {"estado": "error", "texto": "Las evidencias no corresponden a la versión solicitada.", "fuentes": []}
        evidencias = compatibles
    vigentes = [e for e in evidencias if not es_obsoleta(e, version)]
    if estado == "solo_obsoleto" and vigentes:
        return {"estado": "error", "texto": "Estado de obsolescencia incoherente en Agente 2.", "fuentes": []}
    seleccion = vigentes or evidencias
    versiones = {e["metadata"]["version"] for e in seleccion if e["metadata"].get("version")}
    if not version and len(versiones) > 1 and len({e["texto"] for e in seleccion}) > 1:
        return {"estado": "aclaracion", "texto": "¿Qué versión necesitas consultar (" + ", ".join(sorted(versiones)) + ")?",
                "fuentes": [], "campo_aclaracion": "version"}
    aviso = None if vigentes else "AVISO: La documentación disponible es OBSOLETA / SUSTITUIDA."
    return redactar_respuesta_con_verificacion(pregunta, seleccion, agente, aviso)


def _ejecutar_turno(pregunta: str, agente: Agente1, agente2, nueva_consulta: bool) -> dict:
    """Única ruta de decisión, ciclo de memoria y auditoría para API y consola."""
    inicio = time.monotonic()
    trace = f"t-{uuid.uuid4().hex[:6]}"
    respuesta_a2 = None
    version_pedida = None
    resultado = {"estado": "error", "mensaje": "No se pudo procesar la consulta."}
    evidencias = []
    try:
        with agente.presupuesto_llm():
            resultado = agente.procesar_consulta(pregunta, nueva_consulta=nueva_consulta)
            if resultado["estado"] != "valida":
                final = {"estado": {"rechazo": "fuera_de_ambito"}.get(resultado["estado"], resultado["estado"]),
                         "texto": resultado.get("mensaje", ""), "fuentes": []}
            else:
                query = resultado["query_json"]
                trace = query["trace_id"]
                version_pedida = query["filtros"]["version"]
                try:
                    respuesta_a2 = agente2(query)
                except Exception as exc:
                    logger.error("Fallo en la llamada local a Agente 2 (%s).", type(exc).__name__)
                    respuesta_a2 = {"estado": "error", "evidencias": [],
                                    "mensaje_error": "Error de comunicación con Agente 2.",
                                    "codigo_error": "servicio_no_disponible"}
                respuesta_a2 = normalizar_respuesta_agente2(respuesta_a2)
                evidencias = respuesta_a2["evidencias"]
                final = resolver_evidencias(pregunta, respuesta_a2, agente, version=version_pedida)
                if final["estado"] == "aclaracion":
                    agente._query_pendiente = query
                    aclaracion = agente.pedir_aclaracion(pregunta, final["texto"])
                    final.update(estado=aclaracion["estado"], texto=aclaracion["mensaje"])
    except Exception as exc:
        logger.error("Error controlado al procesar la consulta (%s).", type(exc).__name__)
        final = {"estado": "error", "texto": "No se pudo procesar la consulta.", "fuentes": []}
    estado = final["estado"]
    codigo = ""
    if estado in {"error", "error_verificacion"}:
        codigo = final.get("codigo_error") or resultado.get("codigo_error")
        if not codigo and respuesta_a2 is not None and respuesta_a2.get("estado") == "error":
            codigo = respuesta_a2.get("codigo_error") or "indice_no_disponible"
        if not codigo:
            codigo = "error_verificacion"
        estado = "error"
    if estado != "aclaracion":
        agente.finalizar_consulta()
    fuentes = []
    for ev in evidencias:
        if ev["chunk_id"] in final["fuentes"]:
            meta = ev["metadata"]
            versiones = meta.get("versiones", [meta["version"]] if meta.get("version") else [])
            fuentes.append({"chunk_id": ev["chunk_id"], "documento": meta.get("documento", ""),
                            "seccion": meta.get("seccion", ""), "pagina": meta.get("pagina", 0),
                            "versiones": versiones, "obsoleto": es_obsoleta(ev, version_pedida)})
    respuesta = {"trace_id": trace, "estado": estado, "texto": final["texto"],
                 "fuentes": fuentes, "codigo_error": codigo}
    # Lista cerrada: no se guardan pregunta, prompt, respuesta, configuración ni excepciones.
    registrar_turno_auditoria({"trace_id": trace, "conversacion_id": agente.conversacion_id,
                              "estado": estado, "codigo_error": codigo,
                              "estado_agente2": respuesta_a2["estado"] if respuesta_a2 is not None else None,
                              "fuentes": [f["chunk_id"] for f in fuentes],
                              "latencia_ms": int((time.monotonic() - inicio) * 1000)})
    return {"resultado_agente1": resultado, "respuesta_agente2": respuesta_a2,
            "decision": final["estado"], "respuesta_final": final, "respuesta_ctr001": respuesta}


def consultar_asistente(pregunta: str, agente: Agente1, agente2=simulador_agente_2,
                        *, nueva_consulta: bool = False) -> dict:
    """CTR-001 local; nueva_consulta separa una pregunta de una aclaración pendiente.

    Se audita exactamente una vez por turno y se elimina la memoria al finalizar.
    El llamador conserva una instancia de Agente1 por conversación.
    """
    return _ejecutar_turno(pregunta, agente, agente2, nueva_consulta)["respuesta_ctr001"]


def ejecutar_paso_a_paso(pregunta: str, agente: Optional[Agente1] = None,
                        agente2=simulador_agente_2, *, nueva_consulta: bool = False) -> dict:
    """Misma ejecución y auditoría que CTR-001, mostrando la traza en consola."""
    if agente is None:
        agente = Agente1()
    print("\n=== Preprocesamiento → Query JSON → Agente 2 → Decisión → Redacción y verificación ===")
    if isinstance(pregunta, str):
        print(json.dumps(PreprocesadorAutomocion.procesar(pregunta), ensure_ascii=False, indent=2))
    detalle = _ejecutar_turno(pregunta, agente, agente2, nueva_consulta)
    print(json.dumps(detalle, ensure_ascii=False, indent=2))
    if detalle["resultado_agente1"]["estado"] != "valida":
        return detalle["resultado_agente1"]
    return detalle


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
    # Ej: python -m Agents.agente1.core "par de apriete culata Golf 7"
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

        ejecutar_paso_a_paso(pregunta, agente)


if __name__ == "__main__":
    main()
