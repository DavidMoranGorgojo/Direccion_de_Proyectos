# Evaluación de Agentes antes de integrar en main

Fecha: 19/11/2026. Evaluación sin correcciones de código, commits, push, comentarios ni cambios de estado en GitHub. La PR #17 queda fuera del alcance.

## Dictamen

No recomiendo fusionar todavía la PR #36 como entrega funcional completa. Contiene la integración más avanzada y conserva las aportaciones individuales, pero su entrada pública real tiene dos fallos de arranque, el registro no cumple CTR-003 y existen desviaciones de los contratos y paquetes de A1 y A2.

La batería existente pasa. Eso demuestra la regresión cubierta por esas pruebas, pero no demuestra el funcionamiento real completo: las pruebas del pipeline suelen inyectar el cliente Backend y los modelos, ocultando los fallos de construcción por defecto.

## Referencias y alcance

Se han leído los seis documentos de `../documentacion`: PAQ-001 edición 1.1, DIS-001 y CTR-001 a CTR-004 firmados. También se ha contrastado la parte relevante del Backend para verificar las interfaces, sin modificar ese departamento ni Frontend.

| Referencia | Commit auditado | Observación |
| --- | --- | --- |
| origin/main | `81e596fb20f38c3e8fe3a59782d9702cfc9eb113` | No contiene `Agents/Agent_2`. |
| origin/agent_2 | `8ae8bac25de35442b6aea5f147102f95d5b753fc` | Contiene el merge de la PR #18 de Víctor. |
| PR #32, Alba | `cfebf932c79cb48cf9f5129228f7db74049331d3` | Abierta, destino `agent_2`. |
| PR #34, Álvaro | `b3890a06ec74200d3331b11e5d126c8e8fcd9c97` | Abierta, destino `agent_2`. |
| PR #36, integración | `1ebc6e013d8315b6257de988c691e2c1df77bd13` | Abierta, destino `main`; GitHub indica merge limpio y no está marcada Draft. |

Las copias de los cuatro árboles están en `.worktrees/auditoria-20261119/`. Son extracciones de los archivos versionados, sin dependencias de archivos locales ignorados. La carpeta principal continúa en su rama original.

## Relación entre las PR y autoría

Se verificó con `git merge-base --is-ancestor` que los commits completos de las PR #32 y #34 son antepasados de la #36. También lo es la rama de Víctor consultada. La #36 añade correcciones de integración sobre esas aportaciones: no es solo una tercera pieza que deba combinarse necesariamente con las otras dos.

La PR #18 está fusionada en `agent_2`, no en el `main` actual. Por tanto, fusionar únicamente #32 y #34 en `agent_2` tampoco lleva automáticamente A2 a main, y no incorpora las correcciones posteriores de #36.

**Recomendación para decidir después de esta evaluación:** usar #36 como PR final de integración a main, preservando los merges y autores existentes, sin squash si se desea conservar la autoría por commit. No hace falta abrir una cuarta PR con el mismo conjunto. Las correcciones propias de Alba o Álvaro pueden mantenerse en sus ramas y sincronizarse expresamente con la integración; las correcciones de conexión A1-A2 y despliegue corresponden a #36. Corregir una rama individual después de esta auditoría no actualiza por sí solo #36.

Si se prefiere el flujo de PR individuales, completar #32 y #34 hacia `agent_2` y preparar la integración final conservando las correcciones de #36 es posible. Requiere reconciliar las dos líneas; no basta con fusionar las individuales y dar por incorporada la integración. La #32 tiene un diff amplio contra su base antigua, incluyendo historia de otros departamentos: conviene revisar ese alcance al escoger esta alternativa.

## Hallazgos reproducidos y desviaciones

### R1. La construcción del cliente Backend por defecto utiliza una constante inexistente — bloqueante

`Agents/Agent_2/src/services/pipeline.py:63` utiliza `config.BACKEND_API_BASE`. `src/core/config.py:228` define `BACKEND_BASE_URL`, sin el alias utilizado por el pipeline.

Reproducción: con catálogos de prueba habilitados y un encoder inyectado de 1024 dimensiones, invocar `recuperar_evidencias` sin inyectar Backend produce `servicio_no_disponible`, con mensaje interno `module ...config has no attribute BACKEND_API_BASE`. No se alcanza la búsqueda real.

Afecta a A2-01, A2-07 y CJ-03. La corrección pertenece a la integración #36.

### R2. A2 intenta cargar catálogos antes de construir el cliente que los descargaría — bloqueante

`pipeline.py:181` pasa `self._backend_client` a `infer_filters`; en la entrada pública ese atributo aún es `None`. En producción y sin archivos locales, `filter_inference.py:284` no puede usar fixtures y devuelve error antes de intentar la descarga.

Reproducción: `ARSOFT_ENV=production`, llamada pública normal con texto válido. Resultado `error/indice_no_disponible`; el constructor de Backend ni siquiera fue llamado. Esto es distinto de que el índice real esté caído.

El método de descarga de catálogos sí existe. Falta conectarlo al arranque normal. Afecta a A2-01/A2-10 y CJ-03. Corresponde a #36, con participación del responsable del cliente/filtros.

### R3. El servicio y el contenedor no activan ni empaquetan el circuito real completo — bloqueante para integración real

`Agents/service.py:27` usa `USE_REAL_AGENT2=0` por defecto. Sin configuración explícita las consultas siguen pasando al simulador con evidencias preparadas. Activar la variable requiere resolver R1 y R2.

`Agents/apptainer/agentes.def` no copia `Agents/Agent_2` ni instala sus requisitos; solo instala `Agents/requirements.txt`, que contiene las dependencias HTTP del servicio. Por tanto el contenedor actual no entrega el recuperador real aunque se active la variable.

Además, `/agentes/salud` solo comprueba Ollama y que la función de A2 se importó. Se reprodujo `status=ok, recuperacion=agente2` simulando únicamente la respuesta de Ollama, sin comprobar Backend, índice, BGE-M3 ni reranker. No demuestra la salud exigida por CTR-001.

Afecta a A2-09, CJ-03 y CJ-04; integración #36.

### R4. El registro activo no implementa CTR-003 — bloqueante contractual

`Agents/agente1/core.py:1123` escribe JSONL de forma síncrona. La llamada activa en `core.py:1450` guarda una telemetría reducida: no incluye `pregunta`, `respuesta`, `marca_tiempo`, `modelo` ni `version_prompt` con el esquema firmado, y usa `estado`/`fuentes` en lugar de `estado_respuesta`/`chunks_usados`.

El cliente `cliente_backend.py` tiene envío HTTP y sincronización manual, pero el flujo del servicio no lo llama ni programa un trabajador de reenvío. Su formateador también usa el esquema antiguo (`pregunta_original`, campos extra y feedback; falta `codigo_error`). Tener ese cliente y sus pruebas no significa que esté integrado.

Las entradas rechazadas directamente en el servicio tampoco pasan por la auditoría del núcleo. CTR-003 pide un registro por turno, de cualquier estado, sin bloquear la respuesta y con buffer/reenvío automático.

**Dependencia externa comprobada:** el Backend actual expone lectura en `/consultas` y registra internamente desde la pasarela; no expone `POST /registros`. Esto exige coordinación con Backend o un cambio contractual acordado; corregir solo Agentes no completa el circuito firmado. No se ha modificado Backend.

Afecta a A1-08/M9 y CJ-03. Es una carencia ya presente en main, que #36 no resuelve.

### R5. Las entradas inválidas no se convierten al formato CTR-001 — bloqueante contractual

En `Agents/service.py` no hay manejador de `RequestValidationError`. Se reprodujeron tres llamadas con ASGI: cuerpo `{}`, pregunta numérica e identificador de conversación vacío. Las tres devuelven HTTP 422 y `detail` de FastAPI.

CTR-001 §3.1 exige HTTP 200 con los cinco campos habituales y `estado=error`, `codigo_error=entrada_invalida`. La validación manual de una pregunta en blanco no cubre los fallos anteriores a entrar en la función.

El servicio también puede propagar códigos internos (`servicio_no_disponible`, `filtro_invalido`, `error_verificacion`, etc.) que no están en la lista cerrada firmada de CTR-001. La pasarela actual acepta una cadena libre, de modo que esto es una desviación contractual, no un rechazo de esquema del Backend actual. Se debe decidir mapeo exterior o actualización formal del contrato.

Afecta a CTR-001/M1/M9; ya está en main y persiste en #36.

### R6. A1 y A2 no comparten completamente el vocabulario de filtros — fallo de integración

`core.py:81` transforma `codigo_averia`, `mantenimiento`, `boletin` y `catalogo` en `otro`. `filter_vocab.py` no admite `otro` ni `normativa` como tipo documental. Por tanto una consulta válida puede terminar en `filtro_invalido` por la adaptación entre agentes.

Los ejemplos del propio prompt de A1 producen componentes como `culata` o `encendido / inyección`; A2 los rechaza por no pertenecer al conjunto cerrado. Se reprodujo el rechazo de esos valores y de `CMP-18`, mientras que `refrigeracion` sí se admite.

Matiz relevante: la ingesta actual del Backend ya usa nombres de subsistemas en `componente`, compatibles con A2, y mantiene los códigos CMP en `ids_referenciados`. Por ello no se afirma que todo componente del Backend sea incompatible. El catálogo descargado sí usa códigos CMP y el documento firmado deja abierto el acuerdo nombre/código: falta una política común y una traducción segura desde A1.

Además, A1 genera `texto_busqueda`, mientras el campo firmado es `texto_preprocesado`. La #36 acepta ambos y permite funcionar internamente; falta alinear la salida canónica con el contrato. Los códigos deben seguir viajando también en el texto léxico y no convertirse en un filtro de Backend.

Afecta a A1-04/A1-10 y A2-10; resolver coordinadamente entre el núcleo A1 y la integración de filtros.

### R7. Los vecinos se solicitan pero se eliminan de la salida final — requisito incompleto

`pipeline.py:505` descarta todo vecino sin `rerank_score`. La expansión habitual de `neighbors.py` marca `es_vecino`, pero no calcula esa puntuación.

Reproducción: Backend devuelve un padre relevante y un vecino compatible de la misma sección con un aviso de desconexión. El pipeline acaba en `suficiente`, pero `resultados` contiene solo el padre. El aviso vecino no llega al redactor.

Evitar inventar un score es correcto, pero hace falta completar el diseño: rerankear también los vecinos o definir contexto asociado trazable con reglas explícitas. No se puede dar por cerrado el paso 8 del flujo ni A2-06.

### R8. A1 puede omitir una ambigüedad de versiones en una respuesta CTR-004 válida — fallo defensivo

`resolver_evidencias`, `core.py:1368` y `:1387`, busca el campo singular `metadata.version` para detectar versiones múltiples. CTR-004/CTR-002 usan `versiones` como lista. Si A2 solo devuelve el JSON contractual `resultados` sin la extensión `estado=ambiguo`, el adaptador lo toma como suficiente y el decisor puede pasar a redacción.

Reproducción con dos resultados, uno para V1.0 y otro para V2.0, sin versión solicitada y con textos diferentes: se llamó al redactor y el estado fue `respuesta`. La #36 reduce este riesgo al emitir su propio estado, pero el consumidor no es autónomamente conforme al formato firmado.

La decisión de vigencia de A1 tampoco utiliza directamente `vigente_para`; se apoya en `obsoleto`/`sustituido_por`. A2 sí calcula aplicabilidad, pero falta alinear la comprobación final A1 con esa semántica, preservando el aviso de CTR-001 cuando corresponda.

### R9. Faltan partes explícitas de A1 que las pruebas actuales no exigen

- No hay caché semántica de respuestas/evidencias con clave por versión, componente e índice ni invalidación por cambio de índice (A1-01/M2). La caché de catálogos de A2 y la carga reutilizable de modelos son funciones diferentes.
- Hay presupuesto temporal y fallbacks LLM, pero no un Circuit Breaker con estados/corte tras fallos ni el límite de 15 s definido por PAQ-001 (A1-02). El valor actual por defecto es 10 s compartidos entre clasificación, recuperación y redacción. Si A2 consume el presupuesto, el redactor puede quedarse sin tiempo.
- Hay verificación determinista de citas y respaldo literal con un reintento, pero no juez LLM posterior (A1-07). El respaldo extractivo no debe presentarse como ese juez ya implementado.
- El prompt habla de estructura obligatoria y luego permite omitir encabezados; falta el apartado separado de comprobaciones de PAQ-001. No hay una validación de los cinco apartados exigidos (A1-06).
- En la ruta de redacción, una ausencia de respuesta del modelo puede acabar etiquetada como `error_verificacion`; la capa LLM no conserva de forma estructurada la causa timeout/indisponibilidad para todos los llamadores. Se conserva el estado error, pero no siempre el código correcto.

Son carencias de main y no solo de las PR de A2.

## Estado de los paquetes de trabajo

Implementado significa código localizado y pruebas disponibles; no certifica el funcionamiento con infraestructura real. Ningún paquete que dependa del circuito completo se considera cerrado por pruebas sintéticas solamente.

| Paquete A1 | Evaluación |
| --- | --- |
| A1-01 | Parcial: normalización presente; caché semántica e invalidación por índice ausentes. |
| A1-02 | Parcial: llamadas locales/OpenAI-compatible y presupuesto temporal; Circuit Breaker y validación local/API de aceptación pendientes. |
| A1-03 | Implementado en código y cubierto con mocks; calidad real del clasificador pendiente de aceptación. |
| A1-04 | Parcial: Query JSON validado, pero alias de texto y vocabulario de filtros desalineados. |
| A1-05 | Parcial: sesiones, memoria temporal, dos aclaraciones y consulta pendiente presentes; ambigüedad en listas de versiones y condensación general necesitan validación. |
| A1-06 | Parcial: generación, citas, abstención y aviso de obsolescencia presentes; formato completo y aplicabilidad final pendientes. |
| A1-07 | Parcial: verificación determinista y un reintento presentes; juez LLM ausente. |
| A1-08 | Incompleto: no está conectado el envío asíncrono CTR-003 ni el reenvío automático contractual. |
| A1-09 | Parcial: estudio local 3B/14B y datos archivados presentes; falta comparación local/API con aceptación completa. |
| A1-10 | Parcial: normaliza síntomas; no garantiza componentes canónicos ni aclaración por inferencia insegura. |

| Paquete A2 | Evaluación de #36 |
| --- | --- |
| A2-01 | Cliente HTTP y BGE-M3 con `query:` implementados; entrada normal bloqueada por R1/R2. |
| A2-02 | Parser vectorial con scores, metadatos y adaptador implementado y probado. |
| A2-03 | Cliente/parser léxico implementado y probado; falta evidencia de recuperación sobre corpus real. |
| A2-04 | RRF k=60 implementado y probado; aceptación de recall frente al mejor recuperador pendiente con datos representativos. |
| A2-05 | Reranker, umbral y carga reutilizable implementados; inferencia real y corte calibrado pendientes. |
| A2-06 | Estados y vigencia implementados; vecinos no llegan normalmente a la salida final. |
| A2-07 | Empaquetador CTR-004 implementado; servicio real y vocabulario aún no cerrados. |
| A2-08 | Herramientas de métricas/calibración implementadas; no se acredita una calibración real del umbral y tamaños elegidos. |
| A2-09 | Resiliencia y mediciones parciales; contenedor incompleto, sin presupuesto global y sin aceptación real de latencias. |
| A2-10 | Filtros duros y relajación limitada a tipo documental implementados; falta cerrar vocabulario y aprovisionamiento de catálogos. |

En A2-09 el pipeline guarda `tiempo_backend_ms` agrupado, no separa vectorial y léxica como pide el paquete. En A1 se envía normalmente `opciones.top_k=3`, que el pipeline utiliza también como número de candidatos de búsqueda, frente al valor inicial 30 del diseño A2: conviene separar recuperación de selección final y justificar ambos con calibración.

| Paquete conjunto | Evaluación |
| --- | --- |
| CJ-01 | Simuladores amplios presentes; no cubren por sí solos las desviaciones firmadas detectadas. |
| CJ-02 | Dataset de 40 preguntas y evaluador presentes; los cuatro casos multiturmo 033-036 no incluyen turnos previos explícitos. |
| CJ-03 | Incompleto: faltan arranque real, registro contractual y despliegue conjunto. |
| CJ-04 | Pendiente con Frontend, Backend, PostgreSQL, modelos e índice reales; faltan también funciones de A1 exigidas. |
| CJ-05 | Hay documentación y estudio de modelos; debe actualizarse tras resolver contratos y medir el conjunto. |
| CJ-06 | No se puede acreditar la entrega semanal y las horas desde este árbol de código. |

## Pruebas y límites de la evaluación

En la copia limpia de #36, con el Python de `.venv` y `ARSOFT_ENV=test`, `PYTHONPATH=.;shared`:

```powershell
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q -rs --tb=short
```

Resultado reproducido: **826 passed, 2 skipped, 137 subtests passed**. Las dos omitidas son la inferencia opcional del reranker real y su benchmark. La ejecución se repitió fuera del sandbox porque las pruebas HTTP locales necesitan sockets que el entorno restringido bloqueaba; los fallos de permisos iniciales no se consideran errores del proyecto.

Las reproducciones adicionales están en `.worktrees/auditoria-20261119/probes.py`. Usan mocks y un dataset pequeño para aislar el arranque, filtros, vecinos, ambigüedad, respuesta HTTP y telemetría. No descargan modelos ni consultan servicios de producción.

También se recalificaron las 40 respuestas ya archivadas en `Test/test_Models/respuestas_reales_cj02.json` con el evaluador versionado: **8/40 comprobaciones contractuales superadas (20 %)**. Es una evaluación de resultados históricos, no una ejecución nueva del sistema ni una medida de la calidad actual de #36. El propio evaluador declara `certifica_modelo_real=false` y limita la validación semántica y del corpus.

No se han ejecutado BGE-M3, reranker, Ollama, PostgreSQL ni la cadena completa reales. Por tanto no se certifican recall, MRR, abstención, seguridad documental de todo el corpus, latencia total ni despliegue.

## Qué falta para considerar A2 completo

1. Resolver los dos fallos del arranque por defecto y cargar catálogos reales por Backend.
2. Acordar el vocabulario A1-A2-Backend y corregir el paso de filtros y texto canónicos.
3. Completar la entrega de vecinos compatibles con trazabilidad y puntuación/contexto definidos.
4. Activar y empaquetar el recuperador real, con salud útil y límites temporales coordinados con la pasarela de 25 s.
5. Calibrar umbral, tamaños y RRF/reranker con consultas/corpus representativos, documentando recall, MRR, abstención y filtros.
6. Medir latencias vectorial, léxica, RRF, reranker y total; probar fallos y reindexación reales.
7. Ejecutar CJ-03/CJ-04 incluyendo registro CTR-003 y las garantías finales de A1.

Las correcciones de código quedan pendientes de la decisión del usuario. No se ha fusionado ninguna PR ni alterado las contribuciones de los autores.
