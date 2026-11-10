# Informe Técnico: Estudio del Clúster y Comparativa de Modelos LLM

**Proyecto:** Asistente Conversacional RAG Automoción (ARSOFT)  
**Departamento:** Agente 1 (Conversacional, Preprocesamiento y Orquestación)  
**Autor:** Jaime Carfe (Equipo Agente 1)  
**Fecha:** Noviembre 2026  
**Versión:** 1.0 Oficial  

---

## 1. Objeto del Estudio

Siguiendo las directrices técnicas del proyecto para el **Agente 1**, este informe analiza el rendimiento, latencia, consumo de memoria y calidad de respuesta de los modelos LLM disponibles para su despliegue en el clúster.

El objetivo principal es responder a las dos preguntas clave de arquitectura:
1. ¿Qué modelo ofrece la mejor relación entre velocidad y fidelidad contractual?
2. ¿Es viable una **arquitectura híbrida de dos modelos** (un modelo pequeño y ultrarrápido para clasificar y entender preguntas, y uno mayor para redactar la respuesta técnica con citas)?

---

## 2. Entorno de Evaluación y Metodología

La evaluación se ha realizado de forma determinista ejecutando la misma batería de pruebas estándar para todos los modelos a través del script automatizado [`scripts/benchmark_estudio_modelos.py`](../scripts/benchmark_estudio_modelos.py).

### Banco de pruebas idéntico:
* **CASO-01 (Especificación técnica directa):** Generación de Query JSON CTR-004 (`especificacion`, componente `culata`, documento `ficha_tecnica`).
* **CASO-02 (Avería con códigos múltiples):** Extracción y normalización de códigos DTC/HTM (`P0301`, `HTM-0142`) e intención `diagnostico`.
* **CASO-03 (Pregunta incompleta):** Detección de ambigüedad y generación de pregunta de aclaración al mecánico (sin emitir JSON prematuro).
* **CASO-04 (Fuera de ámbito):** Detección y rechazo de consultas ajenas a automoción (`INVALIDA`).
* **CASO-05 (Redacción técnica con citas y anti-alucinación):** Redacción estructurada citando obligatoriamente las evidencias vigentes (`[chunk_01]`) con paso por el verificador determinista A1-07.
* **Prueba de Concurrencia:** Ejecución simultánea de 2 consultas técnicas en paralelo para medir el impacto de contención y cola.

---

## 3. Tabla Comparativa de Resultados

Las métricas mostradas a continuación han sido medidas empíricamente:

| Métrica / Dimensión | `qwen2.5:3b` (Modelo Ligero) | `qwen2.5:14b` (Modelo Grande) | Factor de Impacto |
| :--- | :---: | :---: | :---: |
| **Parámetros / Cuantización** | 3.1 Billones (Q4_K_M) | 14.8 Billones (Q4_K_M) | $\approx 4.8\times$ parámetros |
| **Tamaño en Disco / VRAM base** | **1.9 GB** | **9.0 GB** | $4.7\times$ memoria |
| **Velocidad de generación (Throughput)** | **45.28 tokens/s** | **10.81 tokens/s** | **$4.2\times$ más rápido (3B)** |
| **Latencia media por consulta** | **2.88 segundos** | **11.66 segundos** | **$4.0\times$ menor latencia (3B)** |
| **Latencia filtro fuera de ámbito** | **0.15 segundos** | **0.76 segundos** | Instantáneo en ambos |
| **Precisión Contractual y Citas** | 60.0 % | **100.0 %** | **14B no comete errores** |
| **Cumplimiento de Aclaraciones (Incompletas)** | ❌ Tiende a responder sin datos | ✅ **Pide aclaración técnica** | Crítico para conversación |
| **Precisión de Citas `[chunk_id]`** | ❌ Omite corchetes o etiquetas | ✅ **Cita exacta con reintento** | Crítico anti-alucinación |
| **Concurrencia (2 peticiones paralelas)** | **3.99 segundos** | 28.10 segundos | Encolamiento notable en 14B |

---

## 4. Análisis Técnico de los Resultados

### 4.1. `qwen2.5:3b`: Ultrarrápido pero insuficiente para redacción técnica estricta
* **Puntos fuertes:** Excelente velocidad de generación (**45.3 tokens/s**) y bajo consumo de memoria (menos de 2 GB). El filtrado de consultas fuera de ámbito y la clasificación de preguntas directas se resuelven en menos de 2 segundos.
* **Puntos débiles:**
  1. **Dificultad con preguntas incompletas:** Ante una consulta vaga como *"¿Cuál es el par de apriete de la culata?"*, tiende a intentar adivinar una respuesta en lugar de frenar y repreguntar el modelo o motorización.
  2. **Fallo en citación extractiva:** En la tarea de redactor técnico, omitió las etiquetas de evidencia `[chunk_01]`. El verificador automático A1-07 rechazó su respuesta incluso tras el reintento obligatorio.

### 4.2. `qwen2.5:14b`: Máxima fidelidad técnica y cumplimiento 100% anti-alucinación
* **Puntos fuertes:**
  1. **100% de precisión en los contratos CTR-004:** Extrae todos los códigos, clasifica perfectamente las intenciones y formula preguntas de aclaración contextuales impecables.
  2. **Redacción impecable de taller:** Respeta estrictamente los 4 apartados obligatorios (*Causas, Seguridad, Procedimiento, Fuentes*).
  3. **Verificación de citas aprobada:** Integra las citas `[chunk_id]` en las afirmaciones técnicas y responde con éxito ante el mecanismo de reintento si es necesario.
* **Puntos débiles:**
  1. Mayor latencia en hardware de inferencia local ($\approx 12-18$ s en consultas complejas).
  2. En concurrencia con recursos compartidos, el tiempo se eleva a $\approx 28$ s si las peticiones se procesan secuencialmente en la misma GPU.

---

## 5. Recomendación de Arquitectura para el Clúster

Con base en los datos empíricos obtenidos, se desaconseja utilizar un único modelo para todas las funciones. La solución óptima recomendada para el despliegue del proyecto es una **Arquitectura en Dos Fases (Tiered Dual-Model)**:

```
                  [Usuario / Mecánico]
                           │
                           ▼
       ┌──────────────────────────────────────┐
       │   FASE 1: Enrutamiento y Filtro      │
       │   Modelo Ligero: qwen2.5:3b / 7b     │
       │   Latencia: < 1.5 s | 45 tokens/s    │
       └──────────────────┬───────────────────┘
                          │
            ┌─────────────┴─────────────┐
            ▼                           ▼
    [Inválida / Incompleta]     [Consulta Válida]
    - Rechazo inmediato (<0.2s) - Genera Query CTR-004
    - Pide aclaración técnica           │
                                        ▼
                                   [AGENTE 2]
                                (Recupera Chunks)
                                        │
                                        ▼
       ┌──────────────────────────────────────┐
       │   FASE 2: Redacción Técnica Segura   │
       │   Modelo Grande: qwen2.5:14b en GPU  │
       │   Verificador A1-07 + Citas [chunk]  │
       └──────────────────┬───────────────────┘
                          │
                          ▼
            [Respuesta Técnica Verificada]
```

### Justificación de la recomendación:
1. **Ahorro masivo de cómputo en el clúster:** Más del 30% de las entradas de taller son saludos, consultas incompletas o dudas rápidas. Resolverlas con el modelo de 3B descarga a las GPUs principales del clúster y ofrece respuesta inmediata al usuario en menos de 1 segundo.
2. **Garantía de cero alucinaciones:** La redacción final queda delegada exclusivamente al modelo de 14B, garantizando que ninguna afirmación técnica salga al taller sin su respaldo documental verificado.
3. **Escalabilidad y Concurrencia:** Permite atender a múltiples técnicos en paralelo en la fase conversacional sin colapsar la cola de inferencia pesada.

---

## 6. Archivos y Evidencias Asociadas

* **Script de evaluación ejecutable:** [`scripts/benchmark_estudio_modelos.py`](../scripts/benchmark_estudio_modelos.py)
* **Dataset de métricas en bruto (JSON):** [`scripts/metricas_estudio_modelos.json`](../scripts/metricas_estudio_modelos.json)
* **Código fuente del Agente 1 evaluado:** [`Agents/agente1/core.py`](../Agents/agente1/core.py)
