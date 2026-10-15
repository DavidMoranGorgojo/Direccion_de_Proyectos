"""
AGENTE 1 (Conversacional y Preprocesamiento)
==================================================================
Versión base para repositorio Git (Fase F2 / F3).
Incluye:
  1. Módulo completo de Preprocesamiento y Normalización (A1-01 / A1-10)
  2. Clasificación de consultas y Generación de Query JSON (A1-03 / A1-04)
  3. Capa LLM conectada a Ollama en local (A1-02)
  4. Simulador provisional del Agente 2 (CJ-01) para pruebas desacopladas
"""

import os
import re
import json
import time
from typing import Dict, Any, List, Optional

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
MODELO_LLM = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Falta la librería 'openai'. Instálala con: pip install openai")


# ============================================================================
# 1. MÓDULO DE PREPROCESAMIENTO Y NORMALIZACIÓN (A1-01 y A1-10)
# ============================================================================
class PreprocesadorAutomocion:
    """
    Limpia ruido, normaliza identificadores técnicos y traduce
    síntomas informales al vocabulario estándar de automoción.
    """

    # Diccionario de síntomas: lenguaje coloquial -> término de manual técnico
    DICCIONARIO_SINTOMAS = {
        "tirones": "fallo de encendido / discontinuidad de par",
        "clac clac": "holgura mecánica en articulación / ruido de biela",
        "humo blanco": "consumo de líquido refrigerante",
        "humo negro": "defecto de inyección diésel / exceso de combustible",
        "pedal esponjoso": "presencia de aire en circuito hidráulico de frenos",
        "no arranca": "fallo en circuito de arranque / inmovilizador activo",
        "testigo motor": "código DTC almacenado en ECU / aviso MIL",
        "calentamiento": "temperatura de refrigerante fuera de rango",
    }

    # Expresiones regulares para normalización de códigos
    REGEX_NORMALIZACION = {
        r'\bHTM[-\s]?(\d{4})\b': r'HTM-\1',        # HTM 0142 -> HTM-0142
        r'\bREF[-\s]?([A-Za-z0-9]+)\b': r'REF-\1', # REF 123  -> REF-123
        r'\bv\.?\s?(\d+(?:\.\d+)?)\b': r'V\1',     # v. 1.2   -> V1.2
        r'\b([PCBU])\s?(\d{4})\b': r'\1\2',        # P 0301   -> P0301 (código DTC)
    }

    # Frases de cortesía y ruido
    PATRONES_RUIDO = [
        r'^(hola|buenas|buenos días|buenas tardes|hey|saludos)[,\s!.]*',
        r'^(por favor|podrías decirme|quisiera saber|necesito saber)[,\s]*',
        r'\b(muchas gracias|gracias|por favor)\b',
    ]

    @classmethod
    def procesar(cls, texto_usuario: str) -> Dict[str, Any]:
        """
        Ejecuta el pipeline completo de preprocesamiento sobre el texto.
        """
        texto_limpio = texto_usuario.strip()

        # 1. Limpieza de saludos y ruido
        for patron in cls.PATRONES_RUIDO:
            texto_limpio = re.sub(patron, '', texto_limpio, flags=re.IGNORECASE).strip()

        # 2. Normalización de códigos y versiones
        for patron, reemplazo in cls.REGEX_NORMALIZACION.items():
            texto_limpio = re.sub(patron, reemplazo, texto_limpio, flags=re.IGNORECASE)

        # 3. Mapeo y enriquecimiento de síntomas
        for coloquial, formal in cls.DICCIONARIO_SINTOMAS.items():
            if re.search(r'\b' + re.escape(coloquial) + r'\b', texto_limpio, re.IGNORECASE):
                texto_limpio = re.sub(
                    r'\b' + re.escape(coloquial) + r'\b',
                    f"{coloquial} ({formal})",
                    texto_limpio,
                    flags=re.IGNORECASE
                )

        texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()

        # 4. Extracción preliminar de entidades
        codigos = list(set(re.findall(r'\b(?:HTM-\d{4}|REF-[A-Za-z0-9]+|[PCBU]\d{4})\b', texto_limpio, re.IGNORECASE)))
        versiones = list(set(re.findall(r'\bV\d+(?:\.\d+)?\b', texto_limpio, re.IGNORECASE)))

        return {
            "texto_procesado": texto_limpio if texto_limpio else texto_usuario.strip(),
            "codigos_detectados": codigos,
            "versiones_detectadas": versiones
        }


# ============================================================================
# 2. PROMPT DEL SISTEMA Y CLASIFICACIÓN (A1-03 y A1-04)
# ============================================================================
SYSTEM_PROMPT_AGENTE1 = """
Eres el Agente 1 (Orquestador) de un sistema RAG de automoción.
Tu objetivo es analizar la consulta técnica del usuario y determinar si tiene suficiente
información para que el Agente 2 realice la búsqueda en la base de datos documental.

REGLAS DE CLASIFICACIÓN:
1. INVÁLIDA: Si la consulta no es de automoción (temas generales, saludos vacíos, etc.).
   -> Responde exactamente: INVALIDA
2. INCOMPLETA: Si faltan datos clave (por ejemplo: pregunta por un par de apriete, presión o avería sin especificar vehículo o pieza).
   -> Responde formulando una pregunta breve de aclaración en texto plano.
3. VÁLIDA: Si contiene vehículo/componente y el detalle técnico buscado.
   -> Responde EXCLUSIVAMENTE con este bloque JSON (sin texto adicional):
{
  "accion": "BUSCAR",
  "query_busqueda": "<términos técnicos optimizados para búsqueda vectorial y léxica>",
  "intencion": "<diagnostico|procedimiento|especificacion|normativa|mantenimiento>",
  "filtros": {
    "version": "<versión o año del vehículo si se indica, sino null>",
    "componente": "<pieza o subsistema si se indica, sino null>",
    "tipo_documento": "<manual|ficha_tecnica|procedimiento|normativa|otro>",
    "estado": "vigente"
  },
  "equipo": "<marca y modelo del vehículo, sino null>",
  "idioma": "es",
  "urgencia": "normal"
}
"""


# ============================================================================
# 3. AGENTE 1: LLAMADA A OLLAMA LOCAL (A1-02)
# ============================================================================
class Agente1:
    def __init__(self, base_url: str = OLLAMA_URL, modelo: str = MODELO_LLM):
        self.modelo = modelo
        self.cliente = OpenAI(base_url=base_url, api_key="ollama")
        self.historial: List[Dict[str, str]] = []

    def _consultar_llm(self, mensajes: List[Dict[str, str]]) -> Optional[str]:
        """Realiza la inferencia contra Ollama en localhost."""
        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=mensajes,
                temperature=0.0,
                max_tokens=250,
                timeout=40
            )
            return respuesta.choices[0].message.content.strip()
        except Exception as e:
            print(f"[AGENTE 1 ⚠️] Error al comunicar con Ollama: {e}")
            return None

    def procesar_consulta(self, entrada_usuario: str) -> Dict[str, Any]:
        """
        Flujo del Agente 1: Preprocesa -> Clasifica con LLM -> Devuelve estado.
        """
        # Paso 1: Preprocesamiento de texto
        datos_prep = PreprocesadorAutomocion.procesar(entrada_usuario)
        texto_limpio = datos_prep["texto_procesado"]

        # Paso 2: Preparar contexto para el LLM
        mensajes = [
            {"role": "system", "content": SYSTEM_PROMPT_AGENTE1}
        ] + self.historial + [
            {"role": "user", "content": texto_limpio}
        ]

        # Paso 3: Inferencia
        salida_llm = self._consultar_llm(mensajes)
        if not salida_llm:
            return {
                "estado": "error",
                "mensaje": "No se pudo conectar con Ollama. Verifica que 'ollama serve' esté activo."
            }

        # Paso 4: Evaluar respuesta del LLM
        if salida_llm.strip() == "INVALIDA":
            return {
                "estado": "rechazo",
                "mensaje": "Lo siento, solo puedo resolver dudas técnicas sobre automoción y sus manuales."
            }

        # Intentar parsear como Query JSON (Válida)
        match_json = re.search(r'\{.*\}', salida_llm, re.DOTALL)
        if match_json:
            try:
                query_dict = json.loads(match_json.group(0))
                if query_dict.get("accion") == "BUSCAR":
                    # Actualizar historial
                    self.historial.append({"role": "user", "content": entrada_usuario})
                    self.historial.append({"role": "assistant", "content": json.dumps(query_dict, ensure_ascii=False)})
                    return {
                        "estado": "valida",
                        "query_json": query_dict,
                        "entidades_detectadas": datos_prep
                    }
            except json.JSONDecodeError:
                pass

        # Si no es JSON ni inválida -> es una aclaración (Incompleta)
        self.historial.append({"role": "user", "content": entrada_usuario})
        self.historial.append({"role": "assistant", "content": salida_llm})
        return {
            "estado": "aclaracion",
            "mensaje": salida_llm
        }


# ============================================================================
# 4. SIMULADOR PROVISIONAL DEL AGENTE 2 (Paquete CJ-01)
# ============================================================================
def simulador_agente_2(query_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Mock provisional del Agente 2 para poder probar el flujo completo
    mientras el equipo de base de datos / recuperación termina su parte.
    """
    query = query_json.get("query_busqueda", "").lower()
    componente = str(query_json.get("filtros", {}).get("componente", "")).lower()

    # Ejemplo simulado: culata / apriete
    if "culata" in query or "culata" in componente:
        return [
            {
                "chunk_id": "chunk_01",
                "texto": "El par de apriete de los tornillos de culata se realiza en 3 fases: Fase 1 a 40 Nm, Fase 2 a 90° y Fase 3 a 90° adicionales.",
                "metadata": {"documento": "Manual_Taller_Motor.pdf", "seccion": "Culata", "pagina": 42},
                "estado": "vigente"
            }
        ]

    # Ejemplo simulado: error DTC P0301
    if "p0301" in query:
        return [
            {
                "chunk_id": "chunk_02",
                "texto": "El código DTC P0301 indica fallo de combustión detectado en el cilindro 1. Comprobar bujía, bobina de encendido e inyector.",
                "metadata": {"documento": "Guia_Diagnostico_OBD.pdf", "seccion": "Ignicion", "pagina": 15},
                "estado": "vigente"
            }
        ]

    # Sin resultados
    return []


# ============================================================================
# 5. BUCLE PRINCIPAL DE PRUEBA EN CONSOLA
# ============================================================================
def main():
    print("=" * 60)
    print("  AGENTE 1: CONVERSACIONAL Y PREPROCESAMIENTO (Módulo Git Base)")
    print(f"  Modelo: {MODELO_LLM} (Ollama Local)")
    print("  Escribe 'salir' para terminar")
    print("=" * 60)

    agente = Agente1()

    while True:
        try:
            pregunta = input("\nTú: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if pregunta.lower() in ["salir", "exit", "quit"]:
            print("Cerrando sesión.")
            break
        if not pregunta:
            continue

        resultado = agente.procesar_consulta(pregunta)

        if resultado["estado"] == "valida":
            query_json = resultado["query_json"]
            print("\n[✅ CONSULTA VÁLIDA — Query JSON para Agente 2]:")
            print(json.dumps(query_json, ensure_ascii=False, indent=2))

            # Conexión con el simulador del Agente 2
            print("\n[🔄 Consultando Simulador Agente 2 (CJ-01)...]")
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
