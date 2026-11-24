# Agente 2 — Recuperación de evidencias (RAG)

El Agente 2 recibe la consulta ya preprocesada por el Agente 1, busca en la base
de conocimiento del Backend y devuelve las evidencias que el Agente 1 usará para
redactar y verificar la respuesta. **No redacta la respuesta final.**

- Informe técnico completo: [docs/INFORME_GENERAL_AGENTE2.md](docs/INFORME_GENERAL_AGENTE2.md)
- Calibración A2-08 con las 20+8 preguntas: [docs/CALIBRACION_A2-08_28_PREGUNTAS.md](docs/CALIBRACION_A2-08_28_PREGUNTAS.md)
- README anterior (estados y benchmarks hasta el 17-11): [docs/HISTORICO_README.md](docs/HISTORICO_README.md)

Todos los comandos se ejecutan **desde la raíz del repositorio**.

## 1. Flujo

```
Agente 1 ──CTR-004──▶ recuperar_evidencias()
                        1. Validación de la entrada y filtros (versión, componente, tipo)
                        2. Embedding BGE-M3 (prefijo "query: ")
                        3. Búsqueda vectorial + léxica BM25 en el Backend (CTR-002)
                        4. Fusión RRF (A2-04)
                        5. Reranker bge-reranker-v2-m3 + umbral (A2-05)
                        6. Vigencia y vecinos (A2-06)
                        7. Empaquetado de evidencias (A2-07)
Agente 1 ◀──CTR-004── {estado, evidencias, campo_ambiguo, codigo_error, mensaje_error}
```

| Pieza | Fichero |
|---|---|
| Orquestación | `src/services/pipeline.py` (`Agent2Pipeline`, `recuperar_evidencias`) |
| Cliente del Backend (CTR-002) | `src/clients/backend.py` |
| Embeddings / reranker | `src/clients/bge_m3.py`, `src/clients/reranker_model.py`, `src/clients/reranker_loader.py` |
| Fusión, reranking, vigencia | `src/services/fusion.py`, `reranker.py`, `vigencia.py`, `neighbors.py` |
| Empaquetado CTR-004 | `src/services/evidence_builder.py` |
| Métricas y calibración (A2-08) | `src/evaluation/metrics.py`, `calibration.py`, `dataset_calibracion.py` |
| Simuladores para pruebas | `src/testing/backend_simulator.py`, `agent1_simulator.py` |

## 2. Instalación

```powershell
python -m pip install -r Agents/Agent_2/requirements.txt
```

Los pesos de BGE-M3 y del reranker (unos 2,3 GB) se descargan en la primera
carga. En Apptainer se montan desde `/models` (sección 4).

## 3. Configuración

| Variable | Por defecto | Uso |
|---|---|---|
| `AGENT2_BACKEND_BASE_URL` | `http://localhost:8000` | URL del Backend (CTR-002) |
| `ARSOFT_SERVICE_TOKEN` | vacío | Bearer de servicio de `/conocimiento/*`; sin él el Backend responde 401/503 |
| `AGENT2_REQUEST_TIMEOUT` / `AGENT2_CONNECT_TIMEOUT` | `5` / `3` s | Timeouts de lectura y de conexión, separados |
| `AGENT2_EMBEDDINGS_MODEL` / `AGENT2_EMBEDDING_DIMENSION` | `BAAI/bge-m3` / `1024` | Deben coincidir con el índice del Backend |
| `AGENT2_USE_QUERY_PREFIX` | `true` | Prefijo `query:` en las consultas a BGE-M3 |
| `AGENT2_SEARCH_TOP_K` | `30` | Candidatos por búsqueda |
| `AGENT2_RRF_K` | `60` | Constante de RRF |
| `AGENT2_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Modelo de reranking |
| `AGENT2_RERANK_TOP_K` | `20` | Máximo de candidatos que pasan al reranker |
| `AGENT2_RERANK_THRESHOLD` | `0.45` | Umbral del reranker (pendiente de fijar con A2-08, sección 6) |
| `ARSOFT_ENV` | — | `production` exige catálogos reales; `test` permite los sintéticos de `fixtures/` |

Los valores no válidos fallan al arrancar con un error que nombra la variable.

## 4. Arranque

### Dentro del servicio de Agentes (lo normal)

El Agente 2 no tiene servidor propio: lo llama el servicio de Agentes
(`Agents/service.py`), que expone CTR-001 al Backend en el puerto 8001.

```powershell
$env:USE_REAL_AGENT2 = "1"          # 0 (por defecto) = simulador del Agente 2
$env:ARSOFT_ENV = "production"
$env:AGENT2_BACKEND_BASE_URL = "http://localhost:8000"
# ARSOFT_SERVICE_TOKEN: el mismo valor que tiene el Backend (gestor de secretos)
python -m uvicorn Agents.service:app --host 127.0.0.1 --port 8001
```

### Por línea de comandos (diagnóstico)

```powershell
python -m Agents.Agent_2 --health-backend          # Backend e índice, sin cargar pesos
python -m Agents.Agent_2 --health                  # además carga e infiere con los dos modelos
python -m Agents.Agent_2 --query consulta.json     # una consulta CTR-004
```

`consulta.json`:

```json
{"texto_preprocesado": "Comprobación del circuito de refrigeración V1.1",
 "filtros": {"version": "V1.1", "componente": "refrigeracion"},
 "opciones": {"top_k": 3}}
```

### Apptainer

`Agents/apptainer/agentes.def` empaqueta el servicio completo (Agente 1 +
Agente 2); `Agents/Agent_2/apptainer/agente2.def` solo la CLI del Agente 2:

```bash
apptainer build agente2.sif Agents/Agent_2/apptainer/agente2.def
apptainer run --nv --bind /ruta/modelos:/models agente2.sif --health
```

## 5. Salida (CTR-004, A2-07)

```json
{
  "estado": "suficiente | solo_obsoleto | ambiguo | sin_evidencia | error",
  "evidencias": [
    {"chunk_id": "HTM240-DTC-001@1.0_p1_htm0142", "texto": "...", "score_final": 0.83,
     "estado_documento": "vigente | obsoleto | sustituido",
     "metadata": {"documento": "...", "version": "...", "vigente_para": ["V1.1"], "...": "..."}}
  ],
  "campo_ambiguo": "version | componente | null",
  "codigo_error": "entrada_invalida | modelo_no_disponible | modelo_incompatible | indice_no_disponible | tiempo_agotado | error_verificacion | servicio_no_disponible | null",
  "mensaje_error": "texto | null",
  "metricas": {"tiempo_total_ms": 0, "...": "..."}
}
```

| Estado | Qué hace el Agente 1 |
|---|---|
| `suficiente` | Redacta con las evidencias |
| `solo_obsoleto` | Redacta avisando de que la fuente está obsoleta |
| `ambiguo` | Pide aclaración del `campo_ambiguo` |
| `sin_evidencia` (`insuficiente` es sinónimo) | Se abstiene |
| `error` | Devuelve el `codigo_error` sin redactar |

Un documento sustituido sigue contando como vigente para las versiones de
`vigente_para` (A2-06); el Agente 1 aplica el mismo criterio en `es_obsoleta()`.
`metricas` viaja aparte para auditoría; con `trace_retrieval=True` incluye
también los rankings (vectorial, léxica, fusión y reranker).

El contrato se prueba contra el `core.py` real del Agente 1 en
`Test/test_Models/test_contrato_ctr004_agente1.py`, tanto con mensajes
construidos como de extremo a extremo con el pipeline sobre los 98 fragmentos.

## 6. Calibración del umbral (A2-08)

```powershell
# Con modelos y Backend real: el resultado que vale para fijar el umbral
python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend real --reranker real

# Sin modelos: valida el flujo con el Backend simulado y un reranker sustituto
python Agents/Agent_2/scripts/calibrar_umbrales_28.py --backend simulado --reranker solapamiento
```

Usa la batería oficial de 20 preguntas de control y 8 trampa
(`fixtures/preguntas_control_trampa.json`), calcula Recall@1/3/5, MRR y
abstención para cada umbral entre 0,00 y 1,00 y propone uno. Deja los
resultados en `docs/resultados/`. Detalles y hallazgos en
[docs/CALIBRACION_A2-08_28_PREGUNTAS.md](docs/CALIBRACION_A2-08_28_PREGUNTAS.md).

## 7. Pruebas

Las pruebas usan el Backend simulado y los catálogos sintéticos
(`Test/test_Models/conftest.py` fija `ARSOFT_ENV=test`), así que no necesitan
modelos ni Backend.

```powershell
# Todo lo del Agente 2 y del Agente 1 sin modelos
$env:PYTHONPATH = "shared;Backend/api;."
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q

# Solo el contrato con el Agente 1 y la calibración
python -m pytest Test/test_Models/test_contrato_ctr004_agente1.py Test/test_Models/test_calibracion_28.py -q

# Pruebas con el reranker real (se saltan por defecto)
$env:RUN_REAL_RERANKER_TEST = "1"
python -m pytest Test/test_Models/test_reranker_model.py Test/test_Performance/test_latency_reranker.py -v
```

Resultado el 24-11-2026 en Windows con Python 3.12: **974 passed, 4 skipped**
(los 4 necesitan modelos reales). `test_servicio_a2_integration.py` requiere
`fastapi` instalado (dependencia del servicio de Agentes).

## 8. Pendiente

- Fijar el umbral con `--backend real --reranker real` en una máquina con
  modelos (A2-05/A2-08).
- Validar el cliente CTR-002 y la ingesta con el Backend y PostgreSQL reales
  (PR #53).
- Tres preguntas de control (CTRL-08, CTRL-11 y CTRL-12) piden documentos que no
  están en el dataset de 98 fragmentos.
