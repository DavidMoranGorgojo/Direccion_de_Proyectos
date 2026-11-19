# Informe general del Agente 2 — ARSOFT

Fecha: 19 de noviembre de 2026. Rama de entrega: `codex/agente2-cierre-final`. Destino: `agent_2`. Alcance: código y pruebas de A2, más adaptaciones mínimas de integración entregadas como parches; sin desarrollo funcional de A1 ni modificaciones de Backend, Frontend o base de datos.

## 1. Objetivo y referencias

A2 transforma una consulta estructurada en evidencias documentales trazables. No redacta respuestas, no indexa el corpus y no mantiene una base de conocimiento local de producción.

Se han contrastado PAQ-001 edición 1.1, DIS-001 y CTR-001/002/003/004 firmados, suministrados en la carpeta externa `documentacion`, además de la revisión del 19/11/2026 y la documentación histórica de A2. **DIS-002 no está disponible** en esa carpeta ni en la búsqueda efectuada; no se acredita cumplimiento de requisitos exclusivos de ese documento. Los contratos y sus puntos abiertos no se han modificado.

La base auditada `origin/agent_2` es `8ae8bac25de35442b6aea5f147102f95d5b753fc`; el A1 utilizado para integración procede de `origin/main`, `81e596fb20f38c3e8fe3a59782d9702cfc9eb113`.

## 2. Arquitectura y componentes

```text
A1: Query CTR-004
  -> validación y catálogos Backend
  -> inferencia y restricciones duras
  -> BGE-M3(query:) -> Backend/vectorial
  -> texto plano   -> Backend/lexica
  -> parsers -> RRF -> filtros defensivos -> reranker -> umbral
  -> vigencia/ambigüedad -> vecinos -> reranker de vecinos
  -> evidencias CTR-004 -> A1: decidir, redactar y registrar
```

| Componente | Implementación |
| --- | --- |
| Configuración | `src/core/config.py`, `Agent2Settings.from_env` |
| Cliente HTTP | `src/clients/backend.py`, `BackendAPIClient` |
| Embeddings | `src/clients/bge_m3.py`, cliente reutilizable y carga diferida |
| Parsers | `src/services/vector_parser.py`, `lexical_parser.py`, `candidate_adapter.py` |
| Filtros y catálogos | `filter_inference.py`, `filter_vocab.py`, `filters.py` |
| Fusión y reranking | `fusion.py`, `reranker.py`, clientes de modelo y cargador concurrente |
| Vigencia y vecinos | `vigencia.py`, `neighbors.py` |
| Orquestación y salida | `pipeline.py`, `evidence_builder.py` |
| Disponibilidad real | `runtime.py`, `check_readiness` |
| Evaluación | `src/evaluation/`, `scripts/calibrar_reranker.py`, `scripts/evaluar_agente2.py` |

## 3. Flujo conectado de recuperación

1. Se valida un objeto con `texto_preprocesado`. Se conservan los alias históricos `texto_busqueda` y `query_busqueda` para A1. Opciones o filtros de tipo incorrecto producen un error controlado. El comportamiento histórico de texto vacío es una abstención sin búsqueda.
2. Se construye el cliente por defecto con `BACKEND_BASE_URL`, modelo, token de servicio y `REQUEST_TIMEOUT`. No se utiliza el atributo inexistente `BACKEND_API_BASE`.
3. Se solicitan los catálogos de códigos y componentes mediante `GET /catalogos/{nombre}` antes de inferir filtros. Se validan sus envolturas y listas; los catálogos malformados no entran en caché. Sus versiones son independientes: no se supone sin contrato que todos compartan el mismo número de versión.
4. La caché conserva TTL, invalidación explícita, aislamiento por Backend/configuración y exclusión mutua. En producción no se sustituyen fallos por fixtures sintéticos.
5. Se combinan filtros explícitos e inferidos. Se genera el vector BGE-M3 local y se ejecutan las búsquedas en Backend.
6. Los parsers conservan los metadatos exigidos; se comprueban modelo y versión de índice entre recuperadores y subconsultas. RRF fusiona rankings, se aplican filtros defensivos y el reranker puntúa candidatos.
7. Se aplica el umbral. La decisión de ambigüedad considera el conjunto relevante antes de limitar el número final de padres, evitando ocultar incompatibilidades por truncamiento.
8. Backend proporciona vecinos de sección. Se comprueba que no haya cambiado el índice; se excluyen versiones, componentes y ediciones documentales incompatibles.
9. Cada vecino compatible pasa por el reranker y el mismo corte. No hereda scores del padre. Los vecinos aceptados llegan realmente a `resultados`; también se reevalúa la ambigüedad del conjunto ampliado.
10. El constructor genera evidencias CTR-004, con `resultados`, texto íntegro, puntuación y metadatos. La adaptación interna conserva `evidencias`, estado y códigos para A1.

## 4. Comunicación y contratos

**CTR-004:** punto público `recuperar_evidencias(query_json, **kwargs)` en `src/services/pipeline.py`. La llamada es interna, modalidad admitida por el contrato. No se inventa un endpoint obligatorio adicional. `resultados` es el formato contractual; `estado`, `campo_ambiguo`, `evidencias` y `metricas` son extensiones de integración.

**CTR-002:** A2 consulta `/conocimiento/vectorial`, `/conocimiento/lexica`, `/conocimiento/chunks/{id}?vecinos=1`, `/conocimiento/info` y `/catalogos/{nombre}`. Los códigos viajan en el texto léxico; no se envían como filtros de Backend. Los modelos y catálogos de pruebas no sustituyen la base real.

**CTR-001:** la puerta exterior sigue perteneciendo a A1. La selección explícita `USE_REAL_AGENT2=1` y la comprobación real de A2 están aplicadas en `Agents/service.py`, sin cambiar el modo simulado por defecto.

**CTR-003:** la auditoría de cada turno pertenece al orquestador A1. A2 entrega métricas y errores interpretables. El envío asíncrono, buffer y esquema de registro de A1 no se implementan en esta fase. El Backend auditado no expone `POST /registros`: coordinación externa pendiente.

La adaptación mínima de `Agents/agente1/core.py` (heredada de #36: ausencia de error y códigos internos) está aplicada en la rama. No implementa clasificación, caché, redacción, juez ni registro de A1.

## 5. Paquetes de trabajo y aceptación

Los estados siguientes separan implementación de aceptación con infraestructura real. No se considera completado un criterio empírico por la mera existencia de herramientas.

| Paquete y objetivo | Antes | Corrección/entregable y pruebas | Estado final y dependencia |
| --- | --- | --- | --- |
| **A2-01**, cliente y BGE-M3 | Cliente existente; arranque por defecto defectuoso | Configuración canónica, timeout configurado, catálogos antes de inferencia. `test_cierre_agente2`: arranque público en producción sin catálogos locales, errores de red; `test_bge_m3` comprueba `query:`. | **IMPLEMENTADO, PERO NO VALIDADO CON SERVICIOS REALES**. Necesita Backend y pesos. |
| **A2-02**, recepción y parseo vectorial | Implementado | Se conserva parser, validación de scores, trazabilidad y modelo/índice. Suites `test_vector_parser`, `test_candidate_adapter`, errores HTTP. | **COMPLETO Y VERIFICADO** frente a fixtures/contrato; proveedor real no probado. |
| **A2-03**, recepción y parseo léxico | Implementado | Se conserva parseo BM25, códigos exactos y búsqueda con texto plano. Suites `test_lexical_parser`, `test_backend_client`, `test_lexical_search`. | **IMPLEMENTADO, PERO NO VALIDADO CON SERVICIOS REALES**; ranking de códigos sobre corpus real pendiente. |
| **A2-04**, fusión RRF | Implementado k=60 | Conservación de metadatos, deduplicación y validación. Evaluador compara recall vectorial/léxico/fusión. Suites `test_rrf`, `test_integracion_rrf`, benchmark RRF. | Código **COMPLETO Y VERIFICADO**; criterio de recall no inferior **NO VERIFICADO** con corpus representativo. |
| **A2-05**, reranker y corte | Implementado, vecinos excluidos | Se conserva carga reutilizable, inferencia protegida y umbral; los vecinos reciben score propio. Suites `test_reranker*`, nuevas pruebas de vecino admitido/rechazado. | **IMPLEMENTADO, PERO NO VALIDADO CON SERVICIOS REALES**. Corte inicial 0,45 sin certificar calibración. |
| **A2-06**, estados/vigencia/vecinos | Expansión sin entrega útil de vecinos | Vecinos reevaluados; control de edición e índice; ambigüedad por `vigente_para`, incluso con documentación obsoleta de versiones incompatibles. Suites `test_vigencia`, `test_neighbors`, nuevas regresiones. | **COMPLETO Y VERIFICADO** con datos controlados; semántica del corpus real pendiente. |
| **A2-07**, evidencias y servicio | Empaquetador presente; entrada real bloqueada | Punto público corregido, CLI real, readiness y parches de servicio. Evidencias conservan los metadatos; fallos nunca equivalen a búsqueda vacía. Suites `test_evidence_builder`, `test_fase1_*`, integración A1-A2. | **COMPLETO Y VERIFICADO** en la interfaz con dobles; despliegue real **NO VERIFICADO**. |
| **A2-08**, calibración y métricas | Calibrador de rankings precalculados | Se añade evaluación del pipeline con procedencia, Recall@k, MRR, abstención, hard filters y comparación de recuperadores. El ground truth nunca se entrega al recuperador. | Herramientas **COMPLETAS Y VERIFICADAS**; aceptación/calibración real **BLOQUEADA POR DEPENDENCIA EXTERNA** de corpus y modelos. |
| **A2-09**, latencia/resiliencia/despliegue | Medidas parciales; contenedor A2 ausente | Métricas por etapa y en errores, presupuesto opcional, índice/readiness reales, CLI, definición Apptainer independiente y parche del contenedor conjunto. Pruebas de timeouts, reindexación, modelo indisponible y selección real/mock. | **IMPLEMENTADO, PERO NO VALIDADO CON SERVICIOS REALES**. Apptainer, instalación de inferencia y SLA pendientes. |
| **A2-10**, filtros duros | Filtros existentes; fallos de arranque y vocabulario A1 | Catálogos inicializados, campos desconocidos rechazados, alias canónicos conservados, versión/componente nunca relajados. Suites `test_filters`, `test_filter_inference`, nuevas pruebas de tipos y rechazo seguro. | Código A2 **COMPLETO Y VERIFICADO**; mapeos no acordados del catálogo y normalizador A1 son dependencias externas. |

## 6. Filtros y control de vigencia

Versión y componente confirmados son restricciones duras. Solo `tipo_documento` puede eliminarse en un reintento documentado si no se obtienen resultados. Los valores explícitos desconocidos no se convierten en filtros vacíos. A2 admite tipos canónicos como `codigo_averia`, `mantenimiento`, `catalogo`, `boletin` y alias conocidos como DTC/MNT.

`vigente_para` contiene versiones técnicas de vehículo, no fechas. Prevalece en la aplicabilidad; un documento sustituido sin vigencia para la versión solicitada no se presenta como válido para ella. No se sustituye una lista por su primer elemento. Las ediciones incompatibles tampoco se mezclan en los vecinos.

Se reforzó el caso de documentos obsoletos de versiones incompatibles: ahora pide aclaración de versión, en lugar de permitir que un aviso de obsolescencia oculte la ambigüedad. La prueba histórica que imponía esa precedencia insegura se actualizó expresamente a CTR-004 §4, conservando el caso y sus verificaciones.

El Backend actual usa nombres de subsistemas en el metadato `componente` y mantiene códigos CMP en `ids_referenciados`. El catálogo de componentes utiliza CMP-xx. El contrato deja abierto el mapeo: A2 no inventa equivalencias como `CMP-18 -> refrigeracion` sin información acordada. `culata`, `encendido / inyección`, `otro` y otros valores no canónicos siguen rechazándose, sin relajar la consulta.

## 7. Embeddings, búsqueda híbrida y tamaños

BGE-M3 se carga de forma diferida y reutilizable; la consulta lleva obligatoriamente `query:`. Backend conserva su responsabilidad sobre `passage:`, índice vectorial de 1024 dimensiones y BM25. A2 fusiona con RRF k=60 y utiliza el reranker `BAAI/bge-reranker-v2-m3` con puntuaciones normalizadas.

`AGENT2_SEARCH_TOP_K` configura el pool inicial, 30 por defecto. `opciones.top_k` limita los padres finales, sin reducir ese pool por debajo del valor configurado. `AGENT2_RERANK_TOP_K` limita los candidatos rerankeados por lote, 20 inicialmente. Se consideran las ambigüedades antes del límite final. Los vecinos compatibles se puntúan por lotes, sin scores artificiales.

El constructor permite un modo explícito de pruebas sin reranker; sus métricas lo identifican como `rrf_sin_reranker`. No se utiliza para certificar CTR-004 ni producción. El punto público exige reranker por defecto.

## 8. Vecinos y evidencias

Los vecinos deben pertenecer al mismo documento, sección y edición, cumplir los filtros duros y mantener aplicabilidad. La ficha de índice devuelta con el chunk debe coincidir con la versión de las búsquedas. Un cambio de índice produce `indice_no_disponible`.

Cada vecino válido se evalúa con el mismo modelo cruzado y umbral. Solo los admitidos se empaquetan como evidencia independiente con su propio `score_final`. El orden de sección y la deduplicación se conservan. La política no garantiza incluir un aviso con score inferior al corte: si la documentación requiere indivisibilidad de pasos/avisos, Backend debe respetar el chunking estructural firmado. La revisión de ese chunking sobre el corpus real es externa a esta entrega.

## 9. Errores

Se distinguen entrada/filtros inválidos (`entrada_invalida`), modelo incompatible, índice no disponible, tiempo agotado, conexión fallida, respuesta malformada y ausencia válida de resultados. Los fallos técnicos mantienen `estado=error`, código y mensaje; una búsqueda correcta vacía es abstención.

Los errores HTTP del Backend se interpretan en cuerpos planos o dentro de `detail`. El cliente conserva los códigos internos utilizados por el adaptador. La lista exterior limitada de CTR-001 y su manejo HTTP 200/422 pertenecen al servicio de A1; su alineación final queda pendiente, sin modificar el contrato firmado.

La prueba histórica de ausencia de catálogos se ajustó para simular un 503 contractual del Backend. Sus aserciones de error de índice se conservan: tras corregir el arranque ya no es válido esperar un fallo local antes de intentar la API. Las nuevas pruebas comprueban por separado conexión, timeout y catálogo malformado.

## 10. Configuración y ejecución real

Variables principales: `AGENT2_BACKEND_BASE_URL`, `ARSOFT_SERVICE_TOKEN`, `AGENT2_EMBEDDINGS_MODEL`, `AGENT2_EMBEDDING_DIMENSION`, `AGENT2_REQUEST_TIMEOUT` (lectura, 5 s), `AGENT2_CONNECT_TIMEOUT` (conexión, 3 s), `AGENT2_SEARCH_TOP_K`, `AGENT2_RRF_K`, `AGENT2_RERANKER_MODEL`, `AGENT2_RERANK_TOP_K`, `AGENT2_RERANK_THRESHOLD`, `AGENT2_CATALOG_CACHE_TTL` y `ARSOFT_ENV`.

Desde la raíz, instalar `Agents/Agent_2/requirements.txt` en un entorno de inferencia aislado. Las versiones heredadas se conservan; su instalación conjunta desde cero no está certificada en esta ejecución.

```powershell
$env:ARSOFT_ENV = "production"
$env:AGENT2_BACKEND_BASE_URL = "http://localhost:8000"
# Establecer ARSOFT_SERVICE_TOKEN mediante el gestor de secretos del entorno.
python -m Agents.Agent_2 --health-backend
python -m Agents.Agent_2 --health
python -m Agents.Agent_2 --query consulta.json
```

Ejemplo de `consulta.json`:

```json
{"texto_preprocesado":"Comprobación del circuito de refrigeración V1.1","filtros":{"version":"V1.1","componente":"refrigeracion"},"opciones":{"top_k":3}}
```

`--health-backend` es una comprobación **parcial**: no anuncia modelos disponibles. `--health` consulta índice y catálogos e intenta inferencia de ambos modelos; puede cargar pesos y no debe confundirse con un liveness barato. La CLI no usa simuladores.

El parámetro opcional `--timeout-s`/`timeout_s` comprueba presupuesto entre etapas y produce `tiempo_agotado`. No cancela una inferencia ya iniciada ni promete un límite duro de tiempo. Se mantiene el timeout HTTP configurado; no se ha aumentado para ocultar latencias. El presupuesto final debe acordarse con A1 y la pasarela.

## 11. Apptainer e integración con A1

La definición independiente `Agents/Agent_2/apptainer/agente2.def` copia A2 completo, instala sus requisitos y ejecuta la CLI real:

```bash
apptainer build agente2.sif Agents/Agent_2/apptainer/agente2.def
apptainer run --nv --bind /ruta/modelos:/models agente2.sif --health
apptainer run --nv --bind /ruta/modelos:/models --bind /ruta/consulta.json:/consulta.json agente2.sif --query /consulta.json
```

Configurar Backend y token en el entorno del contenedor. La construcción no se ha ejecutado en Windows; estos comandos requieren el entorno Linux/Apptainer autorizado.

La integración con A1 está aplicada en la rama (antes eran los parches de `integration/`, ya retirados): compatibilidad CTR-004 heredada de #36 en `Agents/agente1/core.py`, selección explícita de A2 real y readiness en `Agents/service.py`, y copia/dependencias A2 en `Agents/apptainer/agentes.def`. `USE_REAL_AGENT2=0` conserva el modo simulado existente y `=1` selecciona A2 real; el servicio no debe anunciarse real por defecto.

## 12. Pruebas reproducibles

Resultado conjunto de desarrollo final: **870 passed, 0 failed, 2 skipped, 137 subtests passed**. Son las 826 pruebas originales más 44 nuevas; no se han introducido skips ni xfails. Las dos omisiones preexistentes requieren el reranker real y su benchmark.

Desde la integración en la PR #32, A1 y A2 conviven en la misma rama y no hace falta componer una copia ni aplicar parches. `Test/test_Models/conftest.py` fija `ARSOFT_ENV=test`. Desde la raíz:

```bash
PYTHONPATH="shared;Backend/api;." python -m pytest Test Backend/api/tests -q
```

(En Linux/macOS, separar el `PYTHONPATH` con `:`.)

Se conservan también las pruebas de imports/configuración, parsers CTR-002, evidencias CTR-004, errores, filtros, vigencia, caché TTL/concurrencia, integración con A1 y rendimiento de RRF. Las pruebas nuevas verifican arranque público en producción con API simulada, vecinos hasta la salida, reindexación, readiness, selección mock/real y evaluación.

## 13. Evaluación, calibración y rendimiento

Se instrumentan embeddings, vectorial, léxica, RRF, reranking (incluidos vecinos), expansión, construcción de evidencias y total. Las métricas también acompañan los errores tempranos. `trace_retrieval=True` activa rankings diagnósticos por identificador; por defecto no se incluyen.

El evaluador necesita un archivo autorizado con `procedencia`, `tipo` (`real` o `sintetico`) y `consultas`: cada caso tiene `id`, `query` CTR-004 y `relevant_chunk_ids`. Solo `query` se entrega al sistema. Se calculan Recall@k, MRR, abstención, filtros y comparación de recall entre recuperadores/fusión; los fallos técnicos no cuentan como abstenciones correctas.

```powershell
python scripts/evaluar_agente2.py --input evaluacion_autorizada.json --output resultados_nuevos.json --k 10
python scripts/calibrar_reranker.py --input rankings_etiquetados.json --output calibracion_nueva.json
```

El archivo de salida debe ser nuevo. No se publica ningún resultado sintético como medición real. El valor 0,45 sigue siendo inicial: se necesita corpus representativo para justificarlo junto con los tamaños y verificar el criterio de recall RRF.

## 14. Limitaciones externas comprobadas

- Hay una **NVIDIA GeForce RTX 4070 Laptop GPU, 8188 MiB**; no se declara ausencia de GPU. En los Python comprobados no están instalados `FlagEmbedding`, `torch` ni `transformers`.
- No hay servicios locales escuchando en 8000, 8001 o 11434: las conexiones devolvieron rechazo. No se ha probado un Backend remoto ni se han usado credenciales privadas de aplicación.
- Apptainer no está disponible en este entorno Windows. No se construyó ni ejecutó una imagen ni se probó SLURM.
- No se dispone aquí de un corpus representativo autorizado conectado a los servicios reales. No se han reproducido las cifras históricas de CPU/Ollama y no se presentan como resultados actuales.
- Quedan sin verificar inferencia y calibración reales, recall/MRR del corpus, latencia total, SLA, instalación limpia del entorno de inferencia, chunking y despliegue conjunto.
- Persisten los puntos abiertos firmados: nomenclatura completa, representación CMP/nombre, sección/página vacías y dependencias de indexación/vigencia.

## 15. Trazabilidad Git y trabajo posterior

La consolidación parte de `origin/agent_2` y conserva como antepasados los commits originales de Alba (`cfebf93`), Álvaro (`b3890a0`) y Víctor (`fe05284`), así como la integración anterior. El merge conserva la autoría; los cambios ajenos se restauran al árbol de la base antes de registrar la consolidación. El diff final contra `agent_2` no modifica Backend, Frontend, base de datos ni el código de A1. No se hace squash, force-push ni merge a ramas protegidas.

**Integración futura con main:** conservar la historia de Alba implica conservar también sus antepasados de main. Para obtener un diff limpio sobre el `agent_2` antiguo se han excluido sus árboles ajenos. No se debe fusionar ciegamente esta rama a main: en la siguiente fase habrá que comprobar el merge y transportar solo A2/adaptaciones necesarias, evitando que la exclusión de árboles históricos retire archivos actuales de otros departamentos.

Las PR #32/#34 no se modifican ni cierran. Tras la eventual aprobación de esta consolidación, sus responsables podrán resolverlas como incorporadas, enlazando la PR final. #36 se cierra únicamente después de verificar una sustituta hacia `agent_2`; ninguna se fusiona automáticamente.

Para A1 quedan caché semántica, Circuit Breaker, juez LLM, estructura final y verificación de aplicabilidad, vocabulario y `texto_preprocesado`, registro CTR-003, errores HTTP 422/formato CTR-001, condensación y ambigüedad defensiva por `versiones`, benchmark local/API y presupuesto temporal conjunto. No se implementan esas funciones en esta ejecución.

**Veredicto:** no se conocen defectos críticos reproducibles de A2 pendientes en el alcance probado. Su código propio y las adaptaciones están preparados para revisión; no se declaran aceptados todos los paquetes con infraestructura real ni certificado el despliegue. Los criterios empíricos y las dependencias externas siguen explícitamente abiertos.
