# Informe Final de Integración, Corrección y Publicación de Pull Requests — ARSOFT Agente 2

**Fecha:** 17 de noviembre de 2026
**Proyecto:** ARSOFT — Asistente RAG de Documentación Técnica de Automoción
**Departamento:** Departamento de Agentes (Agente 2 — Recuperación y Evidencias)
**Entorno de ejecución:** Windows PowerShell / Git 2.47+ / Python 3.10.6 (.venv)

---

## 1. Estado inicial del repositorio

Al comenzar esta fase de trabajo:
- **Worktree principal:** `.worktrees/pipeline` asociado a la rama `fix/agente2-pipeline`.
- **Ramas individuales identificadas:**
  - `agentes-alba-agent2-busqueda` (PR #32 en GitHub, base en `1db8cf7`, con 2 commits locales no publicados `4e57102` y `cfebf93`).
  - `alvaro-agent2-pr` (PR #34 en GitHub, commit `b3890a0`).
  - `victor-agent2` (PR #18 fusionado previamente en `main` `8ae8bac`, con commit local `fe05284`).
- **Remoto configurado:** `origin -> https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos.git`.
- **`origin/main`:** situado en `98b183a` (incorporando guías de Apptainer).
- **Línea base previa:** 513 pruebas superadas con simuladores, 2 omitidas, 137 subtests.

---

## 2. Correcciones HTTP implementadas (Bloqueante 2.1)

**Defecto reproducido:** En `Agents/Agent_2/src/clients/backend.py`, el método `_post_conocimiento()` ejecutaba directamente `response.raise_for_status()`. Como consecuencia, excepciones HTTP de Backend como 409 (`modelo_incompatible`) o 503 (`indice_no_disponible`) eran capturadas como `requests.RequestException` genérica en `pipeline.py`, degradándose incorrectamente al código por defecto `servicio_no_disponible`.

**Solución aplicada:**
- Se eliminó la llamada directa a `raise_for_status()`.
- Se implementó inspección explícita de `response.status_code >= 400` antes de decodificar el cuerpo.
- Se delegó en `_backend_error_code(response)`, que extrae códigos contractuales según CTR-001/CTR-002:
  - **HTTP 400 / 422:** `entrada_invalida` (incluyendo mapeo de `peticion_invalida` y `filtro_invalido`).
  - **HTTP 404:** `indice_no_disponible`.
  - **HTTP 409:** `modelo_incompatible`.
  - **HTTP 503:** `indice_no_disponible` (salvo que el Backend comunique explícitamente otra causa).
  - **HTTP 504 o Timeout:** `tiempo_agotado`.
  - **Fallo de conexión o red:** `servicio_no_disponible`.
  - **JSON malformado:** `servicio_no_disponible`.
  - **HTTP 200 con lista vacía:** respuesta válida sin error (`sin_evidencia`), nunca excepción.
- Se añadieron 26 pruebas parametrizadas en `Test/test_Models/test_backend_http_errors.py`, demostrando que el código contractual exacto se propaga hasta el Agente 1.

---

## 3. Solución para catálogos de producción (Bloqueante 2.2)

**Defecto reproducido:** La inferencia de filtros en `filter_inference.py` dependía de fixtures sintéticos en disco y no contemplaba la obtención real mediante la API del Backend descrita en CTR-002 §2.

**Solución aplicada:**
1. **Cliente de lectura de catálogos:** Se añadió el método `BackendAPIClient.get_catalogo(nombre)` para `codigos`, `terminos`, `vehiculos` y `componentes`, invocando `GET /catalogos/{nombre}`.
2. **Validación y robustez:** Gestión de errores HTTP (404 -> `indice_no_disponible`, timeouts -> `tiempo_agotado`), validación de presencia del campo `contenido`.
3. **Caché en memoria:** Función `load_catalogs_from_backend()` con caché indexada por URL base del Backend.
4. **Política estricta de producción:**
   - En **producción** (`ARSOFT_ENV=production` o `prod`): prohibido el uso de catálogos sintéticos bajo cualquier concepto. Si faltan los catálogos reales o el Backend no responde, se lanza `FileNotFoundError` o `BackendRequestError` controlado.
   - En **entorno no especificado** (`ARSOFT_ENV` vacío): comportamiento seguro que rechaza el uso silencioso de sintéticos.
   - En **desarrollo/test**: fallback a `fixtures/catalogos` autorizado exclusivamente si `ARSOFT_ENV=test` o mediante opt-in explícito con `ARSOFT_ALLOW_SYNTHETIC_CATALOGS=1`.
5. **Pruebas añadidas:** 14 pruebas en `Test/test_Models/test_catalogos_backend_produccion.py` que verifican cliente, caché y política en todos los entornos.

---

## 4. Estado del despliegue (Apartado 2.3)

- **Inspección de `Agents/apptainer/agentes.def`:** La definición actual de Apptainer sólo empaqueta el Agente 1 y `Agents/service.py`, sin incluir el directorio `Agents/Agent_2` ni sus dependencias de inferencia (`FlagEmbedding`, `torch`, `transformers`, `requests`).
- **Bloqueo de infraestructura:** Apptainer es una tecnología de contenedores exclusiva de entornos Linux/HPC; no está disponible en la estación de trabajo Windows. Adicionalmente, el despliegue del clúster del Agente 1 continúa en desarrollo por otros integrantes.
- **Dictamen:** Se declara pendiente la certificación del contenedor Apptainer hasta disponer del entorno de clúster Linux con GPU. No se modificó el clúster del Agente 1 para preservar la estabilidad de su desarrollo.

---

## 5. Resultado exacto de las pruebas

Comando ejecutado en la rama de integración reconstruida:
```powershell
$env:ARSOFT_ENV = "test"
$env:PYTHONPATH = ".;shared"
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q -rs
```

**Resultado obtenido:**
```
556 passed, 2 skipped, 137 subtests passed in 4.21s (100%)
0 fallos, 0 errores
```

- **556 pruebas superadas:**
  - 513 de la batería de referencia del paquete.
  - 26 del mapeo exhaustivo de errores HTTP (`test_backend_http_errors.py`).
  - 14 del cliente de catálogos y política de producción (`test_catalogos_backend_produccion.py`).
  - 3 adicionales de integración del pipeline y vocabulario de filtros.
- **2 pruebas omitidas (skipped justificadas):**
  - `Test/test_Models/test_reranker_model.py:154`: requiere pesos del modelo BAAI/bge-reranker-v2-m3 descargados.
  - `Test/test_Performance/test_latency_reranker.py:151`: benchmark de latencia que requiere inferencia en GPU real.
- **137 subtests superados:** calibración y matrices de umbrales.
- **Mocks vs Servicios Reales:** Todas las pruebas automatizadas se ejecutaron con simuladores contractuales (`BackendSimulator`, sesiones simuladas de requests y embeddings locales sintéticos). La validación con Backend PostgreSQL real y pesos BGE-M3 descargados requiere infraestructura externa.

---

## 6. Archivos nuevos y modificados

Total de archivos involucrados respecto a `origin/main`: **70 archivos** (17.079 adiciones, 8 eliminaciones).

### Núcleo del Agente 2
- `Agents/Agent_2/src/clients/backend.py` (cliente HTTP CTR-002, búsqueda vectorial/léxica, fragmentos, vecinos y catálogos).
- `Agents/Agent_2/src/clients/bge_m3.py` (cliente BGE-M3 lazy con prefijo obligatorio `query:`).
- `Agents/Agent_2/src/services/pipeline.py` (orquestador hibrido CTR-002/CTR-004, validaciones F01-F14, RRF, reintentos).
- `Agents/Agent_2/src/services/filter_inference.py` (inferencia conservadora, catálogos remotos y locales).
- `Agents/Agent_2/src/services/filters.py` (filtros duros, tokens de códigos y vigencia).
- `Agents/Agent_2/src/services/fusion.py` (RRF con deduplicación y verificación de metadatos contradictorios).
- `Agents/Agent_2/src/services/reranker.py` (modelo cruzado, umbrales y métricas).
- `Agents/Agent_2/src/services/vigencia.py` (clasificación documental y vecinos controlados).
- `Agents/Agent_2/src/services/vector_parser.py` (parseo estricto CTR-002).
- `Agents/Agent_2/src/services/evidence_builder.py` (empaquetado contractual CTR-004).
- `Agents/Agent_2/src/models/ctr_002.py` y `ctr_004.py` (modelos de datos contractuales).

### Adaptadores y pruebas
- `Agents/agente1/core.py` (normalización compatible con `codigo_error=None`).
- `Agents/service.py` (adaptador del servicio Agente 1 hacia Agente 2).
- `Test/test_Models/test_backend_http_errors.py` (26 tests nuevos).
- `Test/test_Models/test_catalogos_backend_produccion.py` (14 tests nuevos).
- `Test/test_Models/test_fase1_aceptacion.py` y `test_fase1_verificacion_final.py`.
- `Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json` (dataset sintético versionable).

---

## 7. Organización final de las ramas

La reconstrucción de la integración se llevó a cabo preservando la autoría y ascendencia de cada paquete:

```
origin/main (98b183a)
  ├── victor-agent2 (fe05284) [Rerank with threshold estructurado]
  │     └── Merge into fix/agente2-integracion-final
  ├── alvaro-agent2-pr (b3890a0) [PR #34: Parser vectorial, evidencias, calibracion]
  │     └── Merge into fix/agente2-integracion-final
  └── agentes-alba-agent2-busqueda (cfebf93) [PR #32: Backend client, filtros, vigencia]
        └── Merge into fix/agente2-integracion-final
              └── Commit c8a74f8: Consolidacion pipeline + B01 + B02 + Suite 556 tests
                    └── Commit b70143f: Formato y verificacion de documentacion
```

---

## 8. Commits creados

En `fix/agente2-pipeline`:
1. `444d11c`: *feat(agente2): integrar paquete de correcciones verificado ARSOFT_SOLO_CAMBIOS*
2. `53524eb`: *fix(agente2): mapeo de errores HTTP contractuales y cliente de catalogos CTR-002 con politica de produccion*

En `fix/agente2-integracion-final`:
1. `8671760`: *Merge branch 'victor-agent2' into fix/agente2-integracion-final*
2. `235028c`: *Merge branch 'alvaro-agent2-pr' into fix/agente2-integracion-final*
3. `35f7e9d`: *Merge branch 'agentes-alba-agent2-busqueda' into fix/agente2-integracion-final*
4. `c8a74f8`: *feat(integracion): consolidar pipeline Agente 2, correcciones contractuales CTR-002/CTR-004 y suite verificada*
5. `b70143f`: *docs: limpiar espacios al final de linea en documentacion*

---

## 9. Commits originales preservados

Se conservaron íntegros los commits y autorías históricas de los tres desarrolladores:
- **Alba:** commits de paquetes A2-01, A2-03, A2-06, A2-10 y avances locales `4e57102`, `cfebf93`.
- **Álvaro:** commits de paquetes A2-02, A2-07, A2-08 (`3a2e7ac`, `5afc840`, `7e5742d`, `293b928`, `b3890a0`).
- **Víctor:** commits de paquetes A2-04, A2-05, A2-09 y commit local `fe05284`.

---

## 10. Conflictos Git resueltos

Al fusionar las tres ramas ordenadamente sobre `fix/agente2-integracion-final`:
- **`.gitignore`:** se resolvió unificando la exclusión de `.worktrees/`, `.venv/`, `data/` y cachés locales.
- **Archivos de prueba duplicados:** la rama histórica de Alba contenía 13 tests obsoletos anteriores a la refactorización (que esperaban excepciones `requests.HTTPError` no contractuales o relajación de vecinos). Se desestimaron los tests obsoletos manteniendo exclusivamente la suite consolidada y verificada de 556 pruebas.
- **Datos privados:** se retiró el seguimiento de `Agents/Agent_2/data/` de Git conforme a la política de exclusión documental.

---

## 11. Ramas publicadas y sus hashes exactos

Todas las ramas fueron verificadas y empujadas a GitHub mediante avances limpios y seguros:

| Rama local / remota | Hash SHA-1 | Estado en GitHub |
|---------------------|------------|------------------|
| `origin/main` | `98b183a18fcbbe9453d0e851176109580a7629ff` | Base remota intacta (no modificada) |
| `origin/agentes-alba-agent2-busqueda` | `cfebf932c79cb48cf9f5129228f7db74049331d3` | Actualizada (PR #32) |
| `origin/alvaro-agent2-pr` | `b3890a06ec74200d3331b11e5d126c8e8fcd9c97` | Sincronizada (PR #34) |
| `origin/victor-agent2` | `fe052849c912bb32e510d10629cc0628c1c5951b` | Publicada con commit adicional |
| `origin/fix/agente2-pipeline` | `53524ebfa4f90577246eb64dc51e2ff22aeb6b38` | Publicada como respaldo |
| `origin/fix/agente2-integracion-final` | `b70143f0fdbad745024e7a6c1af187cdad16510c` | Publicada (Integración completa) |

---

## 12. Enlaces reales a Pull Requests

- **PR #32 (Alba):** `agentes-alba-agent2-busqueda -> main`
  https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/32
  *Estado:* Abierto y actualizado con commits `4e57102` y `cfebf93`.
- **PR #34 (Álvaro):** `alvaro-agent2-pr -> main`
  https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/34
  *Estado:* Abierto y sincronizado con `b3890a0`.
- **PR #18 (Víctor):** `victor-agent2 -> main`
  *Estado:* Fusionado previamente en `main`. La rama `victor-agent2` contiene el commit complementario `fe05284`.
- **Nueva PR recomendada (Integración Final):**
  URL para abrir PR Draft:
  `https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/new/fix/agente2-integracion-final`

---

## 13. PR pendientes y motivo

- **PR de Integración Final (`fix/agente2-integracion-final`):** Queda disponible en GitHub para ser abierta en estado **Draft**. No se abrió automáticamente como PR contra `main` porque fusionar antes las PRs individuales #32 y #34 permite mantener el historial lineal y la trazabilidad de paquetes de trabajo de cada desarrollador.
- **PR complementaria de Víctor:** `victor-agent2` está publicada en remoto; puede crearse una PR dependiente o integrarse directamente a través de `fix/agente2-integracion-final`.

---

## 14. Riesgos que impiden un merge definitivo a main

1. **Dependencia de Backend real desplegado:** Las pruebas locales se ejecutan contra sesiones simuladas que cumplen CTR-002. Antes de fusionar a `main`, se debe desplegar el Backend con la base PostgreSQL e índice BM25 y comprobar el handshake de búsqueda y lectura de `/catalogos/`.
2. **Descarga de pesos de modelos:** BAAI/bge-m3 y BAAI/bge-reranker-v2-m3 no están descargados localmente por restricciones de almacenamiento/GPU.
3. **Desarrollo del clúster del Agente 1:** El contenedor Apptainer y el soporte SLURM están en desarrollo activo por el equipo del Agente 1.

---

## 15. Orden recomendado para fusionar los Pull Requests

Para preservar la trazabilidad documental y no generar duplicidades:

1. **Paso 1:** Revisar y fusionar **PR #32** (`agentes-alba-agent2-busqueda`).
2. **Paso 2:** Revisar y fusionar **PR #34** (`alvaro-agent2-pr`).
3. **Paso 3:** Fusionar el commit complementario de Víctor (`victor-agent2` `fe05284`).
4. **Paso 4:** Abrir y fusionar **PR de Integración Final** (`fix/agente2-integracion-final -> main`), que únicamente aportará el orquestador `pipeline.py`, el adaptador `service.py`, las correcciones B01/B02 y la suite unificada de 556 pruebas.

---

## 16. Confirmación de seguridad e integridad

- ✅ `main` **NO** fue modificada directamente.
- ✅ **NO** se realizó ningún merge destructivo a `main`.
- ✅ **NO** se modificaron Backend, Frontend ni Base de Datos.
- ✅ **NO** se modificó el desarrollo del clúster del Agente 1.
- ✅ **NO** se incluyeron credenciales, tokens, archivos temporales ni `.venv`.
- ✅ Todas las ramas remotas fueron actualizadas mediante pushes normales y verificables.
