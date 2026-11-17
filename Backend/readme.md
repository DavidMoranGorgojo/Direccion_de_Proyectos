# Backend — Asistente conversacional RAG (ThermoDrive HTM-240)

Estructura según el diseño «Arquitectura del backend y dockerización» (§7.3). Base de datos única PostgreSQL + pgvector; la lógica RAG vive en Agentes (opción B).

| Carpeta | Contenido | Estado |
|---|---|---|
| `ingesta/` | Ingesta a demanda: PDF → fragmentos JSONL con metadatos y embeddings bge-m3 → pgvector. Ver [`ingesta/README.md`](ingesta/README.md). | Implementada |
| `db/init/` | Scripts SQL que PostgreSQL ejecuta al crear el contenedor. `01_conocimiento.sql`: esquema `conocimiento` (índice versionado, documentos, chunks y catálogos). `02_usuarios.sql`: esquema `aplicacion` (usuarios, chats, mensajes y registro de consultas). | Propuesta para Base de datos y carga |
| `api/` | FastAPI: pasarela hacia Agentes, búsquedas, login, historial y registro. | Pendiente (Infraestructura) |
| `compose.yaml` | Servicios `backend-db`, `backend-api` y `backend-ingesta`. | Pendiente (Infraestructura) |

Los PDF de ARSOFT (`data/manuales`), las credenciales (`.env`) y las salidas de la ingesta no se versionan.

## Login, historial y registro de consultas (CTR-005, CTR-006 y CTR-003)

Código en `api/app/sesiones.py`, `api/app/historial.py` y `api/app/registro.py`; tablas en `db/init/02_usuarios.sql` (esquema `aplicacion`, sin `fragmentos_rag`). `postgres.def` copia el script para que se cree al arrancar una base nueva. En una base ya creada hay que ejecutarlo una vez: `psql "$DATABASE_URL" -f Backend/db/init/02_usuarios.sql`.

**Usuarios de prueba** (solo desarrollo; el script es idempotente):

```bash
apptainer exec instance://arsoft-api python -m app.usuarios_prueba
```

| Usuario  | Contraseña | Rol     | Nota                          |
|----------|------------|---------|-------------------------------|
| admin    | admin123   | admin   | puede ver todo el registro    |
| usuario1 | usuario123 | usuario |                               |
| usuario2 | usuario123 | usuario | para probar el aislamiento    |
| inactivo | usuario123 | usuario | desactivado, el login falla   |

**Sesión.** `POST /auth/login` devuelve un `token` (JWT) que Frontend ya envía como `Authorization: Bearer`. Se firma con `ARSOFT_JWT_SECRET` o, si está vacío, con una clave derivada de `ARSOFT_SERVICE_TOKEN`. Dura `ARSOFT_SESSION_MINUTES` (480 por defecto).

**Endpoints.** Los errores siguen el formato de la API: `{"codigo_error", "mensaje"}`.

- **CTR-005** `POST /auth/login` `{"usuario", "contrasena"}`
  - 200 `{"estado": "autenticado", "mensaje", "usuario": {"id", "nombre_usuario", "nombre", "rol"}, "token", "token_type", "expires_in"}`
  - 401 `credenciales_invalidas` · 422 `datos_incompletos` · 429 `demasiados_intentos` (5 fallos en 5 min por usuario e IP) · 503 `servicio_no_disponible`. Llevan además `"estado": "no_autenticado"`, como espera Frontend.
  - `GET /auth/me`: usuario de la sesión.
- **CTR-001** `POST /consulta` exige sesión (401 `sesion_caducada`). Si `conversacion_id` llega vacío, Backend lo genera y crea el chat; uno ajeno da 404 `conversacion_no_encontrada` y no se reenvía a Agentes. Cada turno se guarda en el historial y en el registro; si la base falla, la respuesta se entrega igual.
- **CTR-006** `GET /chats?limit&offset` → `{"chats": [{"conversacion_id", "titulo", "created_at", "updated_at", "mensajes": [{"message_id", "trace_id", "role", "contenido", "estado", "codigo_error", "timestamp", "fuentes"}]}], "total"}`, con la forma que lee Frontend. También `GET`, `PATCH {"titulo"}` y `DELETE /chats/{conversacion_id}` (al borrar se pide a Agentes que olvide la conversación). Cada usuario solo ve los suyos.
- **CTR-003** `GET /consultas/mias` y `GET /consultas` (solo admin; filtros `usuario_id`, `tipo`, `estado`, `desde`, `hasta`). Guarda el `trace_id`, la pregunta, el estado, el código de error, los `chunk_id` citados y la latencia. Las búsquedas pueden registrar con `registro.registrar(conn, tipo="vectorial" | "lexica", ...)`.

**Pruebas.** `Test/test_Backend/test_usuarios_historial_registro.py`. Las de base de datos necesitan un PostgreSQL de pruebas vacío:

```bash
ARSOFT_TEST_DATABASE_URL=postgresql://... PYTHONPATH=.:shared python -m pytest Test/test_Backend
```
