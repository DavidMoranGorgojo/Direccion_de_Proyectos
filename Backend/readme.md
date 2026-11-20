# Backend — Asistente conversacional RAG (ThermoDrive HTM-240)

Estructura según el diseño «Arquitectura del backend y dockerización» (§7.3). Base de datos única PostgreSQL + pgvector; la lógica RAG vive en Agentes (opción B).

| Carpeta | Contenido | Estado |
|---|---|---|
| `ingesta/` | Ingesta a demanda: PDF → fragmentos JSONL con metadatos y embeddings bge-m3 → pgvector. Ver [`ingesta/README.md`](ingesta/README.md). | Implementada |
| `db/init/` | Esquema único de la base (`01_conocimiento.sql`), que PostgreSQL ejecuta al crear el contenedor: esquema `conocimiento` (índice versionado, documentos, chunks con `vector(1024)` y catálogos) y esquema `aplicacion` (usuarios, chats, mensajes y registro de consultas). Es idempotente. | Implementado |
| `api/` | FastAPI: pasarela hacia Agentes, búsquedas, login, historial y registro. | Pendiente (Infraestructura) |
| `compose.yaml` | Servicios `backend-db`, `backend-api` y `backend-ingesta`. | Pendiente (Infraestructura) |

Los PDF de ARSOFT (`data/manuales`), las credenciales (`.env`) y las salidas de la ingesta no se versionan.

## Login, historial y registro de consultas (CTR-005, CTR-006 y CTR-003)

Código en `api/app/sesiones.py`, `api/app/historial.py` y `api/app/registro.py`; tablas en el esquema `aplicacion` de `db/init/01_conocimiento.sql` (sin `fragmentos_rag`). `postgres.def` copia el script para que se cree al arrancar una base nueva.

> **Migración en bases ya creadas.** PostgreSQL solo ejecuta `db/init/` la primera vez que inicia un directorio de datos vacío. En una base que ya exista hay que aplicar el esquema a mano, una vez: `psql "$DATABASE_URL" -f Backend/db/init/01_conocimiento.sql` (es idempotente: crea lo que falte y no toca los datos).

**Usuarios de prueba.**

> ⚠️ **Nunca en producción.** Las contraseñas de abajo son públicas y `admin` puede leer todo el registro de consultas. El script se niega a ejecutarse sin `--desarrollo`. En producción los usuarios se crean con contraseñas propias.

```bash
apptainer exec instance://arsoft-api python -m app.usuarios_prueba --desarrollo
```

| Usuario  | Contraseña | Rol     | Nota                          |
|----------|------------|---------|-------------------------------|
| admin    | admin123   | admin   | puede ver todo el registro    |
| usuario1 | usuario123 | usuario |                               |
| usuario2 | usuario123 | usuario | para probar el aislamiento    |
| inactivo | usuario123 | usuario | desactivado, el login falla   |

**Sesión.** `POST /auth/login` devuelve un `token` (JWT) que Frontend ya envía como `Authorization: Bearer`. Se firma con `ARSOFT_JWT_SECRET` o, si está vacío, con una clave derivada de `ARSOFT_SERVICE_TOKEN`. Se exigen `exp` y `sub`. Dura `ARSOFT_SESSION_MINUTES` (480 por defecto; un valor no numérico o menor que 1 usa el valor por defecto).

- **Una sesión no se puede revocar antes de que caduque**: no hay lista de sesiones ni cierre de sesión en el servidor. Desactivar el usuario (`activo = false`) sí la corta, porque se comprueba en cada petición. Cambiar `ARSOFT_JWT_SECRET` cierra las sesiones de todos.
- **Límite de intentos de login** (en memoria): 5 fallos en 5 minutos por usuario e IP, y 20 por IP con cualquier usuario. Guarda como mucho 10.000 claves y purga las caducadas. La IP es la que ve uvicorn. Si hay un proxy delante, uvicorn usa `X-Forwarded-For` solo cuando el proxy está en `FORWARDED_ALLOW_IPS` (por defecto `127.0.0.1`, donde escucha el backend). Con un proxy en otra máquina hay que añadir su IP ahí; si no, todos los clientes contarían como la misma IP. Con varias réplicas el límite habría que llevarlo a la base.

**Endpoints.** Los errores siguen el formato de la API: `{"codigo_error", "mensaje"}`.

- **CTR-005** `POST /auth/login` `{"usuario", "contrasena"}`
  - 200 `{"estado": "autenticado", "mensaje", "usuario": {"id", "nombre_usuario", "nombre", "rol"}, "token", "token_type", "expires_in"}`
  - 401 `credenciales_invalidas` · 422 `datos_incompletos` · 429 `demasiados_intentos` (5 fallos en 5 min por usuario e IP) · 503 `servicio_no_disponible`. Llevan además `"estado": "no_autenticado"`, como espera Frontend.
  - `GET /auth/me`: usuario de la sesión.
- **CTR-001** `POST /consulta` exige sesión (401 `sesion_caducada`). Si `conversacion_id` llega vacío, Backend lo genera. Antes de llamar a Agentes reserva el chat de forma atómica (`INSERT … ON CONFLICT … WHERE usuario_id`): si el ID es de otro usuario, aunque lo use a la vez, devuelve 404 `conversacion_no_encontrada` y no se reenvía a Agentes. Cada turno se guarda en el historial y en el registro; si la base falla al guardar, la respuesta se entrega igual. El acceso a PostgreSQL va en un hilo aparte (`run_in_threadpool`) para no bloquear el event loop.
- **CTR-002** `POST /conocimiento/vectorial` queda montado en la app (`crear_router(connect, service_access)`), con el token de servicio como el resto de `/conocimiento`.
- **CTR-006** `GET /chats?limit&offset` → `{"chats": [{"conversacion_id", "titulo", "created_at", "updated_at", "mensajes": [{"message_id", "trace_id", "role", "contenido", "estado", "codigo_error", "timestamp", "fuentes"}]}], "total"}`, con la forma que lee Frontend. También `GET`, `PATCH {"titulo"}` y `DELETE /chats/{conversacion_id}` (al borrar se pide a Agentes que olvide la conversación). Cada usuario solo ve los suyos.
- **CTR-003** `GET /consultas/mias` y `GET /consultas` (solo admin; filtros `usuario_id`, `tipo`, `estado`, `desde`, `hasta`). Guarda el `trace_id`, la pregunta, el estado, el código de error, los `chunk_id` citados y la latencia. Las búsquedas pueden registrar con `registro.registrar(conn, tipo="vectorial" | "lexica", ...)`.

**Pruebas.** `Test/test_Backend/test_usuarios_historial_registro.py`. Las de base de datos necesitan un PostgreSQL de pruebas vacío:

```bash
ARSOFT_TEST_DATABASE_URL=postgresql://... PYTHONPATH=.:shared python -m pytest Test/test_Backend
```
