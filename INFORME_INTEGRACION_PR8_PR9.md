# Integración local PR8 + PR9

Fecha: 4 de noviembre de 2026 (Europe/Madrid).
Rama: `feat/integracion-pr8-pr9`. Destino propuesto: `main`.

## Base, alcance y seguridad

Estado inicial limpio, checkout `main`. Se creó un worktree independiente en
`.worktrees/integracion-pr8-pr9` y la rama partió de `main`, no de la base antigua
`agent_1` de PR9. La incorporación de ambas ramas no produjo conflictos textuales.
Se conservan sus historiales mediante merges locales, incluyendo los cambios
más recientes de frontend que ya estaban en main.

Referencias locales utilizadas:

| Referencia | Commit |
| --- | --- |
| main y origin/main | f95b7677e6c6431aa46d4a8859b9ac3d444b49cf |
| PR8: origin/agente_1/jaime y pr-8-agente | a196f33d2b02f24f056dbeef1f00c9a8ce43d0cb |
| PR9: origin/agente1-marco y pr-9-bateria | bb57c3bd01735a1725a81206c2371cd3171164cd |

No se ejecutó fetch: estas referencias son la copia local disponible y no se
certifica su coincidencia con el estado actual de GitHub. No hubo push,
publicación, cambios de credenciales, infraestructura, permisos o protecciones.
Git requirió autorización del entorno para escribir metadatos protegidos en
`.git`. Los cambios de código se hicieron exclusivamente en el worktree.
El checkout principal conserva main; su carpeta `.worktrees/` aparece como
contenido local no rastreado, sin cambios en los archivos versionados de main.

## Archivos incorporados o modificados respecto a main

| Archivo | Procedencia y cambio |
| --- | --- |
| agente1_core.py | PR8; correcciones y adaptador local CTR-001 |
| test_agente1.py | Las 24 pruebas de PR8 conservadas sin modificar |
| Test/test_Models/benchmark_completo_CJ02_40_preguntas.json | Dataset de PR9 conservado exactamente |
| Test/test_Models/evaluar_benchmark.py | PR9; separación explícita de modos, validación y adaptador |
| Test/test_Models/metricas_cj02_resultado.json | Histórico PR9 preservado, etiquetado como simulación circular |
| Test/test_Models/metricas_cj02_simulacion_integracion.json | Ejecución de simulación de esta integración |
| test_integracion_pr8_pr9.py | 50 pruebas nuevas de integración, regresión, contratos y límites |
| requirements.txt | Base sin paquetes obligatorios para el núcleo, que usa biblioteca estándar |
| requirements-agente1-optional.txt | Rangos opcionales de API de OpenAI y Pydantic, sin instalar |
| .gitignore | Caché Python y auditoría local generada |
| pruebas_integracion.log | Salida completa de la última suite |
| pruebas_regresion_origen.json | Reproducciones de defectos contra el commit original de PR8 |
| INFORME_INTEGRACION_PR8_PR9.md | Este informe y pasos reproducibles |

No hay diferencias en `Backend/`, `Frontend/` ni `Agents/` respecto a main.
No se incorporaron otras ramas de compañeros para completar servicios ausentes.

## Funcionalidades conservadas

De PR8: normalización y extracción de códigos, enriquecimiento de síntomas,
clasificación con LLM local y fallback urllib, Query JSON CTR-004, memoria por
instancia y reset, cinco escenarios del simulador, redactor con un reintento,
verificador de identificadores de citas, consola paso a paso, batería de cinco
casos y auditoría JSONL tolerante a fallos.

De PR9: las 40 preguntas con sus IDs, categorías, criterios, ground truth y chunks;
evaluador por caso, agregación por categoría, precisión/cobertura de citas,
exportación JSON y resultado histórico con su procedencia real aclarada.

## Correcciones

- `versión V1.1` ya no genera `VV1.1`. Se conserva la versión completa, incluso
  `1.2.3`, y V6/V8 de motores no se interpretan como versiones sin prefijo explícito.
- Una versión explícita del usuario prevalece sobre la propuesta por el LLM;
  varias versiones requieren aclaración. Los códigos regex se conservan.
- El alias `query_busqueda` se normaliza antes de la validación opcional Pydantic.
  El validador de respaldo rechaza tipos inválidos sin excepciones inesperadas:
  filtros, opciones, listas de códigos, IDs, booleanos y `top_k` positivo.
- Entradas vacías, JSON truncado y fallos del modelo son errores, no aclaraciones.
- El simulador aplica versión, `top_k` y exclusión de obsoletos; no oculta la
  ambigüedad truncando variantes antes de decidir. Se conserva su interfaz legacy
  de lista/diccionario, probando también su serialización JSON.
- Una cita correcta ya no encubre identificadores falsos como `c_999` o `ABC`.
  Se admiten citas agrupadas. Tras dos intentos se devuelve la última verificación.
- La decisión compartida reconoce obsolescencia por estado, metadatos y sustitución;
  filtra documentos antiguos cuando hay vigentes y advierte si solo hay obsoletos.
- Se elimina el `UnboundLocalError` de la consola al recibir evidencias sin
  `estado_documento`. Una aclaración sin evidencias no se pierde como falta de datos.
  Las versiones y el campo de aclaración proceden de la respuesta recibida.
- Se validan metadatos que se convierten en fuentes JSON. Un error de recuperación
  no se convierte en ausencia de evidencia.
- El benchmark exige modo explícito; no comunica ground truth al pipeline externo,
  cuenta excepciones como fallos y no acepta respuestas declaradas simuladas como
  externas. Las citas deben ser esperadas y haber sido recuperadas. No se inventa
  latencia de inferencia: solo se mide duración del evaluador.
- Los informes nuevos se crean sin sobrescribir dataset ni ejecuciones existentes.

## Contratos y arquitectura

`consultar_asistente(pregunta, agente, agente2)` llama localmente a un callable
sustituible y entrega exactamente `trace_id`, `estado`, `texto`, `fuentes` y
`codigo_error`. Convierte rechazo a `fuera_de_ambito` y fallo de verificación a
`error`. Las fuentes son objetos con `chunk_id`, `documento`, `seccion`, `pagina`,
`versiones` y `obsoleto`, compatibles con los modelos actuales del frontend.
El redactor conserva internamente su lista de IDs de fuentes para no romper su
interfaz anterior. La prueba de integración carga los modelos reales del frontend
sin arrancar Qt y deserializa el JSON producido.

`crear_pipeline_local(agente_factory, agente2, simulado=...)` adapta este flujo al
vocabulario de CJ-02: `sin_evidencia`/`fuera_de_ambito` corresponden a `insuficiente`,
y `aclaracion` a `ambiguo`. El estado original de recuperación y el campo de
ambigüedad se observan en el callable. Cada caso crea una sesión; solo se reproducen
turnos anteriores si un escenario los proporciona explícitamente.

No se añaden servicios HTTP entre agentes. El llamador debe seleccionar y conservar
una instancia de Agente1 por conversación; este cambio no introduce un gestor de
sesiones ni una ruta nueva en el backend.

## Pruebas ejecutadas y evidencias

Entorno real de ejecución: CPython 3.10.6 en Windows, biblioteca estándar;
OpenAI SDK, Pydantic y pytest no están instalados en ese intérprete. Los alias
`python`/`python3` y el launcher registrado para 3.12 no eran ejecutables; se usó
el ejecutable existente de Python 3.10. No se instaló ningún paquete.

| Comprobación | Resultado verificable |
| --- | --- |
| Suite original PR8 antes de las correcciones | 24/24 correctas |
| Suite final `unittest discover -v` | 74 descubiertas: 73 correctas, 0 fallidas, 1 omitida |
| Prueba omitida | Paridad con Pydantic v2; dependencia opcional ausente |
| Regresión contra PR8 original | `VV1.1`, cita `c_999` aceptada, `UnboundLocalError` reproducidos |
| Simulación CJ-02 | 39/40 comprobaciones contractuales; 97,5%; no evaluación real |
| Precisión/cobertura macro de citas de esa simulación | 86,25% / 78,75%; incluye casos sin citas |
| Sintaxis de núcleo, evaluador y dos suites | Correcta |
| `git diff --check` | Correcto |
| Dataset respecto a PR9 y tests originales respecto a PR8 | Sin diferencias |
| Backend, frontend y Agents respecto a main | Sin diferencias |

La suite cubre casos unitarios y de integración con dobles locales: versión y
códigos, esquema estricto y alias, memoria/reset, JSON malformado, transportes
HTTP v1 y Ollama nativo interceptados sin red, agotamiento de endpoints, sustitución
de Agente 2, estados de error y falta de evidencia, aclaraciones, obsolescencia,
reintentos, auditoría, fuentes consumidas por frontend y evaluador CJ-02.
Los mensajes WARNING/ERROR del log corresponden a fallos provocados por las pruebas.

Reproducción desde el worktree (PowerShell; ajustar ruta del intérprete si procede):

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\Juan Miguel\AppData\Local\Programs\Python\Python310\python.exe' -m unittest discover -v
& 'C:\Users\Juan Miguel\AppData\Local\Programs\Python\Python310\python.exe' Test/test_Models/evaluar_benchmark.py --simulacion --salida nueva_simulacion_cj02.json
git diff main --stat
git diff --check
```

El segundo comando exige un archivo de salida nuevo. El JSON de simulación
incorporado se generó con el evaluador corregido; el adaptador añadido después
no altera su ruta de simulación. El histórico de PR9 no se presenta como una
nueva ejecución. La CLI también acepta `--respuestas archivo.json --salida nuevo.json`
para resultados archivados que declaren `modo: real`, `procedencia` y un objeto
`respuestas` con exactamente los 40 IDs. Esa declaración la aporta el operador;
no demuestra por sí sola que se haya ejecutado un modelo real.

## Pendientes y límites de certificación

1. CJ02-003: `chunks_esperados` incluye
   `HTM240-ESQ-001@1.0_p1_arquitectura_general`, mientras el ground truth cita
   `HTM240-ESQ-001@1.0_p1_flujo_calentamiento_frio`. El nuevo evaluador lo rechaza.
   No se cambia ninguno sin consultar los documentos fuente. Esto explica el
   39/40 de la simulación y evita conservar el 100% engañoso del informe original.
2. CJ02-033 a CJ02-036 dependen de antecedentes que el dataset no proporciona
   como turnos ejecutables. CJ02-034 además combina V1.1 con un ID terminado en
   `_v20`; requiere revisión documental. No se inventa ese contexto ni su solución.
3. En main no hay implementación operativa de Agente 2 y el fichero
   `Backend/api/app/main.py` está vacío. La ruta del frontend está marcada como
   pendiente de contrato. Se certifica el adaptador local, no el recorrido HTTP
   completo frontend/backend/recuperador.
4. No hay corpus documental para contrastar ground truth y valores. Los cinco
   escenarios del simulador contienen datos ficticios de desarrollo y no cubren
   las 40 preguntas reales. No se lanzaron Ollama, modelos, base de datos ni Qt.
5. La verificación de citas comprueba identificadores, no que cada afirmación se
   deduzca del fragmento. Los criterios técnicos, intención, valores/versiones
   semánticamente correctos y la política de dos aclaraciones de CJ02-032 requieren
   validación adicional. La regla histórica de obsolescencia del evaluador basada
   en 80.000 y palabras de aviso es limitada y se declara como tal.
6. Los pins transitivos de PR8 no estaban respaldados por un entorno reproducible
   presente. Se sustituyen por una base sin dependencias obligatorias y un archivo
   de APIs opcionales. No se consultó PyPI ni se certificó instalación/resolución
   de esos rangos; la vía con SDK/Pydantic queda pendiente, al igual que pytest y
   la interfaz Qt. No se afirma que los pins originales sean inexistentes.
7. No se ha verificado el estado remoto más reciente, CI remota, rendimiento,
   recuperación real ni calidad de un modelo. La procedencia externa requiere
   registrar versión del modelo, corpus, configuración y fecha por el operador.

## Recomendación

Rama preparada para revisión de código y una única PR hacia main, preferiblemente
como borrador mientras se revisan los puntos anteriores. La integración local y
sus pruebas automatizadas pasan. No recomiendo aprobar el merge como certificación
funcional del chatbot completo hasta resolver las discrepancias del dataset,
proveer contexto multiturno, ejecutar el flujo con Agente 2/corpus/modelo reales y
validar las dependencias opcionales. No se ha creado ni publicado ninguna PR.
