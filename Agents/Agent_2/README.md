# Agente 2 — Recuperación de evidencias (RAG)

## 1. Descripción

El Agente 2 del proyecto ARSOFT/FaCyL se encarga de recuperar y seleccionar evidencias documentales relevantes para responder a las consultas recibidas.

Su función es recuperar información y preparar evidencias para el Agente 1, no generar directamente la respuesta final.

El flujo previsto es:

1. Validación de la consulta.
2. Aplicación de filtros obligatorios.
3. Búsqueda vectorial y búsqueda léxica BM25.
4. Fusión de resultados mediante Reciprocal Rank Fusion (RRF).
5. Reordenación de candidatos mediante un modelo reranker.
6. Aplicación de un umbral mínimo de relevancia.
7. Comprobación de vigencia y recuperación de chunks vecinos.
8. Generación del JSON de evidencias para el Agente 1.

**Estado:** los componentes RRF, reranker y configuración están implementados y probados. La integración completa del pipeline sigue pendiente.

## 2. Requisitos

- Python 3.10, versión utilizada durante las pruebas.
- Acceso a Internet para descargar inicialmente el modelo de reranking.
- Espacio suficiente para almacenar los pesos del modelo.
- Dependencias indicadas en `Agents/Agent_2/requirements.txt`.

La dependencia declarada actualmente es:

```text
FlagEmbedding==1.4.2
```

La instalación de esta biblioteca puede incorporar dependencias adicionales.

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
| `AGENT2_RRF_K` | `60` | Constante utilizada en la fusión RRF |
| `AGENT2_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Identificador del modelo de reranking |
| `AGENT2_RERANK_THRESHOLD` | `0.45` | Umbral mínimo de relevancia |
| `AGENT2_SEARCH_TOP_K` | `30` | Número configurado de candidatos de búsqueda |

`AGENT2_RRF_K` y `AGENT2_SEARCH_TOP_K` deben ser enteros positivos.

`AGENT2_RERANK_THRESHOLD` debe ser un número finito entre 0 y 1.

Los valores no válidos producen errores explícitos.

### Ejemplo de configuración en PowerShell

```powershell
$env:AGENT2_RRF_K = "60"
$env:AGENT2_RERANK_THRESHOLD = "0.45"
$env:AGENT2_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
$env:AGENT2_SEARCH_TOP_K = "30"
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
- Conserva los metadatos disponibles.
- Ordena por puntuación RRF descendente.
- No modifica las listas de entrada.
- Valida la constante `k` y los identificadores de los resultados.

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

El código comprueba puntuaciones inválidas y propaga los errores del modelo, evitando ocultar fallos como si fueran resultados válidos.

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

La caché es local al proceso. Si se utilizan varios procesos, cada uno puede necesitar su propia instancia del modelo.

El modelo se ha probado en CPU con `use_fp16=False`.

## 8. Pruebas

Los siguientes comandos se ejecutan desde la raíz del repositorio.

### Pruebas unitarias

```powershell
python -m pytest Test/test_Models/test_rrf.py Test/test_Models/test_reranker.py Test/test_Models/test_reranker_model.py Test/test_Models/test_reranker_loader.py Test/test_Models/test_config_agent2.py -v
```

En la última ejecución conjunta se obtuvieron **65 pruebas superadas**.

### Prueba opcional con el modelo real

En PowerShell:

```powershell
$env:RUN_REAL_RERANKER_TEST = "1"
python -m pytest Test/test_Models/test_reranker_model.py -v
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
```

Los resultados pueden variar según el hardware, la carga del sistema y el número de candidatos.

## 9. Resultados de rendimiento

Mediciones realizadas durante el desarrollo:

| Operación | Resultado |
|---|---|
| Fusión RRF — media | 0,1410 ms |
| Fusión RRF — p95 | 0,2350 ms |
| Carga inicial del reranker | 13.453,78 ms |
| Reranking de 10 candidatos — media | 1.374,95 ms |
| Reranking de 10 candidatos — p95 | 1.445,29 ms |

El benchmark RRF utilizó 100 resultados vectoriales y 100 BM25, con 150 candidatos únicos, tras un calentamiento de 100 ejecuciones y 1.000 mediciones.

El benchmark del reranker utilizó 10 candidatos y 10 mediciones con el modelo real en CPU.

**Importante:** estos resultados corresponden a componentes individuales. No representan la latencia extremo a extremo del Agente 2.

El número reducido de muestras del benchmark del reranker limita la precisión estadística del p95.

## 10. Resiliencia y consideraciones de despliegue

Se han incorporado comprobaciones para evitar comportamientos silenciosos ante entradas inválidas o fallos de inicialización.

Para el despliegue se recomienda:

- Inicializar el reranker una vez por proceso y reutilizarlo.
- Asegurar que los pesos del modelo estén disponibles antes de atender consultas que los requieran.
- Dimensionar memoria y CPU según el número de procesos concurrentes.
- Configurar explícitamente los parámetros mediante variables de entorno cuando sea necesario.
- Registrar y gestionar los errores en la capa de orquestación, sin convertir fallos internos en respuestas vacías aparentemente válidas.
- Medir la latencia completa una vez integrado el pipeline.

No se ha validado todavía un despliegue de producción ni el comportamiento del pipeline completo ante fallos.

## 11. Trabajo pendiente

Para completar la integración del Agente 2 quedan pendientes:

1. Conectar los servicios de búsqueda, fusión, reranking y generación de evidencias.
2. Verificar la compatibilidad del dataset y de los filtros obligatorios.
3. Validar el umbral del reranker con las métricas de evaluación.
4. Medir la latencia extremo a extremo.
5. Ejecutar pruebas de resiliencia del flujo integrado.
6. Validar el JSON de evidencias entregado al Agente 1.

Las pruebas de los componentes individuales no sustituyen las pruebas de integración del sistema completo.
