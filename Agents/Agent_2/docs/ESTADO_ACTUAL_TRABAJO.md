# Estado Actual de Trabajo y Guía de Continuidad — ARSOFT Agente 2

**Fecha de actualización:** 18 de noviembre de 2026 (Cierre Definitivo y Verificación en Copia Limpia)
**Proyecto:** ARSOFT — Asistente RAG de Documentación Técnica de Automoción
**Departamento:** Departamento de Agentes (Agente 2 — Recuperación y Evidencias)
**Rama activa:** `fix/agente2-integracion-final`
**Directorio de trabajo principal:** `.worktrees/pipeline` (worktree dedicado)

---

## 1. Resumen Ejecutivo del Cierre Definitivo

El desarrollo, depuración, integración, recuperación de pruebas y verificación en copia limpia del **Agente 2** ha finalizado con éxito total:

- **100% de la batería de pruebas superada en local y en copia limpia aislada (`git archive`):** **826 tests pasados**, 2 omitidos (requieren modelos reales/GPU), 137 subtests pasados (0 fallos).
- **Parche de rutas para checkout limpio aplicado:** Corregidas las rutas de fixtures en los tests para depender exclusivamente de `Agents/Agent_2/fixtures/bbdd_sintetica_chunks.json`, asegurando que cualquier clon fresco desde GitHub supera las pruebas sin requerir el directorio ignorado `data/`.
- **Recuperación completa de las 13 suites eliminadas:** Se recuperaron 3.518 líneas de código de pruebas del árbol de Alba, adaptando 8 casos puntuales que esperaban comportamientos pre-contractuales para cumplir estrictamente CTR-002 y CTR-004.
- **Caché de catálogos robustecida:**
  - Implementada clase `CatalogCacheEntry` con metadatos de versión y timestamp.
  - Clave de identidad compuesta (`base_url`, `token`, `model_embeddings`).
  - Caducidad configurable (TTL) y función de invalidación explícita `invalidate_backend_catalog_cache()`.
  - Sincronización reentrante para concurrencia con `threading.RLock`.
  - Manejo de errores controlado con soporte para `stale_if_error`.
  - 8 nuevas pruebas añadidas en [`test_catalog_cache_politica.py`](file:///c:/Users/Juan%20Miguel/Desktop/UNIVERSIDAD/CUARTO/PRIMER%20CUATRI/DIRECCION_PROYECTOS/Direccion_de_Proyectos/Test/test_Models/test_catalog_cache_politica.py).
- **Ramas y commits protegidos:** Conservada toda la autoría histórica de Alba, Álvaro y Víctor.

---

## 2. Mapa de Ramas y Commits en GitHub

| Rama | Hash SHA-1 | Estado / Pull Request | Propósito |
|---|---|---|---|
| `main` | `98b183a18fcbbe9453d0e851176109580a7629ff` | Intacta en remoto | Rama base protegida (no modificada) |
| `agentes-alba-agent2-busqueda` | `cfebf932c79cb48cf9f5129228f7db74049331d3` | PR #32 abierta y actualizada | Backend client, filtros duros, vigencia |
| `alvaro-agent2-pr` | `b3890a06ec74200d3331b11e5d126c8e8fcd9c97` | PR #34 abierta y sincronizada | Parser vectorial, CTR-004, calibración |
| `victor-agent2` | `fe052849c912bb32e510d10629cc0628c1c5951b` | Publicada en remoto | Reranker estructurado con score y métricas |
| `fix/agente2-pipeline` | `53524ebfa4f90577246eb64dc51e2ff22aeb6b38` | Publicada en remoto | Respaldo anterior |
| `fix/agente2-integracion-final` | *(último commit publicado)* | Lista para PR Draft | **Integración final certificada en copia limpia (826 tests)** |

### Enlaces directos a Pull Requests:
- **PR #32 (Alba):** https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/32
- **PR #34 (Álvaro):** https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/34
- **PR Draft Integración Final:** https://github.com/DavidMoranGorgojo/Direccion_de_Proyectos/pull/new/fix/agente2-integracion-final

---

## 3. Guía Rápida para Reanudar el Trabajo

Para cualquier revisor o ingeniero que clone el proyecto:

### 3.1. Entorno de Ejecución
- **Ubicación:**
  ```powershell
  cd "C:\Users\Juan Miguel\Desktop\UNIVERSIDAD\CUARTO\PRIMER CUATRI\DIRECCION_PROYECTOS\Direccion_de_Proyectos\.worktrees\pipeline"
  ```
- **Ejecutar la suite completa (826 tests):**
  ```powershell
  $env:ARSOFT_ENV = "test"
  $env:PYTHONPATH = ".;shared"
  python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q -rs
  ```
- **Verificar en copia limpia aislada:**
  ```powershell
  $temp = "$env:TEMP\clean_test"
  git archive HEAD | tar -x -C $temp
  cd $temp
  $env:ARSOFT_ENV = "test"; $env:PYTHONPATH = ".;shared"
  python -m pytest Test/test_Models Test/test_Agents Test/test_Performance -q -rs
  cd ..; Remove-Item -Recurse -Force $temp
  ```

### 3.2. Reglas Críticas de Seguridad
1. **NO modificar `main` directamente:** Todos los cambios deben ingresar exclusivamente vía Pull Request.
2. **NO modificar Backend, Frontend ni Base de Datos:** Este workspace corresponde al Departamento de Agentes.
3. **NO modificar el clúster ni el contenedor del Agente 1:** En desarrollo por el subequipo correspondiente.
4. **NO incluir credenciales ni datos privados.**
