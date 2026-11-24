# Agente 2 — Recuperación de evidencias (RAG)

El Agente 2 del proyecto ARSOFT/FaCyL se encarga de recuperar y seleccionar evidencias documentales relevantes para responder a las consultas recibidas.

Su función es recuperar información y preparar evidencias para el Agente 1, no generar directamente la respuesta final.

- Informe técnico completo: [docs/INFORME_GENERAL_AGENTE2.md](docs/INFORME_GENERAL_AGENTE2.md)
- Calibración A2-08 con las 20+8 preguntas: [docs/CALIBRACION_A2-08_28_PREGUNTAS.md](docs/CALIBRACION_A2-08_28_PREGUNTAS.md)

Todos los comandos se ejecutan **desde la raíz del repositorio**.

## 1. Flujo

El flujo previsto es:

1. Validación de la consulta.
2. Aplicación de filtros obligatorios.
3. Búsqueda vectorial y búsqueda léxica BM25.
4. Fusión de resultados mediante Reciprocal Rank Fusion (RRF).
5. Selección de un máximo configurable de candidatos para el reranker.
6. Reordenación de candidatos mediante un modelo reranker.
7. Aplicación de un umbral mínimo de relevancia.
8. Comprobación de vigencia y recuperación de chunks vecinos.
9. Generación del JSON de evidencias para el Agente 1.

Detalle por paquete de trabajo y contrato:

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

Los siguientes comandos se ejecutan desde la raíz del repositorio.

Instalar las dependencias del Agente 2:

```powershell
python -m pip install -r Agents/Agent_2/requirements.txt
```

Comprobar que las dependencias instaladas son compatibles:

```powershell
python -m pip check
```

La primera carga del modelo puede requerir descargar sus pesos. En las pruebas realizadas, el modelo ocupaba aproximadamente 2,27 GB.

En Apptainer los pesos se montan desde `/models` (sección 4).

### Requisitos

- Python 3.10, versión utilizada durante las pruebas.
- Acceso a Internet para descargar inicialmente el modelo de reranking.
- Espacio suficiente para almacenar los pesos del modelo.
- Dependencias indicadas en `Agents/Agent_2/requirements.txt`.

Las dependencias principales declaradas son:

```text
FlagEmbedding==1.4.2
torch==2.14.1
transformers==5.20.2
pytest==9.1.1
```

Estas versiones corresponden al entorno utilizado para las pruebas y el benchmark real.

La comprobación `python -m pip check` finalizó con:

```text
No broken requirements found.
```

Esto confirma que no se detectaron incompatibilidades declaradas entre los paquetes instalados. No se ha verificado todavía una instalación limpia desde cero en otro equipo.

La instalación de estas bibliotecas puede incorporar dependencias adicionales.

## 3. Configuración

La configuración se encuentra en:

`Agents/Agent_2/src/core/config.py`

Los parámetros pueden modificarse mediante variables de entorno.

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
| `AGENT2_RERANK_THRESHOLD` | `0.45` | Umbral del reranker (pendiente de fijar con A2-08, sección 7) |
| `ARSOFT_ENV` | — | `production` exige catálogos reales; `test` permite los sintéticos de `fixtures/` |

Las variables `AGENT2_RRF_K`, `AGENT2_SEARCH_TOP_K` y `AGENT2_RERANK_TOP_K` deben ser enteros positivos.

`AGENT2_RERANK_THRESHOLD` debe ser un número finito entre 0 y 1.

`AGENT2_RERANKER_MODEL` debe contener un identificador no vacío. Los espacios iniciales y finales se eliminan.

`ARSOFT_SERVICE_TOKEN` es opcional en la configuración, pero el Backend real protege `/conocimiento/*` con un Bearer de servicio: sin el mismo token que usa el Backend, las búsquedas responden `401` (o `503` si el Backend no lo tiene configurado). Debe coincidir con el valor desplegado en el entorno del Backend.

Los valores no válidos producen errores explícitos que identifican la variable de configuración correspondiente.

### Ejemplo de configuración en PowerShell

```powershell
$env:AGENT2_BACKEND_BASE_URL = "http://localhost:8000"
$env:ARSOFT_SERVICE_TOKEN = "token-de-servicio"
$env:AGENT2_RRF_K = "60"
$env:AGENT2_RERANK_THRESHOLD = "0.45"
$env:AGENT2_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
$env:AGENT2_SEARCH_TOP_K = "30"
$env:AGENT2_RERANK_TOP_K = "20"
```

Estas variables se aplican a la sesión actual de PowerShell y a los procesos que se inicien desde ella.

La configuración se lee al importar el módulo correspondiente. Para aplicar cambios en un proceso que ya está ejecutándose, se recomienda reiniciarlo.

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

## 6. Componentes

### Fusión RRF (A2-04)

Archivo:

`Agents/Agent_2/src/services/fusion.py`

La función `rrf()` combina dos rankings:

- Resultados de búsqueda vectorial.
- Resultados de búsqueda BM25.

La puntuación se calcula mediante:

`RRF(d) = suma(1 / (k + posición))`

El algoritmo:

- Identifica los resultados mediante `chunk_id`.
- Combina las aportaciones de ambos rankings.
- Conserva los metadatos disponibles y las puntuaciones originales.
- Completa metadatos vacíos cuando la otra fuente aporta información válida.
- Ordena por puntuación RRF descendente.
- No modifica las listas de entrada.
- Valida la constante `k` y los identificadores de los resultados.
- Evita sumar dos veces la contribución de un mismo `chunk_id` dentro de un mismo ranking.

#### Tratamiento de duplicados

Si un mismo `chunk_id` aparece repetido en la búsqueda vectorial o en BM25, únicamente aporta una vez a la puntuación RRF de esa fuente.

Los duplicados pueden utilizarse para completar metadatos, pero no para aumentar artificialmente la relevancia.

Las posiciones utilizadas para calcular RRF corresponden al orden de los resultados únicos de cada ranking.

#### Validación de identificadores

Se aceptan identificadores de tipo cadena no vacía o entero, incluido `0`.

Se rechazan identificadores ausentes, cadenas vacías o formadas únicamente por espacios, booleanos y otros tipos no admitidos.

### Reranker y umbral (A2-05)

Archivos:

- `Agents/Agent_2/src/services/reranker.py`
- `Agents/Agent_2/src/clients/reranker_model.py`

El modelo utilizado es:

`BAAI/bge-reranker-v2-m3`

El reranker evalúa pares formados por una consulta y el texto de un candidato.

El adaptador utiliza:

`compute_score(pairs, normalize=True)`

Los candidatos se ordenan por su puntuación de reranking y posteriormente se aplica el umbral de relevancia.

El umbral inicial configurado es `0.45`. Este valor todavía debe validarse mediante las métricas y consultas de evaluación del proyecto.

#### Validación de entradas

Antes de ejecutar la inferencia se comprueba que:

- La consulta sea una cadena de texto no vacía.
- Cada candidato tenga una estructura válida.
- Cada candidato incluya un campo `texto` con contenido no vacío.
- Las puntuaciones devueltas por el modelo sean numéricas y finitas.
- El número de puntuaciones recibidas coincida con el número de candidatos evaluados.

Las entradas inválidas producen errores explícitos en lugar de aceptarse silenciosamente.

Los errores del modelo se propagan para que puedan gestionarse desde la capa de orquestación.

#### Límite de candidatos

La variable `AGENT2_RERANK_TOP_K` establece un límite predeterminado de **20 candidatos**.

Cuando la fusión RRF devuelve más candidatos que ese límite:

1. Se validan sus puntuaciones RRF.
2. Se ordenan por puntuación RRF descendente.
3. Se seleccionan los candidatos mejor posicionados hasta alcanzar el límite.
4. Se ejecuta el reranker únicamente sobre los candidatos seleccionados.

Este límite reduce el número de pares que procesa el modelo y evita enviar automáticamente todos los resultados de ambas búsquedas a la inferencia.

La selección previa se basa en RRF; la ordenación final se basa en las puntuaciones del reranker.

#### Protección de inferencias concurrentes

`RerankerModel` incorpora un bloqueo de inferencia mediante `threading.Lock`.

El bloqueo protege la llamada a `compute_score()` para impedir que varios hilos utilicen simultáneamente la misma instancia del modelo.

Esto evita errores de acceso concurrente como `RuntimeError: Already borrowed`.

El bloqueo se libera también cuando la inferencia produce una excepción.

Esta protección se ha verificado mediante pruebas con llamadas concurrentes. No implica que el rendimiento bajo carga concurrente esté validado para producción.

### Carga reutilizable del modelo (A2-09)

Archivo:

`Agents/Agent_2/src/clients/reranker_loader.py`

La función `get_reranker()` proporciona acceso al modelo configurado.

El cargador utiliza una caché en memoria para reutilizar la instancia del modelo dentro de un mismo proceso.

Esto permite:

- Evitar cargar los pesos en cada consulta.
- Reducir el coste de inicialización en llamadas posteriores.
- Retrasar la carga hasta que se necesite el modelo.
- Propagar errores de inicialización.

La carga del modelo está protegida frente a accesos concurrentes y la inferencia dispone de su propio bloqueo.

La caché es local al proceso. Si se utilizan varios procesos, cada uno puede necesitar su propia instancia del modelo.

El modelo se ha probado en CPU con `use_fp16=False`.

## 7. Calibración del umbral (A2-08)

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

## 8. Pruebas

Las pruebas usan el Backend simulado y los catálogos sintéticos
(`Test/test_Models/conftest.py` fija `ARSOFT_ENV=test`), así que no necesitan
modelos ni Backend.

```powershell
# Todo lo del Agente 2 y del Agente 1 sin modelos
$env:PYTHONPATH = "shared;Backend/api;."
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q

# Por marcador (registrados en pytest.ini, asignados en Test/test_Models/conftest.py)
python -m pytest Test/test_Models -m agente2 -q    # todo el Agente 2
python -m pytest Test/test_Models -m contrato -q   # contrato CTR-004 con el Agente 1 y calibración A2-08
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -m "not modelo_real" -q

# Pruebas con el reranker real (se saltan por defecto)
$env:RUN_REAL_RERANKER_TEST = "1"
python -m pytest Test/test_Models/test_reranker_model.py Test/test_Performance/test_latency_reranker.py -v
```

Resultado el 24-11-2026 en Windows con Python 3.12: **974 passed, 4 skipped**
(los 4 necesitan modelos reales). `test_servicio_a2_integration.py` requiere
`fastapi` instalado (dependencia del servicio de Agentes).


### Qué cubren las pruebas de los componentes

Las pruebas incluyen comprobaciones de:

- Fusión RRF y conservación de metadatos.
- Duplicados dentro de un mismo ranking.
- Identificadores inválidos y aceptación del identificador `0`.
- Validación de parámetros de configuración.
- Restauración de la configuración entre pruebas.
- Consultas y textos vacíos o de tipos incorrectos.
- Resultados sin puntuaciones válidas.
- Respuestas `None` del modelo.
- Puntuaciones no numéricas o no finitas.
- Límite configurable de candidatos.
- Selección de candidatos mediante puntuación RRF.
- Protección de inferencias concurrentes.
- Liberación del bloqueo después de una excepción.
- Conservación de las entradas originales.

Estas pruebas comprueban que los errores no se acepten silenciosamente como resultados válidos.

### Prueba opcional con el modelo real

En PowerShell:

```powershell
$env:RUN_REAL_RERANKER_TEST = "1"
python -m pytest Test/test_Models/test_reranker_model.py -v
Remove-Item Env:RUN_REAL_RERANKER_TEST
```

Esta prueba requiere disponer de las dependencias y los pesos del modelo.

### Benchmark RRF

```powershell
python -m pytest Test/test_Performance/test_latency_rrf.py -v -s
```

### Benchmark del reranker real

```powershell
$env:RUN_REAL_RERANKER_TEST = "1"
python -m pytest Test/test_Performance/test_latency_reranker.py -v -s
Remove-Item Env:RUN_REAL_RERANKER_TEST
```

El benchmark utiliza `get_reranker()` y la función `rerank_results()` del Agente 2.

Compara 1, 5, 10 y 20 candidatos con fragmentos de texto de longitud más representativa que los empleados en el benchmark anterior.

Durante la última ejecución verificada se configuraron temporalmente:

- 2 mediciones por tamaño.
- 1 calentamiento por tamaño.

Estas cantidades permiten comprobar el funcionamiento del benchmark con un coste de ejecución menor, pero no son suficientes para establecer percentiles de latencia robustos.

El modelo se carga una sola vez y se reutiliza en todas las mediciones.

Los resultados pueden variar según el hardware, la carga del sistema, la longitud de los textos y el número de candidatos.

## 9. Rendimiento del reranker real

### Benchmark actualizado del reranker real

Modelo: `BAAI/bge-reranker-v2-m3`.

Entorno: Python 3.10.11, ejecución en CPU con `use_fp16=False`.

Se utilizaron fragmentos de aproximadamente 78 a 95 palabras de media, según el tamaño del conjunto.

Tiempo de obtención inicial del modelo: **20.984,25 ms**, aproximadamente **20,98 segundos**.

Se realizaron 2 mediciones y 1 calentamiento por cantidad de candidatos.

| Candidatos | Media | Mediana | P95 calculado | Máximo |
|---|---:|---:|---:|---:|
| 1 | 1.272,05 ms | 1.272,05 ms | 1.284,61 ms | 1.284,61 ms |
| 5 | 6.895,32 ms | 6.895,32 ms | 6.945,34 ms | 6.945,34 ms |
| 10 | 12.443,00 ms | 12.443,00 ms | 12.542,88 ms | 12.542,88 ms |
| 20 | 17.207,92 ms | 17.207,92 ms | 17.285,25 ms | 17.285,25 ms |

**Resultado de ejecución:** `1 passed in 135.77s`.

La prueba completó 12 inferencias, contando los calentamientos, sin errores.

**Limitación:** con solo dos mediciones por tamaño, el P95 calculado coincide con el máximo. No debe interpretarse como una estimación estadísticamente fiable del percentil 95.

### Interpretación de resultados

Los resultados muestran que:

- La inicialización del modelo es costosa, por lo que conviene cargarlo una vez y reutilizarlo.
- La inferencia en CPU tiene un coste significativo.
- El tiempo de inferencia aumenta al procesar conjuntos mayores de candidatos en esta ejecución.
- Limitar los candidatos enviados al reranker es importante para controlar la latencia.
- Los textos de mayor longitud pueden incrementar el coste de inferencia.
- El bloqueo de inferencia protege el acceso al modelo, pero puede hacer que las solicitudes concurrentes esperen su turno.

Las mediciones no incluyen búsqueda vectorial, BM25, filtros, generación de evidencias ni comunicación con el Agente 1.

**Importante:** estos resultados corresponden a componentes individuales. No representan la latencia extremo a extremo del Agente 2.

El número de mediciones sigue siendo insuficiente para establecer garantías de rendimiento en producción.

## 10. Resiliencia y despliegue

Se han incorporado comprobaciones para evitar comportamientos silenciosos ante entradas inválidas o fallos de inicialización.

Para el despliegue se recomienda:

- Inicializar el reranker una vez por proceso y reutilizarlo.
- Asegurar que los pesos del modelo estén disponibles antes de atender consultas que los requieran.
- Dimensionar memoria y CPU según el número de procesos concurrentes.
- Mantener el bloqueo de inferencia cuando se comparta una instancia del modelo entre hilos.
- Configurar explícitamente `AGENT2_RERANK_TOP_K` según los objetivos de latencia.
- Configurar los demás parámetros mediante variables de entorno cuando sea necesario.
- Registrar y gestionar los errores en la capa de orquestación, sin convertir fallos internos en respuestas vacías aparentemente válidas.
- Medir la latencia completa una vez integrado el pipeline.
- Evaluar el comportamiento bajo concurrencia antes de un despliegue real.
- Verificar la instalación de dependencias en un entorno limpio antes del despliegue.

La limitación de candidatos reduce el trabajo de inferencia, pero no garantiza por sí sola el cumplimiento de un objetivo de latencia.

No se ha validado todavía un despliegue de producción ni el comportamiento del pipeline completo ante fallos.

### Notas de la revisión técnica (17/11/2026, Juanmi)

- **Probar sin modelos pesados:** `python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q` desde la raíz del proyecto.
- **Entorno sintético explícito:** en PowerShell, establecer `$env:ARSOFT_ENV = "test"` antes de ejecutar los tests en una copia sin catálogos reales. La carpeta `fixtures/catalogos/` contiene **solo datos de prueba**; `fixtures/bbdd_sintetica_chunks.json` es un corpus sintético para la batería de filtros y RRF.
- **En producción:** configurar los catálogos reales accesibles desde Backend; sin catálogos requeridos se devuelve `indice_no_disponible`. `ARSOFT_ENV=production` impide el fallback a datos sintéticos, incluso con un permiso accidental.
- **Vigencia:** `vigente_para` determina la aplicabilidad de documentos sustituidos. Para documentos actuales con lista vacía se permite la alternativa `versiones` utilizada por el corpus sintético; no se relajan filtros confirmados de versión/componente.
- **Vecinos:** los chunks de contexto que no han sido reranqueados no se publican como evidencias puntuadas, y se filtran por versión y componente.
- **Reintento CTR-002:** si una consulta no devuelve resultados y se había filtrado por `tipo_documento`, el pipeline realiza un único reintento sin ese filtro y conserva siempre los de versión/componente.
- **Limitaciones:** no se ha verificado en esta revisión la exactitud de modelos reales, la API Backend ni la ejecución final en Apptainer; los benchmarks de GPU siguen siendo dependencias de infraestructura.

Véase `docs/AUDITORIA_CORRECCIONES_2026-11-17.md` para los cambios y pruebas exactas.

## 11. Pendiente

- Fijar el umbral con `--backend real --reranker real` en una máquina con
  modelos (A2-05/A2-08).
- Validar el cliente CTR-002 y la ingesta con el Backend y PostgreSQL reales
  (PR #53).
- Tres preguntas de control (CTRL-08, CTRL-11 y CTRL-12) piden documentos que no
  están en el dataset de 98 fragmentos.
