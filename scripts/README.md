# Scripts de Utilidad, Calibración y Diagnóstico

Este directorio contiene herramientas de línea de comandos para la evaluación de contratos, pruebas de estrés y diagnósticos del sistema RAG Automotriz:

## 1. Conexión y Pruebas con el Clúster Legio (GVIS - ULE)

- **`probar_conexion_cluster.py`**:
  Diagnóstico de conectividad en 4 pasos: validación de API Key, comprobación del túnel SSH en `localhost:4000`, prueba de inferencia ligera con rol `"rapido"` y prueba técnica con rol `"potente"`.
  ```bash
  python scripts/probar_conexion_cluster.py
  ```

- **`probar_rag_cluster.py`**:
  Ejecución extremo a extremo del flujo RAG combinando la recuperación y filtrado léxico local en el PC con la inferencia de intención y redacción técnica en el clúster.
  ```bash
  python scripts/probar_rag_cluster.py --pregunta "¿A qué temperatura inicial abre el termostato CMP-08?"
  ```

> **Aviso de recursos:**
> - El nodo de acceso `legio2` tiene una cuota estricta de 4 GiB de RAM y 1 CPU por usuario. No ejecutar cálculos pesados en `legio2`.
> - Las GPUs son compartidas: mantener `temperature=0.0`, `max_tokens=512` y `stream=False`.
> - Abrir previamente el túnel SSH: `ssh -L 4000:localhost:4000 juan.pinos@193.146.98.97` (con VPN ULE si se está fuera del campus).

---

## 2. Benchmarks Oficiales

- **`ejecutar_benchmark_cj02_real.py`**:
  Batería oficial de 40 preguntas técnicas, de control, trampas de versión y casos multiturno bajo el contrato CJ-02.
  ```bash
  python scripts/ejecutar_benchmark_cj02_real.py
  ```

- **`evaluar_28_preguntas_a1_a2.py`**:
  Evaluación de calibración y umbrales sobre el conjunto de 20 preguntas de control y 8 preguntas trampa.

---

## 3. Pruebas Locales del Agente 2

- **`probar_agente2_local.py`**:
  Pruebas aisladas del motor de recuperación híbrida (BM25 + vectorial + RRF).

- **`probar_flujo_completo.py`**:
  Prueba del flujo integrado en modo local / Ollama.
