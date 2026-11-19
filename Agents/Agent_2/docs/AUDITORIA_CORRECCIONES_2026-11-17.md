# Auditoría independiente y correcciones de prepublicación — Agente 2

**Fecha:** 17/11/2026
**Origen:** `Direccion_de_Proyectos (2).zip`, subárbol `.worktrees/pipeline/` (`fix/agente2-pipeline`).
**Alcance:** código de Agentes, tests y `.gitignore`. Sin alterar otros departamentos ni fusionar ramas.

## Verificación ejecutada

Antes de corregir: **491 pruebas correctas, 7 fallidas, 2 omitidas y 137 subtests superados** en `Test/test_Models`, `Test/test_Agents` y `Test/test_Performance`.

Después de corregir: **513 pruebas correctas, 0 fallidas, 2 omitidas y 137 subtests superados** en esa misma batería. Se incorporaron 15 casos nuevos de regresión. Se ejecutó también en una copia limpia sin `.git`, `.venv` ni `Agents/Agent_2/data/`, usando `ARSOFT_ENV=test` para obtener únicamente fixtures versionables.

Comando (PowerShell, desde la carpeta raíz del proyecto corregido):

```powershell
$env:ARSOFT_ENV = "test"
$env:PYTHONPATH = ".;shared"
python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q
```

## Cambios implementados

1. **Inferencia y catálogos (`filter_inference.py`)**: importación de `os`; configuración del directorio de catálogos dinámica para que los tests y entornos distintos sean efectivos. No se utilizan fixtures sintéticos en producción ni cuando no hay entorno definido. El desarrollo precisa habilitación explícita; los tests pueden utilizar `ARSOFT_ENV=test`. Si faltan catálogos reales, el punto de entrada devuelve un error controlado `indice_no_disponible`.
2. **Filtros explícitos**: valores inexistentes de versión, componente o tipo documental ya no se descartan silenciosamente para ampliar la búsqueda. Se rechazan como filtros inválidos; los campos nulos o cadenas en blanco no se consideran restricciones confirmadas.
3. **Inferencia conservadora**: no se infiere componente a partir de la palabra genérica «motor», ni tipo documental a partir de «diagnóstico». Se evita inferir batería en contextos como «motor de la batería». Se reconoce la expresión inequívoca «circuito del motor».
4. **Vigencia (`filters.py` y `vigencia.py`)**: un documento sustituido solo aplica a versiones listadas en `vigente_para`, aunque su historial `versiones` contenga más. Para documentos *no sustituidos* con `vigente_para` vacío se preserva la semántica de `versiones` del corpus sintético; una lista no vacía de `vigente_para` siempre prevalece. Los vecinos se someten también a filtros duros de versión y componente.
5. **Fusión (`fusion.py`)**: si dos recuperadores atribuyen metadatos documentales contradictorios al mismo `chunk_id`, se rechaza la fusión en lugar de elegir arbitrariamente el primer valor. Se conservan las reglas de deduplicación RRF.
6. **Pipeline (`pipeline.py`)**: valida filtros incorrectos y ausencia de catálogos sin excepciones sin controlar; valida el modelo declarado en ambos índices y su versión entre búsquedas; distingue incompatibilidad de índice (`indice_no_disponible`) de modelo (`modelo_incompatible`).
7. **CTR-002, §4**: reintento limitado si la búsqueda con `tipo_documento` no devuelve resultados; se elimina únicamente ese tipo y no se relajan los filtros de versión ni componente. El resultado indica `metricas.tipo_documento_ampliado`.
8. **Reranker y puntuaciones**: el punto de entrada público requiere un reranker por defecto. El modo opcional de desarrollo sin reranker distingue `modo_recuperacion=rrf_sin_reranker`. Los vecinos sin puntuación propia no heredan la del padre ni se anuncian como evidencias rerankeadas.
9. **CTR-004**: se conserva `resultados` como salida contractual. Se eliminó la invención de un metadato `version` único basado en `versiones[0]`. El constructor contractual de evidencias es obligatorio y sus fallos se comunican; se elimina el fallback que creaba metadatos ficticios. La salida interna para el Agente 1 conserva `evidencias` con los metadatos íntegros.
10. **Normalización de Agente 1 (`Agents/agente1/core.py`)**: se permite `codigo_error=None` para ausencia de error sin convertirlo a cadena vacía, y se acepta `filtro_invalido`. Único cambio en Agente 1; no se ha tocado el clúster.
11. **Fechas**: el parser vectorial acepta `fecha_revision=None` sin inventar fecha, en coherencia con el origen que la admite opcionalmente. Un test anterior que exigía rechazarla se actualizó, documentando esa decisión.
12. **Reproducibilidad**: el dataset sintético pasó a `Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json`. Los tests de filtros y RRF leen esa ruta versionable. Se excluyen archivos reales/ignorados de `data/`. Se añade `.worktrees/` a `.gitignore` para proteger worktrees locales.
13. **Pruebas modificadas**: dos mocks de Backend anunciaban un modelo no textual (un `MagicMock`) y detenían la ejecución antes del reranker; se hicieron contractuales. Se actualizaron verificaciones anticuadas sobre versiones, inferencia genérica y documentos obsoletos, evitando modificar el código para satisfacer expectativas contrarias a los contratos.

## Qué no se ha validado

- **Modelos reales**: no hay `FlagEmbedding` instalado en el entorno de auditoría. No se descargaron pesos; no se midió precisión, calibración ni latencia real de inferencia.
- **Backend real e índice PostgreSQL/BM25**: las pruebas de integración emplean sesiones simuladas; no se ha realizado conexión a un servidor real.
- **Clúster del Agente 1 y despliegue Apptainer**: quedan fuera del alcance. No se ha declarado aptitud para producción.
- **Suite global de Backend/Frontend**: no forma parte de la cifra de 513. Puede requerir dependencias y servicios ajenos a Agentes.
- **Documentación contractual pendiente de acordar**: criterios de páginas cero, algunas nomenclaturas de tipos y la semántica exacta del umbral deben validarse con los responsables. No se han modificado los contratos firmados.
- **Vecinos contextuales**: los que carecen de una puntuación real se excluyen de las evidencias con umbral. Una implementación futura podría añadirlos al contexto no puntuado de manera expresamente contractual.

## Criterio de publicación

El paquete se puede **incorporar y revisar en una rama de desarrollo**. No se debe anunciar como verificado en producción ni fusionar automáticamente a `main` hasta validar contratos con los equipos y pasar el entorno real. No se ha hecho commit, push ni merge.
