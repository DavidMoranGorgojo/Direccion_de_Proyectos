# Agentes: Asistente Conversacional RAG (ThermoDrive HTM-240)

Este módulo implementa la lógica completa del sistema multiagente RAG para el asistente técnico automotriz ThermoDrive HTM-240:
- **Agente 1 (`Agents/agente1/`):** Agente conversacional, preprocesamiento léxico/DTC/REF, extracción del Query JSON formal (CTR-004), adaptador universal bidireccional, verificación estricta de citas y respaldo extractivo anti-alucinación, cliente HTTP de Backend (CTR-003/CTR-007) y auditoría local JSONL.
- **Agente 2 (`Agents/Agent_2/`):** Agente de recuperación híbrida (vectorial BGE-M3 + léxica BM25), fusión recíproca de rankings (RRF), filtrado por vigencia/obsolescencia, modelo reranker (bge-reranker-v2-m3) y construcción de evidencias trazables.
- **Servicio Unificado (`Agents/service.py`):** Pasarela HTTP FastAPI que orquesta ambos agentes bajo el contrato oficial CTR-001 interno (`/agentes/consulta`).

---

## 1. Requisitos e Instalación

Desde la raíz del repositorio:

```bash
# Dependencias base del servicio de Agentes
pip install -r Agents/requirements.txt

# Dependencias específicas de Agente 2 (recuperación y embeddings)
pip install -r Agents/Agent_2/requirements.txt

# Dependencias para pruebas unitarias y de integración
pip install pytest
```

---

## 2. Variables de Entorno

Configurar las variables de entorno antes de arrancar los servicios (o definirlas en `.env`):

| Variable | Valor por defecto | Descripción |
| :--- | :--- | :--- |
| `OLLAMA_URL` | `http://localhost:11434/v1` | URL base de la API de Ollama (compatible con OpenAI). |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Modelo LLM utilizado para razonamiento y redacción técnica. |
| `OLLAMA_TIMEOUT_S` | `10` | Timeout por petición LLM en segundos. |
| `ARSOFT_SERVICE_TOKEN` | *(vacío en dev)* | Token de autenticación Bearer entre Backend y Agentes (CTR-001/007). |
| `USE_REAL_AGENT2` | `0` | `1` activa el pipeline real de Agente 2; `0` usa el simulador integrado en A1. |
| `BACKEND_URL` | `http://localhost:8000` | URL del Backend real para registro (CTR-003) e historial (CTR-007). |
| `AGENT2_BACKEND_BASE_URL` | `http://localhost:8000` | URL del Backend para búsqueda vectorial/léxica en Agente 2. |
| `ARSOFT_AUDIT_PATH` | `agente1_registros.jsonl` | Ruta del archivo de auditoría local en contingencia JSONL. |

---

## 3. Cómo Arrancar los Agentes

### Opción A: Servicio HTTP Conjunto (Modo Producción / Integración Backend)

Levanta la pasarela HTTP de Agentes (`Agents/service.py`) en el puerto 8001:

```bash
# Con Agente 2 simulado (pruebas locales rápidas sin base de datos)
uvicorn Agents.service:app --host 0.0.0.0 --port 8001

# Con Agente 2 real (conectado a PostgreSQL / pgvector del Backend)
USE_REAL_AGENT2=1 ARSOFT_SERVICE_TOKEN="tu-token-secreto" uvicorn Agents.service:app --host 0.0.0.0 --port 8001
```

**Endpoints expuestos:**
- `POST /agentes/consulta` (CTR-001): Recibe `{"conversacion_id": "...", "pregunta": "..."}` y devuelve la respuesta verificada con fuentes.
- `DELETE /agentes/conversaciones/{conversacion_id}`: Libera la memoria temporal de la conversación.
- `GET /agentes/salud`: Comprueba el estado de Ollama y del pipeline de Agente 2.

---

### Opción B: Agente 1 en Modo Consola / Interactivo

Para depurar el flujo paso a paso en terminal (preprocesamiento → Query JSON → recuperación → verificación de citas):

```bash
# Bucle interactivo por consola
python -m Agents.agente1.core
```

O desde código Python:
```python
from Agents.agente1.core import ejecutar_paso_a_paso

resultado = ejecutar_paso_a_paso("¿Cada cuántos km se sustituye el refrigerante?")
print(resultado["respuesta_ctr001"]["texto"])
```

---

### Opción C: Agente 2 Standalone

Para evaluar o calibrar la recuperación de evidencias de Agente 2 de forma aislada:

```bash
python -m Agents.Agent_2
```

---

## 4. Batería de Pruebas Automatizadas (Pytest)

Ejecutar la suite completa de pruebas unitarias y de integración de Agente 1:

```bash
pytest Test/test_Agents -v
```

La suite cubre 118 casos:
- `test_agente1.py` (28 tests): Preprocesador, regex DTC/REF, normalizador universal CTR-004, verificación de citas.
- `test_cliente_backend.py` (15 tests): Registro CTR-003, login CTR-005, historial CTR-006/CTR-007, resiliencia offline JSONL e idempotencia.
- `test_integracion_pr8_pr9.py` (48 tests): Integración completa A1 ↔ A2, contratos, oráculo y benchmark.
- `test_revision_final.py` (27 tests): Robustez ante ambigüedades, límites de aclaración y obsolescencia.

---

## 5. Batería Oficial de Benchmark CJ-02 (40 Preguntas)

Ejecución y evaluación automática de las 40 preguntas contractuales:

```bash
# Ejecutar la batería completa sobre el pipeline integrado
python scripts/ejecutar_benchmark_cj02_real.py

# Verificar las métricas oficiales con el evaluador
python Test/test_Models/evaluar_benchmark.py \
  --respuestas Test/test_Models/respuestas_reales_cj02.json \
  --salida Test/test_Models/metricas_cj02_real_resultado.json
```

Resultados detallados e informe técnico: [`INFORME_BENCHMARK_CJ02.md`](file:///C:/Users/marco/Desktop/4º%20carrera/DP/Proyecto/Direccion_de_Proyectos/INFORME_BENCHMARK_CJ02.md).
