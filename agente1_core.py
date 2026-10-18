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
import uuid
import logging
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

try:
    from pydantic import BaseModel, Field, field_validator

    class FiltrosQuerySchema(BaseModel):
        version: Optional[str] = Field(default=None)
        componente: Optional[str] = Field(default=None)
        tipo_documento: Optional[str] = Field(default=None)
        codigos: List[str] = Field(default_factory=list)

        @field_validator("tipo_documento")
        @classmethod
        def validar_tipo_doc(cls, v):
            if v is not None and v.lower() not in TIPOS_DOC_VALIDOS:
                raise ValueError(f"tipo_documento '{v}' no válido. Opciones: {TIPOS_DOC_VALIDOS}")
            return v.lower() if v else None

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

        @field_validator("intencion")
        @classmethod
        def validar_intencion(cls, v):
            v_clean = str(v).strip().lower() if v else "otro"
            if v_clean in {"fallo", "averia", "analizar_fallo", "codigo_error", "sintoma"}:
                return "diagnostico"
            if v_clean not in INTENCIONES_VALIDAS:
                raise ValueError(f"Intención '{v}' no válida. Opciones: {INTENCIONES_VALIDAS}")
            return v_clean

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

    if HAS_PYDANTIC:
        try:
            validado = QueryJSONSchema(**datos)
            return True, None, validado.model_dump()
        except Exception as e:
            return False, f"Fallo de validación Pydantic: {e}", None
    else:
        # Validación de respaldo manual (idénticas reglas que Pydantic)
        texto = datos.get("texto_busqueda") or datos.get("query_busqueda")
        if not texto or not isinstance(texto, str) or not texto.strip():
            return False, "El campo 'texto_busqueda' debe ser una cadena no vacía.", None

        pregunta = datos.get("pregunta_original") or texto
        trace_id = datos.get("trace_id") or f"t-{uuid.uuid4().hex[:6]}"
        conv_id = datos.get("conversacion_id") or "c-0001"

        intencion_raw = str(datos.get("intencion", "")).strip().lower()
        if intencion_raw in {"fallo", "averia", "analizar_fallo", "codigo_error", "sintoma"}:
            intencion = "diagnostico"
        elif intencion_raw in INTENCIONES_VALIDAS:
            intencion = intencion_raw
        else:
            return False, f"Intención '{intencion_raw}' inválida. Debe ser una de {INTENCIONES_VALIDAS}.", None

        filtros = datos.get("filtros")
        if filtros is not None and not isinstance(filtros, dict):
            return False, "El campo 'filtros' debe ser un objeto o diccionario.", None

        filtros = filtros or {}
        tipo_doc = filtros.get("tipo_documento")
        if tipo_doc is not None and str(tipo_doc).lower() not in TIPOS_DOC_VALIDOS:
            return False, f"tipo_documento '{tipo_doc}' no permitido.", None

        codigos = filtros.get("codigos") or []
        if not isinstance(codigos, list):
            codigos = [str(codigos)]

        opciones = datos.get("opciones") or {}
        if not isinstance(opciones, dict):
            opciones = {}

        datos_limpios = {
            "trace_id": trace_id,
            "conversacion_id": conv_id,
            "texto_busqueda": texto.strip(),
            "pregunta_original": pregunta.strip(),
            "intencion": intencion,
            "filtros": {
                "version": filtros.get("version"),
                "componente": filtros.get("componente"),
                "tipo_documento": str(tipo_doc).lower() if tipo_doc else None,
                "codigos": codigos
            },
            "opciones": {
                "top_k": int(opciones.get("top_k", 3)),
                "incluir_obsoletos": bool(opciones.get("incluir_obsoletos", True))
            }
        }
        return True, None, datos_limpios



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
        r'^(?:buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|saludos|buenas|hola|hey)[,\s!.]*',
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
    RE_VERSION = re.compile(r'\b(?:versión|version|ver\.)\s*([vV]?\d+(?:\.\d+)?)\b', re.IGNORECASE)

    # Patrón para extracción determinista de códigos
    PATRON_EXTRACCION_CODIGOS = re.compile(
        r'\b(?:HTM-\d{4}|REF-[A-Za-z0-9]*\d[A-Za-z0-9]*|[PCBU]\d{4})\b'
    )
    PATRON_EXTRACCION_VERSIONES = re.compile(r'\bV\d+(?:\.\d+)?\b')

    @classmethod
    def procesar(cls, texto_usuario: str) -> Dict[str, Any]:
        """
        Ejecuta el pipeline de preprocesamiento sobre el texto.
        """
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

        # 5. Normalización de versión solo con prefijo explícito (BLOQUEANTE 3)
        texto = cls.RE_VERSION.sub(r'V\1', texto)

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
        versiones_detectadas = list(dict.fromkeys(v.upper() for v in versiones_raw))

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
   -> Responde ÚNICAMENTE con un JSON conforme al contrato CTR-004:

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

        # Intento 2: Fallback nativo usando urllib (biblioteca estándar de Python, sin pip)
        try:
            import urllib.request
            payload = {
                "model": self.modelo,
                "messages": mensajes,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 512
                }
            }
            # Derivar URL de Ollama /api/chat a partir de base_url
            host = self.base_url.replace("/v1", "").rstrip("/")
            url = f"{host}/api/chat"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=50) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"Error conectando con Ollama en {self.base_url}: {e}")
            return None

    def procesar_consulta(self, entrada_usuario: str) -> Dict[str, Any]:
        """
        Flujo de procesamiento:
          1. Preprocesamiento determinista (limpieza, normalización y extracción de códigos).
          2. Consulta al LLM.
          3. Tratamiento de respuestas y validación estricta de JSON CTR-004.
        """
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
            filtros = query_dict.get("filtros") or {}
            if not isinstance(filtros, dict):
                filtros = {}

            # Incorporar códigos detectados por regex deterministamente
            codigos_existentes = filtros.get("codigos") or []
            if not isinstance(codigos_existentes, list):
                codigos_existentes = [str(codigos_existentes)]
            filtros["codigos"] = list(dict.fromkeys(codigos_existentes + codigos_detectados))
            query_dict["filtros"] = filtros

            if "opciones" not in query_dict or not isinstance(query_dict["opciones"], dict):
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
# 5. SIMULADOR DEL AGENTE 2 (Mock CJ-01) - BLOQUEANTE 6
# ============================================================================
def simulador_agente_2(query_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Simulador provisional del Agente 2 tolerante a None/null en cualquier campo.
    """
    filtros = query_json.get("filtros") or {}
    query = (query_json.get("texto_busqueda") or query_json.get("query_busqueda") or "").lower()
    componente = str(filtros.get("componente") or "").lower()
    codigos = [str(c).lower() for c in (filtros.get("codigos") or [])]

    # Búsqueda simulada por culata / apriete
    if "culata" in query or "culata" in componente:
        return [
            {
                "chunk_id": "chunk_01",
                "texto": "El par de apriete de los tornillos de culata se realiza en 3 fases: Fase 1 a 40 Nm, Fase 2 a 90° y Fase 3 a 90° adicionales.",
                "metadata": {"documento": "Manual_Taller_Motor.pdf", "seccion": "Culata", "pagina": 42},
                "estado": "vigente"
            }
        ]

    # Búsqueda simulada por código DTC P0301
    if "p0301" in query or any("p0301" in c for c in codigos):
        return [
            {
                "chunk_id": "chunk_02",
                "texto": "El código DTC P0301 indica fallo de combustión detectado en el cilindro 1. Comprobar bujía, bobina de encendido e inyector.",
                "metadata": {"documento": "Guia_Diagnostico_OBD.pdf", "seccion": "Ignicion", "pagina": 15},
                "estado": "vigente"
            }
        ]

    # Búsqueda simulada por código HTM-0142 / HTM0142
    if "htm-0142" in query or any("htm-0142" in c or "htm0142" in c for c in codigos):
        return [
            {
                "chunk_id": "chunk_03",
                "texto": "Procedimiento HTM-0142: Verificación de presiones en rampa de inyección common rail.",
                "metadata": {"documento": "Procedimiento_Inyeccion.pdf", "seccion": "HTM", "pagina": 8},
                "estado": "vigente"
            }
        ]

    return []



# ============================================================================
# 6. BUCLE PRINCIPAL DE CONSOLA
# ============================================================================
def main():
    print("=" * 65)
    print("  AGENTE 1: CONVERSACIONAL Y PREPROCESAMIENTO (Core)")
    print(f"  Modelo: {MODELO_LLM} en {OLLAMA_URL}")
    print("  Escribe 'salir' para terminar o 'reset' para reiniciar conversación.")
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
        if not pregunta:
            continue

        resultado = agente.procesar_consulta(pregunta)

        if resultado["estado"] == "valida":
            query_json = resultado["query_json"]
            print("\n[CONSULTA VÁLIDA — Query JSON validado CTR-004]:")
            print(json.dumps(query_json, ensure_ascii=False, indent=2))

            print("\n[Consultando Simulador Agente 2 (CJ-01)...]")
            evidencias = simulador_agente_2(query_json)

            if evidencias:
                print(f"-> Se recuperaron {len(evidencias)} evidencia(s) simulada(s):")
                for ev in evidencias:
                    print(f"   [{ev['chunk_id']}] {ev['texto']} (Fuente: {ev['metadata']['documento']}, pág. {ev['metadata']['pagina']})")
            else:
                print("-> El simulador no encontró datos para estos términos.")

        elif resultado["estado"] == "aclaracion":
            print(f"\nAgente 1 (Aclaración): {resultado['mensaje']}")

        elif resultado["estado"] == "rechazo":
            print(f"\nAgente 1: {resultado['mensaje']}")

        else:
            print(f"\n[Error]: {resultado['mensaje']}")


if __name__ == "__main__":
    main()
