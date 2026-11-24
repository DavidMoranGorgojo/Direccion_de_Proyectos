# Histórico del README del Agente 2

> Copia íntegra del README anterior al 24-11-2026. Se conserva como referencia:
> estados, cifras de pruebas y benchmarks corresponden a sus fechas originales
> (hasta el 17-11-2026) y no describen la versión actual. El README vigente es
> [../README.md](../README.md).

---


# Agente 2 — Recuperación de evidencias (RAG)

**Entrega vigente:** [Informe general del Agente 2](docs/INFORME_GENERAL_AGENTE2.md).
Incluye arranque real, contratos, validación reproducible y limitaciones actuales.
Las métricas y estados de las secciones históricas siguientes corresponden a sus
fechas originales y no certifican esta entrega ni un despliegue de producción.

## 1. Descripción

El Agente 2 del proyecto ARSOFT/FaCyL se encarga de recuperar y seleccionar evidencias documentales relevantes para responder a las consultas recibidas.

Su función es recuperar información y preparar evidencias para el Agente 1, no generar directamente la respuesta final.

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

**Estado revisado (17/11/2026):** el orquestador `src/services/pipeline.py` y el enlace local con el Agente 1 están implementados y tienen pruebas automatizadas con simuladores. La ejecución con Backend real y pesos BGE-M3/reranker, así como el despliegue y la calibración final, **no se han validado en esta revisión**. La interfaz pública `recuperar_evidencias()` exige el reranker por defecto; las pruebas de RRF pueden desactivarlo mediante `Agent2Pipeline(require_reranker=False)`.

## 2. Requisitos

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

## 3. Instalación

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

## 4. Configuración

La configuración se encuentra en:

`Agents/Agent_2/src/core/config.py`

Los parámetros pueden modificarse mediante variables de entorno.

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `AGENT2_BACKEND_BASE_URL` | `http://localhost:8000` | URL del Backend para CTR-002 |
| `ARSOFT_SERVICE_TOKEN` | vacío | Bearer de servicio interno que exige el Backend en `/conocimiento/*` |
| `AGENT2_RRF_K` | `60` | Constante utilizada en la fusión RRF |
| `AGENT2_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Identificador del modelo de reranking |
| `AGENT2_RERANK_THRESHOLD` | `0.45` | Umbral mínimo de relevancia |
| `AGENT2_SEARCH_TOP_K` | `30` | Número configurado de candidatos por búsqueda |
| `AGENT2_RERANK_TOP_K` | `20` | Número máximo de candidatos enviados al reranker |

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

## 5. Fusión RRF (A2-04)

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

### Tratamiento de duplicados

Si un mismo `chunk_id` aparece repetido en la búsqueda vectorial o en BM25, únicamente aporta una vez a la puntuación RRF de esa fuente.

Los duplicados pueden utilizarse para completar metadatos, pero no para aumentar artificialmente la relevancia.

Las posiciones utilizadas para calcular RRF corresponden al orden de los resultados únicos de cada ranking.

### Validación de identificadores

Se aceptan identificadores de tipo cadena no vacía o entero, incluido `0`.

Se rechazan identificadores ausentes, cadenas vacías o formadas únicamente por espacios, booleanos y otros tipos no admitidos.

## 6. Reranker y umbral (A2-05)

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

### Validación de entradas

Antes de ejecutar la inferencia se comprueba que:

- La consulta sea una cadena de texto no vacía.
- Cada candidato tenga una estructura válida.
- Cada candidato incluya un campo `texto` con contenido no vacío.
- Las puntuaciones devueltas por el modelo sean numéricas y finitas.
- El número de puntuaciones recibidas coincida con el número de candidatos evaluados.

Las entradas inválidas producen errores explícitos en lugar de aceptarse silenciosamente.

Los errores del modelo se propagan para que puedan gestionarse desde la capa de orquestación.

### Límite de candidatos

La variable `AGENT2_RERANK_TOP_K` establece un límite predeterminado de **20 candidatos**.

Cuando la fusión RRF devuelve más candidatos que ese límite:

1. Se validan sus puntuaciones RRF.
2. Se ordenan por puntuación RRF descendente.
3. Se seleccionan los candidatos mejor posicionados hasta alcanzar el límite.
4. Se ejecuta el reranker únicamente sobre los candidatos seleccionados.

Este límite reduce el número de pares que procesa el modelo y evita enviar automáticamente todos los resultados de ambas búsquedas a la inferencia.

La selección previa se basa en RRF; la ordenación final se basa en las puntuaciones del reranker.

### Protección de inferencias concurrentes

`RerankerModel` incorpora un bloqueo de inferencia mediante `threading.Lock`.

El bloqueo protege la llamada a `compute_score()` para impedir que varios hilos utilicen simultáneamente la misma instancia del modelo.

Esto evita errores de acceso concurrente como `RuntimeError: Already borrowed`.

El bloqueo se libera también cuando la inferencia produce una excepción.

Esta protección se ha verificado mediante pruebas con llamadas concurrentes. No implica que el rendimiento bajo carga concurrente esté validado para producción.

## 7. Carga reutilizable del modelo (A2-09)

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

## 8. Pruebas

Los siguientes comandos se ejecutan desde la raíz del repositorio.

### Pruebas unitarias, resiliencia e integración disponible

```powershell
python -m pytest Test/test_Models/test_rrf.py Test/test_Models/test_config_agent2.py Test/test_Models/test_reranker.py Test/test_Models/test_reranker_resiliencia.py Test/test_Models/test_reranker_model.py Test/test_Models/test_integracion_rrf.py Test/test_Performance/test_latency_reranker.py -v
```

En la última ejecución conjunta, realizada con Python 3.10.11 y pytest 9.1.1, se obtuvieron:

- **132 pruebas recopiladas.**
- **129 pruebas superadas.**
- **3 pruebas omitidas.**
- **0 pruebas fallidas.**

Resultado:

```text
129 passed, 3 skipped in 0.69s
```

Las tres pruebas omitidas corresponden a:

1. Integración opcional con el modelo real, desactivada por defecto.
2. Integración BM25 real con RRF, pendiente del dataset de Alba.
3. Benchmark del reranker real, desactivado por defecto.

El benchmark real se ejecutó y superó por separado.

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

## 9. Resultados de rendimiento

### 9.1. Fusión RRF

Mediciones realizadas durante el desarrollo:

| Métrica | Resultado |
|---|---:|
| Media | 0,1410 ms |
| Mediana | 0,1392 ms |
| P95 | 0,2350 ms |
| Máximo | 0,8633 ms |

El benchmark RRF utilizó 100 resultados vectoriales y 100 BM25, con 150 candidatos únicos, tras un calentamiento de 100 ejecuciones y 1.000 mediciones.

Estos resultados corresponden a una medición anterior a las últimas modificaciones de validación y tratamiento de duplicados. Deben considerarse una referencia histórica hasta repetir el benchmark con el código actualizado.

### 9.2. Benchmark actualizado del reranker real

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

### 9.3. Interpretación de resultados

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

### 9.4. Benchmark comparativo anterior del reranker

Antes de ampliar los textos del benchmark se realizó una ejecución con fragmentos más cortos.

Modelo: `BAAI/bge-reranker-v2-m3`.

Entorno: Python 3.10.11, ejecución en CPU con `use_fp16=False`.

Tiempo de carga inicial: **15.385,86 ms**, aproximadamente **15,39 segundos**.

Se realizaron 20 mediciones por cantidad de candidatos, después de 2 calentamientos.

| Candidatos | Media | Mediana | P95 | Máximo |
|---|---:|---:|---:|---:|
| 1 | 1.078,00 ms | 1.091,39 ms | 1.150,23 ms | 1.150,24 ms |
| 5 | 2.121,85 ms | 2.119,16 ms | 2.290,13 ms | 2.305,17 ms |
| 10 | 3.104,56 ms | 3.546,17 ms | 3.927,04 ms | 4.119,41 ms |
| 20 | 3.098,10 ms | 3.111,36 ms | 3.224,40 ms | 3.301,68 ms |

**Resultado de ejecución:** `1 passed in 250.15s`.

La prueba completó 88 inferencias, contando los calentamientos, sin errores.

El percentil 95 se calculó mediante el método de rango más cercano.

Estos resultados se conservan como referencia histórica. No son directamente comparables con el benchmark actualizado, debido a las diferencias de longitud de los textos y metodología.

### 9.5. Benchmark inicial del reranker

Antes del benchmark comparativo se realizó una medición inicial con 10 candidatos y 10 ejecuciones:

| Métrica | Resultado |
|---|---:|
| Tiempo de carga | 13.453,78 ms |
| Media | 1.374,95 ms |
| Mediana | 1.381,75 ms |
| P95 | 1.445,29 ms |

Estos resultados se conservan únicamente como referencia histórica.

Las diferencias entre las mediciones pueden deberse a las características de los textos, las condiciones del entorno y la metodología. No deben interpretarse directamente como una regresión confirmada.

## 10. Resiliencia y consideraciones de despliegue

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

## 11. Trabajo pendiente

Para completar la integración del Agente 2 quedan pendientes:

1. Conectar los servicios de búsqueda, fusión, reranking y generación de evidencias.
2. Verificar la compatibilidad del dataset y de los filtros obligatorios.
3. Validar el umbral del reranker con las métricas de evaluación.
4. Medir la latencia extremo a extremo.
5. Ejecutar pruebas de resiliencia del flujo integrado.
6. Validar el JSON de evidencias entregado al Agente 1.
7. Evaluar el rendimiento y la estabilidad con consultas concurrentes.
8. Repetir los benchmarks con el código definitivo y un número suficiente de mediciones.
9. Comprobar la instalación de dependencias en un entorno limpio.

Las pruebas de los componentes individuales no sustituyen las pruebas de integración del sistema completo.


## Revisión técnica prepublicación (17/11/2026)

- **Probar sin modelos pesados:** `python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q` desde la raíz del proyecto.
- **Entorno sintético explícito:** en PowerShell, establecer `$env:ARSOFT_ENV = "test"` antes de ejecutar los tests en una copia sin catálogos reales. La carpeta `fixtures/catalogos/` contiene **solo datos de prueba**; `fixtures/bbdd_sintetica_chunks.json` es un corpus sintético para la batería de filtros y RRF.
- **En producción:** configurar los catálogos reales accesibles desde Backend; sin catálogos requeridos se devuelve `indice_no_disponible`. `ARSOFT_ENV=production` impide el fallback a datos sintéticos, incluso con un permiso accidental.
- **Contrato:** la entrada pública acepta `texto_preprocesado` y la salida mantiene `resultados` con `metadatos`; el adaptador interno utiliza además `evidencias`.
- **Vigencia:** `vigente_para` determina la aplicabilidad de documentos sustituidos. Para documentos actuales con lista vacía se permite la alternativa `versiones` utilizada por el corpus sintético; no se relajan filtros confirmados de versión/componente.
- **Vecinos:** los chunks de contexto que no han sido reranqueados no se publican como evidencias puntuadas, y se filtran por versión y componente.
- **Reintento CTR-002:** si una consulta no devuelve resultados y se había filtrado por `tipo_documento`, el pipeline realiza un único reintento sin ese filtro y conserva siempre los de versión/componente.
- **Limitaciones:** no se ha verificado en esta revisión la exactitud de modelos reales, la API Backend ni la ejecución final en Apptainer; los benchmarks de GPU siguen siendo dependencias de infraestructura.

Véase `docs/AUDITORIA_CORRECCIONES_2026-11-17.md` para los cambios y pruebas exactas.
