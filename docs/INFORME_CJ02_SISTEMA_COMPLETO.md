# Informe de Evaluación Real CJ-02 sobre el Sistema Integrado (Agente 1 + Agente 2)

**Responsable de ejecución:** Jaime Carnicero (Agente 1)  
**Fecha:** 24 de noviembre de 2026  
**Entorno de ejecución:** Ollama local en Apple M4 (16 GB RAM unificada, **100 % GPU Metal**)  
**Recuperación conectada:** Pipeline real de Agente 2 (`Agent2Pipeline`) sobre los 98 fragmentos de `Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json` (con vectorización por hash en ausencia de `torch`/`FlagEmbedding` locales y sin `bge-reranker-v2-m3`, `threshold=0.0`).

---

## 1. Comparativa Oficial CJ-02 (40 Preguntas): Qwen 3B vs Qwen 14B

Ejecución realizada con [`scripts/ejecutar_benchmark_cj02_real.py`](../scripts/ejecutar_benchmark_cj02_real.py) usando el flag `--agente2-real` (sin inyectar respuestas `ground truth` ni citas simuladas):

| Métrica | `qwen2.5:3b` + A2 real | `qwen2.5:14b` + A2 real | Observación |
| :--- | :---: | :---: | :--- |
| **Preguntas evaluadas** | 40 | 40 | Batería completa CJ-02 |
| **Casos superados (Evaluador CJ-02)** | **3 / 40 (7.5 %)** | **4 / 40 (10.0 %)** | Exige coincidencia exacta con `chunks_esperados` |
| **Respuestas con citas verificadas (A1-07)** | **1 / 40** (`CJ02-017`) | **8 / 40** | **14B supera 8× más la verificación extractiva** |
| **Precisión de citas (Evaluador CJ-02)** | 10.0 % | **17.5 %** | — |
| **Cobertura (Recall) de citas** | 10.0 % | **16.25 %** | — |
| **Tiempo total de ejecución** | **435.11 s** (~7.2 min) | **1181.91 s** (~19.7 min) | — |
| **Latencia media por pregunta** | **10.88 s** | **29.55 s** | `14B` corre al 100 % en GPU (~10.8 tokens/s) |

---

## 2. Desglose por Categoría (Evaluador Oficial CJ-02)

| Categoría (Total) | `qwen2.5:3b` | `qwen2.5:14b` |
| :--- | :---: | :---: |
| `valida_tecnica` (10) | 00/10 (0.0 %) | **01/10 (10.0 %)** |
| `trampa_version` (8) | 00/08 (0.0 %) | 00/08 (0.0 %) |
| `sustituido_obsoleto` (5) | 00/05 (0.0 %) | 00/05 (0.0 %) |
| `codigo_cruzado` (4) | 00/04 (0.0 %) | **01/04 (25.0 %)** |
| `ambigua_aclaracion` (5) | 02/05 (40.0 %) | 02/05 (40.0 %) |
| `dependiente_multiturno` (4) | 00/04 (0.0 %) | 00/04 (0.0 %) |
| `fuera_de_ambito` (1) | 00/01 (0.0 %) | 00/01 (0.0 %) |
| `sin_evidencia` (2) | **01/02 (50.0 %)** | 00/02 (0.0 %) |
| `error_simulado` (1) | 00/01 (0.0 %) | 00/01 (0.0 %) |

### Respuestas verificadas con citas reales generadas por `qwen2.5:14b`:
* `CJ02-002` (`[HTM240-CAT-001@1.0_p3_cat_001_10]`)
* `CJ02-006` (`[HTM240-HIS-001@1.0_p1_caso_002]`)
* `CJ02-008` (`[HTM240-ESQ-001@1.0_p1_arquitectura_general]`)
* `CJ02-012` (`[HTM240-PRC-003@1.0_p1_sustituido_corriente_bomba_3_5A]`)
* `CJ02-017` (`[HTM240-DTC-001@1.0_p5_htm0501]`)
* `CJ02-021` (`[HTM240-PRC-003@1.0_p1_sustituido_corriente_bomba_3_5A]`)
* `CJ02-025` (`[HTM240-DTC-001@1.0_p1_htm0142]`)
* `CJ02-027` (`[HTM240-DTC-001@1.0_p4_htm0405]`)

---

## 3. Causas Técnicas de la Brecha frente al Ideal

1. **Retrieval local sin BGE-M3 ni Reranker (`threshold=0.0`):** En esta máquina no están instalados `torch` ni `FlagEmbedding`. Sin BGE-M3 ni el corte del reranker, Agente 2 recupera fragmentos parciales con distinta aplicabilidad o fuera de tema y devuelve `ambiguo` en preguntas donde debería responder o abstenerse (`sin_evidencia`).
2. **Coincidencia estricta de `chunks_esperados`:** En varios casos donde `qwen2.5:14b` respondió con cita verificada (p. ej. `CJ02-002` citando `CAT-001`, o `CJ02-006` citando `HIS-001`), el evaluador CJ-02 los marcó como no pasados porque esperaba el ID exacto de `HTM240-MAN-001` o `HTM240-DTC-001`.
3. **Verificación extractiva estricta (A1-07):** `qwen2.5:3b` solo superó 1 vez el verificador oración a oración; `qwen2.5:14b` lo superó 8 veces, confirmando que el modelo de 14B es imprescindible para la fase de redacción en producción.
4. **Falta de contexto previo en `dependiente_multiturno` (`CJ02-033` a `CJ02-036`):** El propio `EvaluadorBenchmarkCJ02` documenta como limitación que faltan los turnos previos explícitos en el JSON del benchmark.

---

## 4. Archivos Generados para Marco y Equipo

* **Métricas JSON (3B + A2 real):** [`scripts/metricas_cj02_qwen2.5_3b_a2real.json`](../scripts/metricas_cj02_qwen2.5_3b_a2real.json)
* **Métricas JSON (14B + A2 real):** [`scripts/metricas_cj02_qwen2.5_14b_a2real.json`](../scripts/metricas_cj02_qwen2.5_14b_a2real.json)
* **Respuestas reales completas:** `Test/test_Models/respuestas_reales_cj02_qwen2.5_3b_a2real.json` y `Test/test_Models/respuestas_reales_cj02_qwen2.5_14b_a2real.json`
* **Informe de las 28 preguntas (20 control + 8 trampa):** [`docs/INFORME_PRUEBA_28_PREGUNTAS_qwen2.5_3b_redactor-qwen2.5_14b.md`](INFORME_PRUEBA_28_PREGUNTAS_qwen2.5_3b_redactor-qwen2.5_14b.md)
