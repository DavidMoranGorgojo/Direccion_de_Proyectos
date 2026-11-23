# Agente 2: recuperación de evidencias

Recibe la consulta estructurada de A1, obtiene candidatos del Backend,
fusiona rankings mediante RRF, aplica filtros y reranker y devuelve evidencias
trazables. No redacta respuestas ni mantiene un índice de producción local.

## Estructura

```text
Agent_2/
├── src/clients/       # HTTP Backend, BGE-M3 y reranker
├── src/core/          # Configuración y errores
├── src/models/        # Mensajes CTR-002 y CTR-004
├── src/services/      # Pipeline, filtros, vigencia, vecinos y evidencias
├── src/evaluation/    # Métricas y calibración
├── src/testing/       # Simuladores y búsquedas sintéticas para pruebas
├── fixtures/          # Corpus y catálogos sintéticos
├── tests/             # Unitarias, contratos, rendimiento e integración
├── tools/             # Evaluación y calibración ejecutables
└── apptainer/         # Contenedor independiente
```

## Instalación

Python 3.10 o posterior, desde la raíz del repositorio:

```powershell
python -m pip install -r Agents/Agent_2/requirements.txt
```

Para ejecutar el servicio conjunto se necesitan además las dependencias de
`Agents/requirements.txt`. Las pruebas se instalan con
`Agents/Agent_2/requirements-test.txt`; `requirements-dev.txt` incluye tanto
inferencia como pruebas. Los modelos BGE-M3 y reranker necesitan pesos disponibles
en la caché de modelos y memoria suficiente. La primera carga puede descargarlos.

## Configuración real

Configurar las variables del proceso antes de iniciarlo. `.env.example` es una
plantilla: no se carga automáticamente ni contiene credenciales.

| Variable | Valor inicial o finalidad |
| --- | --- |
| `ARSOFT_ENV` | `production` para impedir catálogos sintéticos |
| `AGENT2_BACKEND_BASE_URL` | `http://localhost:8000` |
| `ARSOFT_SERVICE_TOKEN` | Mismo secreto de servicio que Backend |
| `USE_REAL_AGENT2` | `1` activa A2 en `Agents.service`; por defecto el servicio conserva su simulador |
| `AGENT2_EMBEDDINGS_MODEL` | `BAAI/bge-m3` |
| `AGENT2_EMBEDDING_DIMENSION` | `1024` |
| `AGENT2_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `AGENT2_SEARCH_TOP_K` | `30` candidatos por búsqueda |
| `AGENT2_RERANK_TOP_K` | `20` candidatos tras RRF |
| `AGENT2_RERANK_THRESHOLD` | `0.45`, valor inicial pendiente de calibración real |
| `AGENT2_REQUEST_TIMEOUT` | `5` segundos de lectura HTTP |
| `AGENT2_CONNECT_TIMEOUT` | `3` segundos para conexión HTTP |
| `AGENT2_CATALOG_CACHE_TTL` | `300` segundos |

Los límites HTTP no constituyen un límite total de inferencia. La opción
`--timeout-s` comprueba el presupuesto entre etapas; no interrumpe un cálculo
de modelo ya iniciado.

## Interfaz interna CTR-004

```python
from Agents.Agent_2.src.services.pipeline import recuperar_evidencias

respuesta = recuperar_evidencias({
    "texto_preprocesado": "Comprobar bomba de refrigeracion en V1.1",
    "filtros": {"version": "V1.1", "componente": "refrigeracion"},
})
```

La salida pública siempre contiene `resultados`, también ante abstención o error.
Cada resultado tiene `chunk_id`, `score_final`, `texto` y `metadatos` con todos los
campos CTR-002. Se mantienen `evidencias`/`metadata` como adaptación al A1 existente,
además de `estado`, `campo_ambiguo`, `codigo_error`, `mensaje_error` y `metricas`.
Un fallo técnico lleva estado `error` y código explícito; una lista vacía por sí
sola no representa un fallo.

Los alias de entrada `texto_busqueda` y `query_busqueda` se mantienen por
compatibilidad. Versión y componente confirmados nunca se relajan. Si no hay
resultados, se permite un único reintento sin `tipo_documento`. Los códigos
viajan en el texto léxico. Los valores de componente no reconocidos se rechazan;
no se inventa una equivalencia entre códigos CMP y nombres de subsistemas.

El vectorizador añade `query:`. Backend debe haber indexado con `passage:` y el
mismo modelo. Los vecinos se limitan a sección, edición, versión y componente
compatibles y reciben su propia puntuación de reranker antes de entregarse.

## Ejecución y disponibilidad

Desde la raíz:

```powershell
python -m Agents.Agent_2 --query consulta.json
python -m Agents.Agent_2 --health-backend
python -m Agents.Agent_2 --health
```

`--health-backend` comprueba índice y catálogos y devuelve disponibilidad parcial.
`--health` también ejecuta ambos modelos. El servicio conjunto permanece en
`Agents.service:app`; su comprobación de salud real requiere además el LLM de A1.
No se añade una ruta pública que permita saltarse A1 y la pasarela de Backend.

## Pruebas

```powershell
python -m pip install -r Agents/Agent_2/requirements-test.txt
$env:ARSOFT_ENV = "test"
python -m pytest Agents/Agent_2/tests/unit Agents/Agent_2/tests/performance Test/test_Agents -q -rs
```

El corpus y los catálogos de `fixtures/` son sintéticos y solo permiten verificar
comportamientos controlados. Las pruebas opcionales del reranker real se habilitan
con `RUN_REAL_RERANKER_TEST=1` y necesitan las dependencias y pesos de inferencia.

`tests/integration/test_ingesta_bge_pgvector_a2.py` requiere
`ARSOFT_TEST_DATABASE_URL`, una base PostgreSQL de pruebas con pgvector, y
`ARSOFT_TEST_MANUALES`, la carpeta de PDF. La prueba carga un índice de pruebas y
activa su versión; no debe apuntar a una base de producción. Su pipeline usa
el vectorizador real y un modo sin reranker: no acredita la cadena completa.

## Evaluación

```powershell
python -m Agents.Agent_2.tools.calibrar_reranker --input puntuaciones.json --output umbrales.json
python -m Agents.Agent_2.tools.evaluar_agente2 --input consultas_etiquetadas.json --output evaluacion.json
```

La calibración trabaja sobre puntuaciones previamente calculadas. El evaluador
invoca el pipeline y compara recuperación vectorial, léxica y fusión, Recall@k,
MRR, abstención y filtros duros. Exige identificar la procedencia y el carácter
real o sintético de los datos. Las etiquetas de relevancia no se envían al
recuperador y los errores no se cuentan como abstenciones correctas.

## Despliegue e integración pendiente

`apptainer/agente2.def` ejecuta A2 por consola. `Agents/apptainer/agentes.def`
incluye A2 en el servicio conjunto. Ambas definiciones deben construirse y
verificarse en el entorno de despliegue; una prueba de importación no certifica
los modelos ni la disponibilidad de Backend.

La entrega aporta el código de recuperación y su regresión controlada. La
aceptación posterior a la integración debe medir recuperación y umbral con el
corpus real, latencias, concurrencia y el flujo Frontend–Backend–A1–A2. El cierre
de conversación, redacción, verificación final y registro CTR-003 corresponden
a A1. Estos criterios permanecen pendientes hasta ejecutar la prueba conjunta.
