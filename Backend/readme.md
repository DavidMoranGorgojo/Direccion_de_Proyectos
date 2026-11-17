# Backend — Asistente conversacional RAG (ThermoDrive HTM-240)

Estructura según el diseño «Arquitectura del backend y dockerización» (§7.3). Base de datos única PostgreSQL + pgvector; la lógica RAG vive en Agentes (opción B).

| Carpeta | Contenido | Estado |
|---|---|---|
| `ingesta/` | Ingesta a demanda: PDF → fragmentos JSONL con metadatos y embeddings bge-m3 → pgvector. Ver [`ingesta/README.md`](ingesta/README.md). | Implementada |
| `db/init/` | Scripts SQL que PostgreSQL ejecuta al crear el contenedor. `01_conocimiento.sql`: esquema `conocimiento` (índice versionado, documentos, chunks y catálogos). | Propuesta para Base de datos y carga |
| `api/` | FastAPI: pasarela hacia Agentes, búsquedas, login, historial y registro. | Pendiente (Infraestructura) |
| `compose.yaml` | Servicios `backend-db`, `backend-api` y `backend-ingesta`. | Pendiente (Infraestructura) |

Los PDF de ARSOFT (`data/manuales`), las credenciales (`.env`) y las salidas de la ingesta no se versionan.
